"""Authenticated MySQL dialogue endpoint; separate from the original scaffold handler."""
import base64
import hashlib
import hmac
import json
import os
import re
from uuid import UUID

from src.config import load_local_settings
from src.bedrock.client import BedrockPlanner
from src.bedrock.questioner import BedrockQuestioner
from src.repositories.mysql_connection import connect_mysql
from src.repositories.job_search_factory import create_job_repository
from src.repositories.elasticsearch_training import create_training_repository
from src.repositories.mysql_chat import MySQLChatStore
from src.services.dialogue import DialogueFlow, FlowError
from src.services.dependency_errors import dependency_error, error_code


def response(status, value):
    return {"statusCode": status, "headers": {"Content-Type": "application/json; charset=utf-8",
                                              "Cache-Control": "no-store"},
            "body": json.dumps(value, ensure_ascii=False)}


def validate_payload(value):
    if not isinstance(value, dict):
        raise ValueError("Request must be an object")
    common = {"action", "session_id", "request_id", "model_tier"}
    fields = {"review_answers": {"offset"}, "revise_answer": {"condition_id", "assessment", "detail", "review_version", "offset"}, "search": {"message", "search_plan", "profile"}, "select": {"source_id", "grouped", "assessment_checkpoint"},
              "answer": {"question_id", "assessment", "detail"}, "remember": {"message"}, "answer_batch": {"answers"}, "next_results": {"target"}, "assessment_control": {"control"}, "confirm_search": {"search_id"}, "consult": {"task", "message", "summary_id"}}
    action = value.get("action")
    if action not in fields or set(value) - common - fields[action]:
        raise ValueError("Unsupported request fields")
    if value.get("model_tier", "main") != "main":
        raise ValueError("Invalid model choice")
    UUID(value.get("request_id", ""))
    if value.get("session_id"):
        UUID(value["session_id"])
    if action != "search" and not value.get("session_id"):
        raise ValueError("Session required")
    if action in {'review_answers','revise_answer'}:
        if type(value.get('offset',0)) is not int or not 0<=value.get('offset',0)<=1000 or value.get('offset',0)%10:
            raise ValueError('Invalid answer review page')
        if action=='revise_answer':
            if not isinstance(value.get('condition_id'),str) or not 1<=len(value['condition_id'])<=200:raise ValueError('Invalid saved condition')
            if not isinstance(value.get('review_version'),str) or not re.fullmatch('[a-f0-9]{64}',value['review_version']):raise ValueError('Invalid saved answer revision')
            if value.get('assessment') not in {'met','unmet','unknown'}:raise ValueError('Invalid revised assessment')
            if not isinstance(value.get('detail',''),str) or len(value.get('detail',''))>2000:raise ValueError('Invalid revised detail')
    elif action == "search":
        if value.get("search_plan") is not None:
            from src.schemas.search import SearchPlan
            SearchPlan.parse(value["search_plan"])
        elif not isinstance(value.get("message"), str) or not 1 <= len(value["message"]) <= 4000:
            raise ValueError("Search message required")
        profile = value.get("profile", {})
        if not isinstance(profile, dict) or len(json.dumps(profile, ensure_ascii=False)) > 4000:
            raise ValueError("Invalid profile")
    elif action == "next_results":
        if value.get("target") not in {"jobs","training"}:raise ValueError("Invalid navigation target")
    elif action == "assessment_control":
        if value.get("control") not in {"stop","resume","preferred"}:raise ValueError("Invalid assessment control")
    elif action == "consult":
        from src.services.consultation import TASKS
        if not isinstance(value.get('task'),str) or value['task'] not in TASKS:
            raise ValueError('Invalid counseling task')
        if not isinstance(value.get('message'),str) or not 1<=len(value['message'].strip())<=4000:
            raise ValueError('Invalid counseling message')
        if 'summary_id' in value and (not isinstance(value['summary_id'],str) or not re.fullmatch('[a-f0-9]{64}',value['summary_id'])):
            raise ValueError('Invalid summary reference')
    elif action == "confirm_search":
        UUID(value.get("search_id", ""))
    elif action == "remember":
        if not isinstance(value.get("message"), str) or not 1 <= len(value["message"].strip()) <= 2000:
            raise ValueError("Memory statement required")
    elif action == "select":
        if "assessment_checkpoint" in value and type(value["assessment_checkpoint"]) is not bool:
            raise ValueError("Invalid assessment checkpoint")
        if "grouped" in value and type(value["grouped"]) is not bool:
            raise ValueError("Invalid grouped choice")
        if not isinstance(value.get("source_id"), str) or not re.fullmatch(r"\d{1,128}", value["source_id"]):
            raise ValueError("Invalid source ID")
    elif action == "answer_batch":
        answers = value.get("answers")
        if not isinstance(answers, list) or not 1 <= len(answers) <= 40:
            raise ValueError("Invalid answer batch")
        for item in answers:
            if not isinstance(item, dict) or set(item) != {"question_id", "assessment", "detail"}:
                raise ValueError("Invalid answer item")
            validate_payload(dict(item, action="answer", request_id=value["request_id"], session_id=value["session_id"]))
    else:
        if value.get("assessment") not in {"met", "unmet", "unknown"}:
            raise ValueError("Invalid assessment")
        if not isinstance(value.get("question_id"), str) or not 1 <= len(value["question_id"]) <= 200:
            raise ValueError("Invalid question")
        if not isinstance(value.get("detail", ""), str) or len(value.get("detail", "")) > 2000:
            raise ValueError("Answer too long")
    return value


def handle_request(event, *, jobs=None, store=None, planner=None, questioner=None, training=None, on_progress=None, intent_store=None, condition_reviews=None, condition_classifier=None, condition_question_cache=None):
    headers = {key.lower(): value for key, value in event.get("headers", {}).items()}
    from src.services.admin_auth import authenticate
    identity=authenticate(headers,os.getenv('CHAT_API_TOKEN',''),os.getenv('ADMIN_API_TOKEN',''))
    if not identity:
        return response(401, {'status':'unauthorized'})
    owner,client_token,role=identity
    try:
        body = event.get("body", "{}")
        if event.get("isBase64Encoded"):
            body = base64.b64decode(body, validate=True).decode("utf-8")
        if not isinstance(body, str) or len(body) > 24000:
            raise ValueError("Request too large")
        payload = validate_payload(json.loads(body))
        include_unverified = os.getenv("CHAT_INCLUDE_UNVERIFIED") == "true"
        region = os.getenv("BEDROCK_REGION") or os.getenv("AWS_REGION")
        model = os.getenv("MODEL_ID") or os.getenv("BEDROCK_MODEL_ID")
        retention = int(os.environ["CHAT_RETENTION_HOURS"])
        jobs = jobs or create_job_repository(connect_mysql, include_unverified=include_unverified)
        store = store or MySQLChatStore(connect_mysql, retention_hours=retention, max_calls=None if role=="admin" else 12)
        planner = planner or (BedrockPlanner(model, region, on_partial=on_progress) if on_progress is not None else BedrockPlanner(model, region))
        questioner = questioner or BedrockQuestioner(model, region)
    except (ValueError, TypeError, AttributeError):
        return response(400, {"status": "invalid_request_or_settings"})
    except KeyError:
        return response(503, {"status": "retention_not_configured"})
    ticket = None
    audit = None
    decision_id = None
    try:
        ticket = store.begin(owner, payload)
        if "cached" in ticket:
            return response(200, dict(ticket["cached"], cached=True))
        audit_enabled = os.getenv("INTENT_AUDIT_ENABLED", os.getenv("CONTEXT_ROUTING_ENABLED", "false")) == "true"
        if audit_enabled:
            from src.repositories.intent_decisions import IntentDecisionStore
            from src.services.intent_context import routing_context
            audit = intent_store or IntentDecisionStore(connect_mysql)
            source = "model" if payload["action"] == "search" and payload.get("search_plan") is None else "direct"
            decision_id = audit.start(ticket, source, routing_context(ticket["state"]))

        on_demand=os.getenv('ENABLE_ON_DEMAND_CONDITIONS')=='true'
        selected_classifier=condition_classifier
        if on_demand and selected_classifier is None:
            from src.bedrock.question_reviewer import QuestionConditionReviewer
            selected_classifier=QuestionConditionReviewer(model,region)

        def invoke(purpose, function, *args):
            adapter = planner if purpose in {"search_plan", "consultation", "intent_classification", "context_response"} else questioner
            if purpose=='condition_review':adapter=selected_classifier
            from src.bedrock.prompts import SEARCH_PROMPT_VERSION, CONSULTATION_PROMPT_VERSION
            version = SEARCH_PROMPT_VERSION if purpose == "search_plan" else "question-memory-v2"
            if purpose == 'consultation':version = CONSULTATION_PROMPT_VERSION
            if purpose == 'intent_classification':
                from src.schemas.intent import INTENT_VERSION
                version = INTENT_VERSION
            if purpose == 'context_response':version = 'context-response-v1'
            if purpose == 'condition_review':
                from src.schemas.condition_review import POLICY_VERSION
                version=getattr(adapter,'prompt_version',POLICY_VERSION)
            identity = store.begin_invocation(ticket, purpose, adapter.model_id, adapter.region, version, args)
            if purpose == 'intent_classification':ticket['_intent_invocation_id'] = identity
            try:
                result, usage = function(*args)
            except Exception as exc:
                store.finish_invocation(ticket, identity, usage=getattr(exc, "usage", None), error_code=error_code(exc))
                raise
            store.finish_invocation(ticket, identity, usage=usage)
            return result

        condition_resolver=None
        if on_demand:
            from src.repositories.condition_question_cache import ConditionQuestionCache
            from src.repositories.condition_reviews import ConditionReviewStore
            from src.services.selected_condition_review import SelectedConditionReview
            condition_resolver=SelectedConditionReview(jobs,condition_question_cache or ConditionQuestionCache(connect_mysql),selected_classifier,approved=condition_reviews or ConditionReviewStore(connect_mysql))
        if condition_reviews is None and not on_demand and os.getenv('ENABLE_AI_CONDITION_SELECTION')=='true':
            from src.repositories.condition_reviews import ConditionReviewStore
            condition_reviews=ConditionReviewStore(connect_mysql)
        flow = DialogueFlow(jobs, planner, questioner, include_unverified=include_unverified,
                            condition_reviews=condition_reviews,condition_resolver=condition_resolver,
                            training=training if training is not None else create_training_repository(connect_mysql))
        from src.services.context_router import ContextRouter
        def decided(raw, decision):
            if audit:audit.classified(ticket, decision_id, raw, decision)
        state, result, evidence = ContextRouter(flow).advance(ticket['state'], payload, invoke, decided)
        from src.services.condition_review import attach_selection
        result=attach_selection(state,result)
        if state.get("selected"):
            result["active_job"] = {k:state["selected"].get(k) for k in ("source_id","title","company_name","source_version")}
        if decision_id:result["intent_decision_id"] = decision_id
        result["snapshot_warning"] = include_unverified
        delivered = store.finish(ticket, payload, state, result, evidence)
        if audit:audit.finish(ticket, decision_id, result=result)
        return response(200, delivered)
    except Exception as exc:
        if audit and decision_id:
            try:
                if hasattr(exc,'intent_raw_output'):
                    audit.classified(ticket, decision_id, exc.intent_raw_output, None, valid=False)
                audit.finish(ticket, decision_id, error=error_code(exc))
            except Exception:
                # Audit failures are not silently accepted as successful execution.
                # Start/validated records remain for reconciliation; never log raw exception text.
                pass
        if ticket and "cached" not in ticket:
            try:
                store.abort(ticket, failure={'error_code':error_code(exc),'error_type':type(exc).__name__})
            except Exception:
                # No source/user content or database exception text is logged.
                pass
        if isinstance(exc, FlowError):
            info = {"status": exc.code, "request_id": payload["request_id"]}
            if ticket and ticket.get("session_id"):info["session_id"] = ticket["session_id"]
            if decision_id:info["intent_decision_id"] = decision_id
            return response(exc.status, info)
        status_code, error = dependency_error(exc)
        error["request_id"] = payload["request_id"]
        if decision_id:error["intent_decision_id"] = decision_id
        if ticket and "session_id" in ticket:
            error["session_id"] = ticket["session_id"]
        return response(status_code, error)


def lambda_handler(event, context):
    load_local_settings()
    if os.getenv("CHAT_RUNTIME_ENABLED") != "true":
        return response(503, {"status": "dialogue_runtime_disabled"})
    return handle_request(event)




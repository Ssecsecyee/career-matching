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
from src.repositories.mysql_jobs import MySQLJobRepository
from src.repositories.mysql_training import MySQLTrainingRepository
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
    fields = {"search": {"message", "search_plan", "profile"}, "select": {"source_id", "grouped"},
              "answer": {"question_id", "assessment", "detail"}, "remember": {"message"}, "answer_batch": {"answers"}}
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
    if action == "search":
        if value.get("search_plan") is not None:
            from src.schemas.search import SearchPlan
            SearchPlan.parse(value["search_plan"])
        elif not isinstance(value.get("message"), str) or not 1 <= len(value["message"]) <= 4000:
            raise ValueError("Search message required")
        profile = value.get("profile", {})
        if not isinstance(profile, dict) or len(json.dumps(profile, ensure_ascii=False)) > 4000:
            raise ValueError("Invalid profile")
    elif action == "remember":
        if not isinstance(value.get("message"), str) or not 1 <= len(value["message"].strip()) <= 2000:
            raise ValueError("Memory statement required")
    elif action == "select":
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


def handle_request(event, *, jobs=None, store=None, planner=None, questioner=None, training=None, on_progress=None):
    headers = {key.lower(): value for key, value in event.get("headers", {}).items()}
    expected = os.getenv("CHAT_API_TOKEN", "")
    if len(expected) < 32:
        return response(503, {"status": "chat_auth_not_configured"})
    if not hmac.compare_digest(headers.get("authorization", ""), "Bearer " + expected):
        return response(401, {"status": "unauthorized"})
    client_token = headers.get("x-client-token", "")
    if not isinstance(client_token, str) or not re.fullmatch(r"[A-Za-z0-9_-]{32,128}", client_token):
        return response(400, {"status": "client_token_required"})
    owner = hmac.new(expected.encode(), client_token.encode(), hashlib.sha256).hexdigest()
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
        jobs = jobs or MySQLJobRepository(connect_mysql, include_unverified=include_unverified)
        store = store or MySQLChatStore(connect_mysql, retention_hours=retention)
        planner = planner or (BedrockPlanner(model, region, on_partial=on_progress) if on_progress is not None else BedrockPlanner(model, region))
        questioner = questioner or BedrockQuestioner(model, region)
    except (ValueError, TypeError, AttributeError):
        return response(400, {"status": "invalid_request_or_settings"})
    except KeyError:
        return response(503, {"status": "retention_not_configured"})
    ticket = None
    try:
        ticket = store.begin(owner, payload)
        if "cached" in ticket:
            return response(200, dict(ticket["cached"], cached=True))

        def invoke(purpose, function, *args):
            adapter = planner if purpose in {"search_plan", "conversation"} else questioner
            version = "conversation-training-v4" if purpose == "conversation" else ("search-v1" if purpose == "search_plan" else "question-memory-v2")
            identity = store.begin_invocation(ticket, purpose, adapter.model_id, adapter.region, version, args)
            try:
                result, usage = function(*args)
            except Exception as exc:
                store.finish_invocation(ticket, identity, usage=getattr(exc, "usage", None), error_code=error_code(exc))
                raise
            store.finish_invocation(ticket, identity, usage=usage)
            return result

        flow = DialogueFlow(jobs, planner, questioner, include_unverified=include_unverified,
                            training=training if training is not None else MySQLTrainingRepository(connect_mysql))
        state, result, evidence = flow.advance(ticket["state"], payload, invoke)
        result["snapshot_warning"] = include_unverified
        return response(200, store.finish(ticket, payload, state, result, evidence))
    except Exception as exc:
        if ticket and "cached" not in ticket:
            try:
                store.abort(ticket)
            except Exception:
                # No source/user content or database exception text is logged.
                pass
        if isinstance(exc, FlowError):
            return response(exc.status, {"status": exc.code})
        status_code, error = dependency_error(exc)
        error["request_id"] = payload["request_id"]
        if ticket and "session_id" in ticket:
            error["session_id"] = ticket["session_id"]
        return response(status_code, error)


def lambda_handler(event, context):
    load_local_settings()
    if os.getenv("CHAT_RUNTIME_ENABLED") != "true":
        return response(503, {"status": "dialogue_runtime_disabled"})
    return handle_request(event)




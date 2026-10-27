"""API Gateway proxy handler. Production chat stays closed until persistence/auth exist."""
import base64
import json
import os
from uuid import uuid4

from src.config import load_local_settings
from src.bedrock.client import BedrockPlanner
from src.repositories.jobs import JsonJobRepository
from src.schemas.search import SearchPlan
from src.services.search import search_candidates


def reply(code, payload):
    return {"statusCode": code,
            "headers": {"Content-Type": "application/json; charset=utf-8",
                        "Cache-Control": "no-store"},
            "body": json.dumps(payload, ensure_ascii=False)}


def lambda_handler(event, context):
    load_local_settings()
    request_id = getattr(context, "aws_request_id", None) or str(uuid4())
    path = event.get("rawPath", event.get("path", ""))
    method = event.get("requestContext", {}).get("http", {}).get("method") or event.get("httpMethod")
    if path == "/health" and method == "GET":
        return reply(200, {"status": "ok", "readiness": "scaffold_only"})
    if path != "/chat" or method != "POST":
        return reply(404, {"status": "not_found", "request_id": request_id})
    if os.getenv("AWS_LAMBDA_FUNCTION_NAME") or os.getenv("APP_MODE", "local") != "local":
        return reply(503, {"status": "not_configured", "request_id": request_id,
                           "message": "영구 DB 저장·인증 연결 전에는 운영 채팅을 제공하지 않습니다."})
    try:
        body = event.get("body", "{}")
        if event.get("isBase64Encoded"):
            body = base64.b64decode(body, validate=True).decode("utf-8")
        if not isinstance(body, str) or len(body) > 20000:
            raise ValueError("Invalid request body")
        payload = json.loads(body)
        if not isinstance(payload, dict) or set(payload) - {"message", "search_plan"}:
            raise ValueError("Allowed local fields: message, search_plan")
        usage = None
        if "search_plan" in payload:
            plan = SearchPlan.parse(payload["search_plan"])
        elif os.getenv("ENABLE_LIVE_BEDROCK") == "true":
            planner = BedrockPlanner(os.getenv("BEDROCK_MODEL_ID"), os.getenv("BEDROCK_REGION"))
            plan, usage = planner.plan(payload.get("message"))
        else:
            return reply(200, {"request_id": request_id, "stage": "need_search_plan",
                               "message": "모의 모드에서는 search_plan을 전달하세요. 실제 모델 호출은 꺼져 있습니다."})
        data_path = os.getenv("LOCAL_JOBS_JSON")
        if not data_path:
            return reply(503, {"status": "data_not_configured", "request_id": request_id,
                               "search_plan": plan.to_dict()})
        include_unverified = os.getenv("LOCAL_INCLUDE_UNVERIFIED", "false") == "true"
        result = search_candidates(JsonJobRepository(data_path, include_unverified=include_unverified), plan)
        result["includes_unverified_snapshots"] = include_unverified
        result.update(request_id=request_id, mode="local", model_usage=usage)
        return reply(200, result)
    except (ValueError, TypeError, UnicodeError):
        return reply(400, {"status": "invalid_request_or_plan", "request_id": request_id})
    except OSError:
        return reply(503, {"status": "local_data_unavailable", "request_id": request_id})



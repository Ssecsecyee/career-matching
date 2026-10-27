"""One explicitly requested, small live call. Never runs on import."""
import argparse
import json
import os

from src.config import load_local_settings
from src.bedrock.client import runtime_client


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="Allow one billable Bedrock test")
    args = parser.parse_args()
    if not args.live:
        parser.error("Use --live to explicitly allow a billable request")
    load_local_settings()
    if os.getenv("ENABLE_LIVE_BEDROCK") != "true":
        parser.error("Live calls disabled. Check BEDROCK_MOCK and CMD ENABLE_LIVE_BEDROCK.")
    region = os.getenv("BEDROCK_REGION") or os.getenv("AWS_REGION")
    model = os.getenv("MODEL_ID") or os.getenv("BEDROCK_MODEL_ID")
    if not region or not model:
        parser.error("Set AWS_REGION and MODEL_ID in backend/.env")
    try:
        from botocore.exceptions import BotoCoreError, ClientError
    except ImportError:
        parser.exit(2, "Install dependencies: python -m pip install -r requirements.txt\n")
    try:
        response = runtime_client(region).converse(
            modelId=model,
            messages=[{"role": "user", "content": [{"text": "한국어로 '연결 확인'이라고만 답하세요."}]}],
            inferenceConfig={"maxTokens": 32},
        )
    except ClientError as exc:
        # Print error code only; no credentials, request body or raw service error.
        code = exc.response.get("Error", {}).get("Code", "UnknownServiceError")
        parser.exit(1, "Bedrock error code: " + code + "\n")
    except BotoCoreError as exc:
        parser.exit(1, "AWS client error: " + type(exc).__name__ + "\n")
    print(json.dumps({
        "model_id": model,
        "region": region,
        "stop_reason": response.get("stopReason"),
        "reply": "".join(block.get("text", "") for block in
                         response.get("output", {}).get("message", {}).get("content", [])),
        "usage": response.get("usage", {}),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

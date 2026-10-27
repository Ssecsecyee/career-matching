"""Explicit opt-in real Bedrock adapter; import alone never creates a client."""
import json
import os
from functools import lru_cache
from time import perf_counter

from src.bedrock.prompts import SEARCH_PROMPT_VERSION, SEARCH_SYSTEM
from src.schemas.search import SearchPlan
from src.bedrock.model_json import parse_object, usage_metadata, ModelOutputFormatError


@lru_cache(maxsize=2)
def runtime_client(region):
    import boto3
    from botocore.config import Config
    return boto3.Session(region_name=region).client(
        "bedrock-runtime",
        config=Config(connect_timeout=2 if os.getenv("AWS_LAMBDA_FUNCTION_NAME") else 5,
                      read_timeout=18 if os.getenv("AWS_LAMBDA_FUNCTION_NAME") else 40,
                      retries={"mode": "adaptive", "total_max_attempts": 1 if os.getenv("AWS_LAMBDA_FUNCTION_NAME") else 2}),
    )


class BedrockPlanner:
    def __init__(self, model_id, region, *, client=None, max_tokens=512):
        if not model_id or not region or ":prompt/" in model_id:
            raise ValueError("Configure a Converse model or inference profile ID and region")
        if type(max_tokens) is not int or not 1 <= max_tokens <= 2048:
            raise ValueError("Invalid output budget")
        self.model_id, self.region = model_id, region
        self.client, self.max_tokens = client, max_tokens

    def plan(self, message):
        if os.getenv("ENABLE_LIVE_BEDROCK") != "true":
            raise RuntimeError("Live Bedrock calls are disabled")
        if not isinstance(message, str) or not 1 <= len(message.strip()) <= 4000:
            raise ValueError("Invalid message")
        client = self.client if self.client is not None else runtime_client(self.region)
        started = perf_counter()
        response = client.converse(
            modelId=self.model_id,
            system=[{"text": SEARCH_SYSTEM}],
            messages=[{"role": "user", "content": [{"text": message}]}],
            inferenceConfig={"maxTokens": self.max_tokens},
        )
        metadata = usage_metadata(response, model_id=self.model_id, region=self.region,
                                  prompt_version=SEARCH_PROMPT_VERSION, started=started)
        if response.get("stopReason") != "end_turn":
            raise ModelOutputFormatError(metadata)
        blocks = response["output"]["message"]["content"]
        text = "".join(block.get("text", "") for block in blocks)
        try:
            plan = SearchPlan.parse(parse_object(text, metadata))
        except ValueError as exc:
            raise ModelOutputFormatError(metadata) from exc
        return plan, metadata


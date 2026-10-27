import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import sys

from src.bedrock.client import BedrockPlanner
from src.handlers.chat import lambda_handler
from src.repositories.jobs import JsonJobRepository
from src.schemas.search import SearchPlan
from src.services.cache_key import response_cache_key
from src.services.search import search_candidates

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "ingestion"))
from normalize_jumpit import normalize


class FakeRuntime:
    def __init__(self, text, stop="end_turn"):
        self.text, self.stop, self.calls = text, stop, []

    def converse(self, **kwargs):
        self.calls.append(kwargs)
        return {"stopReason": self.stop, "output": {"message": {"content": [{"text": self.text}]}},
                "usage": {"inputTokens": 30, "outputTokens": 12}}


class BackendTests(unittest.TestCase):
    def test_plan_rejects_sql_and_invalid_limits(self):
        for value in ({"sql": "DROP TABLE jobs"}, {"limit": True}, {"limit": 31},
                      {"skills": "Python"}, {"skills": [""]}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                SearchPlan.parse(value)

    def test_live_call_requires_opt_in(self):
        runtime = FakeRuntime('{}')
        with patch.dict(os.environ, {"ENABLE_LIVE_BEDROCK": "false"}):
            with self.assertRaises(RuntimeError):
                BedrockPlanner("test-model", "test-region", client=runtime).plan("검색")
        self.assertEqual(runtime.calls, [])

    def test_converse_budget_and_usage(self):
        runtime = FakeRuntime('{"skills":["Python"],"limit":3}')
        with patch.dict(os.environ, {"ENABLE_LIVE_BEDROCK": "true"}):
            plan, usage = BedrockPlanner("test-model", "test-region", client=runtime).plan("검색")
        self.assertEqual(plan.skills, ("Python",))
        self.assertEqual(runtime.calls[0]["inferenceConfig"]["maxTokens"], 512)
        self.assertEqual(usage["input_tokens"], 30)
        self.assertIsNone(usage["cache_read_input_tokens"])

    def test_model_output_and_truncation_rejected(self):
        for text, stop in [('{"query":"anything"}', "end_turn"), ('{}', "max_tokens")]:
            with patch.dict(os.environ, {"ENABLE_LIVE_BEDROCK": "true"}):
                with self.assertRaises(ValueError):
                    BedrockPlanner("model", "region", client=FakeRuntime(text, stop)).plan("검색")

    def test_cache_owner_state_and_data_isolation(self):
        base = dict(owner_scope="user1", session_id="s1", state_version=1,
                    profile_version=1, request={"q": "Python"}, selected_job_ids=[1],
                    stage="checking_required", model_id="model", prompt_version="v1",
                    policy_version="p1", data_generation=1, dependency_versions={"1": 1})
        first = response_cache_key(**base)
        for change in ({"owner_scope": "user2"}, {"state_version": 2},
                       {"data_generation": 2}, {"profile_version": 2}, {"prompt_version": "v2"}):
            self.assertNotEqual(first, response_cache_key(**(base | change)))
        with self.assertRaises(ValueError):
            response_cache_key(**(base | {"owner_scope": ""}))

    def test_json_search_filters_status_region_skills_and_summarizes(self):
        rows = [dict(source_id=str(i), title="백엔드", company_name="Test fixture",
                     recruitment_status=status, tech_stacks=skills, addresses=["서울"],
                     qualifications="x" * 200, raw_detail={"private": "not for cards"})
                for i, status, skills in [(1, "active", ["Python"]), (2, "closed", ["Python"]),
                                         (3, "active", ["Java"]), (4, "unknown", ["Python"])]]
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "test.json"
            path.write_text(json.dumps(rows), encoding="utf-8")
            result = search_candidates(JsonJobRepository(path),
                                       SearchPlan.parse({"skills": ["Python"], "region": "서울"}),
                                       input_char_budget=20)
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["stage"], "choose_job")
        self.assertNotIn("raw_detail", result["candidate_jobs"][0])

    def test_aws_chat_fails_closed(self):
        event = {"rawPath": "/chat", "httpMethod": "POST", "body": "{}"}
        with patch.dict(os.environ, {"AWS_LAMBDA_FUNCTION_NAME": "test-function"}):
            self.assertEqual(lambda_handler(event, None)["statusCode"], 503)

    def test_health_and_malformed_body(self):
        with patch.dict(os.environ, {"APP_MODE": "local"}, clear=True):
            response = lambda_handler({"rawPath": "/health", "httpMethod": "GET"}, None)
            self.assertEqual(response["statusCode"], 200)
            for body in ('[]', 'not json', '{"search_plan":{"limit":0}}'):
                response = lambda_handler({"rawPath": "/chat", "httpMethod": "POST", "body": body}, None)
                self.assertEqual(response["statusCode"], 400)

    def test_offline_normalization_preserves_unknowns_and_all_original_fields(self):
        body = {"result": {"id": 42, "title": "test", "responsibility": "업무",
                           "welfares": "혜택", "recruitProcess": "절차",
                           "newUnknownField": "원본 보존"}}
        result = normalize(body)
        self.assertEqual(result["benefits"], "혜택")
        self.assertEqual(result["hiring_process"], "절차")
        self.assertIsNone(result["application_notes"])
        self.assertIsNone(result["fetched_at"])
        self.assertEqual(result["recruitment_status"], "unknown")
        self.assertEqual(result["raw_detail"]["newUnknownField"], "원본 보존")
        self.assertEqual(result["content_hash"], normalize(body)["content_hash"])


if __name__ == "__main__":
    unittest.main()

import hashlib
import json
import os
import unittest
from unittest.mock import patch

from src.bedrock.questioner import BedrockQuestioner


class Runtime:
    def __init__(self, value):
        self.value, self.calls = value, []

    def converse(self, **kwargs):
        self.calls.append(kwargs)
        return {"stopReason": "end_turn", "output": {"message": {"content": [{"text": json.dumps(self.value)}]}},
                "usage": {"inputTokens": 40, "outputTokens": 20}}


class QuestionerTests(unittest.TestCase):
    def test_original_quote_stays_server_owned_and_output_budget_is_bounded(self):
        quote = "Python 또는 Java 경험"
        fake = Runtime({"question": "이 원문 조건에 해당하는 경험이 있으신가요?",
                        "source_hash": hashlib.sha256(quote.encode()).hexdigest()})
        with patch.dict(os.environ, {"ENABLE_LIVE_BEDROCK": "true"}):
            value, usage = BedrockQuestioner("fake", "fake", fake).question({"quote": quote, "type": "required"}, {})
        self.assertEqual(value["quote"], quote)
        self.assertEqual(fake.calls[0]["inferenceConfig"]["maxTokens"], 1024)
        self.assertEqual(usage["output_tokens"], 20)

    def test_changed_source_hash_rejected(self):
        fake = Runtime({"question": "changed", "source_hash": "wrong"})
        with patch.dict(os.environ, {"ENABLE_LIVE_BEDROCK": "true"}), self.assertRaises(ValueError):
            BedrockQuestioner("fake", "fake", fake).question({"quote": "원문", "type": "required"}, {})

    def test_large_section_rejected_before_model_call(self):
        fake = Runtime({})
        with patch.dict(os.environ, {"ENABLE_LIVE_BEDROCK": "true"}), self.assertRaises(ValueError):
            BedrockQuestioner("fake", "fake", fake).question({"quote": "a" * 18001, "type": "required"}, {})
        self.assertFalse(fake.calls)


class MemoryExtractionTests(unittest.TestCase):
    def test_memory_quotes_require_exact_user_source_and_never_accept_job_text(self):
        quote = "MySQL 설계 및 최적화 경험"
        value = {"question": "최적화 경험도 있으신가요?", "source_hash": hashlib.sha256(quote.encode()).hexdigest(),
                 "memory_updates": [{"category": "experience", "subject": "MySQL", "quote": "MySQL 프로젝트 경험",
                                     "statement_id": "1"}]}
        profile = {"recent_statements": [{"id": "1", "kind": "statement", "text": "MySQL 프로젝트 경험이 있어요"}]}
        with patch.dict(os.environ, {"ENABLE_LIVE_BEDROCK": "true"}):
            result, _ = BedrockQuestioner("fake", "fake", Runtime(value)).question({"quote": quote, "type": "required"}, profile)
            self.assertEqual(len(result["memory_updates"]), 1)
            value["memory_updates"][0]["quote"] = "쿼리 최적화 전문가"
            with self.assertRaises(ValueError):
                BedrockQuestioner("fake", "fake", Runtime(value)).question({"quote": quote, "type": "required"}, profile)
            value["memory_updates"][0]["quote"] = "MySQL 프로젝트 경험"
            profile["recent_statements"][0]["kind"] = "selection"
            with self.assertRaises(ValueError):
                BedrockQuestioner("fake", "fake", Runtime(value)).question({"quote": quote, "type": "required"}, profile)

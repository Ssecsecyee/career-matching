import json
import os
import unittest
from unittest.mock import MagicMock, patch
from uuid import uuid4

from src.handlers.dialogue import handle_request, validate_payload


class ModelChoiceTests(unittest.TestCase):
    def test_model_choice_only_accepts_known_presets(self):
        with self.assertRaises(ValueError):
            validate_payload({"action": "search", "request_id": str(uuid4()),
                              "search_plan": {}, "model_tier": "arbitrary-model"})
        with self.assertRaises(ValueError):
            validate_payload({"action": "search", "request_id": str(uuid4()),
                              "search_plan": {}, "model_tier": "fast"})

    def test_only_main_selects_configured_model(self):
        for tier, expected in ((None, "configured-main"), ("main", "configured-main")):
            with self.subTest(tier=tier):
                payload = {"action": "search", "request_id": str(uuid4()), "search_plan": {}}
                if tier:
                    payload["model_tier"] = tier
                store = MagicMock()
                store.begin.return_value = {"cached": {"stage": "choose_job"}}
                token = "x" * 40
                env = {"CHAT_API_TOKEN": token, "CHAT_RETENTION_HOURS": "1", "BEDROCK_REGION": "test-region",
                       "MODEL_ID": "configured-main"}
                with patch.dict(os.environ, env), patch('src.handlers.dialogue.BedrockPlanner') as planner, patch('src.handlers.dialogue.BedrockQuestioner') as questioner:
                    result = handle_request({"headers": {"Authorization": "Bearer " + token, "X-Client-Token": "a" * 64},
                                             "body": json.dumps(payload)}, jobs=MagicMock(), store=store)
                self.assertEqual(result["statusCode"], 200)
                planner.assert_called_once_with(expected, "test-region")
                questioner.assert_called_once_with(expected, "test-region")

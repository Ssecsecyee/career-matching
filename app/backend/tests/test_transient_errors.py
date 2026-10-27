import unittest
import json
import os
from unittest.mock import MagicMock, patch
from uuid import uuid4
from src.services.dependency_errors import dependency_error, error_code


class ServiceError(Exception):
    def __init__(self, code):
        self.response = {"Error": {"Code": code, "Message": "private service message"}}


class TransientErrorTests(unittest.TestCase):
    def test_service_unavailable_is_retryable_without_message_leak(self):
        status, result = dependency_error(ServiceError("ServiceUnavailableException"))
        self.assertEqual(status, 503)
        self.assertTrue(result["retryable"])
        self.assertEqual(result["retry_after_seconds"], 10)
        self.assertNotIn("private service message", str(result))

    def test_access_denied_is_not_retried(self):
        status, result = dependency_error(ServiceError("AccessDeniedException"))
        self.assertFalse(result["retryable"])

    def test_throttling_has_separate_status(self):
        status, result = dependency_error(ServiceError("ThrottlingException"))
        self.assertEqual(status, 429)

    def test_non_service_exception_uses_type_only(self):
        self.assertEqual(error_code(RuntimeError("private")), "RuntimeError")

    def test_handler_keeps_session_and_logs_retryable_service_failure(self):
        from src.handlers.dialogue import handle_request
        store, planner = MagicMock(), MagicMock()
        request_id, session_id = str(uuid4()), str(uuid4())
        store.begin.return_value = {"state": {}, "session_id": session_id, "request_id": request_id}
        store.begin_invocation.return_value = "fake-invocation"
        planner.model_id, planner.region = "fake-model", "fake-region"
        planner.plan.side_effect = ServiceError("ServiceUnavailableException")
        token = "x" * 40
        event = {"headers": {"Authorization": "Bearer " + token, "X-Client-Token": "a" * 64},
                 "body": json.dumps({"action": "search", "request_id": request_id, "message": "MySQL"})}
        with patch.dict(os.environ, {"CHAT_API_TOKEN": token, "CHAT_RETENTION_HOURS": "1"}):
            result = handle_request(event, store=store, planner=planner, jobs=MagicMock(), questioner=MagicMock())
        self.assertEqual(result["statusCode"], 503)
        body = json.loads(result["body"])
        self.assertEqual(body["session_id"], session_id)
        self.assertTrue(body["retryable"])
        self.assertNotIn("private service message", result["body"])
        self.assertEqual(store.finish_invocation.call_args.kwargs["error_code"], "ServiceUnavailableException")
        store.abort.assert_called_once()

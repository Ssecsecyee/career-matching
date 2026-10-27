"""Optional actual MySQL integration test; never connects unless TEST_MYSQL_PORT is set."""
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import unittest
from unittest.mock import patch
from uuid import uuid4

from src.handlers.dialogue import handle_request
from src.repositories.mysql_chat import MySQLChatStore
from src.repositories.mysql_jobs import MySQLJobRepository
from src.schemas.search import SearchPlan
from src.services.dialogue import FlowError


class FakeModel:
    model_id, region = "offline-test-model", "test-region"
    fail = False

    def question(self, condition, profile):
        if self.fail:
            raise RuntimeError("offline simulated model failure")
        return {"question": "원문 조건에 해당하시나요?", "quote": condition["quote"]}, {
            "input_tokens": 10, "output_tokens": 5, "latency_ms": 1}


@unittest.skipUnless(os.getenv("TEST_MYSQL_PORT"), "Isolated MySQL integration environment not configured")
class MySQLDialogueIntegrationTests(unittest.TestCase):
    def setUp(self):
        import pymysql
        self.pymysql = pymysql
        self.factory = lambda: pymysql.connect(host="127.0.0.1", port=int(os.environ["TEST_MYSQL_PORT"]),
            user="root", database="career_verify", charset="utf8mb4", autocommit=True,
            cursorclass=pymysql.cursors.DictCursor)
        self.store = MySQLChatStore(self.factory, retention_hours=1)
        self.jobs = MySQLJobRepository(self.factory, include_unverified=True)
        self.model = FakeModel()
        self.token = secrets.token_hex(32)
        self.auth = "integration-test-only-" + "x" * 32
        self.environment = patch.dict(os.environ, {"CHAT_API_TOKEN": self.auth,
             "CHAT_INCLUDE_UNVERIFIED": "true", "CHAT_RETENTION_HOURS": "1"})
        self.environment.start()

    def tearDown(self):
        self.environment.stop()

    def request(self, payload, token=None):
        return handle_request({"headers": {"Authorization": "Bearer " + self.auth,
                                           "X-Client-Token": token or self.token}, "body": json.dumps(payload)},
                              jobs=self.jobs, store=self.store, planner=self.model, questioner=self.model)

    def start(self):
        request = {"action": "search", "request_id": str(uuid4()),
                   "search_plan": {"skills": ["Python"], "limit": 3}}
        result = self.request(request)
        self.assertEqual(result["statusCode"], 200, result)
        body = json.loads(result["body"])
        self.assertGreater(body["total"], 0)
        return request, body

    def select(self):
        _, start = self.start()
        payload = {"action": "select", "session_id": start["session_id"], "request_id": str(uuid4()),
                   "source_id": start["candidate_jobs"][0]["source_id"]}
        response = self.request(payload)
        self.assertEqual(response["statusCode"], 200, response)
        return payload, json.loads(response["body"])

    def test_search_isolation_cache_and_changed_request_id_payload(self):
        payload, first = self.start()
        replay = json.loads(self.request(payload)["body"])
        self.assertTrue(replay["cached"])
        self.assertEqual(replay["session_id"], first["session_id"])
        changed = dict(payload, session_id=first["session_id"], search_plan={"skills": ["Java"]})
        self.assertEqual(self.request(changed)["statusCode"], 409)
        other_user = {"action": "select", "session_id": first["session_id"], "request_id": str(uuid4()),
                      "source_id": first["candidate_jobs"][0]["source_id"]}
        self.assertEqual(self.request(other_user, token=secrets.token_hex(32))["statusCode"], 404)

    def test_required_preferred_evidence_and_cache_do_not_duplicate_model_call(self):
        select_payload, body = self.select()
        self.assertEqual(body["stage"], "checking_required")
        repeated = json.loads(self.request(select_payload)["body"])
        self.assertTrue(repeated["cached"])
        session_id = body["session_id"]
        with self.factory() as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT COUNT(*) AS n FROM model_invocations WHERE session_id=%s", (session_id,))
                self.assertEqual(cursor.fetchone()["n"], 1)
        answer = {"action": "answer", "session_id": session_id, "request_id": str(uuid4()),
                  "question_id": body["question_id"], "assessment": "met", "detail": "검증용 사용자 진술"}
        next_response = self.request(answer)
        self.assertEqual(next_response["statusCode"], 200, next_response)
        next_body = json.loads(next_response["body"])
        self.assertEqual(next_body["stage"], "checking_preferred")
        unknown = dict(answer, request_id=str(uuid4()), question_id=next_body["question_id"], assessment="unknown")
        completed = json.loads(self.request(unknown)["body"])
        self.assertEqual(completed["stage"], "completed")
        self.assertEqual(completed["unconfirmed_count"], 1)
        with self.factory() as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT COUNT(*) AS n FROM recommendation_evidence e JOIN chat_messages m ON m.message_id=e.message_id WHERE m.session_id=%s", (session_id,))
                self.assertEqual(cursor.fetchone()["n"], 2)
                cursor.execute("SELECT SUM(input_tokens) AS n FROM model_invocations WHERE session_id=%s", (session_id,))
                self.assertEqual(int(cursor.fetchone()["n"]), 20)

    def test_model_failure_recorded_and_retry_after_abort(self):
        _, start = self.start()
        payload = {"action": "select", "session_id": start["session_id"], "request_id": str(uuid4()),
                   "source_id": start["candidate_jobs"][0]["source_id"]}
        self.model.fail = True
        self.assertEqual(self.request(payload)["statusCode"], 502)
        self.model.fail = False
        self.assertEqual(self.request(dict(payload, request_id=str(uuid4())))["statusCode"], 200)
        with self.factory() as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT status FROM model_invocations WHERE session_id=%s", (start["session_id"],))
                self.assertEqual(sorted(row["status"] for row in cursor.fetchall()), ["failed", "succeeded"])

    def test_session_lease_blocks_concurrent_requests_and_releases(self):
        _, first = self.start()
        owner = hmac.new(self.auth.encode(), self.token.encode(), hashlib.sha256).hexdigest()
        payload = {"action": "select", "session_id": first["session_id"], "request_id": str(uuid4()),
                   "source_id": first["candidate_jobs"][0]["source_id"]}
        ticket = self.store.begin(owner, payload)
        with self.assertRaises(FlowError) as error:
            self.store.begin(owner, dict(payload, request_id=str(uuid4())))
        self.assertEqual(error.exception.code, "session_busy_retry_later")
        self.store.abort(ticket)
        self.assertEqual(self.request(payload)["statusCode"], 200)

    def test_expired_session_cannot_be_read(self):
        _, first = self.start()
        with self.factory() as connection:
            with connection.cursor() as cursor:
                cursor.execute("UPDATE chat_sessions SET expires_at=UTC_TIMESTAMP(6)-INTERVAL 1 SECOND WHERE session_id=%s", (first["session_id"],))
        payload = {"action": "select", "session_id": first["session_id"], "request_id": str(uuid4()),
                   "source_id": first["candidate_jobs"][0]["source_id"]}
        self.assertEqual(self.request(payload)["statusCode"], 404)


    def test_memory_survives_database_round_trip_and_research_in_same_session(self):
        _, first = self.start()
        request = {"action": "search", "session_id": first["session_id"], "request_id": str(uuid4()),
                   "search_plan": {"skills": ["Python"]}, "profile": {"user_statement": "MySQL 프로젝트 경험이 있어요"}}
        self.assertEqual(self.request(request)["statusCode"], 200)
        payload = {"action": "select", "session_id": first["session_id"], "request_id": str(uuid4()),
                   "source_id": first["candidate_jobs"][0]["source_id"]}
        selected = json.loads(self.request(payload)["body"])
        answer = {"action": "answer", "session_id": first["session_id"], "request_id": str(uuid4()),
                  "question_id": selected["question_id"], "assessment": "met", "detail": "Python API를 개발했어요"}
        self.assertEqual(self.request(answer)["statusCode"], 200)
        # A fresh request reloads state from MySQL rather than sharing a Python dict.
        request = dict(request, request_id=str(uuid4()), profile={})
        self.assertEqual(self.request(request)["statusCode"], 200)
        with self.factory() as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT profile_snapshot FROM chat_sessions WHERE session_id=%s", (first["session_id"],))
                value = json.loads(cursor.fetchone()["profile_snapshot"])
                self.assertTrue(any("MySQL" in item["text"] for item in value["memory"]["statements"]))
                self.assertTrue(value["memory"]["confirmed"])
        resumed = json.loads(self.request(dict(payload, request_id=str(uuid4())))["body"])
        self.assertEqual(resumed["stage"], "checking_preferred")


    def test_existing_session_model_call_cap_is_preserved(self):
        self.store = MySQLChatStore(self.factory, retention_hours=1, max_calls=1)
        _, body = self.select()
        request = {"action": "answer", "session_id": body["session_id"], "request_id": str(uuid4()),
                   "question_id": body["question_id"], "assessment": "met"}
        response = self.request(request)
        self.assertEqual(response["statusCode"], 429)
        self.assertEqual(json.loads(response["body"])["status"], "session_model_budget_exceeded")
        with self.factory() as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT model_call_count FROM chat_sessions WHERE session_id=%s", (body["session_id"],))
                self.assertEqual(cursor.fetchone()["model_call_count"], 1)

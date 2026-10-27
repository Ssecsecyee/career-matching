"""MySQL sessions, per-request leases, replay cache and evidence transactions."""
import hashlib
import json
import time
from datetime import datetime, timedelta, timezone
from uuid import uuid4, uuid5, NAMESPACE_URL

from src.services.dialogue import FlowError
from src.services.memory import memory, restore_user_statements


def packed(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def unpacked(value):
    return json.loads(value) if isinstance(value, (str, bytes)) else (value or {})


def now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class MySQLChatStore:
    def __init__(self, factory, *, retention_hours, max_calls=12):
        if not 1 <= retention_hours <= 168:
            raise ValueError("Set retention hours between 1 and 168")
        self.factory, self.hours, self.max_calls = factory, retention_hours, max_calls

    def begin(self, owner, payload):
        request_id = payload["request_id"]
        session_id = payload.get("session_id") or str(uuid5(NAMESPACE_URL, owner + ":" + request_id))
        fingerprint = hashlib.sha256(packed(payload).encode()).hexdigest()
        cache_key = hashlib.sha256((session_id + ":" + request_id).encode()).hexdigest()
        connection = self.factory()
        try:
            connection.begin()
            with connection.cursor() as cur:
                if not payload.get("session_id"):
                    if payload["action"] != "search":
                        raise FlowError("search_required_to_start_session")
                    cur.execute("INSERT IGNORE INTO chat_sessions(session_id,owner_scope,requirement_answers,expires_at) VALUES(%s,%s,%s,%s)",
                                (session_id, owner, "{}", now() + timedelta(hours=self.hours)))
                cur.execute("SELECT * FROM chat_sessions WHERE session_id=%s AND owner_scope=%s FOR UPDATE", (session_id, owner))
                row = cur.fetchone()
                if not row or row["expires_at"] <= now():
                    raise FlowError("session_not_found_or_expired", 404)
                cur.execute("SELECT payload FROM response_cache WHERE scope_key=%s AND cache_kind='response' AND cache_key=%s AND expires_at>UTC_TIMESTAMP(6) AND invalidated_at IS NULL",
                            (owner, cache_key))
                cached = cur.fetchone()
                if cached:
                    cached = unpacked(cached["payload"])
                    if cached["fingerprint"] != fingerprint:
                        raise FlowError("request_id_reused_with_different_content", 409)
                    connection.commit()
                    return {"cached": cached["response"]}
                cur.execute("SELECT structured_content FROM chat_messages WHERE session_id=%s AND idempotency_key=%s AND role='user'", (session_id, request_id))
                if cur.fetchone():
                    raise FlowError("request_replay_expired_use_new_request_id", 409)
                state = unpacked(row["requirement_answers"])
                if state.get("_lease", {}).get("until", 0) > time.time():
                    raise FlowError("session_busy_retry_later", 409)
                if row["model_call_count"] >= self.max_calls:
                    raise FlowError("session_model_budget_exceeded", 429)
                if not memory(state).get('user_history_version'):
                    cur.execute("SELECT sequence_no, structured_content FROM chat_messages WHERE session_id=%s AND role='user' ORDER BY sequence_no DESC LIMIT 80", (session_id,))
                    rows = cur.fetchall()
                    restore_user_statements(state, [(item['sequence_no'], unpacked(item['structured_content'])) for item in reversed(rows)])
                state["_lease"] = {"request": request_id, "until": time.time() + 90}
                cur.execute("UPDATE chat_sessions SET requirement_answers=%s WHERE session_id=%s", (packed(state), session_id))
            connection.commit()
            return {"session_id": session_id, "owner": owner, "request_id": request_id,
                    "fingerprint": fingerprint, "cache_key": cache_key,
                    "state": state, "state_version": row["state_version"],
                    "expires_at": row["expires_at"], "calls_remaining": self.max_calls - row["model_call_count"]}
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def begin_invocation(self, ticket, purpose, model, region, prompt_version, inputs):
        identity = str(uuid4())
        connection = self.factory()
        try:
            connection.begin()
            with connection.cursor() as cur:
                cur.execute("UPDATE chat_sessions SET model_call_count=model_call_count+1 WHERE session_id=%s AND owner_scope=%s AND model_call_count<%s",
                            (ticket["session_id"], ticket["owner"], self.max_calls))
                if cur.rowcount != 1:
                    raise FlowError("session_model_budget_exceeded", 429)
                cur.execute("INSERT INTO model_invocations(invocation_id,session_id,request_id,purpose,model_id,region,prompt_version,policy_version,input_fingerprint,status,started_at,expires_at) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,'pending',%s,%s)",
                            (identity, ticket["session_id"], ticket["request_id"], purpose, model, region,
                             prompt_version, "dialogue-memory-v2", hashlib.sha256(packed(inputs).encode()).hexdigest(), now(), ticket["expires_at"]))
            connection.commit()
            return identity
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def finish_invocation(self, ticket, identity, usage=None, error_code=None):
        usage = usage or {}
        connection = self.factory()
        try:
            connection.begin()
            with connection.cursor() as cur:
                cur.execute("UPDATE model_invocations SET status=%s,input_tokens=%s,output_tokens=%s,cache_read_input_tokens=%s,cache_write_input_tokens=%s,latency_ms=%s,provider_request_id=%s,error_code=%s,finished_at=%s WHERE invocation_id=%s AND session_id=%s",
                            ("failed" if error_code else "succeeded", usage.get("input_tokens"), usage.get("output_tokens"),
                             usage.get("cache_read_input_tokens"), usage.get("cache_write_input_tokens"), usage.get("latency_ms"),
                             usage.get("provider_request_id"), error_code, now(), identity, ticket["session_id"]))
                cur.execute("UPDATE chat_sessions SET cumulative_input_tokens=cumulative_input_tokens+%s,cumulative_output_tokens=cumulative_output_tokens+%s WHERE session_id=%s",
                            (usage.get("input_tokens") or 0, usage.get("output_tokens") or 0, ticket["session_id"]))
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def finish(self, ticket, payload, state, response, evidence):
        state.pop("_lease", None)
        response = dict(response, session_id=ticket["session_id"], state_version=ticket["state_version"] + 1,
                        request_id=ticket["request_id"], cached=False)
        connection = self.factory()
        try:
            connection.begin()
            with connection.cursor() as cur:
                self._lock_ticket(cur, ticket)
                cur.execute("UPDATE chat_sessions SET stage=%s,selected_job_ids=%s,profile_snapshot=%s,requirement_answers=%s,state_version=state_version+1 WHERE session_id=%s",
                            (state["stage"], packed([state["selected"]["source_id"]] if state.get("selected") else []),
                             packed(state.get("profile", {})), packed(state), ticket["session_id"]))
                cur.execute("SELECT COALESCE(MAX(sequence_no),0) AS n FROM chat_messages WHERE session_id=%s", (ticket["session_id"],))
                sequence = int(cur.fetchone()["n"])
                for offset, role, content in ((1, "user", payload), (2, "assistant", response)):
                    cur.execute("INSERT INTO chat_messages(session_id,sequence_no,idempotency_key,role,content,structured_content,stage,expires_at) VALUES(%s,%s,%s,%s,%s,%s,%s,%s)",
                                (ticket["session_id"], sequence + offset, ticket["request_id"], role,
                                 packed(content), packed(content), state["stage"], ticket["expires_at"]))
                message_id = cur.lastrowid
                for item in evidence:
                    job, check = item["job"], item["check"]
                    cur.execute("INSERT INTO recommendation_evidence(message_id,subject_type,subject_id,source_version,source_url,requirement_type,requirement_snapshot,source_section,evidence_quote,user_fact_snapshot,assessment_status,explanation,validation_status,rule_version,expires_at) VALUES(%s,'job',%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'validated','dialogue-memory-v2',%s)",
                                (message_id, job["job_id"], job["source_version"], job["source_url"], check["type"],
                                 packed({"section": item["section"], "quote": check["quote"]}), item["section"], check["quote"],
                                 packed({"assessment": check["assessment"], "detail": check["detail"]}),
                                 check["assessment"], check["explanation"], ticket["expires_at"]))
                cur.execute("INSERT INTO response_cache(scope_key,cache_kind,cache_key,session_id,session_state_version,profile_version,stage,policy_version,data_generation,dependency_versions,payload,expires_at) VALUES(%s,'response',%s,%s,%s,1,%s,'dialogue-memory-v2',1,%s,%s,%s)",
                            (ticket["owner"], ticket["cache_key"], ticket["session_id"], ticket["state_version"] + 1,
                             state["stage"], packed({state["selected"]["source_id"]: state["selected"]["source_version"]} if state.get("selected") else {}),
                             packed({"fingerprint": ticket["fingerprint"], "response": response}),
                             min(ticket["expires_at"], now() + timedelta(minutes=10))))
            connection.commit()
            return response
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _lock_ticket(self, cur, ticket):
        cur.execute("SELECT state_version,requirement_answers FROM chat_sessions WHERE session_id=%s AND owner_scope=%s FOR UPDATE",
                    (ticket["session_id"], ticket["owner"]))
        current = cur.fetchone()
        if (not current or current["state_version"] != ticket["state_version"] or
                unpacked(current["requirement_answers"]).get("_lease", {}).get("request") != ticket["request_id"]):
            raise FlowError("session_state_conflict", 409)

    def abort(self, ticket):
        connection = self.factory()
        try:
            connection.begin()
            with connection.cursor() as cur:
                self._lock_ticket(cur, ticket)
                cur.execute("SELECT requirement_answers FROM chat_sessions WHERE session_id=%s", (ticket["session_id"],))
                state = unpacked(cur.fetchone()["requirement_answers"])
                state.pop("_lease", None)
                cur.execute("UPDATE chat_sessions SET requirement_answers=%s WHERE session_id=%s", (packed(state), ticket["session_id"]))
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

"""Independent, lease/owner-checked routing audit transactions. No public raw log endpoint."""
import json
from uuid import uuid4
from src.schemas.intent import INTENT_VERSION
from src.services.intent_context import redact
from src.services.dialogue import FlowError


def packed(value):return json.dumps(redact(value),ensure_ascii=False,separators=(',',':'),allow_nan=False)


class IntentDecisionStore:
    def __init__(self,factory):self.factory=factory

    @staticmethod
    def lock(cur,ticket):
        cur.execute('SELECT state_version,requirement_answers FROM chat_sessions WHERE session_id=%s AND owner_scope=%s FOR UPDATE',
                    (ticket['session_id'],ticket['owner']))
        row=cur.fetchone()
        state=json.loads(row['requirement_answers']) if row and isinstance(row['requirement_answers'],(str,bytes)) else (row or {}).get('requirement_answers',{})
        if not row or row['state_version']!=ticket['state_version'] or state.get('_lease',{}).get('request')!=ticket['request_id']:
            raise FlowError('intent_audit_session_conflict',409)

    def start(self,ticket,source,context):
        identity=str(uuid4());connection=self.factory()
        snapshot=packed(context)
        if len(snapshot)>20000:raise ValueError('Audit snapshot exceeds budget')
        try:
            connection.begin()
            with connection.cursor() as cur:
                self.lock(cur,ticket)
                cur.execute('SELECT COALESCE(MAX(attempt_no),0)+1 AS n FROM intent_decisions WHERE session_id=%s AND request_id=%s',
                            (ticket['session_id'],ticket['request_id']))
                attempt=int(cur.fetchone()['n'])
                cur.execute('INSERT INTO intent_decisions(decision_id,session_id,request_id,attempt_no,decision_source,context_snapshot,policy_version,expires_at) VALUES(%s,%s,%s,%s,%s,%s,%s,%s)',
                            (identity,ticket['session_id'],ticket['request_id'],attempt,source,snapshot,INTENT_VERSION,ticket['expires_at']))
            connection.commit();return identity
        except Exception:
            connection.rollback();raise
        finally:connection.close()

    def classified(self,ticket,identity,raw,decision,*,valid=True):
        connection=self.factory()
        try:
            connection.begin()
            with connection.cursor() as cur:
                self.lock(cur,ticket)
                cur.execute('UPDATE intent_decisions SET model_invocation_id=%s,raw_output=%s,validated_decision=%s,validation_status=%s,executed_action=%s WHERE decision_id=%s AND session_id=%s AND request_id=%s',
                    (ticket.get('_intent_invocation_id'),redact(raw)[:12000] if raw is not None else None,
                     packed(decision) if decision is not None else None,'validated' if valid else 'invalid',
                     (decision or {}).get('action') or (decision or {}).get('direct_action'),identity,ticket['session_id'],ticket['request_id']))
            connection.commit()
        except Exception:
            connection.rollback();raise
        finally:connection.close()

    def finish(self,ticket,identity,result=None,error=None):
        # Called after chat commit or before abort. Owner checked without requiring an active lease.
        summary={k:(result or {}).get(k) for k in ('stage','total','remaining_total','search_backend','clarification_required','search_attempts')}
        summary['selected_job']={k:(result or {}).get('active_job',{}).get(k) for k in ('source_id','source_version')}
        summary['displayed_jobs']=len((result or {}).get('candidate_jobs',[]))
        summary['displayed_courses']=len((result or {}).get('learning_opportunities',[]))
        connection=self.factory()
        try:
            connection.begin()
            with connection.cursor() as cur:
                cur.execute('UPDATE intent_decisions i JOIN chat_sessions s ON s.session_id=i.session_id SET i.execution_status=%s,i.result_summary=%s,i.error_code=%s,i.model_invocation_id=COALESCE(i.model_invocation_id,%s),i.finished_at=UTC_TIMESTAMP(6) WHERE i.decision_id=%s AND i.session_id=%s AND i.request_id=%s AND s.owner_scope=%s',
                    ('failed' if error else 'succeeded',packed(summary),error,ticket.get('_intent_invocation_id'),identity,ticket['session_id'],ticket['request_id'],ticket['owner']))
            connection.commit()
        except Exception:
            connection.rollback();raise
        finally:connection.close()

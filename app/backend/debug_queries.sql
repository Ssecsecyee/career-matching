-- DBeaver SQL editor: choose career_matching / 127.0.0.1:13308.
-- Read-only investigation. SET changes connection variables only, not DB rows.
-- All recorded DATETIME values below follow the application's UTC convention.

-- 1. Find the conversation by latest activity. Copy its session_id.
SELECT session_id, stage, selected_job_ids, model_call_count,
       cumulative_input_tokens, cumulative_output_tokens,
       DATE_ADD(created_at, INTERVAL 9 HOUR) AS created_at_kst,
       DATE_ADD(updated_at, INTERVAL 9 HOUR) AS updated_at_kst,
       expires_at AS expires_at_utc
FROM chat_sessions
ORDER BY updated_at DESC
LIMIT 20;

-- 2. Replace the placeholder with the copied UUID; execute in this same editor/connection.
SET @debug_session_id = 'PASTE_SESSION_UUID_HERE';

-- 3. Read the user text and application replies in order.
-- An answer_batch has no message string; its answers JSON carries the response.
SELECT message_id, sequence_no, role, idempotency_key AS request_id, stage,
       JSON_UNQUOTE(JSON_EXTRACT(structured_content, '$.action')) AS action,
       JSON_UNQUOTE(JSON_EXTRACT(structured_content, '$.message')) AS message,
       JSON_UNQUOTE(JSON_EXTRACT(structured_content, '$.question')) AS question,
       JSON_PRETTY(JSON_EXTRACT(structured_content, '$.answers')) AS batch_answers,
       JSON_PRETTY(JSON_EXTRACT(structured_content, '$.checks')) AS final_checks,
       DATE_ADD(created_at, INTERVAL 9 HOUR) AS created_at_kst
FROM chat_messages
WHERE session_id = @debug_session_id
ORDER BY sequence_no
LIMIT 200;

-- 4. Full request/response JSON if the concise columns did not explain the symptom.
-- Do not publish these results; they can contain private user statements.
SELECT message_id, sequence_no, role,
       JSON_PRETTY(structured_content) AS request_or_response_json
FROM chat_messages
WHERE session_id = @debug_session_id
ORDER BY sequence_no
LIMIT 200;

-- 5. CURRENT memory, selected job and all saved criterion checks.
-- This is not the exact historical model prompt at every earlier call.
SELECT stage, state_version,
       JSON_PRETTY(JSON_EXTRACT(profile_snapshot, '$.memory.user_statements')) AS user_statements,
       JSON_PRETTY(JSON_EXTRACT(profile_snapshot, '$.memory.facts')) AS extracted_facts,
       JSON_PRETTY(JSON_EXTRACT(profile_snapshot, '$.memory.statements')) AS recent_statements,
       JSON_PRETTY(JSON_EXTRACT(requirement_answers, '$.selected')) AS selected_job,
       JSON_PRETTY(JSON_EXTRACT(requirement_answers, '$.checks')) AS all_checks
FROM chat_sessions
WHERE session_id = @debug_session_id;

-- 6. Original source + explicit user assessment for this conversation.
-- subject_id is the internal job_id, not the site's source_id.
SELECT e.evidence_record_id, m.sequence_no, m.idempotency_key AS request_id,
       j.source, j.source_id, j.company_name, j.title,
       e.requirement_type, e.assessment_status, e.evidence_quote,
       JSON_PRETTY(e.user_fact_snapshot) AS user_answer,
       e.explanation, e.validation_status,
       e.source_version AS assessed_source_version,
       j.source_version AS current_source_version,
       e.source_url
FROM recommendation_evidence e
JOIN chat_messages m ON m.message_id = e.message_id
LEFT JOIN job_postings j ON e.subject_type = 'job' AND j.job_id = e.subject_id
WHERE m.session_id = @debug_session_id
ORDER BY m.sequence_no, e.evidence_record_id;

-- 7. Model calls. Failed requests can have a call row but no saved message pair.
SELECT invocation_id, request_id, purpose, status, error_code,
       model_id, region, prompt_version, policy_version,
       input_tokens, output_tokens, cache_read_input_tokens, cache_write_input_tokens,
       latency_ms, provider_request_id,
       DATE_ADD(started_at, INTERVAL 9 HOUR) AS started_at_kst,
       DATE_ADD(finished_at, INTERVAL 9 HOUR) AS finished_at_kst
FROM model_invocations
WHERE session_id = @debug_session_id
ORDER BY started_at, invocation_id;

-- 8. Summarize assessments. This is user self-assessment, not verified competence.
SELECT e.requirement_type, e.assessment_status, COUNT(*) AS criterion_records
FROM recommendation_evidence e
JOIN chat_messages m ON m.message_id = e.message_id
WHERE m.session_id = @debug_session_id
GROUP BY e.requirement_type, e.assessment_status;
-- Rechecking/reselecting can create more than one evidence record for a criterion.
-- For the latest single evaluation, use requirement_answers.checks from query 5.

-- 9. Cache entries. A row count is not a cache-hit count.
SELECT cache_id, cache_kind, stage, session_state_version,
       dependency_versions, invalidated_at, expires_at,
       CASE WHEN invalidated_at IS NULL AND expires_at > UTC_TIMESTAMP(6)
            THEN 'within_time_window' ELSE 'expired_or_invalidated' END AS time_status,
       JSON_UNQUOTE(JSON_EXTRACT(payload, '$.response.request_id')) AS request_id
FROM response_cache
WHERE session_id = @debug_session_id
ORDER BY cache_id DESC
LIMIT 50;

-- 10. Focus on one successful request; replace with the request_id from query 3 or 7.
SET @debug_request_id = 'PASTE_REQUEST_UUID_HERE';
SELECT message_id, role, JSON_PRETTY(structured_content) AS payload
FROM chat_messages
WHERE session_id = @debug_session_id AND idempotency_key = @debug_request_id
ORDER BY sequence_no;

SELECT purpose, status, error_code, prompt_version, input_tokens, output_tokens, input_fingerprint
FROM model_invocations
WHERE session_id = @debug_session_id AND request_id = @debug_request_id
ORDER BY started_at;
-- input_fingerprint is a hash; the complete model prompt is not stored here.

-- 11. Per-session application usage, including recorded failures.
SELECT purpose, status, COUNT(*) AS calls,
       COALESCE(SUM(input_tokens), 0) AS input_tokens,
       COALESCE(SUM(output_tokens), 0) AS output_tokens,
       ROUND(AVG(latency_ms)) AS average_latency_ms
FROM model_invocations
WHERE session_id = @debug_session_id
GROUP BY purpose, status;

-- 12. Recent failures across conversations (metadata only).
SELECT session_id, request_id, purpose, error_code, prompt_version,
       input_tokens, output_tokens, DATE_ADD(started_at, INTERVAL 9 HOUR) AS started_at_kst
FROM model_invocations
WHERE status = 'failed'
ORDER BY started_at DESC
LIMIT 30;

-- Run inside DBeaver connected to career_matching, not CMD.
-- Read-only examples; audit rows are restricted operational records.
SELECT decision_id,session_id,request_id,attempt_no,decision_source,
       validation_status,executed_action,execution_status,error_code,policy_version,created_at
FROM intent_decisions ORDER BY created_at DESC LIMIT 30;

SELECT executed_action,validation_status,execution_status,COUNT(*) AS n
FROM intent_decisions WHERE created_at>=UTC_TIMESTAMP()-INTERVAL 1 DAY
GROUP BY executed_action,validation_status,execution_status;

SELECT i.decision_id,i.context_snapshot,i.validated_decision,i.result_summary,
       m.model_id,m.purpose,m.status,m.input_tokens,m.output_tokens,m.error_code AS model_error
FROM intent_decisions i LEFT JOIN model_invocations m ON m.invocation_id=i.model_invocation_id
ORDER BY i.created_at DESC LIMIT 20;

-- Raw classifier output is private debugging material; inspect only a selected row.
-- SELECT raw_output FROM intent_decisions WHERE decision_id='replace-with-decision-id';

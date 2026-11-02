"""Read-only admin intent views. No arbitrary SQL and no bulk raw/context payloads."""
import json
from uuid import UUID
from src.services.dialogue import FlowError
from src.services.intent_context import redact

VALIDATION={'pending','validated','invalid'}
EXECUTION={'pending','succeeded','failed'}
BASE={'action','request_id','operation'}
ID_FIELDS={'session_id','filter_request_id','decision_id'}
META=('decision_id','session_id','request_id','attempt_no','decision_source',
      'model_invocation_id','validation_status','executed_action','execution_status',
      'error_code','policy_version','created_at','finished_at','expires_at')
MODEL='m.model_id,m.purpose AS model_purpose,m.status AS model_status,m.input_tokens,m.output_tokens,m.latency_ms'
JOIN=' LEFT JOIN model_invocations m ON m.invocation_id=i.model_invocation_id AND m.session_id=i.session_id AND m.request_id=i.request_id'


def validate(value):
    operation=value['operation']
    allowed=({'offset','session_id','filter_request_id','validation_status','execution_status'} if operation=='intent_rows' else {'decision_id','include_raw'})
    if set(value)-BASE-allowed:raise ValueError('Unexpected intent query fields')
    for field in ID_FIELDS & set(value):
        if not isinstance(value[field],str) or len(value[field])!=36:raise ValueError('Invalid intent query ID')
        UUID(value[field])
    if operation=='intent_rows':
        if type(value.get('offset',0)) is not int or not 0<=value.get('offset',0)<=1000000:raise ValueError('Invalid intent offset')
        if 'validation_status' in value and (not isinstance(value['validation_status'],str) or value['validation_status'] not in VALIDATION):raise ValueError('Invalid validation status')
        if 'execution_status' in value and (not isinstance(value['execution_status'],str) or value['execution_status'] not in EXECUTION):raise ValueError('Invalid execution status')
    else:
        if 'decision_id' not in value or type(value.get('include_raw',False)) is not bool:raise ValueError('Invalid intent detail')
    return value


def bounded(value,budget):
    if isinstance(value,(str,bytes)):
        try:value=json.loads(value)
        except (ValueError,TypeError):
            if isinstance(value,bytes):value=value.decode('utf-8',errors='replace')
    value=redact(value)
    encoded=json.dumps(value,ensure_ascii=False,default=str).encode('utf-8')
    if len(encoded)<=budget:return value,False
    return {'preview':encoded[:budget].decode('utf-8',errors='ignore'),'truncated':True,'original_bytes':len(encoded)},True


def query(connection,payload):
    validate(payload)
    if payload['operation']=='intent_rows':
        conditions=['i.expires_at>UTC_TIMESTAMP(6)'];params=[]
        for field,column in [('session_id','session_id'),('filter_request_id','request_id')]:
            if payload.get(field):conditions.append('i.'+column+'=%s');params.append(str(UUID(payload[field])))
        for field in ('validation_status','execution_status'):
            if payload.get(field):conditions.append('i.'+field+'=%s');params.append(payload[field])
        where=' WHERE '+' AND '.join(conditions)
        with connection.cursor() as cur:
            cur.execute('SELECT COUNT(*) AS n FROM intent_decisions i'+where,params);total=int(cur.fetchone()['n'])
            columns=','.join('i.'+field for field in META)
            cur.execute('SELECT '+columns+",JSON_UNQUOTE(JSON_EXTRACT(i.validated_decision,'$.target')) AS target,JSON_UNQUOTE(JSON_EXTRACT(i.validated_decision,'$.action')) AS decision_action,JSON_UNQUOTE(JSON_EXTRACT(i.validated_decision,'$.reason')) AS decision_reason,"+MODEL+' FROM intent_decisions i'+JOIN+where+' ORDER BY i.created_at DESC,i.decision_id DESC LIMIT %s OFFSET %s',params+[25,payload.get('offset',0)])
            rows=cur.fetchall()
        for row in rows:
            if isinstance(row.get('decision_reason'),str):row['decision_reason']=redact(row['decision_reason'])[:500]
        return {'status':'ok','rows':rows,'total':total,'offset':payload.get('offset',0),'page_size':25,'unexpired_only':True}
    include_raw=payload.get('include_raw',False)
    fields=list(META)+['context_snapshot','validated_decision','result_summary']
    if include_raw:fields.append('raw_output')
    with connection.cursor() as cur:
        cur.execute('SELECT '+','.join('i.'+field for field in fields)+','+MODEL+' FROM intent_decisions i'+JOIN+' WHERE i.decision_id=%s AND i.expires_at>UTC_TIMESTAMP(6)',(str(UUID(payload['decision_id'])),))
        row=cur.fetchone()
    if not row:raise FlowError('admin_intent_not_found_or_expired',404)
    truncated=[]
    for field,budget in [('context_snapshot',24000),('validated_decision',16000),('result_summary',8000),('raw_output',16000)]:
        if field in row:
            row[field],cut=bounded(row[field],budget)
            if cut:truncated.append(field)
    return {'status':'ok','record':row,'raw_included':include_raw,'truncated_fields':truncated,'unexpired_only':True}

"""Allowlisted administrative views and audited status management; no SQL console."""
from datetime import datetime
from decimal import Decimal
import hashlib
import json
from uuid import UUID
from src.services.dialogue import FlowError

TABLES={
 'job_postings':('채용공고 원본', 'job_id', 'job_id source source_id source_version title company_name recruitment_status deadline_type deadline_at fetched_at last_seen_at updated_at qualifications preferred_requirements application_notes tech_stacks additional_sections'),
 'training_offerings':('교육 과정', 'offering_id','offering_id source source_id source_version title provider_name curriculum learning_topics recruitment_status starts_at ends_at application_deadline updated_at'),
 'chat_sessions':('대화 세션', 'updated_at','session_id stage model_call_count state_version expires_at created_at updated_at'),
 'chat_messages':('사용자·도우미 메시지', 'message_id','message_id session_id sequence_no role content stage created_at expires_at'),
 'recommendation_evidence':('조건 답변과 근거', 'evidence_record_id','evidence_record_id message_id subject_type subject_id source_version source_url evidence_quote assessment_status explanation created_at expires_at'),
 'model_invocations':('모델 호출·토큰·오류', 'started_at','invocation_id session_id request_id purpose model_id status input_tokens output_tokens cache_read_input_tokens cache_write_input_tokens latency_ms error_code started_at finished_at'),
 'response_cache':('앱 응답 캐시 메타데이터', 'cache_id','cache_id cache_kind created_at expires_at invalidated_at'),
 'search_outbox':('DB→검색 동기화 작업', 'event_id','event_id entity_type entity_id source_version operation attempt_count last_error created_at processed_at'),
 'admin_audit':('관리자 변경 기록', 'audit_id','audit_id request_id action entity_id reason before_value after_value created_at'),
}


def validate_admin(value):
    if not isinstance(value,dict) or set(value)-{'action','request_id','operation','table','offset','session_id','job_id','source_version','reason'}:
        raise ValueError('invalid_admin_request')
    UUID(value.get('request_id',''))
    op=value.get('operation')
    if value.get('action')!='admin' or op not in {'summary','rows','hide_job','restore_job'}:raise ValueError('invalid_admin_operation')
    if op=='rows':
        if value.get('table') not in TABLES or type(value.get('offset',0)) is not int or not 0<=value.get('offset',0)<=1000000:raise ValueError('invalid_admin_page')
        if value.get('session_id'):UUID(value['session_id'])
    if op in {'hide_job','restore_job'}:
        if type(value.get('job_id')) is not int or value['job_id']<1 or type(value.get('source_version')) is not int or value['source_version']<1:raise ValueError('invalid_job_revision')
        if not isinstance(value.get('reason'),str) or not 3<=len(value['reason'].strip())<=500:raise ValueError('admin_reason_required')
    return value


def serial(value):
    if isinstance(value,(datetime,Decimal)):return str(value)
    raise TypeError(type(value).__name__)


def job_hash(row):
    # Same business fields as incremental_jumpit.BUSINESS, excluding provenance.
    fields='source_url title company_name company_url service_info responsibilities qualifications preferred_requirements benefits hiring_process application_notes tech_stacks original_categories role_categories addresses location_text education_text education_source career_source published_at deadline_at deadline_type recruitment_status additional_sections'.split()
    obj={k:row.get(k) for k in fields}
    for k in 'tech_stacks original_categories role_categories addresses education_source career_source additional_sections'.split():
        if isinstance(obj[k],(str,bytes)):obj[k]=json.loads(obj[k])
    return hashlib.sha256(json.dumps(obj,ensure_ascii=False,sort_keys=True,separators=(',',':'),default=lambda x:x.isoformat() if isinstance(x,datetime) else str(x)).encode()).hexdigest()


def execute(factory,payload,actor):
    validate_admin(payload)
    c=factory()
    try:
        op=payload['operation']
        if op=='summary':
            with c.cursor() as cur:
                counts={}
                for table in TABLES:
                    cur.execute('SELECT COUNT(*) AS n FROM '+table);counts[table]=cur.fetchone()['n']
                cur.execute('SELECT model_id,status,COUNT(*) AS calls,COALESCE(SUM(input_tokens),0) AS input_tokens,COALESCE(SUM(output_tokens),0) AS output_tokens,COALESCE(SUM(cache_read_input_tokens),0) AS cache_read_input_tokens,COALESCE(SUM(cache_write_input_tokens),0) AS cache_write_input_tokens FROM model_invocations GROUP BY model_id,status');usage=cur.fetchall()
                cur.execute('SELECT COUNT(*) AS pending,COALESCE(MAX(attempt_count),0) AS max_attempts,MIN(created_at) AS oldest FROM search_outbox WHERE processed_at IS NULL');sync=cur.fetchone()
                cur.execute('SELECT recruitment_status,COUNT(*) AS n FROM job_postings GROUP BY recruitment_status');status=cur.fetchall()
                cur.execute('SELECT COUNT(*) AS n FROM job_postings WHERE recruitment_status IN (\'active\',\'unknown\') AND '+__import__('src.services.deadlines',fromlist=['VISIBLE_SQL']).VISIBLE_SQL);visible=cur.fetchone()['n']
            return {'status':'ok','role':'admin','chat_limit':'unlimited_session_calls','counts':counts,'tables':[{'name':k,'description':v[0]} for k,v in TABLES.items()],'model_usage':usage,'sync':sync,'job_status_counts':status,'visible_jobs':visible,'billing_note':'앱 호출 기록이며 AWS 청구 금액은 아닙니다.'}
        if op=='rows':
            table=payload['table'];_,order,columns=TABLES[table]
            # Tables and columns are code constants. All supplied values are parameters.
            where='';params=[]
            if payload.get('session_id'):
                if table not in {'chat_sessions','chat_messages','model_invocations'}:raise ValueError('unsupported_session_filter')
                where=' WHERE session_id=%s';params.append(payload['session_id'])
            with c.cursor() as cur:
                cur.execute('SELECT COUNT(*) AS n FROM '+table+where,params);total=cur.fetchone()['n']
                cur.execute('SELECT '+','.join(columns.split())+' FROM '+table+where+' ORDER BY '+order+' DESC LIMIT %s OFFSET %s',params+[25,payload.get('offset',0)]);rows=cur.fetchall()
                cur.execute('SELECT COLUMN_NAME AS name,COLUMN_TYPE AS type,COLUMN_COMMENT AS description FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=%s ORDER BY ORDINAL_POSITION',(table,));metadata=[x for x in cur.fetchall() if x['name'] in columns.split()]
            # Bound results below DynamoDB's per-item size; show explicit previews.
            previews=[]
            for row in rows:
                remaining=6000;item={};truncated=[]
                for key,value in row.items():
                    if value is None or isinstance(value,(int,float,bool)):
                        item[key]=value;continue
                    text=value if isinstance(value,str) else json.dumps(value,ensure_ascii=False,default=serial)
                    budget=min(2000,max(0,remaining));raw=text.encode('utf-8')
                    if len(raw)>budget:
                        text=raw[:budget].decode('utf-8',errors='ignore');truncated.append(key)
                    item[key]=text;remaining-=len(text.encode('utf-8'))
                if truncated:item['_truncated_columns']=truncated
                previews.append(item)
            return {'status':'ok','table':table,'rows':previews,'columns':metadata,'total':total,'offset':payload.get('offset',0),'page_size':25}
        c.begin()
        with c.cursor() as cur:
            cur.execute('SELECT * FROM job_postings WHERE job_id=%s FOR UPDATE',(payload['job_id'],));row=cur.fetchone()
            if not row:raise FlowError('admin_job_not_found',404)
            cur.execute('SELECT * FROM admin_audit WHERE request_id=%s',(payload['request_id'],));previous=cur.fetchone()
            fingerprint=hashlib.sha256(json.dumps(payload,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
            if previous:
                if previous['actor_scope']!=actor or previous['fingerprint']!=fingerprint:raise FlowError('admin_request_conflict',409)
                c.rollback();return {'status':'ok','replayed':True,'job_id':payload['job_id']}
            if row['source_version']!=payload['source_version']:raise FlowError('admin_source_changed_refresh',409)
            before={'recruitment_status':row['recruitment_status'],'source_version':row['source_version'],'content_hash':row['content_hash']}
            if op=='hide_job':
                if row['recruitment_status']=='unavailable':raise FlowError('admin_job_already_hidden',409)
                new_status='unavailable'
            else:
                cur.execute("SELECT before_value,after_value FROM admin_audit WHERE entity_id=%s AND action='hide_job' ORDER BY audit_id DESC LIMIT 1",(row['job_id'],));last=cur.fetchone()
                if not last or row['recruitment_status']!='unavailable':raise FlowError('admin_restore_not_available',409)
                old=json.loads(last['before_value']) if isinstance(last['before_value'],str) else last['before_value']
                after=json.loads(last['after_value']) if isinstance(last['after_value'],str) else last['after_value']
                if after['source_version']!=row['source_version']:raise FlowError('admin_source_changed_refresh',409)
                new_status=old['recruitment_status']
            row.update(recruitment_status=new_status,source_version=row['source_version']+1)
            digest=job_hash(row)
            cur.execute('UPDATE job_postings SET recruitment_status=%s,source_version=%s,content_hash=%s WHERE job_id=%s',(new_status,row['source_version'],digest,row['job_id']))
            cur.execute('INSERT INTO search_outbox(entity_type,entity_id,source_version,operation) VALUES(%s,%s,%s,%s)',('job',row['job_id'],row['source_version'],'close' if new_status in {'unavailable','closed'} else 'upsert'))
            after={'recruitment_status':new_status,'source_version':row['source_version'],'content_hash':digest}
            cur.execute('INSERT INTO admin_audit(request_id,actor_scope,fingerprint,action,entity_id,reason,before_value,after_value) VALUES(%s,%s,%s,%s,%s,%s,%s,%s)',(payload['request_id'],actor,fingerprint,op,row['job_id'],payload['reason'].strip(),json.dumps(before),json.dumps(after)))
        c.commit()
        return {'status':'ok','job_id':row['job_id'],'source_version':row['source_version'],'message':'변경을 저장했습니다. 검색 반영까지 약 1분 걸립니다.' }
    except Exception:
        c.rollback();raise
    finally:c.close()

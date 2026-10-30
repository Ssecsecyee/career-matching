"""Isolated local MySQL regression; no model/AWS calls, no existing DB changes."""
import json
import os
from pathlib import Path
import secrets
import sys
from uuid import uuid4
ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'app/backend'))
from src.config import load_local_settings
from src.repositories.mysql_connection import connect_mysql
from src.repositories.mysql_chat import MySQLChatStore,unpacked
from src.handlers.bootstrap import sql_statements
from src.services.dialogue import FlowError
load_local_settings()
assert os.environ['MYSQL_HOST']=='127.0.0.1' and os.environ['MYSQL_PORT']=='3308'
admin=('root',os.environ['MYSQL_ADMIN_PASSWORD'])
database='career_chat_failure_verify_'+secrets.token_hex(5)
root=connect_mysql(credentials=admin)
try:
    with root.cursor() as cur:
        cur.execute('CREATE DATABASE '+database+' CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci')
    root.select_db(database)
    with root.cursor() as cur:
        for sql in sql_statements((ROOT/'app/backend/database/schema.sql').read_text(encoding='utf-8')):cur.execute(sql)
    def factory():
        conn=connect_mysql(credentials=admin);conn.select_db(database);return conn
    store=MySQLChatStore(factory,retention_hours=24)
    payload={'action':'search','request_id':str(uuid4()),'message':'synthetic failed request'}
    ticket=store.begin('test-owner',payload)
    with root.cursor() as cur:
        cur.execute('SELECT role,structured_content FROM chat_messages')
        messages=cur.fetchall()
    assert len(messages)==1 and unpacked(messages[0]['structured_content'])['_delivery']['status']=='received'
    invocation=store.begin_invocation(ticket,'conversation','fake-model','fake-region','test',[])
    store.finish_invocation(ticket,invocation,error_code='ServiceUnavailableException')
    store.abort(ticket,failure={'error_code':'ServiceUnavailableException'})
    with root.cursor() as cur:
        cur.execute('SELECT structured_content FROM chat_messages')
        assert unpacked(cur.fetchone()['structured_content'])['_delivery']['status']=='failed'
    retry=store.begin('test-owner',payload)
    invocation=store.begin_invocation(retry,'conversation','fake-model','fake-region','test',[])
    store.finish_invocation(retry,invocation,usage={})
    state=retry['state'];state['stage']='conversation'
    result=store.finish(retry,payload,state,{'stage':'conversation','message':'synthetic reply'},[])
    assert store.begin('test-owner',payload)['cached']['message']=='synthetic reply'
    try:store.begin('test-owner',dict(payload,message='changed'))
    except FlowError as exc:assert exc.code=='request_id_reused_with_different_content'
    else:raise AssertionError('fingerprint check missing')
    with root.cursor() as cur:
        cur.execute('SELECT role,structured_content FROM chat_messages ORDER BY sequence_no')
        messages=cur.fetchall()
        assert [m['role'] for m in messages]==['user','assistant']
        assert unpacked(messages[0]['structured_content'])['_delivery']['status']=='succeeded'
        cur.execute('SELECT attempt_no,status FROM model_invocations ORDER BY attempt_no')
        assert cur.fetchall()==[{'attempt_no':1,'status':'failed'},{'attempt_no':2,'status':'succeeded'}]
    print(json.dumps({'status':'passed','received_before_model':True,'failure_saved':True,
                      'same_id_retry_no_duplicate':True,'invocation_attempts':2,'success_cache_replay':True,
                      'changed_payload_rejected':True,'existing_database_changes':0,'model_calls':0}))
finally:
    with root.cursor() as cur:cur.execute('DROP DATABASE '+database)
    root.close()

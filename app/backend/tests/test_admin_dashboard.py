import json,os,unittest
from unittest.mock import Mock,patch
from uuid import uuid4
from src.services.admin_auth import authenticate
from src.services.admin import validate_admin,execute
from src.handlers.admin import handle_admin
from src.handlers.queued import handle
from src.repositories.mysql_chat import MySQLChatStore
from src.services.dialogue import FlowError
USER='u'*48;ADMIN='a'*48;CLIENT='c'*64

class Cursor:
 def __init__(self,answers):self.answers=iter(answers);self.sql=[];self.rowcount=1
 def __enter__(self):return self
 def __exit__(self,*args):pass
 def execute(self,sql,params=None):self.sql.append((sql,params))
 def fetchone(self):return next(self.answers)

class AdminTests(unittest.TestCase):
 def test_roles_are_derived_from_distinct_tokens(self):
  headers={'Authorization':'Bearer '+ADMIN,'X-Client-Token':CLIENT,'X-Role':'user'}
  self.assertEqual(authenticate(headers,USER,ADMIN)[2],'admin')
  self.assertIsNone(authenticate(headers,USER,USER))
  self.assertIsNone(authenticate(headers,USER,''))
  headers['Authorization']='Bearer '+USER
  self.assertEqual(authenticate(headers,USER,ADMIN)[2],'user')
  self.assertIsNone(authenticate({'Authorization':'Bearer '+ADMIN},USER,ADMIN))
 def test_normal_token_cannot_reach_admin_or_enqueue(self):
  payload={'action':'admin','operation':'summary','request_id':str(uuid4())}
  with patch.dict(os.environ,{'CHAT_API_TOKEN':USER,'ADMIN_API_TOKEN':ADMIN}):
   event={'headers':{'Authorization':'Bearer '+USER,'X-Client-Token':CLIENT},'body':json.dumps(payload),'requestContext':{'http':{'method':'POST','path':'/api/chat'}}}
   factory=Mock();self.assertEqual(handle_admin(event,factory=factory)['statusCode'],403);factory.assert_not_called()
   queue=Mock();self.assertEqual(handle(event,queue=queue,auth=('owner',CLIENT,'user'))['statusCode'],403);queue.send_message.assert_not_called()
 def test_input_cannot_select_sql_or_privileges(self):
  base={'action':'admin','operation':'rows','request_id':str(uuid4()),'table':'chat_messages'}
  self.assertEqual(validate_admin(base)['table'],'chat_messages')
  for v in [dict(base,table='chat_messages; DROP TABLE job_postings'),dict(base,offset=-1),dict(base,role='admin'),dict(base,sql='SELECT 1')]:
   with self.assertRaises(ValueError):validate_admin(v)
 def test_conflicting_job_version_rolls_back_without_updates(self):
  cur=Cursor([{'job_id':1,'source_version':3},None]);db=Mock();db.cursor.return_value=cur
  with self.assertRaises(FlowError):execute(lambda:db,dict(action='admin',operation='hide_job',request_id=str(uuid4()),job_id=1,source_version=2,reason='test reason'),'actor')
  db.rollback.assert_called();db.commit.assert_not_called();self.assertFalse(any(x[0].startswith('UPDATE') for x in cur.sql))
 def test_outbox_failure_rolls_back_audit_and_job(self):
  row={'job_id':1,'source_version':2,'recruitment_status':'unknown','content_hash':'0'*64}
  cur=Cursor([row,None]);original=cur.execute
  def execute_sql(sql,params=None):
   original(sql,params)
   if sql.startswith('INSERT INTO search_outbox'):raise RuntimeError('fixture outbox failure')
  cur.execute=execute_sql;db=Mock();db.cursor.return_value=cur
  with self.assertRaises(RuntimeError):execute(lambda:db,dict(action='admin',operation='hide_job',request_id=str(uuid4()),job_id=1,source_version=2,reason='test reason'),'actor')
  db.rollback.assert_called();db.commit.assert_not_called()
 def test_admin_invocations_have_no_session_call_predicate(self):
  for limit in [None,12]:
   cur=Cursor([{'n':1}]);db=Mock();db.cursor.return_value=cur
   store=MySQLChatStore(lambda:db,retention_hours=24,max_calls=limit)
   store.begin_invocation({'session_id':str(uuid4()),'owner':'o','request_id':str(uuid4()),'expires_at':None},'conversation','model','region','v',[])
   update=cur.sql[0][0]
   self.assertEqual('model_call_count<' in update,limit is not None)

if __name__=='__main__':unittest.main()

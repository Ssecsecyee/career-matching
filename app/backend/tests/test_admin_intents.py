import json,os,unittest
from unittest.mock import MagicMock,Mock,patch
from uuid import uuid4
from src.services.admin import validate_admin,execute,TABLES
from src.handlers.admin import handle_admin
from src.handlers.queued import handle
from src.services.dialogue import FlowError

USER='u'*48;ADMIN='a'*48;CLIENT='c'*64

class AdminIntentTests(unittest.TestCase):
 def payload(self,**values):return dict(action='admin',request_id=str(uuid4()),**values)
 def database(self,row=None,rows=None):
  conn=MagicMock();cur=conn.cursor.return_value.__enter__.return_value
  cur.fetchone.return_value=row;cur.fetchall.return_value=rows or []
  return conn,cur
 def test_user_and_anonymous_never_reach_new_admin_queries(self):
  for values in [dict(operation='intent_rows'),dict(operation='intent_detail',decision_id=str(uuid4()),include_raw=True)]:
   event={'headers':{'Authorization':'Bearer '+USER,'X-Client-Token':CLIENT},'body':json.dumps(self.payload(**values)), 'requestContext':{'http':{'method':'POST','path':'/api/chat'}}}
   with patch.dict(os.environ,{'CHAT_API_TOKEN':USER,'ADMIN_API_TOKEN':ADMIN}):
    factory=Mock();self.assertEqual(handle_admin(event,factory=factory)['statusCode'],403);factory.assert_not_called()
    queue=Mock();self.assertEqual(handle(event,queue=queue,auth=('owner',CLIENT,'user'))['statusCode'],403);queue.send_message.assert_not_called()
    event['headers']={};self.assertEqual(handle_admin(event,factory=factory)['statusCode'],401)
 def test_strict_filters_and_detail_contract(self):
  for extra in [dict(session_id='not-uuid'),dict(filter_request_id=123),dict(offset=True),dict(offset=-1),dict(validation_status='all'),dict(execution_status=[]),dict(sql='SELECT 1'),dict(table='chat_messages')]:
   with self.subTest(extra=extra),self.assertRaises(ValueError):validate_admin(self.payload(operation='intent_rows',**extra))
  for extra in [dict(include_raw='true'),dict(include_raw=1),dict(decision_id='bad'),dict(session_id=str(uuid4()))]:
   values=dict(decision_id=str(uuid4()),**{k:v for k,v in extra.items() if k!='decision_id'})
   if 'decision_id' in extra:values['decision_id']=extra['decision_id']
   with self.assertRaises(ValueError):validate_admin(self.payload(operation='intent_detail',**values))
 def test_list_is_bounded_parameterized_and_omits_private_fields(self):
  sid,rid=str(uuid4()),str(uuid4());conn,cur=self.database({'n':1},[{'decision_id':str(uuid4()),'decision_reason':'mail a@example.com'}])
  result=execute(lambda:conn,self.payload(operation='intent_rows',session_id=sid,filter_request_id=rid,validation_status='invalid',execution_status='failed',offset=25),'actor')
  count,select=cur.execute.call_args_list
  self.assertIn('expires_at>UTC_TIMESTAMP(6)',count.args[0]);self.assertNotIn(sid,count.args[0])
  self.assertEqual(select.args[1],[sid,rid,'invalid','failed',25,25])
  self.assertIn('LEFT JOIN model_invocations',select.args[0]);self.assertIn('i.created_at DESC,i.decision_id DESC',select.args[0])
  self.assertNotIn('raw_output',select.args[0]);self.assertNotIn('context_snapshot',select.args[0])
  self.assertNotIn('a@example.com',json.dumps(result));conn.commit.assert_not_called();conn.close.assert_called_once()
 def test_default_detail_does_not_even_select_raw_output(self):
  identity=str(uuid4());conn,cur=self.database({'decision_id':identity,'context_snapshot':json.dumps({'email':'a@example.com','token':'private'}),'validated_decision':'{"action":"chat"}','result_summary':'{}'})
  result=execute(lambda:conn,self.payload(operation='intent_detail',decision_id=identity),'actor')
  self.assertFalse(result['raw_included']);self.assertNotIn('raw_output',cur.execute.call_args.args[0])
  self.assertNotIn('private',json.dumps(result));self.assertNotIn('a@example.com',json.dumps(result))
 def test_explicit_raw_is_masked_and_large_fields_are_marked(self):
  identity=str(uuid4());conn,cur=self.database({'decision_id':identity,'context_snapshot':{'large':'가'*20000},'validated_decision':{},'result_summary':{},'raw_output':'{"token":"private","text":"'+('나'*20000)+'"}'})
  result=execute(lambda:conn,self.payload(operation='intent_detail',decision_id=identity,include_raw=True),'actor')
  self.assertTrue(result['raw_included']);self.assertIn('raw_output',cur.execute.call_args.args[0])
  self.assertEqual(set(result['truncated_fields']),{'context_snapshot','raw_output'})
  self.assertNotIn('private',json.dumps(result));self.assertLess(len(json.dumps(result,ensure_ascii=False).encode()),100000)
 def test_missing_or_expired_detail_is_404(self):
  conn,cur=self.database()
  with self.assertRaises(FlowError) as error:execute(lambda:conn,self.payload(operation='intent_detail',decision_id=str(uuid4())),'actor')
  self.assertEqual(error.exception.status,404);self.assertIn('expires_at>UTC_TIMESTAMP(6)',cur.execute.call_args.args[0])
 def test_admin_can_query_and_old_summary_allowlist_is_unchanged(self):
  self.assertNotIn('intent_decisions',TABLES)
  conn,cur=self.database({'n':0},[])
  event={'headers':{'Authorization':'Bearer '+ADMIN,'X-Client-Token':CLIENT},'body':json.dumps(self.payload(operation='intent_rows'))}
  with patch.dict(os.environ,{'CHAT_API_TOKEN':USER,'ADMIN_API_TOKEN':ADMIN}):result=handle_admin(event,factory=lambda:conn)
  self.assertEqual(result['statusCode'],200);self.assertEqual(json.loads(result['body'])['rows'],[])

"""Optional isolated MySQL tests. Never run against the application database."""
import json,os,re,unittest
from unittest.mock import patch
from uuid import uuid4
from src.handlers.dialogue import handle_request
from src.repositories.mysql_chat import MySQLChatStore
from src.repositories.mysql_jobs import MySQLJobRepository

class NoModel:
 model_id='offline-summary-test';region='test-region'
 def route(self,*args):raise AssertionError('Unexpected model call')
 def question(self,*args):raise AssertionError('Unexpected model call')
class NoTraining:
 def search(self,*args):raise AssertionError('Unexpected education lookup')

@unittest.skipUnless(os.getenv('TEST_SUMMARY_MYSQL_PORT'),'Isolated summary MySQL environment not configured')
class SummaryMySQLTests(unittest.TestCase):
 def setUp(self):
  import pymysql
  db=os.environ['TEST_SUMMARY_MYSQL_DATABASE']
  if not re.fullmatch(r'career_summary_verify_[a-f0-9]{12}',db):raise ValueError('Isolated database name required')
  self.factory=lambda:pymysql.connect(host='127.0.0.1',port=int(os.environ['TEST_SUMMARY_MYSQL_PORT']),user=os.environ['TEST_SUMMARY_MYSQL_USER'],password=os.environ['TEST_SUMMARY_MYSQL_PASSWORD'],database=db,charset='utf8mb4',autocommit=True,cursorclass=pymysql.cursors.DictCursor,init_command="SET time_zone='+00:00'")
  self.store=MySQLChatStore(self.factory,retention_hours=1)
  self.jobs=MySQLJobRepository(self.factory,include_unverified=True)
  self.client='offline-client-'+uuid4().hex
  self.env=patch.dict(os.environ,{'CHAT_API_TOKEN':'offline-summary-fixture-'+'x'*40,'ADMIN_API_TOKEN':'','CHAT_INCLUDE_UNVERIFIED':'true','CHAT_RETENTION_HOURS':'1','ENABLE_LIVE_BEDROCK':'false'})
  self.env.start();self.addCleanup(self.env.stop)
 def request(self,payload,*,client=None,store=None):
  return handle_request({'headers':{'Authorization':'Bearer '+os.environ['CHAT_API_TOKEN'],'X-Client-Token':client or self.client},'body':json.dumps(payload)},jobs=self.jobs,store=store or self.store,planner=NoModel(),questioner=NoModel(),training=NoTraining())
 def start(self):
  r=self.request(dict(action='search',request_id=str(uuid4()),search_plan={'skills':['React']}));self.assertEqual(r['statusCode'],200)
  body=json.loads(r['body']);self.sid=body['session_id'];r=self.request(dict(action='select',request_id=str(uuid4()),session_id=self.sid,source_id=body['candidate_jobs'][0]['source_id'],grouped=True));self.assertEqual(r['statusCode'],200)
  return json.loads(r['body'])
 def batch(self,response):return dict(action='answer_batch',request_id=str(uuid4()),session_id=self.sid,answers=[dict(question_id=q['question_id'],assessment='met',detail='표본 프로젝트 설명') for q in response['questions']])
 def count(self,table,where=''):
  c=self.factory()
  try:
   with c.cursor() as cur:cur.execute('SELECT COUNT(*) AS n FROM '+table+where);return cur.fetchone()['n']
  finally:c.close()
 def test_summary_is_in_state_assistant_and_cache_and_replay_is_owner_scoped(self):
  pending=self.start();r=self.request(self.batch(pending));self.assertEqual(r['statusCode'],200);last=self.batch(json.loads(r['body']))
  r=self.request(last);self.assertEqual(r['statusCode'],200);body=json.loads(r['body']);identity=body['answer_summary']['summary_id']
  self.assertEqual(body['answer_summary']['kind'],'all_self_reported_met')
  c=self.factory()
  try:
   with c.cursor() as cur:
    cur.execute('SELECT requirement_answers FROM chat_sessions WHERE session_id=%s',(self.sid,));self.assertEqual(json.loads(cur.fetchone()['requirement_answers'])['answer_summary']['summary_id'],identity)
    cur.execute("SELECT structured_content FROM chat_messages WHERE session_id=%s AND idempotency_key=%s AND role='assistant'",(self.sid,last['request_id']));self.assertEqual(json.loads(cur.fetchone()['structured_content'])['answer_summary']['summary_id'],identity)
    cur.execute("SELECT payload FROM response_cache WHERE session_id=%s ORDER BY cache_id DESC LIMIT 1",(self.sid,));self.assertEqual(json.loads(cur.fetchone()['payload'])['response']['answer_summary']['summary_id'],identity)
   counts={t:self.count(t) for t in ['chat_messages','recommendation_evidence','response_cache','model_invocations']}
   replay=self.request(last);self.assertEqual(replay['statusCode'],200);self.assertTrue(json.loads(replay['body'])['cached'])
   self.assertEqual(counts,{t:self.count(t) for t in counts})
   reason=dict(action='search',request_id=str(uuid4()),session_id=self.sid,message='왜 그렇게 정리했어?')
   r=self.request(reason);self.assertEqual(r['statusCode'],200);self.assertEqual(json.loads(r['body'])['answer_summary']['summary_id'],identity)
   self.assertEqual(self.count('model_invocations'),counts['model_invocations'])
   self.assertEqual(self.request(reason,client='different-offline-client-'+'z'*32)['statusCode'],404)
   with c.cursor() as cur:cur.execute('UPDATE chat_sessions SET expires_at=UTC_TIMESTAMP()-INTERVAL 1 SECOND WHERE session_id=%s',(self.sid,))
   self.assertEqual(self.request(reason)['statusCode'],404)
  finally:c.close()
 def test_failed_final_response_rolls_back_summary_and_evidence_then_retry_succeeds(self):
  pending=self.start();r=self.request(self.batch(pending));self.assertEqual(r['statusCode'],200);last=self.batch(json.loads(r['body']))
  before_evidence=self.count('recommendation_evidence');before_assistants=self.count('chat_messages'," WHERE role='assistant'")
  armed=[True]
  class CursorProxy:
   def __init__(self,c):self.c=c
   def __getattr__(self,k):return getattr(self.c,k)
   def __enter__(self):self.c.__enter__();return self
   def __exit__(self,*args):return self.c.__exit__(*args)
   def execute(self,sql,params=None):
    if armed[0] and sql.startswith('INSERT INTO response_cache'):
     armed[0]=False;raise RuntimeError('Isolated response-cache fault')
    return self.c.execute(sql,params)
  class ConnectionProxy:
   def __init__(self,c):self.c=c
   def __getattr__(self,k):return getattr(self.c,k)
   def cursor(self):return CursorProxy(self.c.cursor())
  failing=MySQLChatStore(lambda:ConnectionProxy(self.factory()),retention_hours=1)
  failed=self.request(last,store=failing);self.assertGreaterEqual(failed['statusCode'],500)
  self.assertEqual(self.count('recommendation_evidence'),before_evidence);self.assertEqual(self.count('chat_messages'," WHERE role='assistant'"),before_assistants)
  c=self.factory()
  try:
   with c.cursor() as cur:cur.execute('SELECT requirement_answers FROM chat_sessions WHERE session_id=%s',(self.sid,));saved=json.loads(cur.fetchone()['requirement_answers'])
   self.assertNotIn('answer_summary',saved)
  finally:c.close()
  success=self.request(last);self.assertEqual(success['statusCode'],200);self.assertIn('answer_summary',json.loads(success['body']))

if __name__=='__main__':unittest.main()

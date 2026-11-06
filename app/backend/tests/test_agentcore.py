import tempfile,unittest
from pathlib import Path
from src.agentcore.adapter import HarnessAdapter,HarnessFailure
from src.agentcore.budget import reserve
from src.agentcore.contracts import tools
from src.services.dialogue import DialogueFlow,FlowError
from src.handlers.dialogue import validate_payload
from uuid import uuid4

class AgentCoreTests(unittest.TestCase):
 def adapter(self,client):
  return HarnessAdapter(client,'arn:test',DialogueFlow(None,None,None),str(uuid4()),'owner','model','region',lambda:None)
 def test_inline_handoff_and_final_reply(self):
  class Client:
   calls=[]
   def invoke_harness(self,**kw):
    self.calls.append(kw)
    if len(self.calls)==1:return {'stream':[{'contentBlockStart':{'contentBlockIndex':1,'start':{'toolUse':{'name':'get_saved_answers','toolUseId':'t1'}}}},{'contentBlockDelta':{'contentBlockIndex':1,'delta':{'toolUse':{'input':'{}'}}}},{'messageStop':{'stopReason':'tool_use'}}]}
    return {'stream':[{'contentBlockDelta':{'contentBlockIndex':0,'delta':{'text':'미확인입니다.'}}},{'messageStop':{'stopReason':'end_turn'}},{'metadata':{'usage':{'inputTokens':10,'outputTokens':4}}}]}
  c=Client();state={'profile':{}}
  result,usage=self.adapter(c).run('내 답변',state,{'message':'내 답변'})
  self.assertEqual(state['stage'],'conversation');self.assertEqual(result['engine'],'agentcore');self.assertEqual(usage['output_tokens'],4)
  self.assertEqual(c.calls[0]['runtimeSessionId'],c.calls[1]['runtimeSessionId'])
  self.assertTrue(all(x.startswith('@*/') for x in c.calls[0]['allowedTools']))
  self.assertEqual(c.calls[1]['messages'][0]['content'][0]['toolResult']['toolUseId'],'t1')
  self.assertEqual(state['agentcore_tool_trace'][0]['status'],'success')
 def test_unlisted_tool_and_owner_injection_rejected(self):
  a=self.adapter(None)
  for name,args in [('shell',{}),('get_saved_answers',{'owner':'other'})]:
   with self.assertRaises(ValueError):a.dispatch(name,args,{'profile':{}},{'message':'test'})
 def test_nonfinal_stream_not_accepted(self):
  class Client:
   def invoke_harness(self,**kw):return {'stream':[{'messageStop':{'stopReason':'max_tokens'}}]}
  with self.assertRaises(HarnessFailure):self.adapter(Client()).run('test',{'profile':{}},{'message':'test'})
 def test_counter_continues_after_previous_six_turn_limit(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'budget.json'
   p.write_text('{"reserved_turns":6}')
   for _ in range(20):reserve(p)
   import json
   self.assertEqual(json.loads(p.read_text())['reserved_turns'],26)
 def test_contract_has_no_execution_or_write_tools(self):
  self.assertEqual([t['name'] for t in tools()],['get_saved_answers','search_jobs','search_training'])
 def test_engine_is_only_explicit_free_text_search(self):
  validate_payload({'action':'search','message':'hello','engine':'agentcore','request_id':str(uuid4())})
  with self.assertRaises(ValueError):validate_payload({'action':'search','search_plan':{},'engine':'agentcore','request_id':str(uuid4())})

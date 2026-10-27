import unittest
from test_dialogue import Jobs, Questioner, invoke
from src.services.dialogue import DialogueFlow, FlowError
from src.handlers.dialogue import validate_payload
from src.bedrock.client import BedrockPlanner
from unittest.mock import patch
from uuid import uuid4

class Router:
    def route(self, text, history):
        return {'intent':'chat','reply':'안녕하세요. 편하게 말씀해 주세요.'}, {}

class GroupedTests(unittest.TestCase):
    def start(self):
        jobs=Jobs()
        jobs.job['qualifications']='\n'.join('- 조건 '+str(i) for i in range(20))
        self.jobs=jobs
        self.flow=DialogueFlow(jobs,Router(),Questioner(),include_unverified=True)
        state,_,_=self.flow.advance({}, {'action':'search','search_plan':{}},invoke)
        return self.flow.advance(state,{'action':'select','source_id':'42','grouped':True},lambda *args: self.fail('Checklist must not invoke model'))

    def test_twenty_conditions_complete_without_model_calls(self):
        state,result,_=self.start()
        self.assertEqual(len(result['questions']),20)
        for expected in ('checking_preferred','gap_guidance'):
            answers=[{'question_id':q['question_id'],'assessment':'unmet','detail':''} for q in result['questions']]
            state,result,evidence=self.flow.advance(state,{'action':'answer_batch','answers':answers},lambda *args:self.fail('No model calls'))
            self.assertEqual(result['stage'],expected)
        self.assertEqual(len(state['checks']),21)

    def test_stale_duplicate_or_missing_answers_rejected(self):
        state,result,_=self.start()
        with self.assertRaises(FlowError):
            self.flow.advance(state,{'action':'answer_batch','answers':[]},invoke)
        self.jobs.job['source_version']=2
        with self.assertRaises(FlowError):
            self.flow.advance(state,{'action':'answer_batch','answers':[]},invoke)

    def test_chat_preserves_pending_checklist(self):
        state,first,_=self.start()
        state,result,_=self.flow.advance(state,{'action':'search','message':'나 힘들어'},invoke)
        self.assertEqual(result['questions'],first['questions'])
        self.assertIn('안녕하세요',result['message'])
        self.assertEqual(state['checks'],[])

    def test_greeting_does_not_search_database(self):
        class NoSearch:
            def search(self,*args):raise AssertionError('Greeting must not search')
        flow=DialogueFlow(NoSearch(),Router(),Questioner())
        state,result,_=flow.advance({}, {'action':'search','message':'안녕'},invoke)
        self.assertEqual(result['stage'],'conversation')

    def test_batch_validation(self):
        payload={'action':'answer_batch','session_id':str(uuid4()),'request_id':str(uuid4()),'answers':[{'question_id':'q','assessment':'unknown','detail':''}]}
        validate_payload(payload)
        payload['answers'][0]['assessment']='inferred'
        with self.assertRaises(ValueError):validate_payload(payload)

    def test_route_validates_model_plan_and_keeps_usage(self):
        import json
        class Client:
            def converse(self,**kwargs):
                self.kwargs=kwargs
                return {'stopReason':'end_turn','output':{'message':{'content':[{'text':json.dumps({'intent':'chat','reply':'안녕하세요'})}]}},'usage':{'inputTokens':5,'outputTokens':3}}
        client=Client()
        with patch.dict('os.environ',{'ENABLE_LIVE_BEDROCK':'true'}):
            result,usage=BedrockPlanner('model','region',client=client).route('안녕',{})
        self.assertEqual(result['intent'],'chat')
        self.assertEqual(client.kwargs['inferenceConfig']['maxTokens'],1024)
        self.assertEqual(usage['input_tokens'],5)

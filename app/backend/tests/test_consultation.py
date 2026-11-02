"""Counseling is text-only and never invokes search or new education retrieval."""
import copy
import json
import os
import unittest
from unittest.mock import MagicMock,patch
from uuid import uuid4

from src.bedrock.client import BedrockPlanner
from src.bedrock.model_json import ModelOutputFormatError,ModelOutputTruncatedError
from src.handlers.dialogue import validate_payload
from src.services.consultation import BUTTON_MESSAGES,legacy_task
from src.services.dialogue import DialogueFlow,FlowError
from src.services.assessment_summary import build_summary
from src.services.memory import memory,restore_user_statements
from test_backend import FakeRuntime
from test_dialogue import Jobs,Questioner,invoke


class TextPlanner:
    model_id,region='offline-model','offline-region'
    def __init__(self):self.inputs=[]
    def consult(self,message,history,task):
        self.inputs.append((message,copy.deepcopy(history),task))
        return {'reply':'저장한 답변에 따르면 미확인과 미충족은 다릅니다. 준비할 증빙을 정리해 보세요.'},{}
    def route(self,*args):raise AssertionError('Consultation must not use the route classifier')


class ConsultationFlowTests(unittest.TestCase):
    def setUp(self):
        self.jobs=Jobs();self.planner=TextPlanner();self.training=MagicMock()
        self.flow=DialogueFlow(self.jobs,self.planner,Questioner(),include_unverified=True,training=self.training)
        self.state,first,_=self.flow.advance({}, {'action':'search','search_plan':{}},invoke)
        self.state,result,_=self.flow.advance(self.state,{'action':'select','source_id':'42','grouped':True},invoke)
        while result['stage'] in ('checking_required','checking_preferred'):
            answers=[{'question_id':q['question_id'],'assessment':'unknown' if result['requirement_type']=='preferred' else 'unmet','detail':'입문 수업 경험만 있습니다.'} for q in result['questions']]
            self.state,result,_=self.flow.advance(self.state,{'action':'answer_batch','answers':answers},invoke)
        self.summary=result['answer_summary']
        self.training.search.assert_not_called()

    def test_prepare_calls_only_text_counselor_with_saved_all_answers(self):
        with patch.object(self.jobs,'search',side_effect=AssertionError('No search')),patch.object(self.jobs,'get',side_effect=AssertionError('Use saved snapshot')):
            _,response,evidence=self.flow.advance(self.state,{'action':'consult','task':'prepare','summary_id':self.summary['summary_id'],'message':'이미 답변한 경험을 이력서에 연결해줘'},invoke)
        self.assertEqual(response['stage'],'conversation')
        self.assertEqual(response['consultation']['task'],'prepare')
        self.assertEqual(len(self.planner.inputs),1)
        history=self.planner.inputs[0][1]
        self.assertEqual(len(history['condition_answers']),2)
        self.assertEqual(history['condition_answers'][1]['assessment'],'unknown')
        self.assertIn('입문 수업',history['condition_answers'][0]['detail'])
        self.assertNotIn('learning_search',response)
        self.assertEqual(evidence,[])
        self.training.search.assert_not_called()

    def test_gap_counseling_does_not_treat_education_disclaimer_as_a_lookup(self):
        self.state['learning_context']={'status':'need_topic','topics':[],'courses':[]}
        text=next(m for m,t in BUTTON_MESSAGES.items() if t=='learning_plan')
        _,response,_=self.flow.advance(self.state,{'action':'search','message':text},invoke)
        self.assertEqual(response['consultation']['task'],'learning_plan')
        self.assertNotIn('learning_search',response)
        self.assertNotIn('training_retrieval',self.planner.inputs[0][1])
        self.training.search.assert_not_called()

    def test_all_old_button_requests_follow_their_known_purpose(self):
        original=copy.deepcopy(self.state)
        for message,task in BUTTON_MESSAGES.items():
            with self.subTest(task=task):
                _,response,_=self.flow.advance(copy.deepcopy(original),{'action':'search','message':message},invoke)
                self.assertEqual(response['consultation']['task'],task)

    def test_defer_uses_stored_summary_without_model_or_retrieval(self):
        _,response,_=self.flow.advance(self.state,{'action':'consult','task':'defer','message':'나중에 확인할게'},lambda *args:self.fail('No model'))
        self.assertEqual(response['consultation']['generation'],'stored_summary')
        self.assertEqual(response['answer_summary']['summary_id'],self.summary['summary_id'])
        self.assertEqual(self.state['checks'][1]['assessment'],'unknown')
        self.training.search.assert_not_called()

    def test_stale_summary_or_missing_selected_job_is_rejected_before_model(self):
        for state,summary in [(self.state,'0'*64),({},None)]:
            with self.assertRaises(FlowError):
                self.flow.advance(copy.deepcopy(state),{'action':'consult','task':'prepare','message':'이력서 준비',**({'summary_id':summary} if summary else {})},invoke)
        self.assertEqual(self.planner.inputs,[])

    def test_refusal_and_original_answers_are_preserved_without_reasking(self):
        before=copy.deepcopy(self.state['checks'])
        self.planner.consult=lambda *args:({'reply':'기록으로 안내합니다. 어떤 기술 경험이 있으신가요?'},{})
        _,response,_=self.flow.advance(self.state,{'action':'consult','task':'prepare','message':'역량 질문하지 마. 이력서를 준비해줘'},invoke)
        self.assertTrue(response['assessment_paused'])
        self.assertNotIn('있으신가요',response['message'])
        self.assertEqual(self.state['checks'],before)
        self.assertNotIn('questions',response)

    def test_explicit_search_is_not_intercepted_by_resume_words(self):
        self.assertIsNone(legacy_task('이력서에 React 경험이 있어. 관련 채용공고를 찾아줘'))
        self.assertIsNone(legacy_task('실제 교육 과정을 찾아줘'))
        self.assertEqual(legacy_task('좀 더 구체적인 예시를 보여줘',{'task':'prepare'}),'general')

    def test_followup_free_text_uses_the_existing_counseling_focus(self):
        self.state['consultation_focus']={'task':'prepare'}
        _,response,_=self.flow.advance(self.state,{'action':'search','message':'좀 더 자세한 예시를 알려줘'},invoke)
        self.assertEqual(response['consultation']['task'],'general')

    def test_consult_original_message_can_be_restored_in_user_memory(self):
        state={}
        restore_user_statements(state,[(1,{'action':'consult','message':'입문 프로젝트 경험이 있습니다.'})])
        self.assertIn('입문 프로젝트',memory(state)['user_statements'][0]['text'])


class ConsultationAdapterTests(unittest.TestCase):
    def history(self):return {'selected_job':{'source_id':'42','source_version':1},'assistant_preferences':{'ask_assessment':True}}
    def call(self,runtime,partial=None):
        with patch.dict(os.environ,{'ENABLE_LIVE_BEDROCK':'true'}):
            return BedrockPlanner('offline-model','offline-region',client=runtime,on_partial=partial).consult('보완 방향을 정리해줘',self.history(),'learning_plan')

    def test_plain_text_is_valid_and_no_json_intent_is_required(self):
        runtime=FakeRuntime('필수조건의 미충족부터 확인하고, 미확인 항목은 별도로 남겨 두세요.')
        result,usage=self.call(runtime)
        self.assertIn('미확인',result['reply'])
        self.assertEqual(runtime.calls[0]['inferenceConfig']['maxTokens'],4096)
        self.assertEqual(usage['prompt_version'],'consultation-text-v1')
        self.assertNotIn('검색계획 스키마',runtime.calls[0]['system'][0]['text'])

    def test_plain_stream_is_emitted_before_completion_and_closed(self):
        events=[{'contentBlockDelta':{'delta':{'text':'필수조건부터 '}}},
                {'contentBlockDelta':{'delta':{'text':'보완 방향을 정리합니다.'}}},
                {'messageStop':{'stopReason':'end_turn'}},
                {'metadata':{'usage':{'inputTokens':30,'outputTokens':40}}}]
        class Stream:
            closed=False
            def __iter__(self):return iter(events)
            def close(self):self.closed=True
        stream=Stream();runtime=MagicMock();runtime.converse_stream.return_value={'stream':stream}
        parts=[]
        result,usage=self.call(runtime,parts.append)
        self.assertEqual(parts[0],'필수조건부터 ')
        self.assertEqual(parts[-1],result['reply'])
        self.assertTrue(stream.closed)
        self.assertEqual(usage['output_tokens'],40)

    def test_blank_oversized_and_truncated_are_not_completed_as_success(self):
        for text,stop in [('', 'end_turn'),('a'*4001,'end_turn'),('미완성','max_tokens')]:
            with self.subTest(stop=stop),self.assertRaises(ModelOutputFormatError) as result:
                self.call(FakeRuntime(text,stop=stop))
            if stop=='max_tokens':self.assertIsInstance(result.exception,ModelOutputTruncatedError)

    def test_opt_in_and_context_guards_do_not_call_model(self):
        runtime=FakeRuntime('답변')
        with patch.dict(os.environ,{'ENABLE_LIVE_BEDROCK':'false'}),self.assertRaises(RuntimeError):
            BedrockPlanner('m','r',client=runtime).consult('준비',self.history(),'prepare')
        with patch.dict(os.environ,{'ENABLE_LIVE_BEDROCK':'true'}),self.assertRaises(ValueError):
            BedrockPlanner('m','r',client=runtime).consult('준비',{},'prepare')
        self.assertEqual(runtime.calls,[])


class ConsultationPayloadTests(unittest.TestCase):
    def test_known_task_session_and_summary_are_validated(self):
        value={'action':'consult','task':'prepare','message':'이력서 준비','session_id':str(uuid4()),'request_id':str(uuid4()),'summary_id':'a'*64}
        self.assertEqual(validate_payload(value),value)
        for extra in [{'task':'run_sql'},{'task':[]},{'message':' '},{'summary_id':'old'}, {'search_plan':{}},{'session_id':None}]:
            with self.subTest(extra=extra),self.assertRaises((ValueError,TypeError)):
                validate_payload(dict(value,**extra))


class ConsultationEndpointTests(unittest.TestCase):
    def fixture(self,fail=False):
        from src.handlers.dialogue import handle_request
        jobs=Jobs();planner=TextPlanner();store=MagicMock();training=MagicMock()
        sid,rid=str(uuid4()),str(uuid4())
        state={'stage':'completed','selected':copy.deepcopy(jobs.job),
            'conditions':[{'id':'q','type':'required','quote':'Python 또는 Java 경험'}],
            'checks':[{'condition_id':'q','type':'required','quote':'Python 또는 Java 경험','assessment':'unknown','detail':''}]}
        store.begin.return_value={'state':state,'session_id':sid,'request_id':rid}
        store.begin_invocation.return_value='offline-invocation'
        store.finish.side_effect=lambda ticket,payload,state,response,evidence:response
        if fail:planner.consult=MagicMock(side_effect=RuntimeError('private debug data'))
        token='offline-test-'+'x'*40
        payload={'action':'consult','task':'prepare','session_id':sid,'request_id':rid,'message':'이력서를 준비해줘'}
        event={'headers':{'Authorization':'Bearer '+token,'X-Client-Token':'a'*64},'body':json.dumps(payload)}
        with patch.dict(os.environ,{'CHAT_API_TOKEN':token,'CHAT_RETENTION_HOURS':'24'}),patch.object(jobs,'search',side_effect=AssertionError('No search')):
            response=handle_request(event,store=store,jobs=jobs,planner=planner,questioner=Questioner(),training=training)
        return response,store,training

    def test_handler_records_the_text_counselor_model_and_prompt_version(self):
        response,store,training=self.fixture()
        self.assertEqual(response['statusCode'],200)
        self.assertEqual(json.loads(response['body'])['stage'],'conversation')
        args=store.begin_invocation.call_args.args
        self.assertEqual(args[1],'consultation')
        self.assertEqual(args[2],'offline-model')
        self.assertEqual(args[4],'consultation-text-v1')
        store.finish.assert_called_once();store.abort.assert_not_called()
        training.search.assert_not_called()

    def test_handler_failure_preserves_session_and_uses_existing_abort_path(self):
        response,store,training=self.fixture(True)
        self.assertEqual(response['statusCode'],502)
        self.assertIn('session_id',json.loads(response['body']))
        self.assertNotIn('private debug data',response['body'])
        store.abort.assert_called_once();store.finish.assert_not_called()
        self.assertEqual(store.begin.return_value['state']['checks'][0]['assessment'],'unknown')
        self.assertEqual(store.finish_invocation.call_args.kwargs['error_code'],'RuntimeError')

    def test_no_space_explicit_search_is_not_mistaken_for_counseling(self):
        self.assertIsNone(legacy_task('이력서를 봤으니 공고찾아줘'))
        self.assertIsNone(legacy_task('포트폴리오 기반 교육찾아줘'))

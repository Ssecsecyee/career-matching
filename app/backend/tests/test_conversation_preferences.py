import copy,unittest
from unittest.mock import Mock
from test_dialogue import Jobs,Questioner,invoke
from routing_fixture import advance_intent
from src.services.dialogue import DialogueFlow
from src.services.memory import split_conditions
from src.services.conversation_policy import preferences

class ConversationPreferenceTests(unittest.TestCase):
    def start(self):
        planner=Mock();planner.respond.return_value=({'reply':'기록된 정보로 안내합니다.'},{})
        flow=DialogueFlow(Jobs(),planner,Questioner(),include_unverified=True)
        state,_,_=flow.advance({},dict(action='search',search_plan={}),invoke)
        state,_,_=flow.advance(state,dict(action='select',source_id='42',grouped=True),invoke)
        return flow,state,planner,None
    def test_stop_persists_and_blocks_stale_answer_then_resume(self):
        flow,state,planner,_=self.start();before=copy.deepcopy(state['checks'])
        _,result,_=advance_intent(flow,state,'물어보지 마',dict(target='selected',action='assessment_control',control='stop'))
        self.assertTrue(result['assessment_paused'])
        _,result,e=flow.advance(state,dict(action='answer_batch',answers=[]),invoke)
        self.assertTrue(result['assessment_paused']);self.assertEqual(e,[])
        advance_intent(flow,state,'회사 설명',dict(target='general',action='chat'))
        self.assertFalse(preferences(state)['ask_assessment']);self.assertEqual(before,state['checks'])
        _,result,_=advance_intent(flow,state,'다시 확인',dict(target='selected',action='assessment_control',control='resume'))
        self.assertEqual(result['stage'],'checking_required')
    def test_refusal_filters_model_reasking_without_rewriting_answers(self):
        flow,state,planner,_=self.start()
        planner.respond.return_value=({'reply':'공고를 안내합니다.\n어떤 기술 경험이 있으신가요?'},{})
        _,result,_=advance_intent(flow,state,'묻지 말고 설명',dict(target='general',action='chat',ask_assessment=False))
        self.assertNotIn('있으신가요',result['message']);self.assertIn('공고',result['message'])
    def test_new_selection_respects_prior_stop(self):
        flow,state,planner,_=self.start()
        flow.advance(state,dict(action='assessment_control',control='stop'),invoke)
        _,result,_=flow.advance(state,dict(action='select',source_id='42',grouped=True),invoke)
        self.assertIn('job_overview',result);self.assertNotIn('questions',result)

    def test_source_headings_are_context_not_standalone_questions(self):
            text='* 학력\n- 대졸(4년제) 졸업 이상 또는 졸업 예정자\n* 경력\n- 신입 또는 관련 경력 2년 이하\n* 자격요건\n- Java 프로그래밍 가능 또는 개발 경험자\n(ClassLoader, Multi-Thread, GC 등)'
            rows=split_conditions(text,'required','42',1)
            self.assertEqual(len(rows),3)
            self.assertIn('또는 졸업 예정자',rows[0]['quote'])
            self.assertIn('2년 이하',rows[1]['quote'])
            self.assertIn('ClassLoader',rows[2]['quote'])
            self.assertIn('가능 또는 개발',rows[2]['quote'])

    def test_small_batches_keep_original_and_summary(self):
            flow,state,_,_=self.start()
            result=flow.batch_response(state)
            self.assertLessEqual(len(result['questions']),5)
            self.assertIn('summary',result['questions'][0]);self.assertIn('quote',result['questions'][0])
            self.assertIn('또는',result['questions'][0]['summary'])

import copy
import unittest
from unittest.mock import MagicMock
from test_dialogue import Jobs, Questioner, invoke
from src.services.dialogue import DialogueFlow
from src.services.conversation_policy import preferences, search_target, assessment_request
from src.services.memory import split_conditions


class ConversationPreferenceTests(unittest.TestCase):
    def flow(self,reply=None):
        jobs=Jobs();planner=MagicMock();planner.route.return_value=({'intent':'chat','reply':reply or '기록된 정보로 안내합니다.'},{})
        training=MagicMock();training.search.return_value=[]
        return DialogueFlow(jobs,planner,Questioner(),include_unverified=True,training=training),planner,training

    def start(self):
        flow,planner,training=self.flow()
        state,_,_=flow.advance({}, {'action':'search','search_plan':{}},invoke)
        state,_,_=flow.advance(state,{'action':'select','source_id':'42','grouped':True},invoke)
        return flow,state,planner,training

    def test_education_listing_is_not_a_job_listing(self):
        self.assertEqual(search_target({},'React 교육 공고 찾아줘'),'training')
        self.assertEqual(search_target({},'부트캠프 모집 공고 있어?'),'training')
        self.assertEqual(search_target({},'취업을 위한 React 교육 추천'),'training')
        self.assertEqual(search_target({},'교육 말고 취업하고 싶어'),'jobs')

    def test_training_topic_followup_does_not_search_jobs(self):
        flow,planner,training=self.flow()
        planner.route.return_value=({'intent':'search','plan':{}},{})
        state,result,_=flow.advance({}, {'action':'search','message':'부트캠프 추천해줘'},invoke)
        self.assertEqual(result['learning_search']['status'],'need_topic')
        state,result,_=flow.advance(state,{'action':'search','message':'UI/UX 디자인'},invoke)
        training.search.assert_called_once_with(['UI/UX'])
        self.assertEqual(result['learning_search']['status'],'no_match')
        self.assertEqual(result['stage'],'conversation')
        self.assertNotIn('candidate_jobs',state)

    def test_explicit_switch_from_training_to_jobs(self):
        state={'conversation_target':'training','learning_context':{'status':'no_match','topics':['React'],'courses':[]}}
        self.assertEqual(search_target(state,'교육 말고 React 채용공고'),'jobs')
        self.assertEqual(search_target({'conversation_target':'jobs'},'공고 말고 React 교육'),'training')

    def test_both_targets_ask_before_any_search_or_model_call(self):
        flow,planner,training=self.flow()
        state,result,_=flow.advance({},{'action':'search','message':'채용공고와 교육 둘 다 찾아줘'},lambda *a:self.fail('Clarification must not invoke model'))
        self.assertIn('어떤 것을 먼저',result['message'])
        training.search.assert_not_called();planner.route.assert_not_called()

    def test_refusal_stops_cards_and_persists_across_turns(self):
        flow,state,planner,_=self.start()
        original=copy.deepcopy(state['checks'])
        state,result,evidence=flow.advance(state,{'action':'search','message':'나한테 역량을 물어보지마'},lambda *a:self.fail('No model needed to stop'))
        self.assertTrue(result['assessment_paused']);self.assertNotIn('questions',result)
        self.assertFalse(preferences(state)['ask_assessment']);self.assertEqual(evidence,[])
        state,result,_=flow.advance(state,{'action':'search','message':'회사만 설명해줘'},invoke)
        self.assertNotIn('questions',result);self.assertEqual(state['checks'],original)
        self.assertFalse(planner.route.call_args.args[1]['assistant_preferences']['ask_assessment'])

    def test_model_reasking_is_filtered_after_refusal(self):
        flow,state,planner,_=self.start()
        flow.advance(state,{'action':'search','message':'역량 질문하지 마'},invoke)
        planner.route.return_value=({'intent':'chat','reply':'React 공고를 안내합니다.\n어떤 기술 경험이 있으신가요?'},{})
        _,result,_=flow.advance(state,{'action':'search','message':'안내해줘'},invoke)
        self.assertIn('React 공고',result['message']);self.assertNotIn('있으신가요',result['message'])

    def test_old_answer_cannot_override_refusal(self):
        flow,state,_,_=self.start()
        flow.advance(state,{'action':'search','message':'역량 질문 그만해'},invoke)
        _,result,evidence=flow.advance(state,{'action':'answer_batch','answers':[]},invoke)
        self.assertTrue(result['assessment_paused']);self.assertEqual(evidence,[])

    def test_negative_resume_word_does_not_reenable_questions(self):
        self.assertIs(assessment_request('다시는 역량 질문하지 마'),False)
        self.assertIs(assessment_request('다시 역량을 물어보지 마'),False)
        self.assertIs(assessment_request('이제 역량을 확인해줘'),True)

    def test_explicit_resume_is_required(self):
        flow,state,_,_=self.start()
        flow.advance(state,{'action':'search','message':'역량 물어보지마'},invoke)
        _,result,_=flow.advance(state,{'action':'search','message':'다시 역량 조건을 확인해줘'},invoke)
        self.assertTrue(preferences(state)['ask_assessment']);self.assertEqual(result['stage'],'checking_required')

    def test_new_selection_does_not_force_assessment_after_refusal(self):
        flow,state,_,_=self.start()
        flow.advance(state,{'action':'search','message':'역량 물어보지마'},invoke)
        _,result,_=flow.advance(state,{'action':'select','source_id':'42','grouped':True},invoke)
        self.assertIn('job_overview',result);self.assertNotIn('questions',result)

    def test_training_request_does_not_resurface_old_checklist(self):
        flow,state,_,_=self.start()
        _,result,_=flow.advance(state,{'action':'search','message':'React 교육 찾아줘'},invoke)
        self.assertIn('learning_search',result);self.assertNotIn('questions',result)

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

if __name__=='__main__':unittest.main()

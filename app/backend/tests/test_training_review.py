import copy,json,unittest
from unittest.mock import Mock
from src.schemas.intent import IntentDecision
from src.services.context_router import ContextRouter
from src.services.dialogue import DialogueFlow,FlowError
from src.services.intent_context import routing_context
from routing_fixture import advance_intent


def course(version=1):return {'source':'goyong24_training','source_id':'card:synthetic','source_version':version,'content_hash':'hash'+str(version),'title':'Unseen synthetic course','recommendation_eligible':False}

class TrainingReviewTests(unittest.TestCase):
    def fixture(self,courses=None):
        training=Mock();training.search.return_value=[course()] if courses is None else courses
        planner=Mock();jobs=Mock();flow=DialogueFlow(jobs,planner,None,training=training)
        return flow,training,planner,jobs

    def preview(self,flow,state=None,text='React를 배우고 싶어',**changes):
        return advance_intent(flow,{} if state is None else state,text,dict(target='training',action='search',topics=['React'],**changes))

    def test_implicit_learning_or_institution_decision_uses_review_not_free_answer(self):
        for text in ['React를 배우고 싶어','어디서 배울 수 있을까?','멋쟁이사자처럼 과정 있어?']:
            flow,repo,planner,jobs=self.fixture()
            state,result,_=self.preview(flow,text=text)
            self.assertEqual(result['stage'],'training_search_review')
            self.assertEqual(result['learning_opportunities'],[])
            self.assertNotIn('Unseen synthetic course',json.dumps(result))
            self.assertNotIn('training_navigation',state)
            planner.respond.assert_not_called();jobs.search.assert_not_called()

    def test_learning_goal_is_recorded_not_sent_as_an_or_search_topic(self):
        flow,repo,planner,_=self.fixture()
        state,result,_=advance_intent(flow,{},'데이터분석 교육을 찾되 포트폴리오 목표는 검색 조건이 아니라 참고만 해줘',dict(target='training',action='search',topics=['데이터분석'],learning_goals=['데이터분석 포트폴리오 제작']))
        repo.search.assert_called_once_with(['데이터분석'],exclude_ids=[],delivery_mode=None,candidates_only=True)
        self.assertEqual(state['training_search_context']['learning_goals'],['데이터분석 포트폴리오 제작'])
        self.assertTrue(any('확인되지 않았습니다' in x for x in result['search_summary']['limitations']))
        state,result,_=flow.advance(state,{'action':'confirm_search','search_id':result['search_id']},None)
        self.assertEqual(state['learning_context']['learning_goals'],['데이터분석 포트폴리오 제작'])
        self.assertEqual(state['training_navigation']['learning_goals'],['데이터분석 포트폴리오 제작'])

    def test_confirm_button_rechecks_then_reveals_without_model(self):
        flow,repo,planner,_=self.fixture();state,review,_=self.preview(flow)
        count=planner.classify.call_count
        state,result,_=flow.advance(state,{'action':'confirm_search','search_id':review['search_id']},None)
        self.assertEqual(result['learning_opportunities'],[course()])
        self.assertEqual(repo.search.call_count,2)
        self.assertEqual(planner.classify.call_count,count)
        self.assertEqual(state['training_navigation']['shown_ids'],['goyong24_training:card:synthetic'])
        self.assertTrue(state['training_search_context']['confirmed_at'])

    def test_natural_confirmation_contract_and_persisted_snapshot(self):
        flow,repo,planner,_=self.fixture();state,review,_=self.preview(flow)
        state=json.loads(json.dumps(state))
        state,result,_=advance_intent(flow,state,'응 그 기준으로',dict(target='training',action='confirm_search'))
        self.assertEqual(result['search_id'],review['search_id'])
        self.assertEqual(len(result['learning_opportunities']),1)

    def test_next_before_consent_keeps_review_without_query(self):
        flow,repo,_,_=self.fixture();state,review,_=self.preview(flow)
        _,result,_=advance_intent(flow,state,'다른 거',dict(target='training',action='next_results'))
        self.assertEqual(result['search_id'],review['search_id'])
        self.assertEqual(result['learning_opportunities'],[])
        self.assertEqual(repo.search.call_count,1)

    def test_refine_pending_mode_retains_topic_and_invalidates_old_button(self):
        flow,repo,_,_=self.fixture();state,review,_=self.preview(flow)
        state,new,_=advance_intent(flow,state,'온라인으로',dict(target='training',action='refine_search',delivery_mode='online'))
        self.assertEqual(new['learning_search']['topics'],['React'])
        self.assertNotEqual(review['search_id'],new['search_id'])
        self.assertEqual(state['training_search_context']['delivery_mode'],'online')
        with self.assertRaises(FlowError):ContextRouter(flow).confirm_training(state,review['search_id'])

    def test_changed_or_expired_courses_need_new_confirmation(self):
        for revised in [[course(2)],[]]:
            flow,repo,_,_=self.fixture();state,review,_=self.preview(flow)
            repo.search.return_value=revised
            state,result,_=flow.advance(state,{'action':'confirm_search','search_id':review['search_id']},None)
            self.assertTrue(result['search_changed'])
            self.assertEqual(result['learning_opportunities'],[])
            self.assertNotEqual(result['search_id'],review['search_id'])
            self.assertNotIn('training_navigation',state)

    def test_job_answers_and_last_displayed_education_are_preserved(self):
        flow,repo,_,_=self.fixture();state={'selected':{'source_id':'job'},'checks':[{'assessment':'unknown'}],'learning_context':{'topics':['Python'],'courses':[course(7)]}}
        before=copy.deepcopy(state)
        state,_,_=self.preview(flow,state)
        for field in ['selected','checks','learning_context']:self.assertEqual(state[field],before[field])

    def test_unknown_count_is_not_fabricated_from_preview_size(self):
        flow,repo,_,_=self.fixture();state,result,_=self.preview(flow)
        self.assertIsNone(result['search_summary']['candidate_total'])
        self.assertEqual(result['search_summary']['preview_count'],1)
        repo.last_candidate_total=9000
        _,result,_=self.preview(flow)
        self.assertEqual(result['search_summary']['candidate_total'],9000)
        self.assertNotIn('verified_total',result['search_summary'])

    def test_missing_topic_and_followup_preserve_training_target(self):
        flow,repo,_,_=self.fixture()
        state,result,_=advance_intent(flow,{},'교육 좀',dict(target='training',action='clarify',question='어떤 분야인가요?'))
        self.assertEqual(routing_context(state)['pending_clarification']['target'],'training')
        state,result,_=self.preview(flow,state)
        self.assertTrue(routing_context(state)['training_review']['pending'])

    def test_after_confirmation_next_results_excludes_shown_ids(self):
        flow,repo,_,_=self.fixture();state,review,_=self.preview(flow)
        state,_,_=flow.advance(state,{'action':'confirm_search','search_id':review['search_id']},None)
        repo.search.return_value=[]
        _,result,_=advance_intent(flow,state,'다음 교육',dict(target='training',action='next_results'))
        self.assertEqual(repo.search.call_args.kwargs['exclude_ids'],['goyong24_training:card:synthetic'])
        self.assertEqual(result['learning_opportunities'],[])

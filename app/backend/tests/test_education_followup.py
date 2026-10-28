import copy
import unittest
from unittest.mock import MagicMock
from src.services.dialogue import DialogueFlow
from src.services.learning import retrieve
from src.repositories.mysql_jobs import MySQLJobRepository
from src.schemas.search import SearchPlan

class EducationFollowupTests(unittest.TestCase):
    def context(self):
        return {'status':'found','topics':['React'],'courses':[
            {'source_id':'first','source_version':1,'title':'실제 교육 A','recommendation_eligible':False},
            {'source_id':'second','source_version':2,'title':'실제 교육 B','recommendation_eligible':False}],
            'basis':'explicit_learning_topic_and_self_assessed_gaps','limitations':[]}

    def test_pronoun_and_recommendation_retain_exact_displayed_list_without_new_query(self):
        for text in ['이중 어떤걸 제일 추천해?','이 중 뭐가 좋아?','어떤 걸 제일 추천해?','그중 온라인 과정은?','첫 번째랑 두 번째 비교해줘']:
            with self.subTest(text=text):
                previous=self.context();repo=MagicMock();repo.search.side_effect=AssertionError('Must retain displayed candidates')
                result=retrieve({'learning_context':previous},text,repo)
                self.assertEqual(result['courses'],previous['courses'])
                self.assertEqual(result['reference_resolution'],'previously_displayed_training_courses')
                self.assertIsNot(result,previous)

    def test_new_job_request_is_not_hijacked_by_previous_education(self):
        for text in ['React 관련 공고가 있을까 최근 교육을 들었어','이번에는 백엔드 공고 추천해줘','회사 중 어디가 나을까?']:
            with self.subTest(text=text):
                repo=MagicMock();self.assertIsNone(retrieve({'learning_context':self.context()},text,repo));repo.search.assert_not_called()

    def test_new_education_topic_requeries_instead_of_reusing_react(self):
        repo=MagicMock();repo.search.return_value=[]
        result=retrieve({'learning_context':self.context()},'Python 교육은 어떤 게 좋아?',repo)
        repo.search.assert_called_once_with(['Python']);self.assertEqual(result['topics'],['Python'])

    def test_completed_checklist_followup_delivers_education_even_with_selected_job(self):
        previous=self.context();state={'stage':'gap_guidance','checks':[],'selected':{'source_id':'job','title':'프론트엔드 경력 8년'},'learning_context':copy.deepcopy(previous)}
        jobs=MagicMock();repo=MagicMock();planner=MagicMock()
        planner.route.return_value=({'intent':'chat','reply':'두 교육의 학습 내용을 비교해 드릴게요.'},{})
        def invoke(purpose,fn,*args):return fn(*args)[0]
        _,response,_=DialogueFlow(jobs,planner,None,training=repo).advance(state,{'action':'search','message':'이중 어떤걸 제일 추천해?'},invoke)
        history=planner.route.call_args.args[1]
        self.assertEqual(history['conversation_focus']['kind'],'training')
        self.assertEqual(history['training_retrieval']['courses'],previous['courses'])
        self.assertEqual(response['learning_opportunities'],previous['courses'])
        jobs.search.assert_not_called();repo.search.assert_not_called()

    def test_technology_keyword_search_includes_tags_and_casefold_without_weakening_skill_filter(self):
        for word in ['react','React','REACT']:
            conn=MagicMock();cur=conn.cursor.return_value.__enter__.return_value
            cur.fetchone.return_value={'total':1};cur.fetchall.return_value=[]
            MySQLJobRepository(lambda:conn,include_unverified=True).search(SearchPlan(keyword=word,skills=('React',)))
            query,params=cur.execute.call_args_list[0].args
            self.assertIn('LOWER(CONCAT_WS',query);self.assertIn('COALESCE(tech_stacks',query)
            self.assertIn('JSON_CONTAINS',query);self.assertIn('deadline_at>UTC_TIMESTAMP',query)
            self.assertIn('%'+word+'%',params);self.assertEqual(params[-1],'React')


class ModelSearchNormalizationTests(unittest.TestCase):
    def test_react_phrase_does_not_create_unrequested_frontend_filter(self):
        from src.services.model_search import normalize_model_search
        plan=normalize_model_search(SearchPlan(keyword='React 프론트엔드 개발',skills=('React',)), '안녕 react 관련 공고가 있을까 최근 수업을 들어서 할만할거 같아')
        self.assertEqual(plan.keyword,'');self.assertEqual(plan.skills,('React',))

    def test_explicit_role_domain_region_and_skills_are_preserved(self):
        from src.services.model_search import normalize_model_search
        plan=normalize_model_search(SearchPlan(keyword='React 프론트엔드 개발',region='서울',skills=('React',)), '서울 React 프론트엔드 공고')
        self.assertEqual(plan.keyword,'프론트엔드');self.assertEqual(plan.region,'서울')
        plan=SearchPlan(keyword='React 보안',skills=('React',))
        self.assertEqual(normalize_model_search(plan,'React 보안 공고'),plan)

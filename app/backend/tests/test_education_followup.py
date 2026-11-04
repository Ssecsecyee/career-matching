from routing_fixture import advance_intent
import copy
import unittest
from unittest.mock import MagicMock
from src.services.dialogue import DialogueFlow

from src.repositories.mysql_jobs import MySQLJobRepository
from src.schemas.search import SearchPlan

class EducationFollowupTests(unittest.TestCase):
    def context(self):
        return {'status':'found','topics':['React'],'courses':[
            {'source':'fixture','source_id':'first','source_version':1,'title':'실제 교육 A','delivery_mode':'online','recommendation_eligible':False},
            {'source':'fixture','source_id':'second','source_version':2,'title':'실제 교육 B','delivery_mode':'offline','recommendation_eligible':False}],
            'basis':'explicit_learning_topic_and_self_assessed_gaps','limitations':[]}

    def test_pronoun_and_recommendation_retain_exact_displayed_list_without_new_query(self):
        for text in ['이중 어떤걸 제일 추천해?','첫 번째랑 두 번째 비교해줘']:
            previous=self.context();repo=MagicMock();planner=MagicMock();planner.respond.return_value=({'reply':'두 과정을 비교합니다.'},{})
            flow=DialogueFlow(MagicMock(),planner,None,training=repo)
            _,result,_=advance_intent(flow,{'learning_context':previous},text,dict(target='training',action='chat'))
            self.assertEqual(result['learning_opportunities'],previous['courses']);repo.search.assert_not_called()

    def test_new_job_request_is_not_hijacked_by_previous_education(self):
        repo=MagicMock();jobs=MagicMock();jobs.search.return_value=(0,[])
        flow=DialogueFlow(jobs,MagicMock(),None,training=repo)
        advance_intent(flow,{'learning_context':self.context()},'교육 말고 채용',dict(target='jobs',action='search',plan={'schema_version':2}))
        jobs.search.assert_called_once();repo.search.assert_not_called()

    def test_new_education_topic_requeries_instead_of_reusing_react(self):
        repo=MagicMock();repo.search.return_value=[];flow=DialogueFlow(MagicMock(),MagicMock(),None,training=repo)
        _,result,_=advance_intent(flow,{'learning_context':self.context()},'Python 교육',dict(target='training',action='search',topics=['Python']))
        repo.search.assert_called_once_with(['Python'],exclude_ids=[],delivery_mode=None,candidates_only=True)
        self.assertEqual(result['learning_search']['topics'],['Python'])

    def test_completed_checklist_followup_delivers_education_even_with_selected_job(self):
        previous=self.context();state={'stage':'gap_guidance','checks':[],'selected':{'source_id':'job'},'learning_context':copy.deepcopy(previous)}
        jobs=MagicMock();repo=MagicMock();planner=MagicMock();planner.respond.return_value=({'reply':'교육을 비교합니다.'},{})
        _,result,_=advance_intent(DialogueFlow(jobs,planner,None,training=repo),state,'이중 어떤걸 제일 추천해?',dict(target='training',action='chat'))
        self.assertEqual(planner.respond.call_args.args[1]['conversation_focus']['kind'],'training')
        self.assertEqual(result['learning_opportunities'],previous['courses'])
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

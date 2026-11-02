import copy
import json
from pathlib import Path
import tempfile
import unittest
from uuid import uuid4

from src.schemas.search import SearchPlan
from src.repositories.elasticsearch_jobs import build_query
from src.repositories.jobs import JsonJobRepository
from src.services.search_sql import structured_clauses
from src.services.dialogue import DialogueFlow, FlowError
from src.handlers.dialogue import validate_payload
from src.services.memory import consultation_context
from src.services.search_review import execution_summary


COMPLEX_MESSAGE = '컴퓨터공학 전공에 Python, C/C++ 기반 커스텀 데이터 파이프라인 개발 및 C/FFI 모듈 연동 경험이 있어. AWS(EC2) 인프라 관리 경험도 포함해서 부산이나 경남 지역에서 지원할 만한 백엔드/데이터 엔지니어링 신입~주니어 채용 공고 추천해줘.'
COMPLEX_PLAN = {'schema_version':2, 'target':'jobs', 'regions':['부산','경남'],
    'roles':['백엔드','데이터 엔지니어링'], 'owned_skills':['Python','C','C++','FFI','AWS','EC2'],
    'required_skills':[], 'preferred_skills':[], 'career':{'levels':['entry','junior'],'max_years':None}, 'limit':5}


def job(identity, title, address, skills):
    return {'source_id':identity, 'source':'jumpit', 'job_id':int(identity), 'source_version':1,
            'title':title, 'company_name':'합성 테스트 회사', 'addresses':[address], 'tech_stacks':skills,
            'source_url':'https://example.com/'+identity, 'recruitment_status':'unknown',
            'qualifications':'공고별 경력 요건 확인 필요', 'preferred_requirements':''}


class Jobs:
    def __init__(self):
        self.rows = [job('1','백엔드 개발자','부산',['AWS']),
                     job('2','데이터 엔지니어','경상남도 창원',['Python']),
                     job('3','백엔드 개발자','서울',['Python','C++','AWS','EC2'])]
        self.calls = 0

    def search(self, plan):
        self.calls += 1
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'jobs.json'
            path.write_text(json.dumps(self.rows),encoding='utf-8')
            return JsonJobRepository(path,include_unverified=True).search(plan)

    def get(self, identity):
        return copy.deepcopy(next((r for r in self.rows if r['source_id']==identity),None))


class Planner:
    def __init__(self): self.calls=0
    def route(self, text, history):
        self.calls += 1
        return {'intent':'search','plan':copy.deepcopy(COMPLEX_PLAN)}, {}


def invoke(purpose, function, *args):
    return function(*args)[0]


class StructuredSearchTests(unittest.TestCase):
    def test_old_contract_keeps_required_and_and_positional_callers(self):
        plan=SearchPlan('백엔드','서울',('Python','AWS'),3)
        self.assertEqual(plan.to_dict(),{'keyword':'백엔드','region':'서울','skills':['Python','AWS'],'limit':3})
        self.assertEqual(plan.schema_version,1)

    def test_strict_bounds_unknown_fields_and_mixed_contracts(self):
        for data in [{'limit':'5'},{'limit':True},{'schema_version':True}, {'sql':'SELECT'},
                     {'regions':'부산'}, {'regions':[' ']}, {'owned_skills':[3]},
                     {'schema_version':2,'region':'부산'}, {'career':{'levels':['junior'],'max_years':True}},
                     {'career':{'levels':['executive']}}, {'regions':['부산']*11}]:
            with self.subTest(data=data), self.assertRaises(ValueError): SearchPlan.parse(data)

    def test_json_roundtrip_and_immutable_terms(self):
        plan=SearchPlan.parse(COMPLEX_PLAN)
        self.assertEqual(SearchPlan.parse(json.loads(json.dumps(plan.to_dict()))),plan)
        self.assertEqual(SearchPlan(regions=['부산','부산','경남']).regions,('부산','경남'))
        with self.assertRaises(ValueError): plan.limit=7

    def test_or_regions_roles_owned_not_all_required(self):
        total,rows=Jobs().search(SearchPlan.parse(COMPLEX_PLAN))
        self.assertEqual(total,2)
        self.assertEqual({r['source_id'] for r in rows},{'1','2'})

    def test_explicit_required_skills_are_all_required(self):
        plan=SearchPlan(regions=['부산','경남'], required_skills=['Python','AWS'])
        self.assertEqual(Jobs().search(plan)[0],0)

    def test_owned_only_is_any_and_does_not_include_unrelated_jobs(self):
        total,rows=Jobs().search(SearchPlan(owned_skills=['Python','FFI']))
        self.assertEqual({r['source_id'] for r in rows},{'2','3'})

    def test_region_is_never_silently_relaxed_and_empty_removes_it(self):
        self.assertEqual(Jobs().search(SearchPlan(regions=['제주'],roles=['백엔드']))[0],0)
        self.assertEqual(Jobs().search(SearchPlan(regions=[],roles=['백엔드']))[0],2)

    def test_elastic_optional_boosts_do_not_become_and_filters(self):
        query=build_query(SearchPlan.parse(COMPLEX_PLAN))['query']['bool']
        self.assertEqual(len(query['should']),6)
        self.assertEqual(query['minimum_should_match'],0)
        self.assertEqual(len(query['filter'][2]['bool']['should']),3)
        self.assertEqual(query['filter'][2]['bool']['minimum_should_match'],1)
        self.assertNotIn('career',json.dumps(query))

    def test_mysql_clauses_are_parameterized_and_keep_or_groups(self):
        plan=SearchPlan(regions=["부산' OR 1=1 --"],roles=['백엔드','데이터 엔지니어링'],
                        required_skills=['Python','AWS'], owned_skills=['C++'])
        clauses,values,ranking,rank_values=structured_clauses(plan)
        self.assertNotIn("부산'",' '.join(clauses))
        self.assertEqual(len(clauses),4)
        self.assertIn(' OR ',clauses[1])
        self.assertEqual(rank_values,['C++'])
        self.assertIn('CASE WHEN',ranking)

    def test_career_is_disclosed_as_unapplied_not_faked(self):
        summary=execution_summary(SearchPlan.parse(COMPLEX_PLAN),2,'elasticsearch',False)
        self.assertTrue(any('자동 필터는 적용하지 않았' in s for s in summary['limitations']))


class SearchReviewTests(unittest.TestCase):
    def start(self):
        self.jobs,self.planner=Jobs(),Planner()
        self.flow=DialogueFlow(self.jobs,self.planner,None,include_unverified=True)
        self.state,self.result,_=self.flow.advance({}, {'action':'search','message':COMPLEX_MESSAGE,'request_id':str(uuid4())},invoke)

    def test_complex_message_reviews_before_any_cards_or_selection(self):
        self.start()
        self.assertEqual(self.result['stage'],'search_review')
        self.assertEqual(self.result['total'],2)
        self.assertEqual(self.result['candidate_jobs'],[])
        self.assertEqual(self.state['candidate_ids'],[])
        with self.assertRaises(FlowError): self.flow.advance(self.state,{'action':'select','source_id':'1'},invoke)

    def test_confirmation_reuses_search_without_model_or_new_search(self):
        self.start()
        _,result,_=self.flow.advance(self.state,{'action':'confirm_search','search_id':self.result['search_id']},invoke)
        self.assertEqual(result['stage'],'choose_job')
        self.assertEqual(len(result['candidate_jobs']),2)
        self.assertEqual((self.planner.calls,self.jobs.calls),(1,1))

    def test_natural_confirmation_has_no_additional_model_call(self):
        self.start()
        _,result,_=self.flow.advance(self.state,{'action':'search','message':'공고 보여줘'},invoke)
        self.assertEqual(result['stage'],'choose_job')
        self.assertEqual(self.planner.calls,1)

    def test_old_review_id_and_changed_source_cannot_reveal_cards(self):
        self.start()
        with self.assertRaises(FlowError): self.flow.confirm_search(self.state,{'search_id':str(uuid4())})
        self.jobs.rows[0]['source_version']=2
        result=self.flow.confirm_search(self.state,{'search_id':self.result['search_id']})
        self.assertTrue(result['search_changed'])
        self.assertEqual(result['candidate_jobs'],[])
        self.assertEqual(self.state['candidate_ids'],[])

    def test_zero_results_has_applied_filters_and_no_relaxation(self):
        self.start()
        _,result,_=self.flow.advance({}, {'action':'search','search_plan':{'regions':['제주'],'roles':['백엔드']}},invoke)
        self.assertEqual(result['stage'],'no_results')
        self.assertIn('제주',result['search_summary']['filters'][0])
        self.assertEqual(result['candidate_jobs'],[])

    def test_clear_immediate_request_can_bypass_review(self):
        self.start()
        _,result,_=self.flow.advance({}, {'action':'search','message':'부산 경남 공고 바로 보여줘','search_plan':COMPLEX_PLAN},invoke)
        self.assertEqual(result['stage'],'choose_job')

    def test_context_keeps_preferences_and_hides_unconfirmed_candidates(self):
        self.start()
        context=consultation_context(self.state)
        self.assertEqual(context['search_preferences']['regions'],['부산','경남'])
        self.assertEqual(context['displayed_job_candidates'],[])
        self.assertEqual(context['last_search']['summary']['verified_total'],2)

    def test_confirmation_payload_needs_session_valid_ids_and_no_extra_fields(self):
        payload={'action':'confirm_search','request_id':str(uuid4()),'session_id':str(uuid4()),'search_id':str(uuid4())}
        self.assertEqual(validate_payload(payload),payload)
        for changes in [{'session_id':None},{'search_id':'old'}, {'sql':'SELECT'}]:
            with self.assertRaises((ValueError,TypeError)): validate_payload(dict(payload,**changes))


class ModelContractTests(unittest.TestCase):
    def test_mock_bedrock_output_keeps_full_structured_intent_and_budget(self):
        import os
        from unittest.mock import patch
        from src.bedrock.client import BedrockPlanner
        from test_backend import FakeRuntime
        runtime=FakeRuntime(json.dumps({'intent':'search','plan':COMPLEX_PLAN}))
        with patch.dict(os.environ,{'ENABLE_LIVE_BEDROCK':'true'}):
            result,usage=BedrockPlanner('offline-model','offline-region',client=runtime).route(COMPLEX_MESSAGE,{})
        plan=SearchPlan.parse(result['plan'])
        self.assertEqual(plan.regions,('부산','경남'))
        self.assertEqual(plan.required_skills,())
        self.assertIn('FFI',plan.owned_skills)
        self.assertEqual(runtime.calls[0]['inferenceConfig']['maxTokens'],1024)
        self.assertEqual(usage['prompt_version'],'conversation-structured-search-v7')

    def test_dangerous_or_mixed_model_output_is_rejected(self):
        import os
        from unittest.mock import patch
        from src.bedrock.client import BedrockPlanner
        from test_backend import FakeRuntime
        for extra in [{'sql':'SELECT *'}, {'region':'부산 경남'}]:
            runtime=FakeRuntime(json.dumps({'intent':'search','plan':dict(COMPLEX_PLAN,**extra)}))
            with patch.dict(os.environ,{'ENABLE_LIVE_BEDROCK':'true'}), self.assertRaises(ValueError):
                BedrockPlanner('offline-model','offline-region',client=runtime).route(COMPLEX_MESSAGE,{})


class PreferenceAndPersistenceTests(unittest.TestCase):
    def test_omitted_preferences_inherit_but_explicit_empty_clears(self):
        from src.services.model_search import normalize_model_search
        old=copy.deepcopy(COMPLEX_PLAN)
        plan=normalize_model_search(SearchPlan(owned_skills=['Java']), 'Java도 사용할 수 있어', old)
        self.assertEqual(plan.regions,('부산','경남'))
        self.assertEqual(plan.owned_skills,('Java',))
        cleared=normalize_model_search(SearchPlan(regions=[]), '지역 제한 해제', old)
        self.assertEqual(cleared.regions,())
        self.assertEqual(cleared.roles,('백엔드','데이터 엔지니어링'))
        cleared=normalize_model_search(SearchPlan(regions=['부산']), '지역은 상관없어', old)
        self.assertEqual(cleared.regions,())

    def test_modified_simple_search_still_has_review_checkpoint(self):
        from src.services.search_review import needs_review
        self.assertTrue(needs_review(SearchPlan(regions=['부산']), '부산으로 바꿔줘', changing=True))
        self.assertFalse(needs_review(SearchPlan(regions=['부산']), '부산 공고 바로 보여줘', changing=True))

    def test_search_record_is_transactional_and_not_returned_to_browser(self):
        from datetime import datetime, timedelta
        from unittest.mock import MagicMock, patch
        from src.repositories.mysql_chat import MySQLChatStore
        jobs,planner=Jobs(),Planner()
        state,result,_=DialogueFlow(jobs,planner,None,include_unverified=True).advance({},
            {'action':'search','message':COMPLEX_MESSAGE,'request_id':str(uuid4())}, invoke)
        cursor=MagicMock()
        cursor.__enter__.return_value=cursor
        cursor.fetchone.return_value={'n':1}
        connection=MagicMock()
        connection.cursor.return_value=cursor
        store=MySQLChatStore(lambda:connection,retention_hours=24)
        ticket={'session_id':str(uuid4()),'request_id':str(uuid4()),'owner':'test-owner',
                'state_version':0,'fingerprint':'test','cache_key':'test','expires_at':datetime.utcnow()+timedelta(hours=24)}
        with patch.object(store,'_lock_ticket'):
            returned=store.finish(ticket,{'action':'search'},state,result,[])
        self.assertNotIn('_search_record',returned)
        inserts=[c.args for c in cursor.execute.call_args_list if c.args[0].startswith('INSERT INTO chat_messages')]
        saved=json.loads(inserts[0][1][4])
        self.assertEqual(saved['_search_record']['executed_plan']['regions'],['부산','경남'])
        self.assertEqual(saved['_search_record']['total'],2)
        connection.commit.assert_called_once()

import copy,json,os,sys,unittest
from pathlib import Path
from unittest.mock import Mock,patch
from test_condition_review import fixture
from test_dialogue import Jobs,Questioner,invoke
from src.services.condition_review import validate_review
from src.services.dialogue import DialogueFlow
from src.repositories.elasticsearch_jobs import build_query
from src.schemas.search import SearchPlan
sys.path.insert(0,str(Path(__file__).parents[2]/'ingestion/search_index'))
from sync_outbox import Consumer,job_document
from test_search_sync import Cursor

class ConditionSelectionTests(unittest.TestCase):
    def start(self,review=None,error=None):
        job,p=fixture();jobs=Jobs();jobs.job.update(job)
        store=Mock();store.get.side_effect=error;store.get.return_value=review
        flow=DialogueFlow(jobs,None,Questioner(),include_unverified=True,condition_reviews=store)
        state,_,_=flow.advance({},dict(action='search',search_plan={}),invoke)
        state,result,_=flow.advance(state,dict(action='select',source_id='42',grouped=True),invoke)
        return flow,state,result
    def test_reference_excluded_from_questions_but_original_and_reason_preserved(self):
        job,p=fixture();flow,state,result=self.start(validate_review(job,p))
        self.assertEqual(len(state['conditions']),2);self.assertEqual(len(state['original_conditions']),3)
        self.assertEqual(len(result['reference_conditions']),1)
        self.assertIn('Python',result['questions'][0]['quote'])
        while result['stage'] in {'checking_required','checking_preferred'}:
            state,result,_=flow.advance(state,dict(action='answer_batch',answers=[dict(question_id=q['question_id'],assessment='unknown',detail='') for q in result['questions']]),invoke)
        self.assertEqual(len(state['checks']),2);self.assertEqual(result['answer_summary']['reference_count'],1)
        self.assertFalse(any('학력' in c['quote'] for c in state['checks']))
    def test_missing_failed_or_stale_review_falls_back_to_all_conditions(self):
        job,p=fixture();old=validate_review(job,p);old['condition_hash']='0'*64
        for cached,error in [(None,None),(old,None),(None,RuntimeError('private db issue'))]:
            flow,state,result=self.start(cached,error)
            self.assertEqual(len(state['conditions']),3);self.assertFalse(state.get('reference_conditions'))
    def test_all_reference_is_not_all_met_or_rehydrated_on_resume(self):
        job,p=fixture()
        for item in p['conditions']:item.update(treatment='reference',reason_code='not_eligibility')
        flow,state,result=self.start(validate_review(job,p))
        self.assertEqual(state['checks'],[]);self.assertEqual(result['answer_summary']['kind'],'no_conditions')
        flow.advance(state,dict(action='assessment_control',control='resume'),invoke)
        self.assertEqual(state['conditions'],[])
    def test_review_treatment_still_asks_and_unknown_stays_unknown(self):
        job,p=fixture();p['conditions'][0].update(treatment='review',reason_code='ambiguous')
        flow,state,result=self.start(validate_review(job,p))
        self.assertEqual(len(state['conditions']),3);self.assertEqual(result['questions'][0]['quote'],'- 학력무관')
    def test_existing_answers_are_not_reclassified_by_new_policy(self):
        flow,state,result=self.start()
        state['checks']=[flow.make_check(state['conditions'][0],'met','')]
        before=copy.deepcopy(state['conditions']);state.pop('condition_review',None)
        job,p=fixture();flow.condition_reviews.get.return_value=validate_review(job,p)
        flow.apply_condition_review(state,state['selected'])
        self.assertEqual(before,state['conditions'])

class ConditionProjectionTests(unittest.TestCase):
    def test_index_contains_nested_required_preferred_and_original_logic(self):
        job,p=fixture();job['condition_review']=validate_review(job,p)
        _,doc=job_document(job)
        self.assertEqual(doc['classified_conditions'][1]['logic']['operator'],'any')
        self.assertEqual(doc['preferred_condition_terms'],['Docker'])
        self.assertEqual(doc['qualifications'],job['qualifications'])
    def test_no_review_does_not_add_or_require_classification_fields(self):
        job,_=fixture();_,doc=job_document(job)
        self.assertNotIn('classified_conditions',doc)
    def test_classification_events_use_latest_source_and_require_opt_in(self):
        job,p=fixture();cur=Cursor(job);db=Mock();db.cursor.return_value=cur;engine=Mock()
        event=dict(entity_type='job',entity_id=1,source_version=1,operation='r:7',event_id=9)
        with self.assertRaises(ValueError):Consumer(db,engine).process(event)
        with patch('src.repositories.condition_reviews.ConditionReviewStore.load',return_value=validate_review(job,p)):
            Consumer(db,engine,include_condition_reviews=True).process(event)
        self.assertIn('condition_review',engine.apply.call_args.args[1])
        self.assertIn('processed_at',cur.sql[-1][0])
    def test_invalid_review_event_never_acknowledged(self):
        job,_=fixture();cur=Cursor(job);db=Mock();db.cursor.return_value=cur
        for operation in ('r:0','r:-1','r:abc','r:18446744073709551616'):
            with self.assertRaises(ValueError):Consumer(db,Mock(),include_condition_reviews=True).process(dict(entity_type='job',entity_id=1,source_version=1,operation=operation,event_id=9))
        self.assertFalse(cur.sql)
    def test_ranker_retains_tag_match_and_does_not_add_new_hard_requirements(self):
        plan=SearchPlan(owned_skills=['Python'])
        with patch.dict(os.environ,{'ENABLE_AI_CONDITION_RANKING':'false'}):baseline=build_query(plan)
        with patch.dict(os.environ,{'ENABLE_AI_CONDITION_RANKING':'true'}):extended=build_query(plan)
        self.assertEqual(baseline['query']['bool']['filter'][:2],extended['query']['bool']['filter'][:2])
        anchor=extended['query']['bool']['filter'][-1]
        self.assertIn('skills',json.dumps(anchor));self.assertIn('required_condition_terms',json.dumps(anchor))
        self.assertEqual(extended['query']['bool']['minimum_should_match'],0)

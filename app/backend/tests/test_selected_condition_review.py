import copy,json,os,unittest
from contextlib import contextmanager
from unittest.mock import Mock,MagicMock,patch
from uuid import uuid4
from test_condition_review import fixture,FakeRuntime
from test_dialogue import Jobs,Questioner,invoke
from src.bedrock.condition_classifier import ConditionClassifier
from src.services.condition_review import validate_review,condition_hash
from src.services.selected_condition_review import SelectedConditionReview
from src.repositories.condition_question_cache import QuestionCacheSourceChanged
from src.services.dialogue import DialogueFlow
from src.handlers.dialogue import handle_request

class MemoryCache:
    def __init__(self):self.rows={};self.busy=False;self.writes=0;self.usage=None
    def get(self,job):return copy.deepcopy(self.rows.get((job['job_id'],condition_hash(job))))
    @contextmanager
    def claim(self,job):yield not self.busy
    def save(self,job,review,usage):
        self.writes+=1;self.usage=usage;self.rows[(job['job_id'],condition_hash(job))]=copy.deepcopy(review);return review

class SelectedReviewTests(unittest.TestCase):
    def setUp(self):
        self.job,self.proposal=fixture();self.review=validate_review(self.job,self.proposal)
        self.jobs=Jobs();self.jobs.job.update(self.job);self.cache=MemoryCache()
        self.runtime=FakeRuntime(json.dumps(self.proposal));self.classifier=ConditionClassifier('offline','test',client=self.runtime)
        self.service=SelectedConditionReview(self.jobs,self.cache,self.classifier)
        self.env=patch.dict(os.environ,{'ENABLE_LIVE_BEDROCK':'true'});self.env.start();self.addCleanup(self.env.stop)
    def test_first_selection_generates_once_and_cross_session_reuses(self):
        result=self.service.resolve(self.job,invoke)
        self.assertEqual(result['source'],'generated_question_cache');self.assertEqual(len(self.runtime.calls),1)
        second=self.service.resolve(dict(self.job,source_version=9),invoke)
        self.assertEqual(second['source'],'question_cache');self.assertEqual(len(self.runtime.calls),1);self.assertEqual(self.cache.writes,1)
    def test_approved_review_precedes_generation_and_pending_drafts_are_not_read(self):
        approved=Mock();approved.get.return_value=self.review
        result=SelectedConditionReview(self.jobs,self.cache,self.classifier,approved=approved).resolve(self.job,invoke)
        self.assertEqual(result['source'],'approved_review');self.assertEqual(self.runtime.calls,[])
    def test_busy_cache_failure_bad_model_and_storage_failure_all_keep_original(self):
        self.cache.busy=True;result=self.service.resolve(self.job,invoke)
        self.assertEqual(result['status'],'review_in_progress_all_questions');self.assertFalse(self.runtime.calls)
        self.cache.busy=False
        with patch.object(self.cache,'get',side_effect=RuntimeError('private database text')):
            result=self.service.resolve(self.job,invoke)
        self.assertEqual(result['error_type'],'RuntimeError');self.assertNotIn('private',json.dumps(result));self.assertFalse(self.runtime.calls)
        with patch.object(self.cache,'save',side_effect=RuntimeError('write failed')):result=self.service.resolve(self.job,invoke)
        self.assertIsNone(result['review']);self.assertEqual(self.cache.writes,0)
    def test_source_change_is_not_silently_applied(self):
        self.jobs.job['qualifications']='Changed source'
        with self.assertRaises(QuestionCacheSourceChanged):self.service.resolve(self.job,invoke)
        self.assertFalse(self.runtime.calls)
    def test_search_and_assessment_stop_do_not_generate(self):
        flow=DialogueFlow(self.jobs,None,Questioner(),include_unverified=True,condition_resolver=self.service)
        state,_,_=flow.advance({},dict(action='search',search_plan={}),invoke)
        self.assertFalse(self.runtime.calls)
        state.setdefault('profile',{})['assistant_preferences']={'ask_assessment':False}
        _,result,_=flow.advance(state,dict(action='select',source_id='42',grouped=True),invoke)
        self.assertTrue(result['assessment_paused']);self.assertFalse(self.runtime.calls)
    def test_selected_flow_preserves_all_originals_and_returns_reference(self):
        flow=DialogueFlow(self.jobs,None,Questioner(),include_unverified=True,condition_resolver=self.service)
        state,_,_=flow.advance({},dict(action='search',search_plan={}),invoke)
        state,result,_=flow.advance(state,dict(action='select',source_id='42',grouped=True),invoke)
        self.assertEqual(len(state['original_conditions']),3);self.assertEqual(len(state['conditions']),2)
        self.assertEqual(result['condition_review']['validation_level'],'source_contract_only')
        self.assertEqual(len(self.runtime.calls),1)
        state['checks']=[flow.make_check(state['conditions'][0],'unknown','')]
        flow.apply_condition_review(state,self.job,invoke);self.assertEqual(len(self.runtime.calls),1)
    def test_truncated_whole_job_splits_once_and_audits_each_call(self):
        self.job.update(qualifications='\n'.join('- Python 경험' for _ in range(7)),preferred_requirements='')
        self.jobs.job.update(self.job);runtime=Mock();calls=[]
        def respond(**kw):
            batch=json.loads(kw['messages'][0]['content'][0]['text'])['conditions'];calls.append(batch)
            usage={'inputTokens':10,'outputTokens':5,'cacheReadInputTokens':0,'cacheWriteInputTokens':0}
            if len(batch)>3:return {'stopReason':'max_tokens','usage':usage}
            decisions=[]
            for source in batch:
                item=dict(self.proposal['conditions'][2],condition_id=source['condition_id'],logic={'operator':'atom','term':'Python','evidence':'Python'})
                item['parts']=[{'part_id':part['part_id'],'terms':['Python']} for part in source['parts']];decisions.append(item)
            return {'stopReason':'tool_use','usage':usage,'output':{'message':{'content':[{'toolUse':{'name':'submit_condition_review','input':{'conditions':decisions}}}]}}}
        runtime.converse.side_effect=respond;classifier=ConditionClassifier('offline','test',client=runtime)
        audited=[]
        def tracked(purpose,fn,*args):audited.append(purpose);return fn(*args)[0]
        result=SelectedConditionReview(self.jobs,self.cache,classifier).resolve(self.job,tracked)
        self.assertEqual(result['source'],'generated_question_cache')
        self.assertEqual(len(calls),4);self.assertEqual(audited,['condition_review']*4)
        self.assertEqual(self.cache.usage['calls'],4);self.assertEqual(self.cache.usage['input_tokens'],40)
        self.assertEqual(len(self.cache.rows[(1,condition_hash(self.job))]['conditions']),7)
        other=MemoryCache();calls.clear();audited.clear()
        result=SelectedConditionReview(self.jobs,other,classifier,max_calls=2).resolve(self.job,tracked)
        self.assertIsNone(result['review']);self.assertEqual(len(calls),1);self.assertEqual(other.writes,0)

    def test_handler_audits_each_provider_call_with_classifier_metadata(self):
        store=MagicMock();store.begin.return_value={'state':{'candidate_ids':['42']},'session_id':str(uuid4())}
        store.finish.side_effect=lambda ticket,payload,state,result,evidence:result
        approved=Mock();approved.get.return_value=None
        token='on-demand-unit-token-'+'x'*40;payload={'action':'select','source_id':'42','grouped':True,'request_id':str(uuid4()),'session_id':str(uuid4())}
        with patch.dict(os.environ,{'CHAT_API_TOKEN':token,'CHAT_RETENTION_HOURS':'24','CHAT_INCLUDE_UNVERIFIED':'true','ENABLE_ON_DEMAND_CONDITIONS':'true','INTENT_AUDIT_ENABLED':'false'}):
            result=handle_request({'headers':{'Authorization':'Bearer '+token,'X-Client-Token':'q'*32},'body':json.dumps(payload)},jobs=self.jobs,store=store,planner=Questioner(),questioner=Questioner(),training=Mock(),condition_reviews=approved,condition_classifier=self.classifier,condition_question_cache=self.cache)
        self.assertEqual(result['statusCode'],200,result)
        args=store.begin_invocation.call_args.args
        self.assertEqual(args[1:5],('condition_review','offline','test','condition-review-v2'))
        self.assertEqual(store.begin_invocation.call_count,1);store.finish_invocation.assert_called_once()

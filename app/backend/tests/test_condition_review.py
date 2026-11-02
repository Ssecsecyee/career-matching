import copy,json,os,unittest
from unittest.mock import Mock,MagicMock,patch
from src.services.condition_review import source_conditions,review_key,condition_hash,validate_review,validated_envelope,question_selection,projection
from src.repositories.condition_reviews import ConditionReviewStore
from src.bedrock.condition_classifier import ConditionClassifier
from src.bedrock.model_json import ModelOutputFormatError,ModelOutputTruncatedError
from test_backend import FakeRuntime

def fixture():
    job={'job_id':1,'source':'jumpit','source_id':'42','source_version':1,
         'recruitment_status':'unknown','qualifications':'- 학력무관\n- Python 또는 Java 사용 경험','preferred_requirements':'- Docker 활용'}
    proposal={'conditions':[]}
    for i,c in enumerate(source_conditions(job)):
        proposal['conditions'].append({'condition_id':review_key(c),'treatment':'reference' if i==0 else 'ask',
          'category':'education' if i==0 else 'skill','reason_code':'no_restriction' if i==0 else 'verifiable_requirement',
          'reason':'학력 제한 없음' if i==0 else '원문의 기술 경험 확인',
          'logic':{'operator':'unresolved'} if i==0 else ({'operator':'any','children':[
             {'operator':'atom','term':'Python','evidence':'Python'},{'operator':'atom','term':'Java','evidence':'Java'}]} if i==1 else
             {'operator':'atom','term':'Docker','evidence':'Docker'})})
    return job,proposal

class ConditionReviewTests(unittest.TestCase):
    def test_source_relationships_and_question_reference_boundary(self):
        job,p=fixture();result=validate_review(job,p);q,refs,all_rows=question_selection(job,result)
        self.assertEqual((len(q),len(refs),len(all_rows)),(2,1,3))
        self.assertEqual(refs[0]['quote'],'- 학력무관');self.assertNotIn('assessment',refs[0])
        indexed=projection(job,result)
        self.assertEqual(indexed['required_condition_terms'],['Python','Java'])
        self.assertEqual(indexed['classified_conditions'][1]['logic']['operator'],'any')
    def test_missing_duplicate_unknown_and_fabricated_evidence_rejected(self):
        job,p=fixture()
        for variant in [dict(conditions=p['conditions'][:-1]),dict(conditions=p['conditions']+[p['conditions'][0]])]:
            with self.assertRaises(ValueError):validate_review(job,variant)
        p['conditions'][0]['condition_id']='a'*64
        with self.assertRaises(ValueError):validate_review(job,p)
        job,p=fixture();p['conditions'][2]['logic']['evidence']='invented AWS'
        with self.assertRaises(ValueError):validate_review(job,p)
    def test_cached_quote_is_rebuilt_from_source(self):
        job,p=fixture();cached=validate_review(job,p);cached['conditions'][0]['quote']='tampered'
        result=validated_envelope(job,cached)
        self.assertEqual(result['conditions'][0]['quote'],'- 학력무관')
    def test_address_deadline_and_source_version_change_reuse_but_condition_change_invalidates(self):
        job,p=fixture();result=validate_review(job,p)
        changed=dict(job,source_version=9,deadline_at='2027-01-01',addresses=['부산'])
        self.assertEqual(condition_hash(job),condition_hash(changed))
        q,refs,_=question_selection(changed,result);self.assertTrue(q[0]['id'].startswith('42:9:'))
        with self.assertRaises(ValueError):validated_envelope(dict(job,qualifications='학사 필수'),result)
        result['policy_version']='old'
        with self.assertRaises(ValueError):validated_envelope(job,result)
    def test_repeated_original_lines_have_distinct_stable_ids(self):
        job,_=fixture();job['qualifications']='- Python 경험\n- Python 경험'
        conditions=source_conditions(job)
        self.assertEqual(len({review_key(c) for c in conditions}),len(conditions))
    def test_invalid_treatment_combination_and_deep_logic_are_rejected(self):
        job,p=fixture();p['conditions'][0]['reason_code']='verifiable_requirement'
        with self.assertRaises(ValueError):validate_review(job,p)
        job,p=fixture();node={'operator':'atom','term':'Python','evidence':'Python'}
        for _ in range(6):node={'operator':'all','children':[node,{'operator':'atom','term':'Java','evidence':'Java'}]}
        p['conditions'][1]['logic']=node
        with self.assertRaises(ValueError):validate_review(job,p)
    def test_model_call_opt_in_usage_and_explicit_budget(self):
        job,p=fixture();runtime=FakeRuntime(json.dumps(p,ensure_ascii=False))
        classifier=ConditionClassifier('fake','test',client=runtime)
        with patch.dict(os.environ,{'ENABLE_LIVE_BEDROCK':'false'}),self.assertRaises(RuntimeError):classifier.classify(job)
        self.assertEqual(runtime.calls,[])
        with patch.dict(os.environ,{'ENABLE_LIVE_BEDROCK':'true'}):result,usage=classifier.classify(job)
        self.assertEqual(len(result['conditions']),3);self.assertEqual(usage['prompt_version'],'condition-review-v1')
        self.assertEqual(runtime.calls[0]['inferenceConfig']['maxTokens'],4096)
    def test_model_truncation_and_invalid_output_never_become_empty_review(self):
        job,_=fixture()
        for runtime,error in [(FakeRuntime('{}'),ModelOutputFormatError),(FakeRuntime('{}',stop='max_tokens'),ModelOutputTruncatedError)]:
            with patch.dict(os.environ,{'ENABLE_LIVE_BEDROCK':'true'}),self.assertRaises(error):ConditionClassifier('fake','test',client=runtime).classify(job)

class ReviewStoreTests(unittest.TestCase):
    def setup_store(self):
        job,p=fixture();review=validate_review(job,p);db=MagicMock();cur=db.cursor.return_value.__enter__.return_value
        cur.fetchone.side_effect=[job,None];cur.lastrowid=7
        return job,review,db,cur,ConditionReviewStore(lambda:db)
    def test_atomic_derived_save_does_not_update_original_source(self):
        job,review,db,cur,store=self.setup_store()
        result=store.save(job,review,{'model_id':'fake','region':'test'},apply=True)
        self.assertEqual(result['review_id'],7);db.commit.assert_called_once()
        sql=' '.join(c.args[0] for c in cur.execute.call_args_list)
        self.assertNotIn('UPDATE job_postings',sql)
        self.assertEqual(cur.execute.call_args.args[1],(1,1,'r:7'))
    def test_source_changed_during_call_rolls_back(self):
        job,review,db,cur,store=self.setup_store();cur.fetchone.side_effect=[dict(job,qualifications='new source')]
        with self.assertRaises(ValueError):store.save(job,review,{'model_id':'fake','region':'test'},apply=True)
        db.commit.assert_not_called();db.rollback.assert_called_once()
    def test_outbox_failure_rolls_back_classification(self):
        job,review,db,cur,store=self.setup_store()
        def execute(sql,*args):
            if sql.startswith('INSERT INTO search_outbox'):raise RuntimeError('offline failure')
        cur.execute.side_effect=execute
        with self.assertRaises(RuntimeError):store.save(job,review,{'model_id':'fake','region':'test'},apply=True)
        db.commit.assert_not_called();db.rollback.assert_called_once()
    def test_preview_and_existing_review_do_not_write(self):
        job,review,db,cur,store=self.setup_store()
        self.assertEqual(store.save(job,review,{},apply=False)['status'],'validated_not_applied')
        self.assertFalse(any(c.args[0].startswith('INSERT') for c in cur.execute.call_args_list))
        job,review,db,cur,store=self.setup_store();cur.fetchone.side_effect=[job,{'review_id':9,'classification':json.dumps(review)}]
        self.assertEqual(store.save(job,review,{},apply=True)['status'],'reused');db.commit.assert_not_called()

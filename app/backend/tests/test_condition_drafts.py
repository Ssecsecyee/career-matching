import copy,json,unittest
from unittest.mock import MagicMock,patch
from test_condition_review import fixture
from src.services.condition_review import validate_review
from src.repositories.condition_drafts import ConditionDraftStore,candidate_hash,validate_approval

class DraftTests(unittest.TestCase):
    def setUp(self):
        self.job,p=fixture();self.review=validate_review(self.job,p)
        self.approval={'reviewer':'offline QA','candidate_hash':candidate_hash(self.review),'conditions':[
            {'condition_id':c['condition_id'],'source_complete':True,'logic_preserved':True,'label_confirmed':True,'note':'Checked against original source'} for c in self.review['conditions']]}
    def test_full_exact_approval_required(self):
        validate_approval(self.review,self.approval)
        for key in ('source_complete','logic_preserved','label_confirmed'):
            a=copy.deepcopy(self.approval);a['conditions'][0][key]=False
            with self.assertRaises(ValueError):validate_approval(self.review,a)
        for mutate in ('missing','duplicate','hash'):
            a=copy.deepcopy(self.approval)
            if mutate=='missing':a['conditions'].pop()
            if mutate=='duplicate':a['conditions'][1]=a['conditions'][0]
            if mutate=='hash':a['candidate_hash']='0'*64
            with self.assertRaises(ValueError):validate_approval(self.review,a)
    def db(self):
        db=MagicMock();cur=db.cursor.return_value.__enter__.return_value
        return db,cur
    def test_stage_never_emits_event_or_published_row(self):
        db,cur=self.db();cur.fetchone.side_effect=[self.job,None];cur.lastrowid=7
        result=ConditionDraftStore(lambda:db).stage(self.job,self.review,{'model_id':'offline','region':'test'})
        self.assertEqual(result['status'],'staged');db.commit.assert_called_once()
        sql=' '.join(c.args[0] for c in cur.execute.call_args_list)
        self.assertIn('INSERT INTO job_condition_review_drafts',sql)
        self.assertNotIn('search_outbox',sql);self.assertNotIn('INSERT INTO job_condition_reviews(',sql)
    def test_changed_source_rejected_before_staging(self):
        db,cur=self.db();cur.fetchone.return_value=dict(self.job,qualifications='Changed')
        with self.assertRaises(ValueError):ConditionDraftStore(lambda:db).stage(self.job,self.review,{})
        db.rollback.assert_called_once();db.commit.assert_not_called()
    def test_unverified_cannot_publish(self):
        store=ConditionDraftStore(None)
        with patch.object(store,'inspect',return_value={'status':'pending'}),patch('src.repositories.condition_drafts.ConditionReviewStore.save') as publish:
            with self.assertRaises(ValueError):store.publish(7)
            publish.assert_not_called()
    def test_verified_publish_uses_atomic_source_guarded_store(self):
        store=ConditionDraftStore(None);db,cur=self.db();store.factory=lambda:db
        row={'status':'verified','source_snapshot':json.dumps(self.job),'classification':json.dumps(self.review),'validation_report':json.dumps(self.approval),'model_usage':json.dumps({'model_id':'offline','region':'test'})}
        with patch.object(store,'inspect',return_value=row),patch('src.repositories.condition_drafts.ConditionReviewStore.save',return_value={'status':'saved','review_id':4}) as publish:
            self.assertEqual(store.publish(7)['review_id'],4);publish.assert_called_once()
        self.assertIn("status='published'",cur.execute.call_args.args[0])

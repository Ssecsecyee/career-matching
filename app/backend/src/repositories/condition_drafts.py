"""Quarantine extraction before approval. Only publishing emits a search event."""
import hashlib,json
from src.repositories.condition_reviews import ConditionReviewStore
from src.services.condition_review import condition_hash,validated_envelope

def decode(value):
    return json.loads(value) if isinstance(value,(str,bytes)) else value

def candidate_hash(review):
    return hashlib.sha256(json.dumps(review,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()

def validate_approval(review,approval):
    if not isinstance(approval,dict) or approval.get('candidate_hash')!=candidate_hash(review):
        raise ValueError('Approval must identify the exact candidate')
    if not isinstance(approval.get('reviewer'),str) or not approval['reviewer'].strip():
        raise ValueError('Reviewer required')
    checks=approval.get('conditions')
    expected={c['condition_id'] for c in review['conditions']}
    if not isinstance(checks,list) or len(checks)!=len(expected) or {c.get('condition_id') for c in checks}!=expected:
        raise ValueError('Every original condition must be reviewed exactly once')
    for item in checks:
        if any(item.get(key) is not True for key in ('source_complete','logic_preserved','label_confirmed')):
            raise ValueError('Incomplete content, logic or label verification')
        if not isinstance(item.get('note'),str) or not item['note'].strip():
            raise ValueError('Per-condition review note required')
    return approval

class ConditionDraftStore:
    def __init__(self,factory):self.factory=factory
    def stage(self,job,review,usage):
        checked=validated_envelope(job,review);digest=candidate_hash(checked)
        db=self.factory()
        try:
            db.begin()
            with db.cursor() as cur:
                cur.execute('SELECT job_id,source_id,source_version,qualifications,preferred_requirements FROM job_postings WHERE job_id=%s FOR SHARE',(job['job_id'],))
                current=cur.fetchone()
                if not current or str(current['source_id'])!=str(job['source_id']) or condition_hash(current)!=checked['condition_hash']:
                    raise ValueError('Source changed during extraction')
                cur.execute('SELECT draft_id,status FROM job_condition_review_drafts WHERE job_id=%s AND condition_hash=%s AND candidate_hash=%s',(job['job_id'],checked['condition_hash'],digest))
                existing=cur.fetchone()
                if existing:
                    db.rollback();return {'status':'draft_reused','draft_id':existing['draft_id'],'draft_status':existing['status']}
                cur.execute('INSERT INTO job_condition_review_drafts(job_id,source_version,condition_hash,candidate_hash,source_snapshot,classification,model_usage) VALUES(%s,%s,%s,%s,%s,%s,%s)',
                    (job['job_id'],current['source_version'],checked['condition_hash'],digest,json.dumps(current,ensure_ascii=False),json.dumps(checked,ensure_ascii=False),json.dumps(usage,ensure_ascii=False)))
                identity=cur.lastrowid
            db.commit();return {'status':'staged','draft_id':identity,'candidate_hash':digest}
        except Exception:
            db.rollback();raise
        finally:db.close()
    def inspect(self,draft_id):
        db=self.factory()
        try:
            with db.cursor() as cur:
                cur.execute('SELECT * FROM job_condition_review_drafts WHERE draft_id=%s',(draft_id,));row=cur.fetchone()
            if not row:raise ValueError('Unknown draft')
            return row
        finally:db.close()
    def verify(self,draft_id,approval):
        row=self.inspect(draft_id)
        review=validated_envelope(decode(row['source_snapshot']),decode(row['classification']))
        validate_approval(review,approval)
        db=self.factory()
        try:
            with db.cursor() as cur:
                cur.execute("UPDATE job_condition_review_drafts SET validation_report=%s,status='verified' WHERE draft_id=%s AND status='pending' AND candidate_hash=%s",(json.dumps(approval,ensure_ascii=False),draft_id,candidate_hash(review)))
                if cur.rowcount!=1:raise ValueError('Draft is not pending')
            db.commit()
        except Exception:db.rollback();raise
        finally:db.close()
        return {'status':'verified','draft_id':draft_id}
    def publish(self,draft_id):
        row=self.inspect(draft_id)
        if row['status']=='published':return {'status':'reused','review_id':row['review_id']}
        if row['status']!='verified':raise ValueError('Unverified draft cannot be indexed')
        job=decode(row['source_snapshot']);review=validated_envelope(job,decode(row['classification']))
        validate_approval(review,decode(row['validation_report']))
        # Existing save rechecks current source under a lock and commits review+event atomically.
        saved=ConditionReviewStore(self.factory).save(job,review,decode(row['model_usage']),apply=True)
        db=self.factory()
        try:
            with db.cursor() as cur:
                cur.execute("UPDATE job_condition_review_drafts SET status='published',review_id=%s WHERE draft_id=%s AND status='verified'",(saved['review_id'],draft_id))
            db.commit()
        finally:db.close()
        # A crash after event commit is safe: immutable review reuse makes retry idempotent.
        return dict(saved,draft_id=draft_id)

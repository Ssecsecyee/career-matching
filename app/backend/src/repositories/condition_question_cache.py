"""Public source-derived question cache; never writes approved reviews or ES events."""
from contextlib import contextmanager
import hashlib,json
from src.schemas.condition_review import POLICY_VERSION
from src.services.condition_review import condition_hash,validated_envelope
from src.services.deadlines import VISIBLE_SQL

QUESTION_POLICY='selected-question-v1:'+POLICY_VERSION
class QuestionCacheSourceChanged(ValueError):pass

class ConditionQuestionCache:
    def __init__(self,factory):self.factory=factory
    def get(self,job):
        db=self.factory()
        try:
            with db.cursor() as c:
                c.execute('SELECT cache_id,classification,validation_level FROM job_condition_question_cache WHERE job_id=%s AND condition_hash=%s AND review_policy=%s',(job['job_id'],condition_hash(job),QUESTION_POLICY))
                row=c.fetchone()
            if not row:return None
            if row['validation_level']!='source_contract_only':raise ValueError('Unexpected cache validation level')
            raw=json.loads(row['classification']) if isinstance(row['classification'],(str,bytes)) else row['classification']
            return dict(validated_envelope(job,raw),question_cache_id=row['cache_id'])
        finally:db.close()
    @contextmanager
    def claim(self,job):
        key='condq:'+hashlib.sha256((str(job['job_id'])+':'+condition_hash(job)+':'+QUESTION_POLICY).encode()).hexdigest()[:58]
        db=self.factory();acquired=False
        try:
            with db.cursor() as c:
                c.execute('SELECT GET_LOCK(%s,0) AS acquired',(key,));acquired=c.fetchone()['acquired']==1
            yield acquired
        finally:
            try:
                if acquired:
                    with db.cursor() as c:c.execute('SELECT RELEASE_LOCK(%s)',(key,))
            finally:db.close()
    def save(self,job,review,usage):
        checked=validated_envelope(job,review);db=self.factory()
        try:
            db.begin()
            with db.cursor() as c:
                c.execute("SELECT job_id,source_id,source_version,qualifications,preferred_requirements FROM job_postings WHERE job_id=%s AND recruitment_status IN ('active','unknown') AND "+VISIBLE_SQL+' FOR SHARE',(job['job_id'],))
                current=c.fetchone()
                if not current or str(current['source_id'])!=str(job['source_id']) or condition_hash(current)!=checked['condition_hash']:
                    raise QuestionCacheSourceChanged('Selected source changed or became unavailable')
                c.execute('INSERT INTO job_condition_question_cache(job_id,source_version,condition_hash,review_policy,source_snapshot,classification,model_usage) VALUES(%s,%s,%s,%s,%s,%s,%s)',
                    (job['job_id'],current['source_version'],checked['condition_hash'],QUESTION_POLICY,json.dumps(current,ensure_ascii=False),json.dumps(checked,ensure_ascii=False),json.dumps(usage,ensure_ascii=False)))
                identity=c.lastrowid
            db.commit();return dict(checked,question_cache_id=identity)
        except Exception:db.rollback();raise
        finally:db.close()

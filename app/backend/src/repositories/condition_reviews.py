"""Immutable review cache and transactional projection events; no source updates."""
import json
from src.schemas.condition_review import POLICY_VERSION
from src.services.condition_review import condition_hash,validated_envelope

class ConditionReviewStore:
    def __init__(self,connection_factory):self.factory=connection_factory
    @staticmethod
    def load(connection,job):
        with connection.cursor() as cur:
            cur.execute('SELECT review_id,classification FROM job_condition_reviews WHERE job_id=%s AND condition_hash=%s AND policy_version=%s',
                        (job['job_id'],condition_hash(job),POLICY_VERSION))
            row=cur.fetchone()
        if not row:return None
        raw=json.loads(row['classification']) if isinstance(row['classification'],(str,bytes)) else row['classification']
        return dict(validated_envelope(job,raw),review_id=row['review_id'])
    def get(self,job):
        connection=self.factory()
        try:return self.load(connection,job)
        finally:connection.close()
    def save(self,job,review,usage,*,apply=False):
        checked=validated_envelope(job,review)
        connection=self.factory()
        try:
            connection.begin()
            with connection.cursor() as cur:
                cur.execute('SELECT job_id,source_id,source_version,qualifications,preferred_requirements FROM job_postings WHERE job_id=%s FOR UPDATE',(job['job_id'],))
                current=cur.fetchone()
                if not current or str(current['source_id'])!=str(job['source_id']) or condition_hash(current)!=checked['condition_hash']:
                    raise ValueError('Source changed during classification')
            cached=self.load(connection,current)
            if cached:
                connection.rollback();return {'status':'reused','review_id':cached['review_id']}
            if not apply:
                connection.rollback();return {'status':'validated_not_applied'}
            with connection.cursor() as cur:
                cur.execute('INSERT INTO job_condition_reviews(job_id,source_version,condition_hash,policy_version,parser_version,model_id,region,classification,model_usage) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)',
                    (job['job_id'],current['source_version'],checked['condition_hash'],POLICY_VERSION,checked['parser_version'],usage['model_id'],usage['region'],json.dumps(checked,ensure_ascii=False),json.dumps(usage,ensure_ascii=False)))
                identity=cur.lastrowid
                cur.execute("INSERT INTO search_outbox(entity_type,entity_id,source_version,operation) VALUES('job',%s,%s,%s)",
                    (job['job_id'],current['source_version'],'r:'+str(identity)))
            connection.commit();return {'status':'saved','review_id':identity}
        except Exception:
            connection.rollback();raise
        finally:connection.close()

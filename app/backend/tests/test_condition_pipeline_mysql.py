"""Optional isolated DB/ES tests. Never use production ports, secrets or models."""
import copy,json,os,secrets,sys,time,unittest
from pathlib import Path
from urllib.request import Request,urlopen
from urllib.error import URLError
from unittest.mock import Mock,patch
from test_condition_review import fixture
from src.services.condition_review import validate_review,condition_hash,projection
from src.repositories.condition_reviews import ConditionReviewStore
sys.path.insert(0,str(Path(__file__).parents[2]/'ingestion/search_index'))
sys.path.insert(0,str(Path(__file__).parents[2]/'ingestion'))
from sync_outbox import Consumer,Engine
from index_snapshot import snapshot_mapping,document
from classify_job_conditions import run
from export_classified_snapshot import export
from src.repositories.elasticsearch_jobs import build_query
from src.schemas.search import SearchPlan

@unittest.skipUnless(os.getenv('TEST_MYSQL_PORT'),'Isolated MySQL not configured')
class ReviewDatabaseTests(unittest.TestCase):
    def setUp(self):
        import pymysql
        port=int(os.environ['TEST_MYSQL_PORT'])
        if port!=13339:raise ValueError('This suite only uses isolated port 13339')
        self.options=dict(host='127.0.0.1',port=port,user='root',database='career_verify',charset='utf8mb4',autocommit=True,cursorclass=pymysql.cursors.DictCursor)
        self.factory=lambda:pymysql.connect(**self.options)
        self.job,self.proposal=fixture();self.job['source_id']=str(secrets.randbelow(10**10)+10**11)
        with self.factory() as db:
            with db.cursor() as c:
                c.execute("INSERT INTO job_postings(source,source_id,source_url,title,company_name,qualifications,preferred_requirements,tech_stacks,addresses,recruitment_status,fetched_at) VALUES('jumpit',%s,'https://example.test','Synthetic review','QA',%s,%s,JSON_ARRAY(),JSON_ARRAY(),'unknown',UTC_TIMESTAMP())",(self.job['source_id'],self.job['qualifications'],self.job['preferred_requirements']))
                self.job['job_id']=c.lastrowid
        self.review=validate_review(self.job,self.proposal);self.store=ConditionReviewStore(self.factory)
    def tearDown(self):
        with self.factory() as db:
            with db.cursor() as c:
                c.execute('DELETE FROM search_outbox WHERE entity_type=%s AND entity_id=%s',('job',self.job['job_id']))
                c.execute('DELETE FROM job_condition_reviews WHERE job_id=%s',(self.job['job_id'],))
                c.execute('DELETE FROM job_postings WHERE job_id=%s',(self.job['job_id'],))
    def save(self,store=None):return (store or self.store).save(self.job,self.review,{'model_id':'offline-fixture','region':'test'},apply=True)
    def test_immutable_reuse_source_version_and_content_invalidation(self):
        saved=self.save();again=self.save()
        self.assertEqual(saved['review_id'],again['review_id']);self.assertEqual(again['status'],'reused')
        with self.factory() as db:
            with db.cursor() as c:
                c.execute('SELECT source_version FROM job_postings WHERE job_id=%s',(self.job['job_id'],));self.assertEqual(c.fetchone()['source_version'],1)
                c.execute('SELECT COUNT(*) AS n FROM search_outbox WHERE entity_id=%s AND operation=%s',(self.job['job_id'],'r:'+str(saved['review_id'])));self.assertEqual(c.fetchone()['n'],1)
                c.execute('UPDATE job_postings SET source_version=2,addresses=JSON_ARRAY(%s) WHERE job_id=%s',('부산',self.job['job_id']))
        self.assertIsNotNone(self.store.get(dict(self.job,source_version=2)))
        with self.factory() as db:
            with db.cursor() as c:c.execute('UPDATE job_postings SET qualifications=%s,source_version=3 WHERE job_id=%s',('새 학위 조건',self.job['job_id']))
        current=dict(self.job,source_version=3,qualifications='새 학위 조건')
        self.assertIsNone(self.store.get(current))
        with self.assertRaises(ValueError):self.save()
    def test_minimal_writer_permissions_and_atomic_outbox_failure(self):
        import pymysql
        username='review_qa_'+secrets.token_hex(4);password=secrets.token_hex(16)
        try:
            with self.factory() as db:
                with db.cursor() as c:
                    c.execute("CREATE USER %s@'%%' IDENTIFIED BY %s",(username,password))
                    c.execute("GRANT SELECT ON career_verify.job_postings TO %s@'%%'",(username,))
                    c.execute("GRANT SELECT,INSERT ON career_verify.job_condition_reviews TO %s@'%%'",(username,))
            limited=ConditionReviewStore(lambda:pymysql.connect(**dict(self.options,user=username,password=password)))
            with self.assertRaises(pymysql.MySQLError):self.save(limited)
            self.assertIsNone(self.store.get(self.job))
            with self.factory() as db:
                with db.cursor() as c:c.execute("GRANT INSERT ON career_verify.search_outbox TO %s@'%%'",(username,))
            self.assertEqual(self.save(limited)['status'],'saved')
        finally:
            with self.factory() as db:
                with db.cursor() as c:c.execute("DROP USER IF EXISTS %s@'%%'",(username,))
    def test_default_backfill_is_read_only_and_live_apply_is_cached(self):
        model=Mock();model.classify.return_value=(self.review,{'model_id':'offline-fixture','region':'test'})
        result=run(self.factory,model,after_job_id=self.job['job_id']-1,limit=1)
        self.assertEqual(result['planned'],1);model.classify.assert_not_called();self.assertIsNone(self.store.get(self.job))
        result=run(self.factory,model,after_job_id=self.job['job_id']-1,limit=1,live=True,apply=True)
        self.assertEqual(result['saved'],1);model.classify.assert_called_once()
        result=run(self.factory,model,after_job_id=self.job['job_id']-1,limit=1,live=True,apply=True)
        self.assertEqual(result['reused'],1);model.classify.assert_called_once()
    def test_full_snapshot_export_contains_current_review_without_source_changes(self):
        self.save()
        with self.factory() as db:rows=export(db)
        row=next(row for row in rows if row['job_id']==self.job['job_id'])
        self.assertIn('condition_review',row);self.assertEqual(row['qualifications'],self.job['qualifications'])

@unittest.skipUnless(os.getenv('TEST_MYSQL_PORT') and os.getenv('TEST_CONDITION_ES_PORT')=='19301','Isolated DB/ES not configured')
class ReviewSearchIntegrationTests(ReviewDatabaseTests):
    def request(self,method,path,body=None):
        data=None if body is None else json.dumps(body,ensure_ascii=False).encode()
        with urlopen(Request('http://127.0.0.1:19301'+path,data,{'Content-Type':'application/json'},method=method),timeout=10) as response:return json.load(response)
    def test_review_event_indexes_logic_and_both_classified_and_unclassified_candidates(self):
        name='career-condition-qa-'+secrets.token_hex(5);alias=name+'-read'
        for attempt in range(30):
            try:self.request('GET','/_cluster/health');break
            except (URLError,TimeoutError):
                if attempt==29:raise
                time.sleep(1)
        try:
            self.request('PUT','/'+name,snapshot_mapping())
            self.request('POST','/_aliases',{'actions':[{'add':{'index':name,'alias':alias}}]})
            saved=self.save()
            with self.factory() as db:
                with db.cursor() as c:
                    c.execute('SELECT * FROM search_outbox WHERE entity_id=%s AND operation=%s',(self.job['job_id'],'r:'+str(saved['review_id'])))
                    event=c.fetchone()
                engine=Engine(alias,alias);engine.request=self.request
                Consumer(db,engine,include_condition_reviews=True).process(event)
                with db.cursor() as c:
                    c.execute('SELECT processed_at FROM search_outbox WHERE event_id=%s',(event['event_id'],));self.assertIsNotNone(c.fetchone()['processed_at'])
            other=dict(self.job,source_id=self.job['source_id']+'9',tech_stacks=['Python'])
            key,doc=document(other);self.request('PUT','/'+alias+'/_doc/'+key,doc)
            self.request('POST','/'+alias+'/_refresh')
            with patch.dict(os.environ,{'ENABLE_AI_CONDITION_RANKING':'true'}):query=build_query(SearchPlan(owned_skills=['Python']),include_unverified=True)
            found=self.request('POST','/'+alias+'/_search',query)
            self.assertEqual(found['hits']['total']['value'],2)
            classified=next(h['_source'] for h in found['hits']['hits'] if 'classified_conditions' in h['_source'])
            self.assertEqual(classified['classified_conditions'][1]['logic']['operator'],'any')
            self.assertEqual(classified['qualifications'],self.job['qualifications'])
            # A fresh source version with changed conditions drops stale derived fields.
            with self.factory() as db:
                with db.cursor() as c:c.execute('UPDATE job_postings SET qualifications=%s,source_version=2 WHERE job_id=%s',('미분류 새 조건',self.job['job_id']))
                Consumer(db,engine,include_condition_reviews=True).process(event)
            self.request('POST','/'+alias+'/_refresh')
            current=self.request('POST','/'+alias+'/_search',{'query':{'term':{'source_id':self.job['source_id']}}})['hits']['hits'][0]['_source']
            self.assertNotIn('classified_conditions',current);self.assertEqual(current['source_version'],'2')
        finally:
            if name.startswith('career-condition-qa-'):self.request('DELETE','/'+name)

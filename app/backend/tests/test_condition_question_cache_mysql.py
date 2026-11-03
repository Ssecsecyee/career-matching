import json,os,unittest
import test_condition_pipeline_mysql as database_fixtures
from src.repositories.condition_question_cache import ConditionQuestionCache,QuestionCacheSourceChanged
from src.services.condition_review import condition_hash

@unittest.skipUnless(os.getenv('TEST_MYSQL_PORT'),'Isolated MySQL not configured')
class QuestionCacheDatabaseTests(unittest.TestCase):
    setUp=database_fixtures.ReviewDatabaseTests.setUp
    def tearDown(self):
        with self.factory() as db:
            with db.cursor() as c:c.execute('DELETE FROM job_condition_question_cache WHERE job_id=%s',(self.job['job_id'],))
        database_fixtures.ReviewDatabaseTests.tearDown(self)
    def test_immutable_shared_cache_writes_no_source_or_outbox(self):
        cache=ConditionQuestionCache(self.factory)
        with cache.claim(self.job) as got:
            self.assertTrue(got);saved=cache.save(self.job,self.review,{'model_id':'offline','calls':1})
        self.assertEqual(cache.get(self.job)['question_cache_id'],saved['question_cache_id'])
        with self.factory() as db:
            with db.cursor() as c:
                c.execute('SELECT COUNT(*) AS n FROM search_outbox WHERE entity_id=%s',(self.job['job_id'],));self.assertEqual(c.fetchone()['n'],0)
                c.execute('SELECT qualifications,source_version FROM job_postings WHERE job_id=%s',(self.job['job_id'],));row=c.fetchone()
                self.assertEqual(row['source_version'],1);self.assertEqual(row['qualifications'],self.job['qualifications'])
        with self.assertRaises(Exception):cache.save(self.job,self.review,{})
        self.assertEqual(cache.get(self.job)['question_cache_id'],saved['question_cache_id'])
    def test_two_connections_cannot_generate_same_key_concurrently(self):
        a=ConditionQuestionCache(self.factory);b=ConditionQuestionCache(self.factory)
        with a.claim(self.job) as first:
            self.assertTrue(first)
            with b.claim(self.job) as second:self.assertFalse(second)
        with b.claim(self.job) as again:self.assertTrue(again)
    def test_changed_conditions_and_expired_source_do_not_store(self):
        cache=ConditionQuestionCache(self.factory)
        with self.factory() as db:
            with db.cursor() as c:c.execute("UPDATE job_postings SET deadline_type='fixed_date',deadline_at=UTC_TIMESTAMP()-INTERVAL 1 DAY WHERE job_id=%s",(self.job['job_id'],))
        with self.assertRaises(QuestionCacheSourceChanged):cache.save(self.job,self.review,{})
        self.assertIsNone(cache.get(self.job))
    def test_runtime_cache_needs_no_source_write_or_outbox_privileges(self):
        import pymysql,secrets
        user='qc_'+secrets.token_hex(5);password=secrets.token_hex(16)
        try:
            with self.factory() as db:
                with db.cursor() as c:
                    c.execute("CREATE USER %s@'%%' IDENTIFIED BY %s",(user,password))
                    c.execute("GRANT SELECT ON career_verify.job_postings TO %s@'%%'",(user,))
                    c.execute("GRANT SELECT,INSERT ON career_verify.job_condition_question_cache TO %s@'%%'",(user,))
            factory=lambda:pymysql.connect(**dict(self.options,user=user,password=password))
            cache=ConditionQuestionCache(factory)
            with cache.claim(self.job) as got:
                self.assertTrue(got);saved=cache.save(self.job,self.review,{'model_id':'offline'})
            self.assertEqual(cache.get(self.job)['question_cache_id'],saved['question_cache_id'])
        finally:
            with self.factory() as db:
                with db.cursor() as c:c.execute("DROP USER IF EXISTS %s@'%%'",(user,))

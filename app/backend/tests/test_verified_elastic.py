import os
import unittest
from unittest.mock import patch
from src.repositories.job_search_factory import VerifiedElasticJobs, LocalElasticTransport, create_job_repository
from src.repositories.mysql_jobs import MySQLJobRepository
from src.schemas.search import SearchPlan

class DB:
    def search_details(self,ids):
        return {'1':{'source_id':'1','source_version':2}, '2':{'source_id':'2','source_version':3}}
    def get(self,identity):return {'source_id':identity}

def response():
    return {'hits':{'total':{'value':3,'relation':'eq'},'hits':[
        {'_source':{'source':'jumpit','source_id':i,'source_version':2}} for i in ['1','2','3']]}}

class VerifiedElasticTests(unittest.TestCase):
    def test_latest_db_version_and_removed_rows_excluded_before_count(self):
        repo=VerifiedElasticJobs(lambda *args:response(),DB(),index='test')
        total,rows=repo.search(SearchPlan())
        self.assertEqual(total,1)
        self.assertEqual(rows,[{'source_id':'1','source_version':2}])
        self.assertEqual(repo.get('1'),{'source_id':'1'})
    def test_other_source_not_merged_into_numeric_dialogue_contract(self):
        r=response();r['hits']['hits'][0]['_source']['source']='goyong24'
        repo=VerifiedElasticJobs(lambda *args:r,DB(),index='test')
        with self.assertRaises(RuntimeError):repo.search(SearchPlan())
    def test_response_truncation_is_failure(self):
        r=response();r['hits']['total']['value']=1001
        repo=VerifiedElasticJobs(lambda *args:r,DB(),index='test')
        with self.assertRaises(RuntimeError):repo.search(SearchPlan())
    def test_server_endpoint_and_index_restricted(self):
        for url in ['http://example.com:19200','http://127.0.0.1:19200@evil.com','http://127.0.0.1:19200/?x=y']:
            with self.assertRaises(ValueError):LocalElasticTransport(url)
        with self.assertRaises(ValueError):VerifiedElasticJobs(None,DB(),index='../_all')
    def test_default_is_mysql_and_unknown_selector_fails(self):
        with patch.dict(os.environ,{'JOB_SEARCH_BACKEND':'mysql'}):
            self.assertIsInstance(create_job_repository(None),MySQLJobRepository)
        with patch.dict(os.environ,{'JOB_SEARCH_BACKEND':'invalid'}):
            with self.assertRaises(ValueError):create_job_repository(None)

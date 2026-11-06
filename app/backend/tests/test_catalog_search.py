import unittest
from uuid import uuid4
from src.handlers.dialogue import validate_payload
from src.schemas.search import SearchPlan
from src.schemas.catalog import training_clauses
from src.repositories.elasticsearch_jobs import build_query
from src.services.dialogue import DialogueFlow

class CatalogSearchTests(unittest.TestCase):
 def test_job_field_is_allowlisted_and_preserved(self):
  plan=SearchPlan.parse({'keyword':'Python','text_field':'company_name','limit':20})
  self.assertEqual(SearchPlan.parse(plan.to_dict()).text_field,'company_name')
  self.assertEqual(build_query(plan)['query']['bool']['must'][0]['multi_match']['fields'],['company_name'])
  with self.assertRaises(ValueError):SearchPlan.parse({'text_field':'title; DROP TABLE job_postings'})
 def test_training_filters_are_parameters_not_sql(self):
  parts,params=training_clauses({'keyword':"%' OR 1=1 --",'field':'provider_name','region':'경남','service':'card','delivery_mode':'unknown'})
  self.assertNotIn("OR 1=1",' AND '.join(parts));self.assertIn('card:%',params)
  self.assertIn('%경남%',params);self.assertIn('%경상남도%',params)
  with self.assertRaises(ValueError):training_clauses({'field':'password'})
 def test_training_direct_and_next_do_not_invoke_model(self):
  class Training:
   last_candidate_total=42
   def __init__(self):self.calls=[]
   def search(self,topics,**kwargs):self.calls.append(kwargs);return []
  repo=Training();flow=DialogueFlow(None,None,None,training=repo)
  filters={'keyword':'Python','field':'title','region':'서울','service':'card','delivery_mode':'online'}
  payload={'action':'browse_training','filters':filters,'request_id':str(uuid4())}
  validate_payload(payload)
  def no_model(*args):raise AssertionError('Model must not be invoked')
  state,result,_=flow.advance({},payload,no_model)
  self.assertEqual(repo.calls[0]['catalog_filters'],filters);self.assertEqual(result['training_candidate_total'],42)
  flow.advance(state,{'action':'next_results','target':'training'},no_model)
  self.assertEqual(repo.calls[1]['catalog_filters'],filters)
 def test_jobs_direct_does_not_invoke_model(self):
  class Jobs:
   def search(self,plan,**kwargs):self.plan=plan;return 0,[]
  jobs=Jobs();flow=DialogueFlow(jobs,None,None)
  def no_model(*args):raise AssertionError('Model must not be invoked')
  flow.advance({}, {'action':'search','search_plan':{'keyword':'Backend','text_field':'title','limit':20}},no_model)
  self.assertEqual(jobs.plan.text_field,'title')

 def test_training_detail_remains_read_only_and_independent_of_filters(self):
  from src.repositories.mysql_training import MySQLTrainingRepository
  class Cursor:
   def __enter__(self):return self
   def __exit__(self,*args):pass
   def execute(self,sql,params):
    self.sql=sql;self.params=params
   def fetchone(self):return None
  class Connection:
   def cursor(self):return cursor
   def close(self):pass
  cursor=Cursor()
  self.assertIsNone(MySQLTrainingRepository(Connection).get({'source':'boottent','source_id':'example'}))
  self.assertTrue(cursor.sql.startswith('SELECT '))
  self.assertEqual(cursor.params,('boottent','example'))

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

 def test_region_refinement_preserves_ai_role_and_skills(self):
  class Jobs:
   def search(self,plan,**kwargs):self.plan=plan;return 0,[]
  jobs=Jobs();flow=DialogueFlow(jobs,None,None)
  state={'search_navigation':{'plan':{'schema_version':2,'roles':['프론트엔드'],'owned_skills':['React'],'limit':20},'shown_ids':[]}}
  def no_model(*args):raise AssertionError('Unexpected model invocation')
  flow.advance(state,{'action':'search','preserve_current':True,'search_plan':{'region':'경기','limit':20}},no_model)
  self.assertEqual(jobs.plan.roles,('프론트엔드',))
  self.assertEqual(jobs.plan.owned_skills,('React',))
  self.assertEqual(jobs.plan.regions,('경기',))

 def test_training_direct_uses_search_index_and_keeps_column_scope(self):
  from src.repositories.elasticsearch_training import build_training_query
  q=build_training_query([],browse_all=True,candidates_only=True,catalog_filters={'keyword':'Python','field':'provider_name','service':'card'})
  filters=q['query']['bool']['filter']
  self.assertIn({'prefix':{'source_id':'card:'}},filters)
  self.assertTrue(any(x.get('multi_match',{}).get('fields')==['provider_name'] for x in filters))
  with self.assertRaises(ValueError):build_training_query([],browse_all=True,catalog_filters={'region':'경기'})
 def test_mysql_catalog_sets_comparison_collation_and_uses_light_metadata(self):
  from src.repositories.mysql_training import LIST_FIELDS
  parts,_=training_clauses({'keyword':'Python','region':'경기'})
  self.assertTrue(all('COLLATE utf8mb4_0900_ai_ci' in x for x in parts))
  self.assertIn('JSON_OBJECT',LIST_FIELDS)
  self.assertNotIn('raw_detail',LIST_FIELDS)

 def test_category_keyword_combines_with_structured_filters(self):
  p=SearchPlan.parse({'schema_version':2,'text_query':'platform','roles':['백엔드'],'regions':['경기'],'required_skills':['Python'],'career':{'levels':['entry']}})
  q=build_query(p)
  self.assertEqual(q['query']['bool']['must'][0]['multi_match']['query'],'platform')
  from src.repositories.browse_order import unfiltered_jobs
  self.assertFalse(unfiltered_jobs(SearchPlan.parse({'schema_version':2,'text_query':'platform'})))
  with self.assertRaises(ValueError):SearchPlan.parse({'schema_version':1,'text_query':'platform'})

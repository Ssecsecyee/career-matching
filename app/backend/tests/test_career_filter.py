import unittest
from src.services.career_filter import entry_eligible,filter_career
from src.schemas.search import SearchPlan
from src.services.search_review import execution_summary
class CareerFilterTests(unittest.TestCase):
 def test_explicit_entry_only_and_unknown_excluded(self):
  rows=[{'title':'백엔드 (신입)','source_id':'1'},{'title':'백엔드 경력 5년','source_id':'2'},
        {'title':'백엔드','source_id':'3','career_source':{'newcomer':True}},
        {'title':'백엔드','source_id':'4'},{'title':'개발자','source_id':'5','qualifications':'신입도 지원 가능'}]
  p=SearchPlan.parse({'schema_version':2,'career':{'levels':['entry']}})
  self.assertEqual([r['source_id'] for r in filter_career(rows,p)],['1','3','5'])
  self.assertTrue(execution_summary(p,3,'elasticsearch',False)['filters'])
 def test_not_any_mention_of_new_hires(self):
  self.assertFalse(entry_eligible({'title':'시니어 개발자','qualifications':'신입 개발자 멘토링 경험'}))
  self.assertFalse(entry_eligible({'title':'개발자','career_source':{'newcomer':False,'minCareer':3}}))
  self.assertTrue(entry_eligible({'title':'개발자 경력무관'}))
 def test_verified_search_counts_after_career_filter(self):
  from src.repositories.job_search_factory import VerifiedElasticJobs
  class Database:
   def search_details(self,ids):return {'1':{'source_id':'1','source_version':1,'title':'개발자 신입'},'2':{'source_id':'2','source_version':1,'title':'개발자 경력 5년'}}
  def request(*args):return {'hits':{'total':{'relation':'eq','value':2},'hits':[{'_source':{'source':'jumpit','source_id':i,'source_version':1}} for i in ['1','2']]}}
  p=SearchPlan.parse({'schema_version':2,'career':{'levels':['entry']}})
  total,rows=VerifiedElasticJobs(request,Database(),index='test',include_unverified=True).search(p)
  self.assertEqual(total,1);self.assertEqual(rows[0]['source_id'],'1')

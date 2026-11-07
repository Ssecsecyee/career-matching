import unittest
from unittest.mock import patch
from src.schemas.search import SearchPlan
from src.services.search_terms import normalize_search_plan
from src.services.search_repair import execute_with_repair,compatible
class SearchRepairTests(unittest.TestCase):
 def test_region_and_skill_spellings_are_canonical(self):
  a=normalize_search_plan(SearchPlan.parse({'schema_version':2,'regions':['경기도'],'required_skills':['깃']}))
  b=normalize_search_plan(SearchPlan.parse({'schema_version':2,'regions':['경기'],'required_skills':['Git']}))
  self.assertEqual(a.to_dict(),b.to_dict())
  self.assertEqual(normalize_search_plan(SearchPlan.parse({'schema_version':2,'text_query':'깃'})).text_query,'Git')
 def test_required_constraints_and_git_are_never_replaced(self):
  a=SearchPlan.parse({'schema_version':2,'regions':['경기'],'text_query':'Git'})
  self.assertFalse(compatible(a,SearchPlan.parse({'schema_version':2,'regions':[],'text_query':'Git'})))
  self.assertFalse(compatible(a,SearchPlan.parse({'schema_version':2,'regions':['경기'],'text_query':'GitHub'})))
 def test_zero_result_repairs_are_bounded_and_stop_on_success(self):
  class Planner:
   def plan(self,message):pass
  class Flow:
   planner=Planner()
   calls=0
   def execute_search(self,state,plan,raw,payload,**kwargs):
    self.calls+=1
    state['search_context']={'summary':{'limitations':[]}}
    state['search_navigation']={'plan':plan.to_dict()}
    return state,{'total':2 if plan.text_query=='TypeScript' else 0},[]
  flow=Flow();count=[]
  def invoke(*args):
   count.append(1)
   return SearchPlan.parse({'schema_version':2,'text_query':'TypeScript','regions':['경기']})
  with patch.dict('os.environ',{'ENABLE_SEARCH_REPAIR':'true'}):
   state,response,_=execute_with_repair(flow,{},SearchPlan.parse({'schema_version':2,'text_query':'Typescrpt','regions':['경기']}),{}, {'message':'Typescrpt'},invoke)
  self.assertEqual(flow.calls,2);self.assertEqual(len(count),1);self.assertEqual(response['total'],2)
  self.assertEqual(len(response['search_attempts']),2)
 def test_budget_failure_keeps_initial_response(self):
  class P:
   def plan(self,message):pass
  class F:
   planner=P()
   def execute_search(self,state,plan,raw,payload,**kwargs):return state,{'total':0},[]
  def invoke(*args):raise RuntimeError('budget')
  with patch.dict('os.environ',{'ENABLE_SEARCH_REPAIR':'true'}):
   _,response,_=execute_with_repair(F(),{},SearchPlan.parse({'schema_version':2,'text_query':'unknown'}),{}, {'message':'unknown'},invoke)
  self.assertEqual(response['total'],0)
  self.assertEqual(response['search_attempts'][-1]['kind'],'repair_failed')

class IntentSearchFieldTests(__import__("unittest").TestCase):
    def test_text_query_survives_intent_boundary(self):
        from src.schemas.intent import IntentJobPlan
        plan=IntentJobPlan(text_query="Git").as_search_plan()
        self.assertEqual(plan.text_query,"Git")

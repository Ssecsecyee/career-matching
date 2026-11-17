import hashlib,os,unittest
from unittest.mock import Mock,patch
from src.schemas.search import SearchPlan
from src.services.dialogue import DialogueFlow,FlowError
from src.services.zero_result_vectors import fallback,hard_constraints,embedding_text
from src.services.search_repair import execute_with_repair

class ZeroVectorTests(unittest.TestCase):
 def setUp(self):
  self.env=patch.dict(os.environ,{'ENABLE_ZERO_RESULT_VECTOR_FALLBACK':'true'});self.env.start();self.addCleanup(self.env.stop)
  self.row={'source':'jumpit','source_id':'12','source_version':1,'title':'백엔드 신입','company_name':'A','qualifications':'Python 개발 경험','preferred_requirements':'Docker','tech_stacks':['Python','Docker'],'addresses':['경기도 수원'],'recruitment_status':'unknown'}
  self.jobs=Mock();self.jobs.get.return_value=self.row
  self.flow=DialogueFlow(self.jobs,Mock(),None,include_unverified=True)
  self.plan=SearchPlan(roles=['희귀 검색 표현'],regions=['경기'],required_skills=['Python'],career={'levels':['entry']})
  self.candidate={k:self.row[k] for k in ('source','source_id','source_version')}
  self.candidate.update(scores={'qualifications':.8},section_hashes={s+'_hash':hashlib.sha256(self.row[s].encode()).hexdigest() for s in ('qualifications','preferred_requirements')})
 def test_fallback_preserves_original_and_zero_and_selected_assessment(self):
  state={'search_backend':'elasticsearch','search_degraded':False,'selected':{'source_id':'old'},'checks':[{'assessment':'met'}]}
  query=Mock(return_value={'results':[self.candidate],'input_tokens':40})
  state,result,_=fallback(self.flow,state,self.plan,self.plan.to_dict(),{},query=query)
  self.assertEqual(result['total'],1);self.assertEqual(result['exact_match_total'],0)
  self.assertEqual(result['retrieval_mode'],'section_vector_fallback');self.assertEqual(state['selected']['source_id'],'old')
  self.assertEqual(state['search_context']['total'],0);self.assertEqual(state['search_context']['executed_plan'],self.plan.to_dict())
  self.assertNotIn('OR',query.call_args.args[0])
 def test_region_required_skill_entry_and_exclusions_are_not_relaxed(self):
  self.assertTrue(hard_constraints(self.row,self.plan,set()))
  for row in (dict(self.row,addresses=['서울']),dict(self.row,tech_stacks=['Docker']),dict(self.row,title='경력 개발자')):
   self.assertFalse(hard_constraints(row,self.plan,set()))
  self.assertFalse(hard_constraints(self.row,self.plan,{'12'}))
 def test_failure_is_explicit_and_no_or_search_is_created(self):
  query=Mock(side_effect=FlowError('vector_capacity_busy',503))
  result=fallback(self.flow,{'search_backend':'elasticsearch','search_degraded':False},self.plan,self.plan.to_dict(),{},query=query)
  self.assertEqual(result['status'],'unavailable');self.assertEqual(result['metadata']['original_plan'],self.plan.to_dict())
 def test_disabled_or_empty_browse_never_embeds(self):
  query=Mock()
  with patch.dict(os.environ,{'ENABLE_ZERO_RESULT_VECTOR_FALLBACK':'false'}):self.assertIsNone(fallback(self.flow,{},self.plan,{}, {},query=query))
  self.assertIsNone(fallback(self.flow,{},SearchPlan(),{}, {},query=query));query.assert_not_called()
 def test_positive_and_result_never_uses_fallback(self):
  self.jobs.search.return_value=(1,[self.row])
  with patch('src.services.zero_result_vectors.fallback') as alternate:
   self.flow.execute_search({},self.plan,self.plan.to_dict(),{})
   alternate.assert_not_called()
 def test_vector_attempt_stops_model_replanning_even_when_empty_or_failed(self):
  flow=Mock();flow.execute_search.return_value=({}, {'total':0,'vector_fallback':{'status':'unavailable'}},[])
  with patch.dict(os.environ,{'ENABLE_SEARCH_REPAIR':'true'}):
   invoke=Mock();execute_with_repair(flow,{},SearchPlan(schema_version=2,text_query='Python'),{}, {},invoke)
   invoke.assert_not_called()

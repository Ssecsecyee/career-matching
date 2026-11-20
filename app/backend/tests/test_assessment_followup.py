import copy,json,os,unittest
from unittest.mock import Mock,patch
from src.schemas.intent import IntentDecision
from src.services.dialogue import DialogueFlow
from test_dialogue import Jobs,Questioner,invoke

class AssessmentFollowupTests(unittest.TestCase):
 def fixture(self):
  jobs=Jobs();planner=Mock();planner.consult.return_value=({'reply':'Stored assessment counseling'}, {})
  flow=DialogueFlow(jobs,planner,Questioner(),include_unverified=True)
  state,_,_=flow.advance({}, {'action':'search','search_plan':{'skills':['Python']}},invoke)
  state,result,_=flow.advance(state,{'action':'select','source_id':'42','grouped':True,'assessment_checkpoint':True},invoke)
  state,_,_=flow.advance(state,{'action':'answer_batch','answers':[{'question_id':q['question_id'],'assessment':'met'} for q in result['questions']]},invoke)
  return flow,state,jobs,planner
 def test_jobs_alias_is_canonical_only_for_assessment_control(self):
  d=IntentDecision(target='jobs',action='assessment_control',control='preferred',reason='resume')
  self.assertEqual(d.target,'selected')
  self.assertEqual(IntentDecision(target='jobs',action='next_results',reason='page').target,'jobs')
  with self.assertRaises(ValueError):IntentDecision(target='jobs',action='assessment_control',control='delete',reason='bad')
  with self.assertRaises(ValueError):IntentDecision(target='training',action='assessment_control',control='preferred',reason='bad')
 def test_preferred_resume_after_consult_preserves_required_answers(self):
  flow,state,jobs,planner=self.fixture();checks=copy.deepcopy(state['checks'])
  state,_,_=flow.advance(state,{'action':'consult','task':'learning_plan','message':'counsel'},invoke)
  planner.classify.return_value=({'decision':{'target':'jobs','action':'assessment_control','control':'preferred','reason':'resume'},'raw_output':''},{})
  state,result,_=flow.advance(state,{'action':'search','message':'preferred questions please'},invoke)
  self.assertEqual(result['stage'],'checking_preferred');self.assertEqual(result['requirement_type'],'preferred')
  self.assertEqual(state['checks'],checks);self.assertEqual(state['selected']['source_id'],'42');self.assertTrue(state['preferred_approved'])
 def test_assessment_search_excludes_selected_and_preserves_answers(self):
  flow,state,jobs,planner=self.fixture();checks=copy.deepcopy(state['checks']);selected=copy.deepcopy(state['selected'])
  jobs.search=Mock(return_value=(1,[{**jobs.job,'source_id':'other'}]))
  planner.classify.return_value=({'decision':{'target':'jobs','action':'search','search_basis':'assessment','reason':'met experience','plan':{'schema_version':2,'owned_skills':['Python']}},'raw_output':''},{})
  state,result,_=flow.advance(state,{'action':'search','message':'recommend by answers'},invoke)
  self.assertEqual(jobs.search.call_args.kwargs['exclude_ids'],['42']);self.assertEqual(jobs.search.call_args.args[0].owned_skills,('Python',))
  self.assertEqual(state['checks'],checks);self.assertEqual(state['selected'],selected)
  self.assertEqual(state['search_context']['assessment_basis']['items'][0]['assessment'],'met');self.assertEqual(result['stage'],'search_review')
 def test_no_met_answer_does_not_invent_search_skills(self):
  flow,state,jobs,planner=self.fixture()
  for check in state['checks']:check['assessment']='unknown'
  jobs.search=Mock();planner.classify.return_value=({'decision':{'target':'jobs','action':'search','search_basis':'assessment','reason':'assessment','plan':{'schema_version':2}},'raw_output':''},{})
  _,result,_=flow.advance(state,{'action':'search','message':'recommend by answers'},invoke)
  self.assertTrue(result['clarification_required']);jobs.search.assert_not_called()

 def test_recorded_fenced_assessment_route_is_accepted_by_model_boundary(self):
  from src.bedrock.client import BedrockPlanner
  from test_backend import FakeRuntime
  raw='```json\n'+json.dumps({'target':'jobs','action':'assessment_control','control':'preferred','reason':'resume preferred questions'})+'\n```'
  with patch.dict(os.environ,{'ENABLE_LIVE_BEDROCK':'true'}):
   value,_=BedrockPlanner('mock','offline',client=FakeRuntime(raw)).classify('preferred please',{})
  self.assertEqual(value['decision']['target'],'selected');self.assertEqual(value['decision']['control'],'preferred')

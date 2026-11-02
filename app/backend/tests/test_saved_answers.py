import copy,json,unittest
from unittest.mock import Mock,patch
from uuid import uuid4
from test_dialogue import Jobs,Questioner,invoke
from src.services.dialogue import DialogueFlow,FlowError
from src.services.memory import memory
from src.services.saved_answers import review,review_version
from src.handlers.dialogue import validate_payload
from src.services.context_router import ContextRouter

class SavedAnswerTests(unittest.TestCase):
 def fixture(self):
  jobs=Jobs();jobs.job['qualifications']='- Python API 개발\n- Linux 운영';jobs.job['preferred_requirements']='- Docker 운영'
  flow=DialogueFlow(jobs,Mock(),Questioner(),include_unverified=True)
  state,_,_=flow.advance({}, {'action':'search','search_plan':{}},invoke)
  state,result,_=flow.advance(state,{'action':'select','source_id':'42','grouped':True,'assessment_checkpoint':True},invoke)
  answers=[{'question_id':q['question_id'],'assessment':'met','detail':'직접 해봤어요'} for q in result['questions']]
  state,result,_=flow.advance(state,{'action':'answer_batch','answers':answers},invoke)
  return flow,state,jobs
 def change(self,state,**values):
  return dict(action='revise_answer',condition_id=state['checks'][0]['condition_id'],assessment='unknown',detail='학습만 해봤어요',review_version=review_version(state),offset=0,**values)
 def test_review_reads_saved_quotes_and_details_without_model_or_search(self):
  flow,state,jobs=self.fixture();before=copy.deepcopy(state['checks'])
  with patch.object(jobs,'get',side_effect=AssertionError('No current source lookup')),patch.object(jobs,'search',side_effect=AssertionError('No search')):
   _,result,evidence=flow.advance(state,{'action':'review_answers'},Mock(side_effect=AssertionError('No model')))
  data=result['saved_answers'];self.assertEqual(data['items'][0]['detail'],'직접 해봤어요')
  self.assertEqual(data['items'][-1]['assessment'],'unanswered');self.assertFalse(data['items'][-1]['editable'])
  self.assertEqual(state['checks'],before);self.assertEqual(state['stage'],'assessment_checkpoint');self.assertFalse(evidence)
 def test_single_correction_preserves_other_answers_and_appends_evidence(self):
  flow,state,jobs=self.fixture();before=copy.deepcopy(state['checks']);condition=state['conditions'][0]
  with patch.object(jobs,'get',side_effect=AssertionError('Stored snapshot only')):
   _,result,evidence=flow.advance(state,self.change(state),Mock(side_effect=AssertionError('No model')))
  self.assertEqual(state['checks'][0]['assessment'],'unknown');self.assertEqual(state['checks'][0]['quote'],before[0]['quote'])
  self.assertEqual(state['checks'][1:],before[1:]);self.assertNotIn(condition['key'],memory(state)['confirmed'])
  self.assertEqual(result['answer_revision']['before']['assessment'],'met');self.assertEqual(result['answer_revision']['after']['assessment'],'unknown')
  self.assertEqual(len(evidence),1);self.assertEqual(result['stage'],'assessment_checkpoint')
  self.assertEqual(result['saved_answers']['items'][0]['detail'],'학습만 해봤어요')
 def test_stale_edit_does_not_overwrite_anything(self):
  flow,state,_=self.fixture();old=self.change(state)
  flow.advance(state,old,invoke);before=copy.deepcopy(state['checks'])
  with self.assertRaises(FlowError) as error:flow.advance(state,old,invoke)
  self.assertEqual(error.exception.code,'saved_answers_changed_refresh');self.assertEqual(state['checks'],before)
 def test_cannot_revise_unanswered_or_unrelated_condition(self):
  flow,state,_=self.fixture();value=self.change(state);value['condition_id']=state['conditions'][-1]['id']
  with self.assertRaises(FlowError):flow.advance(state,value,invoke)
 def test_direct_router_does_not_classify_review_or_edit(self):
  flow,state,_=self.fixture();router=ContextRouter(flow)
  router.advance(state,{'action':'review_answers'},Mock(side_effect=AssertionError('No model')))
  router.advance(state,self.change(state),Mock(side_effect=AssertionError('No model')))
  flow.planner.classify.assert_not_called()
 def test_completed_stage_recalculates_without_reasking(self):
  flow,state,_=self.fixture();state['preferred_approved']=True
  result=flow.batch_response(state)
  state['stage']='checking_preferred'
  answers=[{'question_id':q['question_id'],'assessment':'met','detail':''} for q in result['questions']]
  state,result,_=flow.advance(state,{'action':'answer_batch','answers':answers},invoke)
  self.assertEqual(state['stage'],'completed')
  value=self.change(state);value['assessment']='unmet'
  _,result,_=flow.advance(state,value,Mock(side_effect=AssertionError('No model')))
  self.assertEqual(state['stage'],'gap_guidance');self.assertEqual(len(state['checks']),3)
 def test_current_unfinished_questions_are_preserved(self):
  flow,state,_=self.fixture();state['preferred_approved']=True;state['stage']='checking_preferred'
  _,result,_=flow.advance(state,self.change(state),Mock(side_effect=AssertionError('No model')))
  self.assertEqual(result['stage'],'checking_preferred');self.assertEqual(result['questions'][0]['question_id'],state['conditions'][-1]['id'])
 def test_request_cannot_supply_source_quote_or_skip_version(self):
  base={'request_id':str(uuid4()),'session_id':str(uuid4())}
  validate_payload(dict(base,action='review_answers',offset=10))
  for value in [dict(action='review_answers',offset=1),dict(action='review_answers',offset=True),dict(action='review_answers',sql='SELECT'),dict(action='revise_answer',condition_id='x',assessment='met',detail='',review_version='bad')]:
   with self.assertRaises(ValueError):validate_payload(dict(base,**value))
  value=dict(base,action='revise_answer',condition_id='x',assessment='met',detail='',review_version='a'*64,quote='changed source')
  with self.assertRaises(ValueError):validate_payload(value)
 def test_review_paging_keeps_original_text_and_marks_history_scope(self):
  flow,state,_=self.fixture();state['conditions']=state['conditions']*4
  first=review(state,0);second=review(state,10)
  self.assertEqual(len(first['items']),10);self.assertEqual(len(second['items']),2)
  self.assertEqual(first['scope'],'current_session_selected_job');self.assertEqual(first['review_version'],second['review_version'])

 def test_grouped_technical_condition_notice_remains_visible(self):
  flow,state,_=self.fixture();state['conditions'][0]['parse_notes']=['technical_collection']
  self.assertIn('여러 기술',review(state)['items'][0]['source_notice'])

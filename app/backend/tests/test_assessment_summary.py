import copy,json,unittest
from unittest.mock import Mock
from src.services.assessment_summary import build_summary,summary_requested,summary_context
from src.services.dialogue import DialogueFlow
from src.services.memory import consultation_context
from test_dialogue import Jobs,Questioner,invoke

def state_for(required,preferred=()):
 s={'selected':{'job_id':1,'source_id':'42','source_version':3,'source_url':'https://example.com/42','company_name':'표본','title':'개발자'},'conditions':[],'checks':[],'profile':{}}
 for kind,values in [('required',required),('preferred',preferred)]:
  for i,status in enumerate(values):
   q={'id':f'42:3:{kind}:{i}','type':kind,'quote':f'{kind} 조건 {i}','section':'qualifications' if kind=='required' else 'preferred_requirements'}
   s['conditions'].append(q)
   if status is not None:s['checks'].append({'condition_id':q['id'],'type':kind,'assessment':status,'quote':q['quote'],'detail':'직접 남긴 설명'})
 return s

class SummaryTests(unittest.TestCase):
 def test_separate_counts_and_unknown_never_becomes_unmet(self):
  s=state_for(['met','unmet','unknown'],['met','unknown'])
  r=build_summary(s);self.assertEqual(r['groups']['required']['counts'],{'met':1,'unmet':1,'unknown':1,'unanswered':0,'total':3})
  self.assertEqual(r['groups']['preferred']['counts']['unmet'],0);self.assertEqual(r['kind'],'required_gaps');self.assertEqual(r['answered'],5)
  self.assertNotIn('score',r);self.assertTrue(r['not_a_hiring_decision']);self.assertNotIn('quote',r['items'][0])
 def test_all_met_has_preparation_and_interview_choices_without_invented_gaps(self):
  r=build_summary(state_for(['met','met'],['met']));self.assertEqual(r['kind'],'all_self_reported_met');self.assertEqual([x['id'] for x in r['next_actions']],['prepare','interview','similar_jobs']);self.assertEqual(r['groups']['required']['counts']['unmet'],0)
 def test_all_unknown_and_required_unknown_are_not_eligible(self):
  r=build_summary(state_for(['unknown'],['unknown']));self.assertEqual(r['kind'],'all_unconfirmed');self.assertEqual(r['groups']['required']['counts']['unmet'],0)
  self.assertEqual(build_summary(state_for(['unknown'],['met']))['kind'],'required_unconfirmed')
 def test_missing_preferred_is_not_all_conditions_met_and_partial_is_distinct(self):
  self.assertEqual(build_summary(state_for(['met']))['kind'],'required_self_reported')
  r=build_summary(state_for(['met',None],['unknown']));self.assertTrue(r['partial']);self.assertEqual(r['unanswered'],1);self.assertEqual(r['groups']['required']['counts']['unknown'],0)
 def test_same_saved_answers_have_stable_id_and_change_invalidates_summary(self):
  s=state_for(['met'],['unknown']);r=build_summary(s);self.assertEqual(r['summary_id'],build_summary(copy.deepcopy(s))['summary_id'])
  s['checks'][0]['detail']='정정한 설명';self.assertNotEqual(r['summary_id'],build_summary(s)['summary_id'])
  s['selected']['source_version']=4;self.assertNotEqual(r['summary_id'],build_summary(s)['summary_id'])
 def test_invalid_duplicate_or_mismatched_source_answers_are_rejected(self):
  s=state_for(['met']);s['checks'].append(copy.deepcopy(s['checks'][0]))
  with self.assertRaises(ValueError):build_summary(s)
  s=state_for(['met']);s['checks'][0]['quote']='다른 공고의 원문'
  with self.assertRaises(ValueError):build_summary(s)
 def test_explicit_career_conflict_is_flagged_without_changing_user_selection(self):
  s=state_for(['met']);s['conditions'][0]['quote']='관련 개발 경력 3년 이상';s['checks'][0]['quote']=s['conditions'][0]['quote'];s['checks'][0]['detail']=''
  s['profile']={'memory':{'user_statements':[{'id':'1','text':'실무 경력은 없어요'}]}}
  r=build_summary(s);self.assertEqual(len(r['conflicts']),1);self.assertEqual(r['groups']['required']['counts']['met'],1)
  s['profile']['memory']['user_statements'].append({'id':'2','text':'정정할게요. 이전 회사 경력 3년이 있어요'})
  self.assertEqual(build_summary(s)['conflicts'],[])
 def test_summary_lookup_does_not_capture_learning_or_job_search(self):
  for text in ['내가 뭐가 부족해?','왜 그렇게 정리했어?','지금까지 답변을 정리해줘','미확인 조건은 나중에 확인할게. 이미 답한 내용만 다시 정리해줘']:
   self.assertTrue(summary_requested(text),text)
  for text in ['다른 공고를 찾아줘','미확인 조건을 쉽게 설명해줘','부족한 점을 바탕으로 학습 순서를 정리해줘','이력서 준비해줘']:
   self.assertFalse(summary_requested(text),text)
 def test_context_carries_the_persisted_summary_without_duplicate_raw_quotes(self):
  s=state_for(['met'],['unmet']);s['answer_summary']=build_summary(s);r=consultation_context(s)
  self.assertEqual(r['answer_summary']['summary_id'],s['answer_summary']['summary_id']);self.assertNotIn('items',r['answer_summary']);self.assertEqual(len(r['condition_answers']),2)

class SummaryFlowTests(unittest.TestCase):
 def start(self):
  jobs=Jobs();self.flow=DialogueFlow(jobs,None,Questioner(),include_unverified=True)
  self.state,_,_=self.flow.advance({},dict(action='search',search_plan={}),invoke)
  self.state,r,_=self.flow.advance(self.state,dict(action='select',source_id='42',grouped=True),invoke)
  return r
 def answer_group(self,response,status):
  self.state,r,e=self.flow.advance(self.state,dict(action='answer_batch',answers=[dict(question_id=q['question_id'],assessment=status,detail='테스트 설명') for q in response['questions']]),Mock(side_effect=AssertionError('Unexpected model call')))
  return r,e
 def test_completion_builds_and_persists_summary_with_zero_model_calls(self):
  r=self.start();r,_=self.answer_group(r,'met');r,e=self.answer_group(r,'met')
  self.assertEqual(r['stage'],'completed');self.assertEqual(r['answer_summary']['kind'],'all_self_reported_met');self.assertEqual(self.state['answer_summary'],r['answer_summary']);self.assertEqual(len(e),1)
  self.state,r,_=self.flow.advance(self.state,dict(action='search',message='왜 그렇게 정리했어?'),Mock(side_effect=AssertionError('Unexpected model call')))
  self.assertIn('answer_summary',r);self.assertNotIn('questions',r)
 def test_unknown_completion_has_an_explicit_unconfirmed_summary(self):
  r=self.start();r,_=self.answer_group(r,'unknown');r,_=self.answer_group(r,'unknown')
  self.assertEqual(r['answer_summary']['kind'],'all_unconfirmed');self.assertEqual(r['unconfirmed_count'],2)
 def test_pause_retains_answered_and_unanswered_without_reasking(self):
  r=self.start();r,_=self.answer_group(r,'met')
  self.state,r,_=self.flow.advance(self.state,dict(action='search',message='역량 확인 질문은 그만해줘'),Mock(side_effect=AssertionError('Unexpected model call')))
  self.assertTrue(r['assessment_paused']);self.assertEqual(r['answer_summary']['unanswered'],1);self.assertEqual(r['answer_summary']['answered'],1);self.assertNotIn('questions',r)
 def test_new_search_clears_previous_summary(self):
  r=self.start();r,_=self.answer_group(r,'met');r,_=self.answer_group(r,'met')
  self.state,r,_=self.flow.advance(self.state,dict(action='search',search_plan={}),invoke)
  self.assertNotIn('answer_summary',self.state);self.assertNotIn('answer_summary',r)

if __name__=='__main__':unittest.main()

import json,os,unittest
from unittest.mock import Mock,patch
from test_condition_review import fixture
from src.bedrock.question_reviewer import QuestionConditionReviewer
from src.services.condition_review import source_conditions,review_key
from src.bedrock.model_json import ModelOutputFormatError

class QuestionReviewerTests(unittest.TestCase):
    def setUp(self):
        self.job,self.proposal=fixture();self.runtime=Mock()
    def response(self,**kw):
        rows=json.loads(kw['messages'][0]['content'][0]['text'])['conditions']
        known={x['condition_id']:x for x in self.proposal['conditions']}
        labels=[{k:v for k,v in known[row['condition_id']].items() if k not in {'logic','parts'}} for row in rows]
        return {'stopReason':'tool_use','usage':{'inputTokens':10,'outputTokens':5},'output':{'message':{'content':[{'toolUse':{'name':'submit_question_labels','input':{'conditions':labels}}}]}}}
    def test_question_only_contract_preserves_source_without_requesting_extraction(self):
        self.runtime.converse.side_effect=self.response
        model=QuestionConditionReviewer('offline','test',client=self.runtime)
        with patch.dict(os.environ,{'ENABLE_LIVE_BEDROCK':'true'}):review,usage=model.classify(self.job,mode='adaptive')
        self.assertEqual(usage['calls'],1);self.assertEqual(usage['prompt_version'],'selected-question-v1')
        request=self.runtime.converse.call_args.kwargs
        self.assertEqual(request['toolConfig']['toolChoice'],{'tool':{'name':'submit_question_labels'}})
        text=request['messages'][0]['content'][0]['text']
        self.assertNotIn('part_id',text)
        decision_schema=request['toolConfig']['tools'][0]['toolSpec']['inputSchema']['json']['$defs']['QuestionDecision']['properties']
        self.assertNotIn('parts',decision_schema);self.assertNotIn('logic',decision_schema)
        for original,item in zip(source_conditions(self.job),review['conditions']):
            self.assertEqual(item['quote'],original['quote']);self.assertEqual(''.join(p['quote'] for p in item['parts']),original['quote'])
            self.assertEqual(item['logic']['operator'],'unresolved');self.assertEqual(item['parts'][0]['terms'],[])
    def test_twenty_conditions_can_be_one_call_plan_but_long_jobs_split(self):
        job=dict(self.job,qualifications='\n'.join('- Python 경험' for _ in range(20)),preferred_requirements='')
        self.assertEqual(len(QuestionConditionReviewer.plan(job,'adaptive')),1)
        job['qualifications']+='\n- Python 경험'
        self.assertEqual(len(QuestionConditionReviewer.plan(job,'adaptive')),4)
    def test_exhausted_time_budget_does_not_start_a_provider_call(self):
        with patch.dict(os.environ,{'ENABLE_LIVE_BEDROCK':'true'}),self.assertRaises(TimeoutError):
            QuestionConditionReviewer('offline','test',client=self.runtime).classify(self.job,mode='adaptive',max_seconds=0)
        self.runtime.converse.assert_not_called()

    def test_missing_or_invalid_labels_do_not_become_empty_or_suppressed_questions(self):
        response=self.response(messages=[{'content':[{'text':json.dumps({'conditions':[{'condition_id':x['condition_id']} for x in self.proposal['conditions']]})}]}])
        response['output']['message']['content'][0]['toolUse']['input']['conditions'].pop()
        self.runtime.converse.return_value=response
        with patch.dict(os.environ,{'ENABLE_LIVE_BEDROCK':'true'}),self.assertRaises(ModelOutputFormatError):QuestionConditionReviewer('offline','test',client=self.runtime).classify(self.job,mode='adaptive')

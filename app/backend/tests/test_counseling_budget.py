import json
import os
import unittest
from unittest.mock import patch
from src.bedrock.client import BedrockPlanner
from src.bedrock.model_json import ModelOutputFormatError, ModelOutputTruncatedError
from src.services.dependency_errors import dependency_error, error_code
from test_backend import FakeRuntime


class CounselingBudgetTests(unittest.TestCase):
    def invoke(self,runtime,partial=None):
        with patch.dict(os.environ,{'ENABLE_LIVE_BEDROCK':'true'}):
            return BedrockPlanner('offline-model','offline-region',client=runtime,on_partial=partial).route('답변을 기준으로 보완 방향을 정리해줘',{})

    def test_complete_reply_beyond_old_token_budget_is_accepted(self):
        runtime=FakeRuntime(json.dumps({'intent':'chat','reply':'보완 방향과 근거입니다. '*100},ensure_ascii=False))
        original=runtime.converse
        def converse(**kwargs):
            result=original(**kwargs);result['usage']['outputTokens']=1800;return result
        runtime.converse=converse
        result,usage=self.invoke(runtime)
        self.assertEqual(runtime.calls[0]['inferenceConfig']['maxTokens'],4096)
        self.assertEqual(usage['output_tokens'],1800)
        self.assertEqual(usage['prompt_version'],'conversation-qa-budget-v8')
        self.assertIn('근거',result['reply'])

    def test_real_max_tokens_stop_is_distinct_and_keeps_usage(self):
        runtime=FakeRuntime('{"intent":"chat","reply":"미완성',stop='max_tokens')
        with self.assertRaises(ModelOutputTruncatedError) as caught:self.invoke(runtime)
        self.assertIn('output_tokens',caught.exception.usage)
        self.assertEqual(error_code(caught.exception),'ModelOutputTruncatedError')
        status,body=dependency_error(caught.exception)
        self.assertEqual(status,502)
        self.assertFalse(body['retryable'])
        self.assertEqual(body['status'],'model_output_truncated')
        self.assertIn('기존 대화',body['message'])

    def test_malformed_json_and_oversized_text_still_fail_validation(self):
        for text in ('not JSON',json.dumps({'intent':'chat','reply':'a'*4001})):
            with self.assertRaises(ModelOutputFormatError) as caught:self.invoke(FakeRuntime(text))
            self.assertNotIsInstance(caught.exception,ModelOutputTruncatedError)

    def test_streaming_and_final_reply_use_the_same_expanded_generation_budget(self):
        reply='검증된 원문과 사용자 답변 기준입니다. '*80
        class Runtime:
            def converse_stream(self,**kwargs):
                self.arguments=kwargs
                raw=json.dumps({'intent':'chat','reply':reply},ensure_ascii=False)
                return {'stream':iter([{'contentBlockDelta':{'delta':{'text':raw[:500]}}},
                    {'contentBlockDelta':{'delta':{'text':raw[500:]}}},
                    {'messageStop':{'stopReason':'end_turn'}},
                    {'metadata':{'usage':{'inputTokens':100,'outputTokens':1500}}}])}
        runtime=Runtime();parts=[]
        result,usage=self.invoke(runtime,parts.append)
        self.assertEqual(result['reply'],reply)
        self.assertEqual(runtime.arguments['inferenceConfig']['maxTokens'],4096)
        self.assertEqual(usage['output_tokens'],1500)
        self.assertEqual(parts[-1],reply)

import json
import os
import time
import unittest
from unittest.mock import MagicMock,patch
from src.bedrock.streaming import reply_prefix
from src.bedrock.client import BedrockPlanner
from src.handlers.queued import JobStore,job_response
from src.services.progress import ProgressPublisher

class StreamingTests(unittest.TestCase):
    def test_partial_json_decodes_newline_quote_and_complete_surrogate_pairs(self):
        self.assertEqual(reply_prefix('{"intent":"chat","reply":"안녕\\nReact \\uD83D'), '안녕\nReact ')
        self.assertEqual(reply_prefix('{"intent":"chat","reply":"안녕\\nReact \\uD83D\\uDE00'), '안녕\nReact '+chr(0x1f600))
        self.assertEqual(reply_prefix('{"intent":"chat","reply":"say \\"yes\\"'), 'say "yes"')
        self.assertEqual(reply_prefix('{"intent":"search","plan":{"reply":"not user text'), '')
        self.assertEqual(reply_prefix('untrusted prose "reply":"text'), '')

    def test_real_delta_path_emits_before_generation_finishes_and_keeps_usage(self):
        finished=[];snapshots=[]
        raw=json.dumps({'intent':'chat','reply':'안녕하세요. React 학습을 도와드릴게요.'},ensure_ascii=False)
        class Events:
            closed=False
            def __iter__(self):
                for ch in raw:yield {'contentBlockDelta':{'delta':{'text':ch}}}
                finished.append(True)
                yield {'messageStop':{'stopReason':'end_turn'}}
                yield {'metadata':{'usage':{'inputTokens':10,'outputTokens':20}}}
            def close(self):self.closed=True
        events=Events();client=MagicMock();client.converse_stream.return_value={'stream':events}
        def partial(text):
            self.assertFalse(finished);snapshots.append(text)
        with patch.dict(os.environ,{'ENABLE_LIVE_BEDROCK':'true'}):
            result,usage=BedrockPlanner('model','region',client=client,on_partial=partial).route('안녕',{})
        self.assertGreater(len(snapshots),2)
        self.assertEqual(snapshots[-1],result['reply']);self.assertTrue(events.closed)
        self.assertEqual(usage['output_tokens'],20);client.converse.assert_not_called()

    def test_streaming_search_plan_never_publishes_json_or_filters(self):
        events=MagicMock();events.__iter__.return_value=iter([
            {'contentBlockDelta':{'delta':{'text':json.dumps({'intent':'search','plan':{'keyword':'','skills':['React']}})}}},
            {'messageStop':{'stopReason':'end_turn'}},{'metadata':{'usage':{}}}])
        client=MagicMock();client.converse_stream.return_value={'stream':events};partial=MagicMock()
        with patch.dict(os.environ,{'ENABLE_LIVE_BEDROCK':'true'}):
            result,_=BedrockPlanner('model','region',client=client,on_partial=partial).route('React 공고',{})
        self.assertEqual(result['intent'],'search');partial.assert_not_called()

    def test_progress_rate_limit_and_failure_do_not_break_model_completion(self):
        store=MagicMock();clock=MagicMock(side_effect=[0,0.1,1,2,3])
        publish=ProgressPublisher(store,'id',clock=clock)
        publish('안');publish('안녕');publish('안녕하세요')
        self.assertEqual(store.progress.call_count,2)
        store.progress.side_effect=RuntimeError('unavailable')
        publish('안녕하세요 반가워요');publish('안녕하세요 반가워요!')
        self.assertTrue(publish.disabled)

    def test_partial_text_is_owner_scoped_unexpired_and_never_overrides_final(self):
        row={'job_id':'a'*64,'owner':'one','expires_at':int(time.time())+60,'state':'queued','partial_text':'생성 중','partial_version':2}
        self.assertEqual(job_response(row,'two')['statusCode'],404)
        response=json.loads(job_response(row,'one')['body'])
        self.assertEqual(response['partial_text'],'생성 중');self.assertTrue(response['draft'])
        row.update(state='done',response_json=json.dumps({'statusCode':502,'body':'{"status":"format_error"}'}))
        self.assertEqual(job_response(row,'one')['statusCode'],502)
        self.assertNotIn('partial_text',json.loads(job_response(row,'one')['body']))

    def test_dynamo_progress_cannot_create_or_modify_completed_jobs_and_completion_removes_draft(self):
        client=MagicMock()
        with patch.dict(os.environ,{'JOBS_TABLE':'fixture'}):store=JobStore(client)
        store.progress('a'*64,'생성 중',1)
        self.assertIn('attribute_exists',client.update_item.call_args.kwargs['ConditionExpression'])
        store.complete('a'*64,{'statusCode':200})
        expression=client.update_item.call_args.kwargs['UpdateExpression']
        self.assertIn('partial_text',expression);self.assertIn('REMOVE',expression)

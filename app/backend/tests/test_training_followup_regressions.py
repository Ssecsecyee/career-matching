import copy,json,os,unittest
from unittest.mock import Mock,patch
from src.services.context_router import ContextRouter
from src.services.dialogue import DialogueFlow,FlowError
from src.services.condition_review import attach_selection
from src.bedrock.client import BedrockPlanner
from src.bedrock.model_json import ModelOutputFormatError,ModelOutputTruncatedError
from routing_fixture import advance_intent

class FollowupRegressions(unittest.TestCase):
    def test_replacement_survives_review_confirm_and_next_without_old_topics(self):
        repo=Mock();repo.last_candidate_total=0;repo.search.return_value=[]
        flow=DialogueFlow(Mock(),Mock(),None,training=repo)
        state,_,_=advance_intent(flow,{},'비즈니스 역량 교육',dict(target='training',action='search',topics=['커머스 비즈니스 도메인','SCM']))
        state['checks']=[{'condition_id':'one','assessment':'unmet'}]
        repo.search.return_value=[{'source':'goyong24_training','source_id':'marketing','source_version':1}]
        repo.last_candidate_total=1
        state,review,_=advance_intent(flow,state,'마케팅도 좋아',dict(target='training',action='refine_search',topics=['마케팅']))
        state,_,_=flow.advance(state,{'action':'confirm_search','search_id':review['search_id']},None)
        repo.search.return_value=[]
        advance_intent(flow,state,'다음 교육',dict(target='training',action='next_results'))
        self.assertTrue(all(call.args[0]==['마케팅'] for call in repo.search.call_args_list[1:]))
        self.assertTrue(all(call.kwargs['topic_operator']=='and' for call in repo.search.call_args_list))
        self.assertEqual(state['checks'],[{'condition_id':'one','assessment':'unmet'}])

    def test_reference_block_not_repeated_on_education_or_generic_chat(self):
        state={'condition_review':{'status':'applied'},'selected':{'source_url':'https://example.com/job'},
               'reference_conditions':[{'id':'r1','type':'required','quote':'소개 헤더','ai_review':{'reason':'헤더','reason_code':'not_eligibility'}}]}
        before=copy.deepcopy(state)
        for result in [{'stage':'training_no_results','search_target':'training'},
                       {'stage':'conversation','learning_search':{'status':'found'}},{'stage':'conversation'}]:
            self.assertNotIn('reference_conditions',attach_selection(state,result))
        self.assertEqual(state,before)
        self.assertEqual(len(attach_selection(state,{'stage':'checking_required'})['reference_conditions']),1)

    def invoke(self,purpose,fn,*args):return fn(*args)[0]

    def test_saved_invalid_training_output_reinterpreted_once_without_rewriting_user(self):
        bad={'target':'training','action':'refine_search','reason':'test','topics':['마케팅'],'changes':{'regions':None}}
        good={'target':'training','action':'search','reason':'test','topics':['마케팅']}
        def response(value):return {'stopReason':'end_turn','usage':{},'output':{'message':{'content':[{'text':json.dumps(value)}]}}}
        client=Mock();client.converse.side_effect=[response(bad),response(good)]
        planner=BedrockPlanner('offline','offline',client=client)
        repo=Mock();repo.search.return_value=[]
        flow=DialogueFlow(Mock(),planner,None,training=repo)
        payload={'action':'search','message':'부족한 역량을 채우고 싶어, 특히 마케팅'};before=copy.deepcopy(payload)
        with patch.dict(os.environ,{'ENABLE_LIVE_BEDROCK':'true'}):
            _,result,_=ContextRouter(flow).advance({},payload,self.invoke)
        self.assertEqual(client.converse.call_count,2)
        self.assertEqual(payload,before)
        inputs=[json.loads(c.kwargs['messages'][0]['content'][0]['text']) for c in client.converse.call_args_list]
        self.assertEqual(inputs[0]['message'],inputs[1]['message'])
        self.assertIn('classification_retry',inputs[1]['context'])
        self.assertEqual(result['stage'],'training_no_results')
        self.assertEqual(repo.search.call_args.args[0],['마케팅'])

    def test_second_contract_failure_stops_after_two_metered_invocations(self):
        planner=Mock();planner.classify.side_effect=ModelOutputFormatError({})
        flow=DialogueFlow(Mock(),planner,None,training=Mock())
        with self.assertRaises(ModelOutputFormatError):ContextRouter(flow).advance({}, {'action':'search','message':'교육'},self.invoke)
        self.assertEqual(planner.classify.call_count,2)
        flow.training.search.assert_not_called()

    def test_budget_network_and_truncation_are_not_contract_retries(self):
        for error in [FlowError('model_budget_exceeded',429),TimeoutError(),ModelOutputTruncatedError({})]:
            planner=Mock();planner.classify.side_effect=error
            flow=DialogueFlow(Mock(),planner,None,training=Mock())
            with self.assertRaises(type(error)):ContextRouter(flow).advance({}, {'action':'search','message':'교육'},self.invoke)
            self.assertEqual(planner.classify.call_count,1)
            flow.training.search.assert_not_called()

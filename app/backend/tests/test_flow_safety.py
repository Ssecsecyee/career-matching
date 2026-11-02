from routing_fixture import advance_intent
import unittest
from unittest.mock import Mock
from test_dialogue import Jobs, Questioner, invoke
from src.services.dialogue import DialogueFlow



class FlowSafetyTests(unittest.TestCase):
    def test_required_checkpoint_then_preferred_without_losing_answers(self):
        jobs=Jobs()
        jobs.job['qualifications']='- Python 개발'
        jobs.job['preferred_requirements']='- Docker 활용'
        flow=DialogueFlow(jobs,Mock(),Questioner(),include_unverified=True)
        state,_,_=flow.advance({}, {'action':'search','search_plan':{}},invoke)
        state,result,_=flow.advance(state,{'action':'select','source_id':'42','grouped':True,'assessment_checkpoint':True},invoke)
        answers=[{'question_id':q['question_id'],'assessment':'unmet','detail':'실습 예정'} for q in result['questions']]
        state,result,_=flow.advance(state,{'action':'answer_batch','answers':answers},invoke)
        self.assertEqual(result['stage'],'assessment_checkpoint')
        self.assertEqual(len(state['checks']),1)
        state,result,_=flow.advance(state,{'action':'assessment_control','control':'preferred'},invoke)
        self.assertEqual(result['stage'],'checking_preferred')
        self.assertEqual(state['checks'][0]['assessment'],'unmet')
        answers=[{'question_id':q['question_id'],'assessment':'unknown','detail':''} for q in result['questions']]
        state,result,_=flow.advance(state,{'action':'answer_batch','answers':answers},invoke)
        self.assertEqual(result['stage'],'gap_guidance')
        self.assertEqual(state['checks'][1]['assessment'],'unknown')

    def test_ros_online_context_retained_after_no_match(self):
        repo=Mock();repo.search.return_value=[];flow=DialogueFlow(Mock(),Mock(),None,training=repo)
        state,first,_=advance_intent(flow,{},'ROS 교육',dict(target='training',action='search',topics=['ROS 2'],delivery_mode='online'))
        _,again,_=advance_intent(flow,state,'다른 거',dict(target='training',action='next_results'))
        self.assertEqual(again['learning_search']['topics'],['ROS 2'])
        self.assertEqual(again['learning_search']['delivery_mode'],'online')
        self.assertEqual(again['learning_search']['status'],'no_match')

    def test_delivery_filter_and_change_requeries(self):
        repo=Mock();repo.search.return_value=[];flow=DialogueFlow(Mock(),Mock(),None,training=repo)
        state,_,_=advance_intent(flow,{},'온라인',dict(target='training',action='search',topics=['React'],delivery_mode='online'))
        advance_intent(flow,state,'오프라인',dict(target='training',action='refine_search',delivery_mode='offline'))
        self.assertEqual(repo.search.call_count,2)
        self.assertEqual(repo.search.call_args.kwargs['delivery_mode'],'offline')

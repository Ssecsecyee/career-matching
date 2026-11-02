import unittest
from unittest.mock import Mock
from test_dialogue import Jobs, Questioner, invoke
from src.services.dialogue import DialogueFlow
from src.services.learning import retrieve
from src.services.conversation_policy import search_target

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
        state,result,_=flow.advance(state,{'action':'search','message':'우대조건도 계속 확인해줘'},invoke)
        self.assertEqual(result['stage'],'checking_preferred')
        self.assertEqual(state['checks'][0]['assessment'],'unmet')
        answers=[{'question_id':q['question_id'],'assessment':'unknown','detail':''} for q in result['questions']]
        state,result,_=flow.advance(state,{'action':'answer_batch','answers':answers},invoke)
        self.assertEqual(result['stage'],'gap_guidance')
        self.assertEqual(state['checks'][1]['assessment'],'unknown')

    def test_ros_online_context_retained_after_no_match(self):
        repo=Mock();repo.search.return_value=[]
        first=retrieve({},'ROS 2 스레드 관리를 배울 온라인 부트캠프',repo,target='training')
        self.assertEqual(first['topics'],['ROS 2'])
        self.assertEqual(first['status'],'no_match')
        state={'conversation_target':'training','learning_context':first}
        self.assertEqual(search_target(state,'다른 거 추천해줘'),'training')
        again=retrieve(state,'다른 거 추천해줘',repo,target='training')
        self.assertEqual(again['topics'],['ROS 2'])
        self.assertEqual(again['delivery_mode'],'online')
        self.assertEqual(again['status'],'no_match')
        self.assertEqual(search_target(state,'백엔드 채용공고 찾아줘'),'jobs')

    def test_delivery_filter_and_change_requeries(self):
        repo=Mock();repo.search.return_value=[{'source_id':'a','delivery_mode':'online'}, {'source_id':'b','delivery_mode':'offline'}]
        first=retrieve({},'React 온라인 교육 추천',repo,target='training')
        self.assertEqual([c['source_id'] for c in first['courses']],['a'])
        second=retrieve({'learning_context':first},'오프라인으로 바꿔줘',repo,target='training')
        self.assertEqual([c['source_id'] for c in second['courses']],['b'])
        self.assertEqual(repo.search.call_count,2)

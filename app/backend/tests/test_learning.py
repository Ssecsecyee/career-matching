import copy
import json
import unittest
from unittest.mock import MagicMock,patch
from datetime import datetime,timedelta
from src.services.learning import retrieve,topics_in
from src.services.dialogue import DialogueFlow
from src.repositories.mysql_training import MySQLTrainingRepository,card
from src.bedrock.client import BedrockPlanner

class LearningTests(unittest.TestCase):
    def test_only_unmet_technical_conditions_become_gaps(self):
        repo=MagicMock();repo.search.return_value=[]
        state={'checks':[{'type':'required','assessment':'unmet','quote':'React 개발 경험'},
                         {'type':'required','assessment':'unknown','quote':'RAG 활용'},
                         {'type':'preferred','assessment':'met','quote':'Python 활용'},
                         {'type':'required','assessment':'unmet','quote':'학사 학위와 책임감'}]}
        result=retrieve(state,'부족한 역량에 맞는 교육 추천',repo)
        repo.search.assert_called_once_with(['React'])
        self.assertEqual(result['basis'],'explicit_learning_topic_and_self_assessed_gaps')

    def test_greetings_and_gap_summaries_do_not_query_training(self):
        repo=MagicMock()
        self.assertIsNone(retrieve({},'안녕',repo))
        self.assertIsNone(retrieve({},'내 답변만 정리해줘',repo))
        repo.search.assert_not_called()

    def test_missing_topics_asks_instead_of_dumping_every_course(self):
        repo=MagicMock()
        result=retrieve({},'부트캠프 추천해줘',repo)
        self.assertEqual(result['status'],'need_topic');repo.search.assert_not_called()

    def test_online_followup_reuses_learning_topics_without_reclassifying_ability(self):
        repo=MagicMock();repo.search.return_value=[]
        result=retrieve({'learning_context':{'topics':['React']}},'그중 온라인으로 하는 건?',repo)
        repo.search.assert_called_once_with(['React'])
        self.assertEqual(result['topics'],['React'])

    def test_technology_names_have_boundaries(self):
        self.assertEqual(topics_in('MySQL 공부'),['MySQL'])
        self.assertEqual(topics_in('JavaScript 공부'),['JavaScript'])

    def test_history_gets_retrieved_courses_in_one_model_call_and_checklist_remains(self):
        course={'source_id':'actual','recommendation_eligible':False,'matched_topics':['React']}
        repo=MagicMock();repo.search.return_value=[course]
        planner=MagicMock();planner.route.return_value=({'intent':'chat','reply':'기초와 프로젝트를 학습해 보세요.'},{})
        jobs=MagicMock();state={'stage':'gap_guidance','checks':[{'type':'required','assessment':'unmet','quote':'React 개발','detail':''}]}
        before=copy.deepcopy(state['checks']);calls=[]
        def invoke(purpose,fn,*args):calls.append(purpose);return fn(*args)[0]
        _,result,_=DialogueFlow(jobs,planner,None,training=repo).advance(state,{'action':'search','message':'React 학습 루트 추천'},invoke)
        history=planner.route.call_args.args[1]
        self.assertEqual(history['training_retrieval']['courses'],[course])
        self.assertEqual(calls,['conversation']);jobs.search.assert_not_called()
        self.assertEqual(state['checks'],before)
        self.assertIn('참고용',result['message'])
        self.assertEqual(result['learning_opportunities'],[course])

    def test_sql_uses_bound_parameters_and_closes_connection(self):
        conn=MagicMock();cur=conn.cursor.return_value.__enter__.return_value;cur.fetchall.return_value=[]
        topic="React' OR 1=1 --"
        MySQLTrainingRepository(lambda:conn).search([topic])
        query,args=cur.execute.call_args.args
        self.assertNotIn(topic,query);self.assertIn(topic,args);self.assertIn('LIMIT 20',query)
        conn.close.assert_called_once()

    def test_past_or_unknown_cannot_be_application_recommendation(self):
        row={'offering_id':1,'tuition':0,'recruitment_status':'unknown','learning_topics':['React'],
             'additional_sections':{'recommendation_eligible':False,'date_precision':{'starts_at':{'raw':'2024-07-24'}}}}
        result=card(row,['React']);self.assertFalse(result['recommendation_eligible'])
        self.assertEqual(result['usage'],'historical_learning_reference')
        row.update(recruitment_status='active',application_deadline=datetime.utcnow()-timedelta(days=1),additional_sections={'recommendation_eligible':True})
        self.assertFalse(card(row,['React'])['recommendation_eligible'])

    def test_prompt_passes_only_supplied_facts_and_keeps_token_bound(self):
        client=MagicMock();client.converse.return_value={'stopReason':'end_turn','output':{'message':{'content':[{'text':json.dumps({'intent':'chat','reply':'학습 참고 자료입니다.'})}]}},'usage':{'inputTokens':4,'outputTokens':4}}
        with patch.dict('os.environ',{'ENABLE_LIVE_BEDROCK':'true'}):
            _,usage=BedrockPlanner('model','region',client=client).route('학습 루트',{'training_retrieval':{'courses':[]}})
        data=client.converse.call_args.kwargs
        self.assertIn('recommendation_eligible=false',data['system'][0]['text'])
        self.assertEqual(data['inferenceConfig']['maxTokens'],1024)
        self.assertEqual(usage['prompt_version'],'conversation-preferences-v5')

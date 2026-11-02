from routing_fixture import advance_intent
import copy
import json
import unittest
from unittest.mock import MagicMock,patch
from datetime import datetime,timedelta
from src.services.learning import topics_in
from src.services.dialogue import DialogueFlow
from src.repositories.mysql_training import MySQLTrainingRepository,card
from src.bedrock.client import BedrockPlanner

class LearningTests(unittest.TestCase):
    def test_only_unmet_technical_conditions_become_gaps(self):
        repo=MagicMock();repo.search.return_value=[]
        flow=DialogueFlow(MagicMock(),MagicMock(),None,training=repo)
        state={'checks':[{'type':'required','assessment':'unknown','quote':'RAG'}]}
        _,result,_=advance_intent(flow,state,'교육 찾아줘',dict(target='training',action='search',topics=['React']))
        repo.search.assert_called_once_with(['React'],exclude_ids=[],delivery_mode=None)
        self.assertEqual(result['learning_search']['topics'],['React'])

    def test_greetings_and_gap_summaries_do_not_query_training(self):
        repo=MagicMock();planner=MagicMock();planner.respond.return_value=({'reply':'안녕하세요'},{})
        flow=DialogueFlow(MagicMock(),planner,None,training=repo)
        advance_intent(flow,{},'안녕',dict(target='general',action='chat'))
        repo.search.assert_not_called()

    def test_missing_topics_asks_instead_of_dumping_every_course(self):
        repo=MagicMock();flow=DialogueFlow(MagicMock(),MagicMock(),None,training=repo)
        _,result,_=advance_intent(flow,{},'부트캠프',dict(target='training',action='search'))
        self.assertTrue(result['clarification_required']);repo.search.assert_not_called()

    def test_online_followup_reuses_learning_topics_without_reclassifying_ability(self):
        repo=MagicMock();repo.search.return_value=[]
        flow=DialogueFlow(MagicMock(),MagicMock(),None,training=repo)
        state={'learning_context':{'topics':['React']}}
        _,result,_=advance_intent(flow,state,'온라인으로',dict(target='training',action='refine_search',delivery_mode='online'))
        repo.search.assert_called_once_with(['React'],exclude_ids=[],delivery_mode='online')
        self.assertEqual(result['learning_search']['topics'],['React'])

    def test_technology_names_have_boundaries(self):
        self.assertEqual(topics_in('MySQL 공부'),['MySQL'])
        self.assertEqual(topics_in('JavaScript 공부'),['JavaScript'])

    def test_history_gets_retrieved_courses_in_one_model_call_and_checklist_remains(self):
        course={'source':'fixture','source_id':'actual','title':'Course','recommendation_eligible':False}
        repo=MagicMock();repo.search.return_value=[course]
        planner=MagicMock();planner.respond.return_value=({'reply':'참고 자료를 비교합니다.'},{})
        jobs=MagicMock();state={'stage':'gap_guidance','checks':[]}
        flow=DialogueFlow(jobs,planner,None,training=repo)
        state,result,_=advance_intent(flow,state,'교육',dict(target='training',action='search',topics=['React']))
        _,result,_=advance_intent(flow,state,'이중 어떤거',dict(target='training',action='chat'))
        self.assertEqual(planner.respond.call_args.args[1]['training_retrieval']['courses'],[course])
        self.assertEqual(result['learning_opportunities'],[course]);jobs.search.assert_not_called()
        self.assertEqual(repo.search.call_count,1)

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
        client=MagicMock();client.converse.return_value={'stopReason':'end_turn','output':{'message':{'content':[{'text':'학습 참고 자료입니다.'}]}},'usage':{'inputTokens':4,'outputTokens':4}}
        with patch.dict('os.environ',{'ENABLE_LIVE_BEDROCK':'true'}):
            _,usage=BedrockPlanner('model','region',client=client).respond('학습 루트',{'training_retrieval':{'courses':[]}})
        data=client.converse.call_args.kwargs
        self.assertIn('모집 미확인',data['system'][0]['text'])
        self.assertEqual(data['inferenceConfig']['maxTokens'],4096)
        self.assertEqual(usage['prompt_version'],'context-response-v1')

import unittest
from unittest.mock import Mock,MagicMock
from src.schemas.intent import IntentDecision
from src.services.dialogue import DialogueFlow
from src.repositories.elasticsearch_training import build_training_query
from src.repositories.mysql_training import MySQLTrainingRepository
from src.repositories.search_failover import SearchFailover,SearchUnavailable
from routing_fixture import advance_intent

class TrainingBooleanTests(unittest.TestCase):
    def test_es_requires_all_topic_clauses_for_and_and_one_for_or(self):
        for operator,minimum in [('and',2),('or',1)]:
            query=build_training_query(['데이터분석','포트폴리오'],topic_operator=operator)['query']['bool']
            self.assertEqual(query['minimum_should_match'],minimum)
            self.assertEqual(len(query['should']),2)
        with self.assertRaises(ValueError):build_training_query(['React'],topic_operator='xor')

    def test_mysql_keeps_each_topic_clause_grouped_and_binds_values(self):
        queries=[]
        for operator in ('and','or'):
            conn=MagicMock();cur=conn.cursor.return_value.__enter__.return_value;cur.fetchall.return_value=[]
            MySQLTrainingRepository(lambda:conn).search(['A','B'],topic_operator=operator)
            sql,values=cur.execute.call_args.args
            self.assertEqual(values,['boottent','goyong24_training','A','A','B','B'])
            self.assertIn((')) AND (JSON_CONTAINS' if operator=='and' else ')) OR (JSON_CONTAINS'),sql)
            queries.append(sql)
        self.assertNotEqual(*queries)

    def test_and_survives_review_confirm_next_and_zero_never_relaxes(self):
        repo=Mock();repo.search.return_value=[{'source':'goyong24_training','source_id':'one','source_version':1,'title':'Both'}]
        flow=DialogueFlow(Mock(),Mock(),None,training=repo)
        state,review,_=advance_intent(flow,{},'데이터분석과 포트폴리오 둘 다',dict(target='training',action='search',topics=['데이터분석','포트폴리오'],topic_operator='and'))
        self.assertIn('AND',review['search_summary']['filters'][0])
        state,_,_=flow.advance(state,{'action':'confirm_search','search_id':review['search_id']},None)
        self.assertEqual(state['training_navigation']['topic_operator'],'and')
        repo.search.return_value=[]
        state,result,_=advance_intent(flow,state,'다른 교육',dict(target='training',action='next_results'))
        self.assertEqual(result['learning_opportunities'],[])
        self.assertEqual(repo.search.call_count,3)
        self.assertTrue(all(c.kwargs['topic_operator']=='and' for c in repo.search.call_args_list))
        self.assertTrue(all(c.args[0]==['데이터분석','포트폴리오'] for c in repo.search.call_args_list))

    def test_refine_preserves_operator_until_explicitly_changed(self):
        repo=Mock();repo.search.return_value=[];flow=DialogueFlow(Mock(),Mock(),None,training=repo)
        state,_,_=advance_intent(flow,{},'둘 다',dict(target='training',action='search',topics=['A','B'],topic_operator='and'))
        state,_,_=advance_intent(flow,state,'온라인만',dict(target='training',action='refine_search',delivery_mode='online'))
        self.assertEqual(repo.search.call_args.kwargs['topic_operator'],'and')
        state,_,_=advance_intent(flow,state,'둘 중 하나라도',dict(target='training',action='refine_search',topic_operator='or'))
        self.assertNotIn('topic_operator',repo.search.call_args.kwargs)
        self.assertEqual(state['training_search_context']['topic_operator'],'or')

    def test_availability_fallback_preserves_and(self):
        primary=Mock();primary.search.side_effect=SearchUnavailable();fallback=Mock();fallback.search.return_value=[]
        SearchFailover(primary,fallback,entity='training').search(['A','B'],topic_operator='and')
        fallback.search.assert_called_once_with(['A','B'],topic_operator='and')
        with self.assertRaises(ValueError):IntentDecision(target='training',action='search',topics=['A'],topic_operator='xor',reason='test')

    def test_model_cannot_silently_default_multiple_topics_to_or(self):
        with self.assertRaises(ValueError):
            IntentDecision(target='training',action='search',topics=['데이터분석','포트폴리오'],reason='test')

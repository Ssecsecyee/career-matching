import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, MagicMock
from src.repositories.jobs import JsonJobRepository
from src.repositories.elasticsearch_jobs import build_query
from src.repositories.search_failover import SearchFailover, SearchUnavailable
from src.schemas.search import SearchPlan
from src.services.dialogue import DialogueFlow
from src.schemas.intent import IntentDecision

class ContinuationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        path=Path(self.temp.name)/'jobs.json'
        path.write_text(json.dumps([{'source_id':str(i),'source_version':1,'title':'Backend',
            'recruitment_status':'active','tech_stacks':['Python']} for i in range(1,8)]))
        self.repo=JsonJobRepository(path)
        self.flow=DialogueFlow(self.repo,Mock(),Mock())
        self.state={'profile':{}}
        self.invoke=Mock(side_effect=AssertionError('No model allowed'))
    def start(self):
        self.state,r,_=self.flow.advance(self.state,{'action':'search','message':'Python',
            'search_plan':{'skills':['Python'],'limit':3}},self.invoke)
        return r
    def more(self,text='다른 거 추천해줘'):
        self.state,r,_=self.flow.advance(self.state,{'action':'next_results','target':'jobs'},self.invoke)
        return r
    def test_pages_exclude_shown_and_exhaust(self):
        pages=[self.start(),self.more(),self.more('이거 말고 몇개 더 보여줘')]
        ids=[j['source_id'] for p in pages for j in p['candidate_jobs']]
        self.assertEqual(len(ids),7)
        self.assertEqual(len(set(ids)),7)
        self.assertEqual([p['total'] for p in pages],[7,4,1])
        for _ in range(2):self.assertEqual(self.more()['candidate_jobs'],[])
        self.invoke.assert_not_called()
    def test_preserves_answers_and_resets_for_new_search(self):
        self.start()
        self.state.update(selected={'source_id':'1'},checks=[{'assessment':'met'}])
        self.more()
        self.assertEqual(self.state['checks'],[{'assessment':'met'}])
        self.assertEqual(self.state['selected'],{'source_id':'1'})
        self.assertEqual(self.start()['candidate_jobs'][0]['source_id'],'1')
        self.assertEqual(self.state['search_navigation']['shown_ids'],['1','2','3'])
    def test_unambiguous_intent_only(self):
        for target in ('jobs','training'):
            value=IntentDecision(target=target,action='next_results',reason='Validated model target')
            self.assertEqual(value.target,target)
        with self.assertRaises(ValueError):IntentDecision(target='general',action='next_results',reason='Invalid target')
    def test_exclusion_reaches_es_and_mysql_fallback(self):
        plan=SearchPlan(skills=['Python'])
        query=build_query(plan,exclude_ids=['1','2'])
        self.assertIn({'bool':{'must_not':[{'terms':{'source_id':['1','2']}}]}},query['query']['bool']['filter'])
        primary,fallback=Mock(),Mock()
        primary.search.side_effect=SearchUnavailable()
        fallback.search.return_value=(0,[])
        SearchFailover(primary,fallback,entity='job').search(plan,exclude_ids=['1'])
        fallback.search.assert_called_once_with(plan,exclude_ids=['1'])
    def test_review_marks_only_after_confirmation(self):
        self.state,r,_=self.flow.advance(self.state,{'action':'search','message':'찾아줘',
            'search_plan':{'schema_version':2,'owned_skills':['Python','AWS'],'limit':3}},self.invoke)
        self.assertEqual(r['stage'],'search_review')
        self.assertEqual(self.state['search_navigation']['shown_ids'],[])
        self.repo.get=lambda i:next(r for r in self.repo.rows if r['source_id']==i)
        self.state,r,_=self.flow.advance(self.state,{'action':'confirm_search','search_id':r['search_id']},self.invoke)
        self.assertEqual(self.state['search_navigation']['shown_ids'],['1','2','3'])
        self.assertEqual(self.more()['candidate_jobs'][0]['source_id'],'4')

    def test_pre_upgrade_confirmed_session_can_continue(self):
        self.start()
        self.state['search_context']={'confirmed_at':'test','executed_plan':{'skills':['Python'],'limit':3},
            'search_id':'old','summary':{}}
        del self.state['search_navigation']
        self.assertEqual(self.more()['candidate_jobs'][0]['source_id'],'4')

    def test_mysql_excludes_before_limit_with_bound_values(self):
        from src.repositories.mysql_jobs import MySQLJobRepository
        connection=MagicMock()
        cursor=connection.cursor.return_value.__enter__.return_value
        cursor.fetchone.return_value={'total':0}
        cursor.fetchall.return_value=[]
        MySQLJobRepository(lambda:connection).search(SearchPlan(skills=['Python']),exclude_ids=['1','2'])
        count, rows=cursor.execute.call_args_list
        self.assertIn('source_id NOT IN (%s,%s)',count.args[0])
        self.assertEqual(count.args[1][-2:],['1','2'])
        self.assertIn('LIMIT %s',rows.args[0])
        self.assertEqual(rows.args[1][-3:],['1','2',5])

    def test_short_more_forms_keep_plan_and_do_not_restart(self):
        for text in ['딴거','딴 거 추천해줘','다른거','다음','더보기']:
            with self.subTest(text=text):
                self.state={'profile':{}}
                self.start()
                self.assertEqual(self.more(text)['candidate_jobs'][0]['source_id'],'4')
        self.invoke.assert_not_called()

    def test_more_before_confirmation_keeps_same_review(self):
        self.state,r,_=self.flow.advance(self.state,{'action':'search','message':'찾아줘',
            'search_plan':{'schema_version':2,'owned_skills':['Python','AWS'],'limit':3}},self.invoke)
        search_id=r['search_id']
        for text in ['다른 거 추천해줘','딴거']:
            r=self.more(text)
            self.assertEqual(r['stage'],'search_review')
            self.assertEqual(r['search_id'],search_id)
            self.assertEqual(self.state['search_navigation']['shown_ids'],[])
            self.assertIn('아직 공고 목록',r['message'])
        self.invoke.assert_not_called()

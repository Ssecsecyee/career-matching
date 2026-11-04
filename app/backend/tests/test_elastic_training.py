import unittest
from src.repositories.elasticsearch_training import build_training_query, ElasticsearchTrainingRepository

class Cursor:
    def __enter__(self):return self
    def __exit__(self,*args):pass
    def execute(self,sql,params):self.params=params
    def fetchall(self):
        return [{'offering_id':1,'source':'boottent','source_id':'1','source_version':1,
                 'title':'React 학습','recruitment_status':'unknown','additional_sections':{},
                 'learning_topics':[],'tech_stacks':[],'tuition':None}]
class DB:
    def cursor(self):return Cursor()
    def close(self):pass
def hits(version=1):
    return {'hits':{'total':{'value':1,'relation':'eq'},'hits':[
        {'_source':{'source':'boottent','source_id':'1','source_version':version}}]}}
class ElasticTrainingTests(unittest.TestCase):
    def test_query_searches_curriculum_not_only_tags(self):
        query=build_training_query(['React'])
        fields=query['query']['bool']['should'][0]['bool']['should'][2]['multi_match']['fields']
        self.assertIn('curriculum^3',fields)
        self.assertIn('eligibility',fields)
    def test_unknown_result_never_becomes_application_candidate(self):
        repo=ElasticsearchTrainingRepository(DB,lambda *args:hits())
        cards=repo.search(['React'])
        self.assertEqual(len(cards),1)
        self.assertFalse(cards[0]['recommendation_eligible'])
        self.assertEqual(cards[0]['usage'],'historical_learning_reference')
    def test_old_index_version_is_excluded(self):
        self.assertEqual(ElasticsearchTrainingRepository(DB,lambda *args:hits(2)).search(['React']),[])
    def test_bad_topics_and_partial_results_fail(self):
        with self.assertRaises(ValueError):build_training_query([])
        with self.assertRaises(RuntimeError):
            ElasticsearchTrainingRepository(DB,lambda *args:{'timed_out':True}).search(['React'])

class LargeEducationSearchTests(unittest.TestCase):
    def test_large_total_returns_bounded_verified_candidates(self):
        from unittest.mock import MagicMock
        value={'hits':{'total':{'value':138484,'relation':'eq'},'hits':[{'_source':{'source':'boottent','source_id':str(i),'source_version':1}} for i in range(100)]}}
        conn=MagicMock();cur=conn.cursor.return_value.__enter__.return_value
        template=Cursor().fetchall()[0]
        cur.fetchall.return_value=[dict(template,source_id=str(i),offering_id=i) for i in range(3)]
        result=ElasticsearchTrainingRepository(lambda:conn,lambda *args:value).search(['React'])
        self.assertEqual(len(result),3)

    def test_unverified_first_page_uses_search_after(self):
        from unittest.mock import Mock
        first={'hits':{'total':{'value':101,'relation':'eq'},'hits':[
            {'_source':{'source':'boottent','source_id':'stale-'+str(i),'source_version':99},'sort':[1.0,str(i)]} for i in range(100)]}}
        second=hits();second['hits']['total']['value']=101
        request=Mock(side_effect=[first,second])
        result=ElasticsearchTrainingRepository(DB,request).search(['React'])
        self.assertEqual(len(result),1)
        self.assertEqual(request.call_args_list[1].args[2]['search_after'],[1.0,'99'])

    def test_top_thousand_is_a_limit_not_a_total_count_error(self):
        from unittest.mock import MagicMock
        request=MagicMock()
        def page(*args):
            n=request.call_count-1
            return {'hits':{'total':{'value':100000,'relation':'eq'},'hits':[
                {'_source':{'source':'boottent','source_id':'stale-'+str(n*100+i),'source_version':1},'sort':[1.0,str(n*100+i)]} for i in range(100)]}}
        request.side_effect=page
        conn=MagicMock();conn.cursor.return_value.__enter__.return_value.fetchall.return_value=[]
        repo=ElasticsearchTrainingRepository(lambda:conn,request)
        self.assertEqual(repo.search(['React']),[])
        self.assertEqual(request.call_count,10)
        self.assertTrue(repo.search_limited)

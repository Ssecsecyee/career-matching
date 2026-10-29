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

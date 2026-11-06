import unittest
from src.repositories.elasticsearch_training import build_training_query

class TrainingBrowseScopeTests(unittest.TestCase):
    def test_larger_browse_keeps_topic_mode_and_visibility_filters(self):
        options=dict(delivery_mode='online',candidates_only=True,topic_operator='and')
        normal=build_training_query(['Python','portfolio'],**options)
        browse=build_training_query(['Python','portfolio'],browse_all=True,**options)
        self.assertEqual(normal['query'],browse['query'])
        self.assertEqual(browse['query']['bool']['minimum_should_match'],2)

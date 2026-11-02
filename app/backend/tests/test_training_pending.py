import unittest
from unittest.mock import Mock
from routing_fixture import advance_intent
from src.services.dialogue import DialogueFlow
class PendingTrainingTests(unittest.TestCase):
    def test_topic_continues_education_without_job_lookup(self):
        jobs,repo=Mock(),Mock();repo.search.return_value=[]
        flow=DialogueFlow(jobs,Mock(),None,training=repo)
        _,result,_=advance_intent(flow,{},'UI/UX',dict(target='training',action='search',topics=['UI/UX']))
        self.assertEqual(result['learning_search']['status'],'no_match');jobs.search.assert_not_called()
    def test_arbitrary_topic_is_not_restricted_to_hardcoded_aliases(self):
        repo=Mock();repo.search.return_value=[]
        _,result,_=advance_intent(DialogueFlow(Mock(),Mock(),None,training=repo),{},'도자기',dict(target='training',action='search',topics=['도자기']))
        self.assertEqual(result['learning_search']['topics'],['도자기'])
    def test_missing_topic_clarifies_without_broad_lookup(self):
        repo=Mock()
        _,result,_=advance_intent(DialogueFlow(Mock(),Mock(),None,training=repo),{},'교육',dict(target='training',action='search'))
        self.assertTrue(result['clarification_required']);repo.search.assert_not_called()

import unittest
from src.services.learning import retrieve
class Training:
    def __init__(self):self.calls=[]
    def search(self,topics):self.calls.append(topics);return []
class PendingTrainingTests(unittest.TestCase):
    def test_design_topic_continues_education_request(self):
        repo=Training()
        state={'learning_context':{'status':'need_topic','topics':[],'courses':[]}}
        result=retrieve(state,'UI/UX 디자인',repo)
        self.assertEqual(result['status'],'no_match')
        self.assertEqual(repo.calls,[['UI/UX']])
    def test_explicit_job_request_leaves_education(self):
        state={'learning_context':{'status':'need_topic','topics':[],'courses':[]}}
        self.assertIsNone(retrieve(state,'UI/UX 채용 공고 찾아줘',Training()))
    def test_unrecognized_topic_stays_in_education(self):
        state={'learning_context':{'status':'need_topic','topics':[],'courses':[]}}
        self.assertEqual(retrieve(state,'도자기',Training())['status'],'need_topic')

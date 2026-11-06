import unittest
from uuid import uuid4
from src.handlers.dialogue import validate_payload
from src.repositories.elasticsearch_training import build_training_query
from src.services.dialogue import DialogueFlow

class TrainingBrowseTests(unittest.TestCase):
    def test_initial_action_allows_new_session(self):
        validate_payload({'action':'browse_training','request_id':str(uuid4())})
    def test_empty_topics_require_explicit_browse(self):
        with self.assertRaises(ValueError):build_training_query([])
        query=build_training_query([],browse_all=True,candidates_only=True)
        self.assertEqual(query['query']['bool']['minimum_should_match'],0)
        self.assertTrue(any('range' in item for item in query['query']['bool']['filter']))
    def test_initial_browse_does_not_invoke_model_or_clear_selected_job(self):
        class Repo:
            def search(self,topics,**kwargs):
                self.topics=topics;self.kwargs=kwargs;return []
        repo=Repo();flow=DialogueFlow(None,None,None,training=repo)
        selected={'source_id':'42'};state={'profile':{},'selected':selected}
        def forbidden(*a):raise AssertionError('model invoked')
        state,result,_=flow.advance(state,{'action':'browse_training'},forbidden)
        self.assertEqual(repo.topics,[]);self.assertTrue(repo.kwargs['browse_all'])
        self.assertEqual(state['selected'],selected)
        self.assertFalse(result['training_continuation'])
        self.assertFalse(result['training_has_more'])

    def test_detail_uses_displayed_identity_without_changing_assessments(self):
        from src.services.dialogue import FlowError
        course={'source':'goyong24_training','source_id':'course1','source_version':'2','start_window_eligible':True,'recruitment_status':'unknown','curriculum':'Full content'}
        class Repo:
            def get(self,identity):return dict(course)
        flow=DialogueFlow(None,None,None,training=Repo())
        state={'profile':{},'training_displayed':{'key':dict(course)},'checks':[{'assessment':'met'}],'selected':{'source_id':'42'}}
        payload={'action':'view_training','source':course['source'],'source_id':course['source_id'],'source_version':'2'}
        _,result,_=flow.advance(state,payload,lambda *args:self.fail('model invoked'))
        self.assertEqual(result['training_detail']['curriculum'],'Full content')
        self.assertEqual(state['selected']['source_id'],'42');self.assertEqual(len(state['checks']),1)
        with self.assertRaises(FlowError):flow.advance(state,dict(payload,source_id='unseen'),None)
        course['source_version']='3'
        with self.assertRaises(FlowError):flow.advance(state,payload,None)

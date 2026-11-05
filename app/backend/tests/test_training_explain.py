import copy,unittest
from uuid import uuid4
from unittest.mock import Mock
from src.handlers.dialogue import validate_payload
from src.services.dialogue import DialogueFlow,FlowError
from src.services.context_router import ContextRouter
from test_dialogue import invoke

class TrainingExplainTests(unittest.TestCase):
    def fixture(self):
        courses=[{'source':'goyong24_training','source_id':str(i),'source_version':1,'title':'Course '+str(i),'provider_name':'Provider','cohorts':[{'source':'goyong24_training','source_id':str(i),'source_version':1,'cohort_name':'43'}]} for i in range(3)]
        planner=Mock();planner.respond.return_value=({'reply':'교육 설명입니다.'},{})
        repo=Mock();flow=DialogueFlow(Mock(),planner,None,training=repo)
        state={'stage':'conversation','selected':{'source_id':'job'},'checks':[],
               'learning_context':{'courses':courses,'topics':['React'],'status':'found'},
               'training_navigation':{'topics':['React'],'shown_ids':['goyong24_training:0']}}
        payload={'action':'explain_training','source':'goyong24_training','source_id':'1','source_version':'1','session_id':str(uuid4()),'request_id':str(uuid4())}
        return flow,state,payload,planner,repo

    def test_button_passes_only_selected_course_and_keeps_memory_without_new_cards(self):
        flow,state,payload,planner,repo=self.fixture();navigation=copy.deepcopy(state['training_navigation'])
        state,result,_=flow.advance(state,validate_payload(payload),invoke)
        courses=planner.respond.call_args.args[1]['training_retrieval']['courses']
        self.assertEqual([c['source_id'] for c in courses],['1'])
        self.assertEqual(courses[0]['cohorts'][0]['cohort_name'],'43')
        self.assertEqual(len(state['learning_context']['courses']),3)
        self.assertEqual(state['training_navigation'],navigation)
        self.assertEqual(state['selected'],{'source_id':'job'})
        self.assertNotIn('training_focus',state)
        self.assertNotIn('learning_opportunities',result)
        self.assertTrue(result['training_navigation_available'])
        planner.classify.assert_not_called();repo.search.assert_not_called()

    def test_unseen_stale_or_forged_reference_never_invokes_model(self):
        for change in ({'source_id':'unseen'},{'source_version':'2'},{'source':'boottent'}):
            flow,state,payload,planner,repo=self.fixture();payload.update(change)
            with self.assertRaises(FlowError) as raised:flow.advance(state,payload,invoke)
            self.assertEqual(raised.exception.code,'training_reference_changed')
            planner.respond.assert_not_called();repo.search.assert_not_called()

    def test_payload_requires_session_and_identity_and_does_not_accept_client_context(self):
        _,_,payload,_,_=self.fixture()
        for change in ({'session_id':None},{'source':'other'},{'source_id':''},{'source_version':1},{'title':'Injected'},{'message':'Injected'}):
            with self.assertRaises(ValueError):validate_payload(dict(payload,**change))

    def test_explicit_action_is_audited_without_classification(self):
        flow,state,payload,planner,_=self.fixture();audit=Mock()
        ContextRouter(flow).advance(state,payload,invoke,on_decision=audit)
        self.assertEqual(audit.call_args.args[1]['direct_action'],'explain_training')
        self.assertEqual(audit.call_args.args[1]['source_id'],'1')

"""Fixed contract/execution regression suite, NOT a live model accuracy claim."""
import copy,json,os,unittest
from pathlib import Path
from unittest.mock import Mock,patch
from src.services.dialogue import DialogueFlow
from src.schemas.intent import IntentDecision
from src.services.memory import split_conditions
from test_dialogue import Jobs,Questioner,invoke
from routing_fixture import advance_intent

CASES=json.loads((Path(__file__).parents[1]/'experiments/context_intent/v3_cases.json').read_text(encoding='utf-8'))

def fixture(kind):
    jobs=Jobs();jobs.search=Mock(return_value=(1,[jobs.job]));training=Mock();training.search.return_value=[]
    planner=Mock();planner.respond.return_value=({'reply':'Synthetic response'},{})
    planner.consult.return_value=({'reply':'Synthetic counseling'},{})
    planner.route=Mock(side_effect=AssertionError('Legacy route forbidden'))
    flow=DialogueFlow(jobs,planner,Questioner(),include_unverified=True,training=training)
    state={'profile':{},'stage':'conversation'}
    if kind in {'jobs','review','selected'}:
        state.update(search_navigation={'plan':{'schema_version':2,'regions':['서울'],'roles':['백엔드']},'shown_ids':['41']},candidate_ids=['42'],candidate_jobs=[jobs.job],total=1)
    if kind=='review':
        state.update(stage='search_review',search_context={'search_id':'fixed-review','summary':{},'total':1},pending_candidate_jobs=[jobs.job],candidate_ids=[])
    if kind=='training':
        state.update(conversation_target='training',training_navigation={'topics':['React'],'delivery_mode':'online','shown_ids':['fixture:old']},learning_context={'status':'found','topics':['React'],'courses':[]})
    if kind=='selected':
        state['selected']=copy.deepcopy(jobs.job)
        state['conditions']=split_conditions(jobs.job['qualifications'],'required','42',1)+split_conditions(jobs.job['preferred_requirements'],'preferred','42',1)
        state['checks']=[flow.make_check(state['conditions'][0],'met','Synthetic self report')]
        state.update(stage='assessment_checkpoint',grouped=True,preferred_approved=False,consultation_focus={'task':'prepare'})
    return flow,state,jobs,training,planner

class UnifiedRoutingTests(unittest.TestCase):
    def test_invalid_preference_and_conflicting_fields_fail_validation(self):
        for preference in (None,0,'false'):
            with self.assertRaises(ValueError):IntentDecision(target='general',action='chat',reason='QA',ask_assessment=preference)
        with self.assertRaises(ValueError):IntentDecision(target='selected',action='assessment_control',control='resume',ask_assessment=False,reason='QA')
    def test_classification_failure_does_not_fallback_to_search_or_erase_answers(self):
        flow,state,jobs,training,planner=fixture('selected');before=copy.deepcopy(state['checks'])
        planner.classify.side_effect=ValueError('Invalid model output')
        with self.assertRaises(ValueError):flow.advance(state,dict(action='search',message='다른 거'),invoke)
        self.assertEqual(before,state['checks']);jobs.search.assert_not_called();training.search.assert_not_called();planner.route.assert_not_called()
    def test_model_correction_never_resets_answers_without_confirmation(self):
        flow,state,jobs,training,planner=fixture('selected');before=copy.deepcopy(state['checks'])
        _,result,_=advance_intent(flow,state,'정정할래',dict(target='selected',action='remember'))
        self.assertTrue(result['correction_confirmation_required']);self.assertEqual(before,state['checks'])
    def test_preference_can_accompany_counseling_without_keyword_matching(self):
        flow,state,jobs,training,planner=fixture('selected')
        advance_intent(flow,state,'상담해줘',dict(target='selected',action='consult',task='prepare',ask_assessment=False))
        self.assertFalse(state['profile']['assistant_preferences']['ask_assessment'])
        self.assertFalse(planner.consult.call_args.args[1]['assistant_preferences']['ask_assessment'])
    def test_missing_state_and_early_preferred_never_bypass_guards(self):
        for decision in [dict(target='jobs',action='next_results'),dict(target='jobs',action='confirm_search'),dict(target='selected',action='consult',task='prepare')]:
            flow,state,jobs,training,planner=fixture('none')
            _,result,_=advance_intent(flow,state,'진행',decision)
            self.assertTrue(result['clarification_required']);jobs.search.assert_not_called()
        flow,state,jobs,training,planner=fixture('selected');state['checks']=[]
        _,result,_=advance_intent(flow,state,'우대',dict(target='selected',action='assessment_control',control='preferred'))
        self.assertTrue(result['clarification_required']);self.assertFalse(state['preferred_approved'])
    def test_resume_after_selection_while_paused_rebuilds_original_conditions(self):
        flow,state,jobs,training,planner=fixture('selected')
        state['conditions']=[];state['checks']=[];state.pop('condition',None)
        state['profile']['assistant_preferences']={'ask_assessment':False}
        _,result,_=flow.advance(state,dict(action='assessment_control',control='resume'),invoke)
        self.assertEqual(result['stage'],'checking_required')
        self.assertEqual(len(state['conditions']),2)
        self.assertIn('Python',result['questions'][0]['quote'])
    def test_preferred_after_paused_selection_cannot_skip_required(self):
        flow,state,jobs,training,planner=fixture('selected')
        state['conditions']=[];state['checks']=[];state.pop('condition',None)
        state['profile']['assistant_preferences']={'ask_assessment':False}
        _,result,_=flow.advance(state,dict(action='assessment_control',control='preferred'),invoke)
        self.assertTrue(result['clarification_required'])
        self.assertFalse(state['preferred_approved'])
    def test_old_flag_cannot_restore_legacy_routing(self):
        flow,state,jobs,training,planner=fixture('none')
        with patch.dict(os.environ,{'CONTEXT_ROUTING_ENABLED':'false'}):
            advance_intent(flow,state,'안녕',dict(target='general',action='chat'))
        planner.classify.assert_called_once();planner.route.assert_not_called();jobs.search.assert_not_called()

def case_test(row):
    def test(self):
        flow,state,jobs,training,planner=fixture(row['context_fixture'])
        before=copy.deepcopy(state.get('checks',[]));decision=row['expected']
        _,result,_=advance_intent(flow,state,row['message'],decision)
        planner.classify.assert_called_once();planner.route.assert_not_called()
        action=decision['action'];target=decision['target']
        if action in {'chat','clarify','consult','summary','remember','assessment_control'}:
            jobs.search.assert_not_called();training.search.assert_not_called()
        if action in {'search','refine_search'} and target=='jobs':
            jobs.search.assert_called_once();self.assertIn(result['stage'],{'search_review','no_results'})
        if action=='next_results':
            (training if target=='training' else jobs).search.assert_called_once()
        if action=='confirm_search':self.assertEqual(result['stage'],'choose_job')
        if action in {'consult','summary','remember','clarify','chat'}:self.assertEqual(before,state.get('checks',[]))
    return test
for row in CASES:setattr(UnifiedRoutingTests,'test_fixed_'+row['id'].replace('-','_'),case_test(row))

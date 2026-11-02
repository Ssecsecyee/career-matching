"""Inject a model decision explicitly; never infer test decisions from message text."""
from unittest.mock import Mock
from test_dialogue import invoke

def advance_intent(flow,state,message,decision):
    if flow.planner is None:flow.planner=Mock()
    flow.planner.classify=Mock(return_value=({'decision':{'reason':'Synthetic QA expectation',**decision},'raw_output':''},{}))
    return flow.advance(state,{'action':'search','message':message},invoke)

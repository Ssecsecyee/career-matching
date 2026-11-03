import unittest
from src.schemas.intent import IntentDecision
from src.schemas.search import SearchPlan
from src.services.search_constraints import guard_required_skills
from src.services.intent_context import assessment_facts

class SearchConstraintTests(unittest.TestCase):
    def decision(self,**kw):
        return IntentDecision.model_validate(dict(target='jobs',action='search',reason='test',plan={'schema_version':2},**kw))
    def test_assessment_softens_inferred_requirements(self):
        plan=SearchPlan(schema_version=2,roles=['leader'],required_skills=['commerce','AI'])
        result,audit=guard_required_skills(plan,{},self.decision(search_basis='assessment'),'use my answers')
        self.assertEqual(result.required_skills,())
        self.assertEqual(result.preferred_skills,('commerce','AI'))
        self.assertEqual(audit['unsupported_required_skills'],['commerce','AI'])
    def test_explicit_and_inherited_constraints_survive(self):
        plan=SearchPlan(schema_version=2,required_skills=['Python','Docker'])
        d=self.decision(required_skill_evidence=[{'skill':'Python','quote':'Python required'}])
        result,_=guard_required_skills(plan,{'required_skills':['Docker']},d,'Python required')
        self.assertEqual(result.required_skills,('Python','Docker'))
    def test_fabricated_quote_rejected(self):
        result,_=guard_required_skills(SearchPlan(schema_version=2,required_skills=['Python']),{},
            self.decision(required_skill_evidence=[{'skill':'Python','quote':'Python required'}]),'hello')
        self.assertIsNone(result)
    def test_only_linked_answers_are_facts_and_details_excluded(self):
        facts=assessment_facts({'conditions':[{'id':'a','quote':'Python','type':'required'}],
            'checks':[{'condition_id':'a','assessment':'unknown','detail':'private'},
                      {'condition_id':'missing','assessment':'met'}]})
        self.assertEqual(len(facts['items']),1)
        self.assertEqual(facts['items'][0]['assessment'],'unknown')
        self.assertNotIn('private',str(facts))
    def test_wrong_action_rejected(self):
        with self.assertRaises(ValueError):IntentDecision(target='general',action='chat',reason='test',search_basis='assessment')

    def test_assessment_search_records_guard_and_excludes_selected(self):
        from unittest.mock import Mock
        from test_context_routing import ContextRoutingTests, invoke
        router,_,jobs,_=ContextRoutingTests().fixture(dict(target='jobs',action='search',reason='similar',
            search_basis='assessment',plan={'schema_version':2,'roles':['leader'],'required_skills':['commerce']}))
        jobs.search=Mock(return_value=(18,[]))
        state={'selected':{'source_id':'55387294','source_version':2},
            'conditions':[{'id':'a','type':'required','quote':'commerce experience'}],
            'checks':[{'condition_id':'a','assessment':'met'}]}
        _,response,_=router.advance(state,{'action':'search','message':'use my answers'},invoke)
        self.assertEqual(jobs.search.call_args.kwargs['exclude_ids'],['55387294'])
        context=state['search_context']
        self.assertEqual(context['raw_plan']['required_skills'],['commerce'])
        self.assertEqual(context['executed_plan']['required_skills'],[])
        self.assertEqual(context['assessment_basis']['items'][0]['assessment'],'met')
        self.assertGreater(len(response['search_summary']['limitations']),1)

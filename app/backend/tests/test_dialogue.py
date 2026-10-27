import copy
import unittest

from src.schemas.search import SearchPlan
from src.services.dialogue import DialogueFlow, FlowError


class Jobs:
    def __init__(self):
        self.job = {"job_id": 1, "source_id": "42", "source_url": "https://example.com/42",
                    "source_version": 1, "title": "test", "company_name": "fixture",
                    "qualifications": "Python 또는 Java 경험", "preferred_requirements": "AWS 경험 우대",
                    "recruitment_status": "unknown"}

    def search(self, plan):
        return 1, [self.job]

    def get(self, identity):
        return copy.deepcopy(self.job) if identity == "42" else None


class Questioner:
    model_id, region = "fake-model", "fake-region"

    def question(self, condition, profile):
        return {"question": "원문의 조건에 해당하시나요?", "quote": condition["quote"]}, {}


def invoke(purpose, function, *args):
    return function(*args)[0]


class DialogueFlowTests(unittest.TestCase):
    def start(self):
        self.jobs = Jobs()
        self.flow = DialogueFlow(self.jobs, None, Questioner(), include_unverified=True)
        state, _, _ = self.flow.advance({}, {"action": "search", "search_plan": {"skills": ["Python"]}}, invoke)
        return self.flow.advance(state, {"action": "select", "source_id": "42"}, invoke)[0]

    def test_required_before_preferred_and_unknown_advances_as_unconfirmed(self):
        state = self.start()
        self.assertEqual(state["stage"], "checking_required")
        self.assertEqual(state["condition"]["quote"], "Python 또는 Java 경험")
        state, result, evidence = self.flow.advance(state, {
            "action": "answer", "question_id": state["condition"]["id"], "assessment": "unknown"}, invoke)
        self.assertEqual(state["stage"], "checking_preferred")
        self.assertEqual(evidence[0]["check"]["assessment"], "unknown")

    def test_required_unmet_is_retained_while_preferred_is_checked(self):
        state = self.start()
        state, result, evidence = self.flow.advance(state, {
            "action": "answer", "question_id": state["condition"]["id"], "assessment": "unmet"}, invoke)
        self.assertEqual(state["stage"], "checking_preferred")
        state, result, _ = self.flow.advance(state, {"action": "answer", "question_id": state["condition"]["id"], "assessment": "met"}, invoke)
        self.assertEqual(state["stage"], "gap_guidance")
        self.assertEqual(result["learning_opportunities"], [])

    def test_required_met_goes_to_preferred_then_completes(self):
        state = self.start()
        state, result, _ = self.flow.advance(state, {
            "action": "answer", "question_id": state["condition"]["id"], "assessment": "met"}, invoke)
        self.assertEqual(state["stage"], "checking_preferred")
        state, result, _ = self.flow.advance(state, {
            "action": "answer", "question_id": state["condition"]["id"], "assessment": "unmet"}, invoke)
        self.assertEqual(state["stage"], "completed")

    def test_changed_source_requires_reselection(self):
        state = self.start()
        self.jobs.job["source_version"] = 2
        with self.assertRaises(FlowError) as error:
            self.flow.advance(state, {"action": "answer", "question_id": state["condition"]["id"],
                                      "assessment": "met"}, invoke)
        self.assertEqual(error.exception.code, "source_changed_reselect_job")

    def test_cannot_select_arbitrary_job(self):
        self.start()
        with self.assertRaises(FlowError):
            self.flow.advance({"candidate_ids": []}, {"action": "select", "source_id": "42"}, invoke)

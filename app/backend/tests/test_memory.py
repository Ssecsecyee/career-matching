import copy
import json
import unittest

from src.services.memory import context, memory, record, split_conditions
from src.services.dialogue import DialogueFlow, FlowError
from test_dialogue import Jobs, Questioner, invoke


class RecordingQuestioner(Questioner):
    def __init__(self):
        self.contexts = []

    def question(self, condition, profile):
        self.contexts.append(copy.deepcopy(profile))
        return super().question(condition, profile)


class MemoryFlowTests(unittest.TestCase):
    def setUp(self):
        self.jobs = Jobs()
        self.jobs.job['qualifications'] = '- Python 또는 Java 경험\n- MySQL 설계 및 쿼리 최적화\n- Linux 개발 경험'
        self.model = RecordingQuestioner()
        self.flow = DialogueFlow(self.jobs, None, self.model, include_unverified=True)
        self.state, _, _ = self.flow.advance({}, {'action': 'search', 'search_plan': {},
            'profile': {'user_statement': 'MySQL 프로젝트 경험이 있고 Linux는 학습 중입니다.'}}, invoke)

    def select(self):
        self.state, response, _ = self.flow.advance(self.state, {'action': 'select', 'source_id': '42'}, invoke)
        return response

    def answer(self, assessment, detail=''):
        self.state, result, evidence = self.flow.advance(self.state, {'action': 'answer',
            'question_id': self.state['condition']['id'], 'assessment': assessment, 'detail': detail}, invoke)
        return result, evidence

    def test_initial_experience_and_previous_answers_reach_next_question(self):
        self.select()
        self.assertIn('MySQL 프로젝트', self.model.contexts[0]['recent_statements'][0]['text'])
        result, _ = self.answer('met', 'Python으로 API를 개발했습니다.')
        self.assertEqual(result['quote'], '- MySQL 설계 및 쿼리 최적화')
        self.assertEqual(result['progress'], {'answered': 1, 'total': 4})
        self.assertEqual(self.model.contexts[-1]['condition_answers'][0]['assessment'], 'met')
        self.assertTrue(any('API를 개발' in x['text'] for x in self.model.contexts[-1]['recent_statements']))

    def test_unknown_advances_without_becoming_unmet_and_all_required_precede_preferred(self):
        self.select()
        result, _ = self.answer('unknown')
        self.assertEqual(result['quote'], '- MySQL 설계 및 쿼리 최적화')
        self.assertEqual(self.state['checks'][0]['assessment'], 'unknown')
        self.answer('unmet')
        result, _ = self.answer('met')
        self.assertEqual(result['requirement_type'], 'preferred')
        result, _ = self.answer('met')
        self.assertEqual(result['stage'], 'gap_guidance')
        self.assertEqual(result['unconfirmed_count'], 1)

    def test_same_session_search_retains_memory_and_same_version_does_not_repeat_confirmed_condition(self):
        self.select()
        self.answer('met')
        self.state, _, _ = self.flow.advance(self.state, {'action': 'search', 'search_plan': {}}, invoke)
        calls = len(self.model.contexts)
        response = self.select()
        self.assertEqual(response['quote'], '- MySQL 설계 및 쿼리 최적화')
        self.assertEqual(len(self.model.contexts), calls + 1)
        self.assertTrue(self.state['checks'][0]['reused'])
        self.assertTrue(memory(self.state)['statements'])

    def test_changed_job_version_does_not_reuse_old_confirmation(self):
        self.select()
        self.answer('met')
        self.jobs.job['source_version'] = 2
        self.state, _, _ = self.flow.advance(self.state, {'action': 'search', 'search_plan': {}}, invoke)
        response = self.select()
        self.assertEqual(response['quote'], '- Python 또는 Java 경험')

    def test_explicit_correction_invalidates_confirmations_and_reopens_first_condition(self):
        self.select()
        self.answer('met')
        self.state, response, _ = self.flow.advance(self.state, {'action': 'remember',
            'message': '정정합니다. Python은 사용 경험이 없습니다.'}, invoke)
        self.assertEqual(response['quote'], '- Python 또는 Java 경험')
        self.assertEqual(self.state['checks'], [])
        self.assertEqual(memory(self.state)['confirmed'], {})
        self.assertEqual(self.model.contexts[-1]['recent_statements'][-1]['kind'], 'correction')

    def test_unknown_is_not_reused_and_user_memory_cannot_be_supplied_by_client(self):
        self.select()
        self.answer('unknown')
        self.state, _, _ = self.flow.advance(self.state, {'action': 'search', 'search_plan': {},
            'profile': {'memory': {'confirmed': {'forged': 'met'}}}}, invoke)
        self.assertNotIn('forged', memory(self.state)['confirmed'])
        self.assertEqual(self.select()['quote'], '- Python 또는 Java 경험')

    def test_memory_is_session_scoped_and_context_bounded(self):
        for _ in range(50):
            record(self.state, '사용자 발언' * 600)
        value = context(self.state)
        self.assertLessEqual(len(value['recent_statements']), 6)
        self.assertLessEqual(sum(len(x['text']) for x in value['recent_statements']), 6000)
        self.assertLess(len(json.dumps(value, ensure_ascii=False)), 24000)
        other = {}
        self.assertEqual(memory(other)['statements'], [])

    def test_or_clauses_and_continuations_are_preserved(self):
        rows = split_conditions('- MySQL 또는 MariaDB 경험\n  및 설계 경험\n- 경력 3년 이상', 'required', '42', 1)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]['quote'], '- MySQL 또는 MariaDB 경험\n및 설계 경험')
        self.assertIn('3년', rows[1]['quote'])


if __name__ == '__main__':
    unittest.main()

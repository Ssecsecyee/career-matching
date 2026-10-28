import copy
import json
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'ingestion'))
from normalize_training import normalize_training

class TrainingContractTests(unittest.TestCase):
    def record(self):
        path=Path(__file__).resolve().parents[2]/'ingestion/examples/training.fixture.json'
        return json.loads(path.read_text(encoding='utf-8'))[0]
    def test_fixture_and_date_precision_are_explicit(self):
        row=normalize_training(self.record())
        self.assertEqual(row['source'],'fixture')
        self.assertTrue(row['additional_sections']['is_fixture'])
        self.assertIsNone(row['starts_at']);self.assertIsNone(row['application_deadline'])
        self.assertEqual(row['additional_sections']['date_precision']['starts_at']['raw'],'2026-12-01')
        self.assertEqual(row['recruitment_status'],'unknown')
    def test_course_and_cohort_separated_and_unknown_cohort_not_invented(self):
        record=self.record();record['cohort_name']=None
        row=normalize_training(record)
        self.assertEqual(row['course_key'],'demo-course-1')
        self.assertFalse(row['additional_sections']['cohort_verified'])
    def test_reversed_period_rejected(self):
        record=self.record();record['dates']['ends_at']['raw']='2026-01-01'
        with self.assertRaises(ValueError):normalize_training(record)
    def test_unknown_cost_is_not_zero(self):
        row=normalize_training(self.record());self.assertIsNone(row['tuition'])
        for amount in ('NaN','-1','1.001'):
            record=self.record();record.update(tuition=amount,currency='KRW')
            with self.assertRaises(ValueError):normalize_training(record)
    def test_key_in_url_rejected_but_public_course_parameters_allowed(self):
        record=self.record();record.update(source='goyong24_training',source_url='https://www.work24.go.kr/training?trprId=demo&trprDegr=1')
        normalize_training(record)
        record['source_url']+='&authKey=do-not-store'
        with self.assertRaises(ValueError):normalize_training(record)
    def test_status_not_inferred_and_explicit_status_requires_evidence(self):
        record=self.record();record['recruitment_status']='active'
        with self.assertRaises(ValueError):normalize_training(record)
    def test_observation_time_does_not_change_content_hash(self):
        record=self.record();first=normalize_training(record)
        record['fetched_at']='2026-10-28T01:00:00Z'
        self.assertEqual(first['content_hash'],normalize_training(record)['content_hash'])

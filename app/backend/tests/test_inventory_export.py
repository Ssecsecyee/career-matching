"""Inventory batching is read-only; these tests never open a DB connection."""
from datetime import datetime,timedelta,timezone
from pathlib import Path
import sys,unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[3]/'app/ingestion'))
from inventory_jumpit import inventory

class InventoryExportTests(unittest.TestCase):
 def setUp(self):
  self.now=datetime(2026,11,2,tzinfo=timezone.utc)
  self.rows=[dict(source_id=str(i),recruitment_status='unknown',deadline_type='unknown',deadline_at=None,fetched_at=self.now-timedelta(days=8)) for i in range(125)]
 def test_default_preserves_the_100_record_limit(self):
  result=inventory(self.rows,now=self.now)
  self.assertEqual(len(result['recheck_due']),100)
  self.assertEqual(result['due_total_count'],125)
  self.assertEqual(result['remaining_due_count'],25)
 def test_zero_exports_every_due_identity(self):
  result=inventory(self.rows,now=self.now,limit=0)
  self.assertEqual(len(result['recheck_due']),125)
  self.assertEqual(result['remaining_due_count'],0)
  self.assertEqual(result['recheck_limit'],0)
 def test_explicit_limit_does_not_make_closed_jobs_due(self):
  self.rows[0]['recruitment_status']='closed'
  result=inventory(self.rows,now=self.now,limit=1)
  self.assertEqual(result['due_total_count'],124)
  self.assertEqual(len(result['recheck_due']),1)
  self.assertIn('0',result['skip_routine_details'])
 def test_negative_or_non_integer_limit_is_rejected(self):
  for limit in [-1,None,1.5]:
   with self.subTest(limit=limit):
    with self.assertRaises(ValueError):inventory(self.rows,now=self.now,limit=limit)

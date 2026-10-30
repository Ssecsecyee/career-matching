import json
from datetime import datetime, timezone
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'ingestion/search_index'))
from sync_outbox import Consumer, job_document, training_document
from src.services.deadlines import expired


class Cursor:
    def __init__(self,row,tombstone=None):self.row=row;self.tombstone=tombstone;self.sql=[]
    def __enter__(self):return self
    def __exit__(self,*args):pass
    def execute(self,sql,params=None):self.sql.append((sql,params))
    def fetchone(self):return self.tombstone if self.sql[-1][0].startswith('SELECT event_id') else self.row


class SyncTests(unittest.TestCase):
    def row(self,**overrides):
        return dict(source='jumpit',source_id='123',source_version=2,title='React',company_name='Test',source_url='https://example.com',tech_stacks=['React'],addresses=[],recruitment_status='unknown',**overrides)

    def test_date_only_korean_midnight_boundary(self):
        row=self.row(additional_sections={'page_extraction':{'deadline':{'raw':'2026-10-30','precision':'date_only'}}})
        self.assertFalse(expired(row,datetime(2026,10,30,14,59,59,tzinfo=timezone.utc)))
        self.assertTrue(expired(row,datetime(2026,10,30,15,tzinfo=timezone.utc)))
        _,doc=job_document(row)
        self.assertEqual(doc['deadline_at'],'2026-10-30T15:00:00+00:00')
        self.assertEqual(doc['deadline_at_raw'],'2026-10-30')

    def test_always_open_and_unknown_dates(self):
        self.assertFalse(expired(self.row(deadline_type='always_open',deadline_at='2000-01-01T00:00:00Z')))
        self.assertFalse(expired(self.row(additional_sections={'page_extraction':{'deadline':{'raw':'not a date','precision':'date_only'}}})))

    def test_latest_db_state_wins_old_close_event(self):
        cur=Cursor(self.row())
        db=Mock();db.cursor.return_value=cur;engine=Mock()
        Consumer(db,engine).process(dict(entity_type='job',entity_id=1,source_version=1,operation='close',event_id=9))
        self.assertFalse(engine.apply.call_args.kwargs['remove'])
        self.assertEqual(engine.apply.call_args.args[1]['source_version'],2)
        self.assertIn('processed_at',cur.sql[-1][0])

    def test_engine_failure_does_not_ack(self):
        cur=Cursor(self.row());db=Mock();db.cursor.return_value=cur;engine=Mock();engine.apply.side_effect=TimeoutError
        with self.assertRaises(TimeoutError):Consumer(db,engine).process(dict(entity_type='job',entity_id=1,source_version=2,operation='upsert',event_id=1))
        self.assertFalse(any('UPDATE search_outbox' in sql for sql,_ in cur.sql))

    def test_delete_tombstone_prevents_old_upsert_resurrection(self):
        cur=Cursor(self.row(),{'event_id':10});db=Mock();db.cursor.return_value=cur;engine=Mock()
        Consumer(db,engine).process(dict(entity_type='job',entity_id=1,source_version=1,operation='upsert',event_id=1))
        self.assertTrue(engine.apply.call_args.kwargs['remove'])

    def test_missing_row_is_not_silently_acknowledged(self):
        cur=Cursor(None);db=Mock();db.cursor.return_value=cur;engine=Mock()
        with self.assertRaisesRegex(ValueError,'missing_source_identity'):
            Consumer(db,engine).process(dict(entity_type='job',entity_id=1,source_version=1,operation='delete',event_id=1))
        engine.apply.assert_not_called()

    def test_training_historical_record_retained(self):
        _,doc=training_document(dict(source='boottent',source_id='course',source_version=1,title='React',recruitment_status='closed',learning_topics=json.dumps(['React'])))
        self.assertEqual(doc['recruitment_status'],'closed')
        self.assertEqual(doc['learning_topics'],['React'])

if __name__=='__main__':unittest.main()

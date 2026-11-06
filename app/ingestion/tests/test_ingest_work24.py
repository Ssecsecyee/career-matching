import copy,sqlite3,sys,unittest,json
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from work24_export import normalize_list
from ingest_work24 import insert_batch,validated,apply_incremental

class Cursor:
    def __init__(self,db):self.db=db;self.cur=db.cursor()
    def __enter__(self):return self
    def __exit__(self,*args):self.cur.close()
    def execute(self,sql,values=()):self.cur.execute(sql.replace('%s','?'),values)
    def executemany(self,sql,values):self.cur.executemany(sql.replace('%s','?'),values)
    def fetchall(self):return [dict(r) for r in self.cur.fetchall()]
    def fetchone(self):
        row=self.cur.fetchone()
        return dict(row) if row is not None else None
    @property
    def rowcount(self):return self.cur.rowcount
class DB:
    def __init__(self):self.raw=sqlite3.connect(':memory:');self.raw.row_factory=sqlite3.Row
    def cursor(self):return Cursor(self.raw)

def sample():
    return normalize_list('card',{'trprId':'SYNTHETIC','trprDegr':'1','trainstCstId':'0001','title':'Synthetic training','subTitle':'Synthetic provider','titleLink':'https://www.work24.go.kr/test','traStartDate':'2099-12-01'},'2026-11-04T12:00:00+09:00')
class Work24InsertTests(unittest.TestCase):
    def setUp(self):
        self.db=DB();row=sample()
        self.db.raw.execute('CREATE TABLE training_offerings(offering_id INTEGER PRIMARY KEY AUTOINCREMENT,'+','.join('`'+k+'` TEXT' for k in row)+',UNIQUE(source,source_id))')
        self.db.raw.execute('CREATE TABLE search_outbox(entity_type TEXT,entity_id INTEGER,source_version INTEGER,operation TEXT)');self.db.raw.commit()
    def tearDown(self):self.db.raw.close()
    def test_idempotent_insert_outbox_and_preserved_original(self):
        self.assertEqual(insert_batch([sample()],self.db),{'inserted':1,'skipped':0})
        self.assertEqual(insert_batch([sample()],self.db),{'inserted':0,'skipped':1})
        self.assertEqual(self.db.raw.execute('SELECT COUNT(*) FROM search_outbox').fetchone()[0],1)
        checked=validated(sample())
        self.assertIn('list_record',checked['raw_detail']['collection_metadata'])
        self.assertNotIn('list_record',checked['additional_sections']['collection_metadata'])
    def test_rollback_includes_companion_event(self):
        insert_batch([sample()],self.db);self.db.raw.rollback()
        self.assertEqual(self.db.raw.execute('SELECT COUNT(*) FROM training_offerings').fetchone()[0],0)
        self.assertEqual(self.db.raw.execute('SELECT COUNT(*) FROM search_outbox').fetchone()[0],0)
    def test_incremental_card_update_increments_version_and_outbox(self):
        old=sample();insert_batch([old],self.db);self.db.raw.commit()
        raw=copy.deepcopy(old['raw_detail']['collection_metadata']['list_record']);raw['title']='Changed title'
        new=normalize_list('card',raw,'2026-11-06T12:00:00+09:00');new['expected_previous_hash']=old['content_hash']
        self.assertEqual(apply_incremental([new],self.db)['updated'],1)
        stored=dict(self.db.raw.execute('SELECT title,source_version FROM training_offerings').fetchone())
        self.assertEqual(stored['title'],'Changed title');self.assertEqual(int(stored['source_version']),2)
        self.assertEqual(self.db.raw.execute('SELECT COUNT(*) FROM search_outbox').fetchone()[0],2)
        self.assertEqual(apply_incremental([new],self.db)['skipped'],1)
    def test_incremental_rejects_stale_expected_hash_without_writing(self):
        old=sample();insert_batch([old],self.db);self.db.raw.commit()
        raw=copy.deepcopy(old['raw_detail']['collection_metadata']['list_record']);raw['title']='Changed title'
        new=normalize_list('card',raw,'2026-11-06T12:00:00+09:00');new['expected_previous_hash']='stale'
        with self.assertRaises(ValueError):apply_incremental([new],self.db)
        self.assertEqual(self.db.raw.execute('SELECT title FROM training_offerings').fetchone()[0],old['title'])
    def test_incremental_update_and_event_roll_back_together(self):
        old=sample();insert_batch([old],self.db);self.db.raw.commit()
        raw=copy.deepcopy(old['raw_detail']['collection_metadata']['list_record']);raw['title']='Changed title'
        new=normalize_list('card',raw,'2026-11-06T12:00:00+09:00');new['expected_previous_hash']=old['content_hash']
        apply_incremental([new],self.db);self.db.raw.rollback()
        self.assertEqual(self.db.raw.execute('SELECT title FROM training_offerings').fetchone()[0],old['title'])
        self.assertEqual(self.db.raw.execute('SELECT COUNT(*) FROM search_outbox').fetchone()[0],1)
    def test_incremental_preserves_enriched_existing_record(self):
        old=sample();insert_batch([old],self.db);self.db.raw.commit()
        enriched=copy.deepcopy(old['raw_detail']);enriched['collection_metadata']['validation_level']='detail_verified'
        self.db.raw.execute('UPDATE training_offerings SET raw_detail=?',(json.dumps(enriched),));self.db.raw.commit()
        raw=copy.deepcopy(old['raw_detail']['collection_metadata']['list_record']);raw['title']='Changed title'
        new=normalize_list('card',raw,'2026-11-06T12:00:00+09:00');new['expected_previous_hash']=old['content_hash']
        with self.assertRaises(ValueError):apply_incremental([new],self.db)
        self.assertEqual(self.db.raw.execute('SELECT title FROM training_offerings').fetchone()[0],old['title'])
    def test_modified_input_rejected_before_writes(self):
        row=copy.deepcopy(sample());row['content_hash']='invalid'
        with self.assertRaises(ValueError):insert_batch([row],self.db)
        self.assertEqual(self.db.raw.execute('SELECT COUNT(*) FROM training_offerings').fetchone()[0],0)
if __name__=='__main__':unittest.main()

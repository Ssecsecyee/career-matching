import copy,sqlite3,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from work24_export import normalize_list
from ingest_work24 import insert_batch,validated

class Cursor:
    def __init__(self,db):self.db=db;self.cur=db.cursor()
    def __enter__(self):return self
    def __exit__(self,*args):self.cur.close()
    def execute(self,sql,values=()):self.cur.execute(sql.replace('%s','?'),values)
    def executemany(self,sql,values):self.cur.executemany(sql.replace('%s','?'),values)
    def fetchall(self):return [dict(r) for r in self.cur.fetchall()]
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
    def test_modified_input_rejected_before_writes(self):
        row=copy.deepcopy(sample());row['content_hash']='invalid'
        with self.assertRaises(ValueError):insert_batch([row],self.db)
        self.assertEqual(self.db.raw.execute('SELECT COUNT(*) FROM training_offerings').fetchone()[0],0)
if __name__=='__main__':unittest.main()

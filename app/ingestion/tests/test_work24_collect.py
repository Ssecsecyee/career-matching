import json
from datetime import date,datetime,timedelta
from pathlib import Path
import sqlite3
import tempfile
import gzip
from unittest.mock import patch
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from work24_collect import identity, parse, init, save_page, start_state, detail_fingerprint,KST,date_windows
from work24_details import normalize_course
from work24_export import normalize_list,main as export_main
from work24_reconcile import audit

def row():
    return {'trprId':'TEST-1','trprDegr':'01','trainstCstId':'000012','traStartDate':'2099-12-01','title':'Synthetic'}

class Work24InventoryTests(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(':memory:');init(self.db)
    def tearDown(self):self.db.close()
    def save(self,run,item,service='card'):
        self.db.execute('INSERT OR IGNORE INTO buckets(run,service,start,end) VALUES(?,?,?,?)',(run,service,'2099-01-01','2099-12-31'))
        save_page(self.db,run,(service,'2099-01-01','2099-12-31',1),1,[item],'synthetic')
    def test_date_windows_cover_leap_boundary_without_overlap(self):
        windows=list(date_windows(date(2028,2,27),date(2028,3,8),7))
        self.assertEqual(windows,[(date(2028,2,27),date(2028,3,4)),(date(2028,3,5),date(2028,3,8))])
        self.assertEqual(list(date_windows(date(2026,11,4),date(2026,11,4))),[(date(2026,11,4),date(2026,11,4))])
        with self.assertRaises(ValueError):list(date_windows(date(2026,11,4),date(2026,11,3)))

    def test_identity_preserves_round_and_leading_zero(self):
        self.assertEqual(json.loads(identity(row())),['TEST-1','01','000012'])
        with self.assertRaises(ValueError):identity({'trprId':'id'})
    def test_singleton_zero_and_error_responses(self):
        total,rows=parse(b'<HRDNet><scn_cnt>1</scn_cnt><srchList><scn_list><title>X</title></scn_list></srchList></HRDNet>')
        self.assertEqual((total,rows),(1,[{'title':'X'}]))
        self.assertEqual(parse(b'<HRDNet><scn_cnt>0</scn_cnt></HRDNet>'),(0,[]))
        for value in [b'<html/>',b'<HRDNet><error>denied</error></HRDNet>',b'<!DOCTYPE X><HRDNet/>']:
            with self.assertRaises(ValueError):parse(value)
    def test_same_record_across_runs_is_not_new(self):
        self.save('one',row());self.save('two',row())
        self.assertEqual(self.db.execute('SELECT change FROM seen WHERE run=?',('two',)).fetchone()[0],'unchanged')
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM records').fetchone()[0],1)
    def test_services_and_rounds_do_not_collide(self):
        self.save('one',row());self.save('one',row(),'employer')
        other=row();other['trprDegr']='02';self.save('two',other)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM records').fetchone()[0],3)
    def test_detail_revision_changes_queue_but_counter_does_not(self):
        initial=row();self.save('one',initial)
        changed=dict(initial,regCourseMan='999')
        self.assertEqual(detail_fingerprint(initial),detail_fingerprint(changed))
        self.db.execute("UPDATE detail_queue SET status='completed'")
        self.save('two',changed)
        self.assertEqual(self.db.execute('SELECT status FROM detail_queue').fetchone()[0],'completed')
        changed['title']='Revised';self.save('three',changed)
        self.assertEqual(self.db.execute('SELECT status,reason FROM detail_queue').fetchone(),('pending','list_changed'))
    def test_started_unknown_not_queued_or_called_closed(self):
        for run,raw in [('one','2000-01-01'),('two','bad')]:
            item=row();item['traStartDate']=raw;self.save(run,item)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM detail_queue').fetchone()[0],0)
        self.assertEqual(start_state({'traStartDate':'2026-11-04'},date(2026,11,4)),'started')
        self.assertEqual(start_state({},date(2026,11,4)),'unknown')
    def test_unchanged_list_rechecks_expired_detail(self):
        self.save('one',row())
        self.db.execute("UPDATE detail_queue SET status='completed'")
        self.db.execute('INSERT INTO detail_cache VALUES(?,?,?,?,?)',('card',identity(row()),detail_fingerprint(row()),(datetime.now(KST)-timedelta(days=4)).isoformat(),'synthetic'))
        self.save('two',row())
        self.assertEqual(self.db.execute('SELECT status,reason FROM detail_queue').fetchone(),('pending','recheck_due'))

    def test_normalization_keeps_missing_application_dates_and_money_unknown(self):
        item=dict(row(),titleLink='https://www.work24.go.kr/test',subTitle='Synthetic institution',ncsCd='08030209',traEndDate='2099-12-31')
        base={'trprId':item['trprId'],'trprDegr':item['trprDegr'],'ncsCd':item['ncsCd'],'ncsNm':'Synthetic classification'}
        schedule={'scn_list':dict(base,trStaDt='2099-12-01',trEndDt='2099-12-31')}
        value=normalize_course('card',item,{'inst_base_info':base},schedule,'2026-11-04T12:00:00+09:00')
        self.assertIsNone(value['application_deadline'])
        self.assertIsNone(value['tuition'])
        self.assertEqual(value['recruitment_status'],'unknown')
        self.assertFalse(value['additional_sections']['recommendation_eligible'])
        self.assertEqual(value['additional_sections']['date_precision']['starts_at']['raw'],'2099-12-01')
        bad={'scn_list':dict(base,trStaDt='2099-12-02',trEndDt='2099-12-31')}
        with self.assertRaises(ValueError):normalize_course('card',item,{'inst_base_info':base},bad,'2026-11-04T12:00:00+09:00')

    def test_list_counters_do_not_change_common_education_content(self):
        item=dict(row(),titleLink='https://www.work24.go.kr/test',subTitle='Synthetic institution')
        a=normalize_list('card',item,'2026-11-04T12:00:00+09:00')
        b=normalize_list('card',dict(item,regCourseMan='999'),'2026-11-04T13:00:00+09:00')
        self.assertEqual(a['source_id'],b['source_id'])
        self.assertEqual(a['content_hash'],b['content_hash'])
        self.assertEqual(b['raw_detail']['collection_metadata']['list_record']['regCourseMan'],'999')

    def test_export_skips_existing_db_hash_without_external_calls(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);catalog=root/'catalog.sqlite3';conn=sqlite3.connect(catalog);init(conn)
            item=dict(row(),titleLink='https://www.work24.go.kr/test',subTitle='Synthetic institution')
            conn.execute("INSERT INTO runs VALUES('run','2099-01-01','2099-12-31','collected_pending_reconciliation')")
            conn.execute("INSERT INTO buckets(run,service,start,end) VALUES('run','card','2099-01-01','2099-12-31')")
            save_page(conn,'run',('card','2099-01-01','2099-12-31',1),1,[item],'synthetic');conn.commit();conn.close()
            normalized=normalize_list('card',item,datetime.now(KST).isoformat())
            inventory=root/'inventory.json';inventory.write_text(json.dumps({'source':'goyong24_training','generated_at':datetime.now(KST).isoformat(),'records':[{'source_id':normalized['source_id'],'content_hash':normalized['content_hash']}]}),encoding='utf-8')
            with patch.object(sys,'argv',['work24_export','--catalog',str(catalog),'--run-id','run','--output',str(root/'out'),'--db-inventory',str(inventory)]):self.assertEqual(export_main(),0)
            report=json.loads((root/'out/report.json').read_text(encoding='utf-8'))
            self.assertEqual(report['db_unchanged'],1)
            self.assertEqual((root/'out/training.future.normalized.jsonl').read_text(encoding='utf-8'),'')

    def test_audit_detects_duplicate_count_and_preserves_source_state(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);catalog=root/'catalog.sqlite3';conn=sqlite3.connect(catalog);init(conn)
            conn.execute("INSERT INTO runs VALUES('run','2099-01-01','2099-12-31','collected_pending_reconciliation')")
            conn.execute("INSERT INTO buckets(run,service,start,end,status) VALUES('run','card','2099-01-01','2099-12-31','done')")
            save_page(conn,'run',('card','2099-01-01','2099-12-31',1),2,[row(),row()],'synthetic');conn.commit();conn.close()
            folder=root/'pages/card/2099-01-01_2099-12-31';folder.mkdir(parents=True)
            record='<scn_list>'+''.join('<'+k+'>'+v+'</'+k+'>' for k,v in row().items())+'</scn_list>'
            with gzip.open(folder/'1.xml.gz','wt',encoding='utf-8') as stream:stream.write('<HRDNet><scn_cnt>2</scn_cnt><srchList>'+record+record+'</srchList></HRDNet>')
            report=audit(catalog,root,'run')
            self.assertEqual(report['services']['card']['unique'],1)
            self.assertEqual(report['services']['card']['duplicate_rows'],1)
            self.assertIn('provider_count_reconciliation_required',report['warnings'])
            self.assertFalse(report['frozen_snapshot'])

    def test_transaction_rollback_leaves_no_partial_record(self):
        self.db.commit()
        with self.assertRaises(RuntimeError):
            with self.db:self.save('one',row());raise RuntimeError('synthetic')
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM records').fetchone()[0],0)

if __name__=='__main__':unittest.main()


class Work24ServiceScopeTests(unittest.TestCase):
    def test_card_only_run_does_not_require_or_call_other_service_keys(self):
        import work24_collect
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);env=root/'keys.env';env.write_text('WORK24_CARD_TRAINING_API_KEY=synthetic')
            args=['work24_collect.py','--env-path',str(env),'--output',str(root/'run'),'--start','2099-01-01','--end','2099-01-01','--services','card']
            with patch.object(sys,'argv',args),patch.object(work24_collect,'fetch',return_value=b'<HRDNet><scn_cnt>0</scn_cnt><srchList/></HRDNet>') as fetch,patch.object(work24_collect.time,'sleep'):
                self.assertEqual(work24_collect.main(),0)
                self.assertEqual(fetch.call_args.args[0],'card');self.assertEqual(fetch.call_count,1)
            db=sqlite3.connect(root/'run/catalog.sqlite3')
            self.assertEqual(db.execute('SELECT DISTINCT service FROM buckets').fetchall(),[('card',)])
            db.close()

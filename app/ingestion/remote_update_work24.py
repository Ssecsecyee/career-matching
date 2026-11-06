"""Validated card-only incremental import; backup and existing Outbox consumer."""
import gzip,json,os,sys,time
from pathlib import Path
BASE=Path('/opt/career');RUN=Path(__file__).resolve().parent
sys.path.insert(0,str(RUN/'code'));sys.path.insert(0,str(RUN))
from remote_import_work24 import backup,es
from ingest_work24 import validated,apply_incremental
from src.services.training_dates import start_visibility

def batches():
    with gzip.open(RUN/'training.jsonl.gz','rt',encoding='utf-8') as stream:
        rows=[]
        for line in stream:
            rows.append(json.loads(line))
            if len(rows)==200:yield rows;rows=[]
        if rows:yield rows

def main():
    os.umask(0o077)
    report={'status':'starting','inserted':0,'updated':0,'skipped':0,'bedrock_calls':0,'stage':'preflight'}
    conn=None
    try:
        import pymysql
        values=dict(line.split('=',1) for line in (BASE/'mysql-root.env').read_text().splitlines() if '=' in line)
        conn=pymysql.connect(host='127.0.0.1',port=3308,user='root',password=values['MYSQL_ROOT_PASSWORD'],database='career_matching',charset='utf8mb4',cursorclass=pymysql.cursors.DictCursor,autocommit=True,connect_timeout=5,read_timeout=120,write_timeout=120,init_command="SET time_zone='+00:00'")
        seen=set()
        for rows in batches():
            for raw in rows:
                row=validated(raw)
                if row['raw_detail']['collection_metadata']['service']!='card' or row['source_id'] in seen:raise ValueError('invalid_card_scope_or_duplicate')
                seen.add(row['source_id'])
        report['input_records']=len(seen);report['stage']='backup';report['backup']=backup();report['backup_gzip_verified']=True
        report['stage']='apply_incremental'
        with gzip.open(RUN/'before_changed.jsonl.gz','wt',encoding='utf-8') as journal:
            for rows in batches():
                ids=[r['source_id'] for r in rows]
                with conn.cursor() as cur:
                    cur.execute('SELECT * FROM training_offerings WHERE source=%s AND source_id IN ('+','.join(['%s']*len(ids))+')',['goyong24_training']+ids)
                    for row in cur.fetchall():journal.write(json.dumps(row,ensure_ascii=False,default=str)+'\n')
                conn.begin()
                try:
                    counts=apply_incremental(rows,conn);conn.commit()
                except Exception:conn.rollback();raise
                for key in counts:report[key]+=counts[key]
        report['stage']='expire_training_index'
        closed=[]
        with conn.cursor() as cur:
            cur.execute("SELECT offering_id,source_version,starts_at,additional_sections FROM training_offerings WHERE source='goyong24_training' AND source_id LIKE 'card:%'")
            for row in cur.fetchall():
                if not start_visibility(row)[0]:closed.append((row['offering_id'],row['source_version']))
            if closed:
                cur.executemany("INSERT IGNORE INTO search_outbox(entity_type,entity_id,source_version,operation) VALUES('training',%s,%s,'close')",closed)
        report['started_or_unknown_candidates']=len(closed)
        from sync_outbox import Consumer,Engine
        class VisibleEngine(Engine):
            def apply(self,kind,row,remove=False):
                if kind=='training' and str(row.get('source_id','')).startswith('card:'):
                    remove=remove or not start_visibility(row)[0]
                return super().apply(kind,row,remove=remove)
        settings=json.loads((BASE/'search-sync.json').read_text())
        consumer=Consumer(conn,VisibleEngine(settings['jobs_alias'],settings['training_alias']),include_condition_reviews=settings.get('enable_condition_reviews') is True)
        report['stage']='drain_outbox'
        processed=0
        for _ in range(1200):
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) AS n FROM search_outbox o JOIN training_offerings t ON t.offering_id=o.entity_id WHERE o.entity_type='training' AND t.source='goyong24_training' AND t.source_id LIKE 'card:%' AND o.processed_at IS NULL")
                pending=cur.fetchone()['n']
            if not pending:break
            outcome=consumer.run();processed+=outcome.get('processed',0)
            if outcome.get('failed'):raise RuntimeError('outbox_consumer_failed')
            if outcome.get('status')=='busy':time.sleep(1)
        else:raise RuntimeError('outbox_drain_limit')
        report['stage']='verify_index'
        es('POST','/career-training-read/_refresh')
        report.update(status='success',outbox_pending=0,outbox_processed=processed)
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS n FROM training_offerings WHERE source='goyong24_training' AND source_id LIKE 'card:%'")
            report['card_database_total']=cur.fetchone()['n']
        report['card_index_total']=es('POST','/career-training-read/_count',{'query':{'prefix':{'source_id':'card:'}}})['count']
        report['started_card_index_total']=es('POST','/career-training-read/_count',{'query':{'bool':{'filter':[{'prefix':{'source_id':'card:'}},{'range':{'training_start_at':{'lte':'now'}}}]}}})['count']
        if report['started_card_index_total']:raise RuntimeError('expired_card_documents_remain')
        report['stage']='complete'
    except Exception as exc:
        if conn:conn.rollback()
        report.update(status='failed',error_type=type(exc).__name__,driver_code=exc.args[0] if exc.args and type(exc.args[0]) is int else None)
    finally:
        if conn:conn.close()
        (RUN/'result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
        print(json.dumps(report,ensure_ascii=False),flush=True)
    return 0 if report['status']=='success' else 1
if __name__=='__main__':raise SystemExit(main())

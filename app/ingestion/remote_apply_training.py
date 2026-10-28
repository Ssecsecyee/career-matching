"""SSM entry: verified backup, temporary writer, transaction, readback tests."""
import gzip
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
from datetime import datetime,timezone
from ingest_training import prepare,insert_new

def main():
    report={'production_applied':False};root=None;writer=None;created=False;stage='prepare'
    base=Path('/opt/career');os.umask(0o077)
    try:
        records=json.loads(Path(sys.argv[1]).read_text(encoding='utf-8-sig'));rows=prepare(records)
        import pymysql
        values=dict(line.split('=',1) for line in (base/'mysql-root.env').read_text().splitlines())
        options=dict(host='127.0.0.1',port=3308,user='root',password=values['MYSQL_ROOT_PASSWORD'],database='career_matching',charset='utf8mb4',autocommit=True,cursorclass=pymysql.cursors.DictCursor,connect_timeout=5,read_timeout=30,write_timeout=30,init_command="SET time_zone='+00:00'")
        root=pymysql.connect(**options)
        with root.cursor() as cur:
            cur.execute('SELECT job_id,source_version,content_hash FROM job_postings ORDER BY job_id');jobs_before=cur.fetchall()
            cur.execute('SELECT offering_id,content_hash FROM training_offerings ORDER BY offering_id');before=cur.fetchall()
            cur.execute("SELECT COUNT(*) AS n FROM search_outbox WHERE entity_type='training'");outbox_before=cur.fetchone()['n']
        stage='backup'
        if shutil.disk_usage(base).free<256*1024*1024:raise ValueError('backup_space')
        folder=base/'backups';folder.mkdir(mode=0o700,exist_ok=True)
        backup=folder/('before-training-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+secrets.token_hex(3)+'.sql.gz')
        with backup.open('xb') as output:
            proc=subprocess.Popen(['docker','exec','career-mysql','sh','-c','MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysqldump --user=root --single-transaction --set-gtid-purged=OFF career_matching'],stdout=subprocess.PIPE,stderr=subprocess.PIPE)
            with gzip.GzipFile(fileobj=output,mode='wb') as compressed:shutil.copyfileobj(proc.stdout,compressed)
            proc.stdout.close();proc.stderr.read();proc.stderr.close()
            if proc.wait()!=0:raise RuntimeError('backup_failed')
        with gzip.open(backup,'rb') as handle:
            size=0
            for chunk in iter(lambda:handle.read(1024*1024),b''):size+=len(chunk)
        if size<1000:raise RuntimeError('backup_empty')
        report.update(backup_path=str(backup),backup_sha256=hashlib.sha256(backup.read_bytes()).hexdigest(),backup_gzip_verified=True)
        stage='temporary_writer';account='training_batch_'+secrets.token_hex(5)
        options.update(user=account,password=secrets.token_hex(32))
        with root.cursor() as cur:
            cur.execute("CREATE USER %s@'%%' IDENTIFIED BY %s",(account,options['password']));created=True
            cur.execute("GRANT SELECT,INSERT ON career_matching.training_offerings TO %s@'%%'",(account,))
            cur.execute("GRANT INSERT ON career_matching.search_outbox TO %s@'%%'",(account,))
        options['autocommit']=False;writer=pymysql.connect(**options)
        stage='rollback_test';writer.begin();preview=insert_new(rows,writer);writer.rollback()
        with root.cursor() as cur:
            cur.execute('SELECT offering_id,content_hash FROM training_offerings ORDER BY offering_id')
            if cur.fetchall()!=before:raise RuntimeError('rollback_test_failed')
            cur.execute("SELECT COUNT(*) AS n FROM search_outbox WHERE entity_type='training'")
            if cur.fetchone()['n']!=outbox_before:raise RuntimeError('outbox_rollback_failed')
        report['rollback_test_passed']=True
        stage='insert';writer.begin();result=insert_new(rows,writer)
        stage='idempotency_test';replay=insert_new(rows,writer)
        if replay['inserted']!=0 or replay['skipped']!=len(rows):raise RuntimeError('duplicate_test_failed')
        # Verify stored content, dates, JSON, and companion events before committing.
        ids=[r['source_id'] for r in rows];placeholders=','.join(['%s']*len(ids))
        with writer.cursor() as cur:
            cur.execute('SELECT * FROM training_offerings WHERE source=%s AND source_id IN ('+placeholders+')',['boottent']+ids)
            stored={r['source_id']:r for r in cur.fetchall()}
            for row in rows:
                actual=stored[row['source_id']]
                if actual['title']!=row['title'] or actual['content_hash']!=row['content_hash'] or actual['recruitment_status']!='unknown':raise RuntimeError('roundtrip_failed')
                if actual['starts_at'] is not None or not json.loads(actual['additional_sections'])['date_precision']:raise RuntimeError('date_precision_failed')
                if json.loads(actual['additional_sections'])['recommendation_eligible'] is not False:raise RuntimeError('snapshot_exclusion_failed')
        writer.commit();report['production_applied']=True
        stage='readback'
        with root.cursor() as cur:
            cur.execute('SELECT job_id,source_version,content_hash FROM job_postings ORDER BY job_id')
            if cur.fetchall()!=jobs_before:raise RuntimeError('existing_jobs_changed')
            cur.execute('SELECT offering_id,content_hash FROM training_offerings ORDER BY offering_id');after=cur.fetchall()
            if not all(item in after for item in before) or len(after)!=len(before)+result['inserted']:raise RuntimeError('existing_training_changed')
            cur.execute("SELECT COUNT(*) AS n FROM search_outbox WHERE entity_type='training'");outbox_after=cur.fetchone()['n']
            if outbox_after-outbox_before!=result['inserted']:raise RuntimeError('outbox_count_failed')
            topic_counts={}
            for topic in ['React','RAG']:
                cur.execute('SELECT COUNT(*) AS n FROM training_offerings WHERE source=%s AND source_id IN ('+placeholders+') AND JSON_CONTAINS(learning_topics,JSON_QUOTE(%s))',['boottent']+ids+[topic]);topic_counts[topic]=cur.fetchone()['n']
            if not all(topic_counts.values()):raise RuntimeError('topic_query_failed')
            cur.execute('SELECT COUNT(*) AS n FROM training_offerings WHERE source=%s AND source_id IN ('+placeholders+") AND recruitment_status='active'",['boottent']+ids)
            if cur.fetchone()['n']!=0:raise RuntimeError('unverified_sample_exposed')
        report.update(status='success',training_before=len(before),training_after=len(after),inserted=result['inserted'],skipped=result['skipped'],offering_ids=result['offering_ids'],outbox_added=outbox_after-outbox_before,existing_jobs_unchanged=True,existing_training_unchanged=True,idempotency_test_passed=True,date_precision_test_passed=True,topic_query_counts=topic_counts,active_recommendable_samples=0,chatbot_training_connected=False)
    except Exception as exc:
        if writer:writer.rollback()
        report.update(status='failed',failed_stage=stage,error_type=type(exc).__name__,error_code=exc.args[0] if exc.args and isinstance(exc.args[0],int) else None)
    finally:
        if writer:writer.close()
        if created and root:
            try:
                with root.cursor() as cur:cur.execute("DROP USER %s@'%%'",(account,))
                report['temporary_writer_removed']=True
            except Exception:report.update(status='cleanup_required',temporary_writer_removed=False)
        if root:root.close()
        Path(__file__).with_name('result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps(report,ensure_ascii=False))
    return 0 if report.get('status')=='success' else 1

if __name__=='__main__':raise SystemExit(main())

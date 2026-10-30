"""SSM-admin entry point: back up DB and insert a validated, new-only sample.
Only invoke for an explicitly reviewed manifest with a declared count of 1..100.
"""
from datetime import datetime, timezone
import gzip
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import sys

from incremental_jumpit import prepare, ingest


def main():
    base=Path('/opt/career')
    root=None;writer=None;created=False;account=None;stage='validate';applied=False
    report={'production_applied':False}
    report_path=Path(__file__).resolve().parent/'apply-result.json'
    try:
        rows,_=prepare(Path(sys.argv[1]))
        expected=int(sys.argv[2]) if len(sys.argv)>2 else 10
        if not 1<=expected<=100 or len(rows)!=expected:raise ValueError('unexpected_batch_count')
        if any(row['source']!='jumpit' for row in rows):raise ValueError('unexpected_source')
        if shutil.disk_usage(base).free<256*1024*1024:raise ValueError('insufficient_backup_disk_space')
        stage='backup'
        backup_dir=base/'backups';backup_dir.mkdir(mode=0o700,exist_ok=True);os.chmod(backup_dir,0o700)
        backup=backup_dir/('before-jumpit-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+secrets.token_hex(3)+'.sql.gz')
        fd=os.open(backup,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,'wb') as output:
            process=subprocess.Popen(['docker','exec','career-mysql','sh','-c',
                'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysqldump --user=root --single-transaction --set-gtid-purged=OFF career_matching'],stdout=subprocess.PIPE,stderr=subprocess.PIPE)
            with gzip.GzipFile(fileobj=output,mode='wb') as compressed:shutil.copyfileobj(process.stdout,compressed)
            process.stdout.close()
            error=process.stderr.read();process.stderr.close()
            if process.wait()!=0:raise RuntimeError('database_backup_failed')
        with gzip.open(backup,'rb') as handle:
            total=0
            while True:
                chunk=handle.read(1024*1024)
                if not chunk:break
                total+=len(chunk)
        if total<1000:raise RuntimeError('database_backup_empty')
        report.update(backup_path=str(backup),backup_bytes=backup.stat().st_size,
            backup_sha256=hashlib.sha256(backup.read_bytes()).hexdigest(),backup_gzip_verified=True)
        stage='database_preflight'
        import pymysql
        values=dict(line.split('=',1) for line in (base/'mysql-root.env').read_text().splitlines())
        options={'host':'127.0.0.1','port':3308,'user':'root','password':values['MYSQL_ROOT_PASSWORD'],
            'database':'career_matching','charset':'utf8mb4','autocommit':True,'cursorclass':pymysql.cursors.DictCursor,
            'connect_timeout':5,'read_timeout':30,'write_timeout':30,'init_command':"SET time_zone='+00:00'"}
        root=pymysql.connect(**options)
        with root.cursor() as cur:
            cur.execute('SELECT job_id,source_version,content_hash FROM job_postings ORDER BY job_id')
            before={item['job_id']:(item['source_version'],item['content_hash']) for item in cur.fetchall()}
            cur.execute('SELECT COUNT(*) AS n FROM search_outbox');outbox_before=cur.fetchone()['n']
        preview=ingest(rows,root,apply=False,require_new=True)
        if preview['counts']!={'inserted':expected}:raise ValueError('unexpected_preview')
        stage='temporary_writer'
        account='ingest_batch_'+secrets.token_hex(6)
        password=secrets.token_hex(32)
        with root.cursor() as cur:
            cur.execute("CREATE USER %s@'%%' IDENTIFIED BY %s",(account,password));created=True
            cur.execute("GRANT SELECT,INSERT,UPDATE ON career_matching.job_postings TO %s@'%%'",(account,))
            cur.execute("GRANT INSERT ON career_matching.search_outbox TO %s@'%%'",(account,))
        options.update(user=account,password=password)
        writer=pymysql.connect(**options)
        stage='apply'
        result=ingest(rows,writer,apply=True,require_new=True)
        applied=True;report['production_applied']=True
        writer.close();writer=None
        stage='verify'
        identities=[row['source_id'] for row in rows]
        with root.cursor() as cur:
            cur.execute('SELECT job_id,source_version,content_hash FROM job_postings ORDER BY job_id')
            after={item['job_id']:(item['source_version'],item['content_hash']) for item in cur.fetchall()}
            if not all(after.get(key)==value for key,value in before.items()):raise RuntimeError('existing_job_integrity_check_failed')
            if len(after)!=len(before)+expected:raise RuntimeError('job_count_verification_failed')
            cur.execute('SELECT source_id,job_id,source_version,recruitment_status,application_notes,additional_sections FROM job_postings WHERE source=%s AND source_id IN ('+','.join(['%s']*len(identities))+')',['jumpit']+identities)
            inserted=cur.fetchall()
            if len(inserted)!=expected:raise RuntimeError('inserted_id_verification_failed')
            cur.execute('SELECT COUNT(*) AS n FROM search_outbox');outbox_after=cur.fetchone()['n']
            job_ids=[item['job_id'] for item in inserted]
            cur.execute("SELECT COUNT(*) AS n FROM search_outbox WHERE entity_type='job' AND entity_id IN ("+','.join(['%s']*len(job_ids))+')',job_ids)
            if cur.fetchone()['n']!=expected:raise RuntimeError('outbox_verification_failed')
        report.update(status='success',jobs_before=len(before),jobs_after=len(after),inserted=expected,
            source_ids=identities,existing_jobs_unchanged=True,outbox_added=outbox_after-outbox_before,
            combined_notes=sum(bool(item['application_notes']) for item in inserted),
            unknown_statuses=sum(item['recruitment_status']=='unknown' for item in inserted),
            date_only_preserved=sum(json.loads(item['additional_sections'] or '{}').get('page_extraction',{}).get('deadline',{}).get('precision')=='date_only' for item in inserted))
    except Exception as exc:
        code=exc.args[0] if exc.args and type(exc.args[0]) is int else type(exc).__name__
        report.update(status='failed',failed_stage=stage,error_code=code,production_applied=applied)
    finally:
        if writer:writer.close()
        if created and root:
            try:
                with root.cursor() as cur:cur.execute("DROP USER %s@'%%'",(account,))
                report['temporary_writer_removed']=True
            except Exception:
                report.update(temporary_writer_removed=False,status='cleanup_required')
        if root:root.close()
        report_path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');os.chmod(report_path,0o600)
        print(json.dumps(report,ensure_ascii=False))
    return 0 if report.get('status')=='success' else 1

if __name__=='__main__':raise SystemExit(main())

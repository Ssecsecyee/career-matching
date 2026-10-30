"""Run only from the verified SSM deployment package; no secrets in output."""
from pathlib import Path
from datetime import datetime,timezone
import compileall,gzip,hashlib,json,os,pwd,secrets,shutil,subprocess,sys,time

BASE=Path('/opt/career')
RELEASE=Path(__file__).resolve().parent
REPORT=RELEASE/'install-result.json'


def command(args,**kwargs):
    return subprocess.run(args,check=True,capture_output=True,text=True,**kwargs)


def main():
    os.umask(0o077)
    report={'status':'starting','stage':'preflight','model_calls':0}
    old_app=BASE/'app';old_config=BASE/'config.json'
    owner=pwd.getpwnam('career')
    staged=RELEASE/'staged-app';backup_app=RELEASE/'previous-app';backup_config=RELEASE/'previous-config.json'
    account=None;root=None;switched=False;config_changed=False;timer=False
    try:
        if (BASE/'search-sync.json').exists():raise RuntimeError('existing_sync_installation')
        sys.path.insert(0,str(RELEASE/'app/backend'))
        sys.path.insert(0,str(RELEASE/'app/ingestion/search_index'))
        from sync_outbox import Consumer,Engine
        if not compileall.compile_dir(str(RELEASE/'app'),quiet=2):raise RuntimeError('compile_failed')
        engine=Engine('career-jobs-read','career-training-read');engine.verify_aliases()
        if shutil.disk_usage(BASE).free<1024**3:raise RuntimeError('insufficient_backup_space')
        report['stage']='backup'
        destination=BASE/'backups'/('before-search-sync-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'.sql.gz')
        with os.fdopen(os.open(destination,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600),'wb') as out:
            process=subprocess.Popen(['docker','exec','career-mysql','sh','-c','MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysqldump --user=root --single-transaction --set-gtid-purged=OFF career_matching'],stdout=subprocess.PIPE,stderr=subprocess.DEVNULL)
            with gzip.GzipFile(fileobj=out,mode='wb') as packed:shutil.copyfileobj(process.stdout,packed)
            if process.wait()!=0:raise RuntimeError('backup_failed')
        size=0
        with gzip.open(destination,'rb') as handle:
            while True:
                chunk=handle.read(1048576)
                if not chunk:break
                size+=len(chunk)
        if size<1000:raise RuntimeError('empty_backup')
        report['backup']={'file':str(destination),'sha256':hashlib.sha256(destination.read_bytes()).hexdigest(),'gzip_verified':True}
        import pymysql
        values=dict(line.split('=',1) for line in (BASE/'mysql-root.env').read_text().splitlines() if '=' in line)
        options=dict(host='127.0.0.1',port=3308,user='root',password=values['MYSQL_ROOT_PASSWORD'],database='career_matching',charset='utf8mb4',autocommit=True,cursorclass=pymysql.cursors.DictCursor,connect_timeout=5,read_timeout=30,write_timeout=30,init_command="SET time_zone='+00:00'")
        root=pymysql.connect(**options)
        def fingerprint():
            with root.cursor() as cur:
                cur.execute('SELECT job_id,source_version,content_hash,recruitment_status,deadline_at FROM job_postings ORDER BY job_id')
                jobs=cur.fetchall()
                cur.execute('SELECT offering_id,source_version,content_hash,recruitment_status FROM training_offerings ORDER BY offering_id')
                training=cur.fetchall()
            return {'jobs':len(jobs),'training':len(training),'hash':hashlib.sha256(json.dumps([jobs,training],sort_keys=True,default=str).encode()).hexdigest()}
        original=fingerprint()
        report['stage']='least_privilege_account'
        account='career_search_'+secrets.token_hex(5);password=secrets.token_hex(32)
        with root.cursor() as cur:
            cur.execute("CREATE USER %s@'%%' IDENTIFIED BY %s",(account,password))
            for table in ('job_postings','training_offerings'):
                cur.execute('GRANT SELECT ON career_matching.'+table+" TO %s@'%%'",(account,))
            cur.execute("GRANT SELECT,INSERT ON career_matching.search_outbox TO %s@'%%'",(account,))
            cur.execute("GRANT UPDATE (processed_at,attempt_count,last_error) ON career_matching.search_outbox TO %s@'%%'",(account,))
        settings={'user':account,'password':password,'database':'career_matching','port':3308,'jobs_alias':'career-jobs-read','training_alias':'career-training-read'}
        config=BASE/'search-sync.json';config.write_text(json.dumps(settings));config.chmod(0o600)
        sync=pymysql.connect(**dict(options,user=account,password=password))
        try:
            # Reconcile the initial full snapshot and existing historical outbox.
            # Retain source rows and their versions; only add missing queue events.
            sync.begin()
            with sync.cursor() as cur:
                cur.execute("INSERT IGNORE INTO search_outbox(entity_type,entity_id,source_version,operation) SELECT 'job',job_id,source_version,'upsert' FROM job_postings")
                cur.execute("INSERT IGNORE INTO search_outbox(entity_type,entity_id,source_version,operation) SELECT 'training',offering_id,source_version,'upsert' FROM training_offerings")
            sync.commit()
            report['stage']='initial_sync'
            passes=[]
            for _ in range(12):
                value=Consumer(sync,engine).run();passes.append(value)
                if value.get('failed'):raise RuntimeError('initial_sync_failed')
                if value.get('pending')==0:break
            else:raise RuntimeError('initial_sync_not_drained')
            report['initial_sync']=passes
        finally:sync.close()
        for alias in engine.aliases.values():engine.request('POST','/'+alias+'/_refresh')
        if fingerprint()!=original:raise RuntimeError('source_rows_changed')
        report['source_rows_unchanged']=original
        report['stage']='worker_code'
        shutil.copytree(old_app,staged,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
        shutil.copytree(RELEASE/'app/backend/src',staged/'src',dirs_exist_ok=True)
        for name in ('worker.py','server_admin.py'):shutil.copy2(RELEASE/'app/backend'/name,staged/name)
        for path in [staged,*staged.rglob('*')]:
            os.chown(path,owner.pw_uid,owner.pw_gid)
            if path.is_dir():path.chmod(0o755)
            elif path.suffix=='.py':path.chmod(0o644)
        shutil.copy2(old_config,backup_config)
        config_values=json.loads(old_config.read_text())
        config_values.update(JOB_SEARCH_BACKEND='elasticsearch',TRAINING_SEARCH_BACKEND='elasticsearch',ELASTICSEARCH_URL='http://127.0.0.1:19200',ELASTICSEARCH_INDEX='career-jobs-read',ELASTICSEARCH_TRAINING_INDEX='career-training-read')
        command(['systemctl','stop','career-worker'])
        old_app.rename(backup_app);switched=True;staged.rename(old_app)
        replacement=BASE/'config.search-next.json';replacement.write_text(json.dumps(config_values));replacement.chmod(0o600);os.chown(replacement,owner.pw_uid,owner.pw_gid);replacement.replace(old_config);config_changed=True
        command(['systemctl','start','career-worker']);time.sleep(3)
        command(['systemctl','is-active','--quiet','career-worker'])
        report['stage']='search_checks'
        verification=command(['/opt/career/venv/bin/python',str(RELEASE/'verify_sync_remote.py')])
        report['search_checks']=json.loads(verification.stdout)
        report['stage']='timer'
        service='''[Unit]
Description=Career MySQL Outbox to loopback Elasticsearch
After=docker.service network-online.target
[Service]
Type=oneshot
User=root
Environment=PYTHONDONTWRITEBYTECODE=1
ExecStart=/opt/career/venv/bin/python SCRIPT --config /opt/career/search-sync.json
TimeoutStartSec=240
MemoryMax=256M
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
PrivateTmp=true
'''.replace('SCRIPT',str(RELEASE/'app/ingestion/search_index/sync_outbox.py'))
        Path('/etc/systemd/system/career-search-sync.service').write_text(service)
        Path('/etc/systemd/system/career-search-sync.timer').write_text('''[Unit]
Description=Poll career search outbox every minute after each run
[Timer]
OnBootSec=60
OnUnitInactiveSec=60
AccuracySec=5
Unit=career-search-sync.service
[Install]
WantedBy=timers.target
''')
        command(['systemctl','daemon-reload'])
        command(['systemctl','enable','--now','career-search-sync.timer']);timer=True
        command(['systemctl','start','career-search-sync.service'])
        command(['systemctl','is-active','--quiet','career-search-sync.timer'])
        report.update(status='installed',stage='complete',worker_search_backend='elasticsearch',timer_active=True)
    except Exception as exc:
        if timer:subprocess.run(['systemctl','disable','--now','career-search-sync.timer'],capture_output=True)
        if switched:
            subprocess.run(['systemctl','stop','career-worker'],capture_output=True)
            if old_app.exists():old_app.rename(RELEASE/'failed-app')
            backup_app.rename(old_app)
        if config_changed:
            shutil.copy2(backup_config,old_config)
            os.chown(old_config,owner.pw_uid,owner.pw_gid);old_config.chmod(0o600)
        if switched:subprocess.run(['systemctl','start','career-worker'],capture_output=True)
        if account and root:
            with root.cursor() as cur:cur.execute("DROP USER IF EXISTS %s@'%%'",(account,))
            (BASE/'search-sync.json').unlink(missing_ok=True)
        report.update(status='failed',error_type=type(exc).__name__,worker_rollback_attempted=switched)
    finally:
        if root:root.close()
        REPORT.write_text(json.dumps(report,indent=2));REPORT.chmod(0o600)
    print(json.dumps(report),flush=True)
    return 0 if report['status']=='installed' else 1

if __name__=='__main__':raise SystemExit(main())

"""Additive condition-review connection; invoked only from a verified SSM bundle."""
import compileall,gzip,hashlib,json,os,secrets,shutil,subprocess,sys,time
from pathlib import Path
BASE=Path('/opt/career')
RELEASE=Path(__file__).resolve().parents[2]
UNIT=Path('/etc/systemd/system/career-search-sync.service')
SYNC=BASE/'search-sync.json'
WRITER=BASE/'condition-review-db.json'
MARKER=BASE/'condition-review-install.json'

def command(args):return subprocess.run(args,check=True,capture_output=True,text=True,timeout=120)
def write_protected(path,value,original=None):
    temporary=path.with_name(path.name+'.condition-next')
    temporary.write_text(json.dumps(value,ensure_ascii=False));temporary.chmod(0o600)
    if original:os.chown(temporary,original.st_uid,original.st_gid)
    temporary.replace(path)
def allowed_user(value):
    if not isinstance(value,str) or not value or not value.isascii() or any(not (c.isalnum() or c=='_') for c in value):raise ValueError('Invalid database account identifier')
    return value

def main():
    os.umask(0o077)
    report={'status':'starting','stage':'preflight','model_calls':0}
    root=None;account=None;created=False;timer_stopped=False;changed=False;grants=[]
    settings_original=None;unit_original=None
    try:
        if MARKER.exists() or WRITER.exists():raise ValueError('Condition connection already exists; inspect before retry')
        if not SYNC.is_file() or not UNIT.is_file():raise ValueError('Existing search synchronization required')
        if shutil.disk_usage(BASE).free<512*1024*1024:raise ValueError('Insufficient backup space')
        settings_original=SYNC.read_bytes();sync_stat=SYNC.stat();settings=json.loads(settings_original)
        unit_original=UNIT.read_bytes();unit=unit_original.decode()
        if sum(line.startswith('ExecStart=') for line in unit.splitlines())!=1:raise ValueError('Unexpected service definition')
        if not compileall.compile_dir(str(RELEASE/'app'),quiet=2):raise ValueError('Invalid package code')
        sys.path.insert(0,str(RELEASE/'app/backend'));sys.path.insert(0,str(RELEASE/'app/ingestion/search_index'))
        from sync_outbox import Engine
        engine=Engine('career-jobs-read','career-training-read');engine.verify_aliases()
        report['stage']='backup'
        backup=BASE/'backups'/('before-condition-reviews-'+RELEASE.name+'.sql.gz')
        backup.parent.mkdir(mode=0o700,exist_ok=True)
        with os.fdopen(os.open(backup,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600),'wb') as out:
            process=subprocess.Popen(['docker','exec','career-mysql','sh','-c','MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysqldump --user=root --single-transaction --set-gtid-purged=OFF career_matching'],stdout=subprocess.PIPE,stderr=subprocess.DEVNULL)
            with gzip.GzipFile(fileobj=out,mode='wb') as packed:shutil.copyfileobj(process.stdout,packed)
            process.stdout.close()
            if process.wait()!=0:raise RuntimeError('Backup failed')
        size=0
        with gzip.open(backup,'rb') as handle:
            while True:
                data=handle.read(1048576)
                if not data:break
                size+=len(data)
        if size<1000:raise RuntimeError('Empty backup')
        report.update(backup_verified=True,backup_bytes=backup.stat().st_size,backup_sha256=hashlib.sha256(backup.read_bytes()).hexdigest())
        command(['systemctl','stop','career-search-sync.timer']);timer_stopped=True
        command(['systemctl','stop','career-search-sync.service'])
        (RELEASE/'previous-sync.json').write_bytes(settings_original);(RELEASE/'previous-sync.json').chmod(0o600)
        (RELEASE/'previous-service.unit').write_bytes(unit_original)
        import pymysql
        values=dict(line.split('=',1) for line in (BASE/'mysql-root.env').read_text().splitlines() if '=' in line)
        options=dict(host='127.0.0.1',port=3308,user='root',password=values['MYSQL_ROOT_PASSWORD'],database='career_matching',charset='utf8mb4',autocommit=True,cursorclass=pymysql.cursors.DictCursor,connect_timeout=5,read_timeout=30,write_timeout=30,init_command="SET time_zone='+00:00'")
        root=pymysql.connect(**options)
        def fingerprint():
            with root.cursor() as cur:
                cur.execute('SELECT job_id,source_version,content_hash FROM job_postings ORDER BY job_id');jobs=cur.fetchall()
                cur.execute('SELECT offering_id,source_version,content_hash FROM training_offerings ORDER BY offering_id');training=cur.fetchall()
            return {'jobs':len(jobs),'training':len(training),'hash':hashlib.sha256(json.dumps([jobs,training],sort_keys=True,default=str).encode()).hexdigest()}
        before=fingerprint();report['stage']='table_and_grants'
        with root.cursor() as cur:
            cur.execute((RELEASE/'app/backend/database/condition_review_migration.sql').read_text())
            cur.execute('SHOW COLUMNS FROM job_condition_reviews');columns={c['Field'] for c in cur.fetchall()}
            if not {'review_id','job_id','condition_hash','policy_version','classification','model_usage'}<=columns:raise ValueError('Unexpected review table schema')
        config=json.loads((BASE/'config.json').read_text())
        os.environ['AWS_REGION']=config['AWS_REGION']
        from src.repositories.aws_secrets import read_secret
        runtime=allowed_user(read_secret(config['MYSQL_SECRET_ARN'])['username'])
        reader=allowed_user(settings['user'])
        for user in dict.fromkeys([runtime,reader]):
            with root.cursor() as cur:
                cur.execute("SELECT Host FROM mysql.user WHERE User=%s",(user,));hosts=[x['Host'] for x in cur.fetchall()]
                if hosts!=['%']:raise ValueError('Unexpected reader account host')
                cur.execute("SELECT COUNT(*) AS n FROM information_schema.table_privileges WHERE GRANTEE=%s AND TABLE_SCHEMA='career_matching' AND TABLE_NAME='job_condition_reviews' AND PRIVILEGE_TYPE='SELECT'",("'"+user+"'@'%'",))
                exists=cur.fetchone()['n']>0
                if not exists:
                    cur.execute("GRANT SELECT ON career_matching.job_condition_reviews TO %s@'%%'",(user,));grants.append(user)
        account='career_condition_'+secrets.token_hex(5);password=secrets.token_hex(32)
        with root.cursor() as cur:
            cur.execute("CREATE USER %s@'%%' IDENTIFIED BY %s",(account,password));created=True
            cur.execute("GRANT SELECT ON career_matching.job_postings TO %s@'%%'",(account,))
            cur.execute("GRANT SELECT,INSERT ON career_matching.job_condition_reviews TO %s@'%%'",(account,))
            cur.execute("GRANT INSERT ON career_matching.search_outbox TO %s@'%%'",(account,))
        write_protected(WRITER,{'user':account,'password':password,'database':'career_matching','port':3308,'live_calls_allowed':False,'release':str(RELEASE)})
        with pymysql.connect(**dict(options,user=account,password=password)) as limited:
            with limited.cursor() as cur:
                limited.begin();cur.execute('SELECT job_id FROM job_postings ORDER BY job_id LIMIT 1 FOR SHARE');cur.fetchone();limited.rollback()
                cur.execute('SELECT COUNT(*) AS n FROM job_condition_reviews');report['review_rows']=cur.fetchone()['n']
        report['stage']='mapping'
        mapping=json.loads((RELEASE/'infra/elasticsearch/config/conditions.mapping.json').read_text())
        engine.request('PUT','/career-jobs-read/_mapping',mapping)
        report['mapping_fields']=list(mapping['properties'])
        report['stage']='consumer'
        lines=unit.splitlines()
        replacement='ExecStart=/opt/career/venv/bin/python '+str(RELEASE/'app/ingestion/search_index/sync_outbox.py')+' --config /opt/career/search-sync.json'
        UNIT.write_text(chr(10).join(replacement if line.startswith('ExecStart=') else line for line in lines)+chr(10));changed=True
        settings['enable_condition_reviews']=True;write_protected(SYNC,settings,sync_stat)
        command(['systemctl','daemon-reload'])
        command(['systemctl','start','career-search-sync.service'])
        command(['systemctl','start','career-search-sync.timer'])
        unit_result=command(['systemctl','show','career-search-sync.service','-p','Result','-p','ExecMainStatus']).stdout
        if 'Result=success' not in unit_result or 'ExecMainStatus=0' not in unit_result:raise RuntimeError('Consumer did not finish cleanly')
        if fingerprint()!=before:raise RuntimeError('Original source fingerprint changed')
        report.update(status='connected',source_rows_unchanged=before,consumer_enabled=True,classification_live_calls_enabled=False,
                      question_selection_enabled=config.get('ENABLE_AI_CONDITION_SELECTION','false'),ranking_enabled=config.get('ENABLE_AI_CONDITION_RANKING','false'),
                      writer_account_prepared=True,reader_grants_prepared=True,release=str(RELEASE))
        write_protected(MARKER,report)
    except Exception as exc:
        if changed:
            UNIT.write_bytes(unit_original)
            write_protected(SYNC,json.loads(settings_original),sync_stat)
            subprocess.run(['systemctl','daemon-reload'],capture_output=True)
        if root:
            try:
                with root.cursor() as cur:
                    if created:cur.execute("DROP USER IF EXISTS %s@'%%'",(account,))
                    for user in grants:cur.execute("REVOKE SELECT ON career_matching.job_condition_reviews FROM %s@'%%'",(user,))
            except Exception:report['grant_cleanup_required']=True
        if created and WRITER.exists():WRITER.unlink()
        report.update(status='failed',error_type=type(exc).__name__,error_code=exc.args[0] if exc.args and type(exc.args[0]) is int else None,http_status=getattr(exc,'code',None),consumer_rollback_attempted=changed,
                      additive_table_or_mapping_may_remain=True)
    finally:
        if timer_stopped:subprocess.run(['systemctl','start','career-search-sync.timer'],capture_output=True)
        if root:root.close()
        path=RELEASE/'connection-result.json';path.write_text(json.dumps(report,indent=2));path.chmod(0o600)
    print(json.dumps(report));return 0 if report['status']=='connected' else 1
if __name__=='__main__':raise SystemExit(main())

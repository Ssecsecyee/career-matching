"""Install v2 projection consumer and publish only pre-reviewed source-bound pilot candidates."""
import compileall,gzip,hashlib,json,os,secrets,shutil,subprocess,sys
from pathlib import Path
BASE=Path('/opt/career');RELEASE=Path(__file__).resolve().parents[2]
UNIT=Path('/etc/systemd/system/career-search-sync.service')
MARKER=BASE/'condition-review-v2-install.json'

def command(args):return subprocess.run(args,check=True,capture_output=True,text=True,timeout=120)
def main():
    os.umask(0o077);report={'status':'starting','stage':'preflight','model_calls':0}
    root=None;paused=False;switched=False;publishing=False;account_created=False;account=None;old=None
    try:
        if MARKER.exists():raise ValueError('V2 publication already installed; inspect marker before retry')
        if not compileall.compile_dir(str(RELEASE/'app'),quiet=2):raise ValueError('Package compile failed')
        sys.path.insert(0,str(RELEASE/'app/backend'));sys.path.insert(0,str(RELEASE/'app/ingestion/search_index'))
        from src.repositories.condition_drafts import ConditionDraftStore,validate_approval
        from src.services.condition_review import validated_envelope,condition_hash,projection
        from sync_outbox import Engine
        cfg=json.loads((BASE/'config.json').read_text())
        if any(str(cfg.get(k,'false')).lower()=='true' for k in ('ENABLE_AI_CONDITION_SELECTION','ENABLE_AI_CONDITION_RANKING')):raise ValueError('Pilot requires user-facing features off')
        sync=json.loads((BASE/'search-sync.json').read_text())
        if sync.get('enable_condition_reviews') is not True:raise ValueError('Condition consumer not enabled')
        engine=Engine(sync['jobs_alias'],sync['training_alias']);engine.verify_aliases()
        payload=json.loads((RELEASE/'reviewed-pilot.json').read_text())
        if len(payload)!=3:raise ValueError('Expected exactly three reviewed pilot jobs')
        secret=dict(x.split('=',1) for x in (BASE/'mysql-root.env').read_text().splitlines() if '=' in x)
        import pymysql
        options=dict(host='127.0.0.1',port=3308,database='career_matching',charset='utf8mb4',autocommit=True,cursorclass=pymysql.cursors.DictCursor,connect_timeout=5,read_timeout=30,write_timeout=30)
        root=pymysql.connect(**options,user='root',password=secret['MYSQL_ROOT_PASSWORD'])
        def fingerprint():
            with root.cursor() as c:
                c.execute('SELECT job_id,source_version,content_hash FROM job_postings ORDER BY job_id');jobs=c.fetchall()
                c.execute('SELECT offering_id,source_version,content_hash FROM training_offerings ORDER BY offering_id');training=c.fetchall()
            return {'jobs':len(jobs),'training':len(training),'sha256':hashlib.sha256(json.dumps([jobs,training],sort_keys=True,default=str).encode()).hexdigest()}
        before=fingerprint();current={}
        for item in payload:
            checked=validated_envelope(item['job'],item['review']);validate_approval(checked,item['approval'])
            with root.cursor() as c:
                c.execute('SELECT * FROM job_postings WHERE job_id=%s',(item['job']['job_id'],));row=c.fetchone()
            if not row or str(row['source_id'])!=str(item['job']['source_id']) or condition_hash(row)!=checked['condition_hash']:raise ValueError('Pilot source changed')
            current[row['job_id']]=row
        report['stage']='backup'
        backup=BASE/'backups'/('before-condition-v2-'+RELEASE.name+'.sql.gz');backup.parent.mkdir(exist_ok=True,mode=0o700)
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
        report.update(backup_verified=True,backup_sha256=hashlib.sha256(backup.read_bytes()).hexdigest())
        command(['systemctl','stop','career-search-sync.timer']);paused=True
        command(['systemctl','stop','career-search-sync.service'])
        old=UNIT.read_bytes();(RELEASE/'previous-service.unit').write_bytes(old)
        account='career_approve_'+secrets.token_hex(5);password=secrets.token_hex(32)
        with root.cursor() as c:
            c.execute("CREATE USER %s@'%%' IDENTIFIED BY %s",(account,password));account_created=True
            for table,privileges in [('job_postings','SELECT'),('job_condition_review_drafts','SELECT,INSERT,UPDATE'),('job_condition_reviews','SELECT,INSERT'),('search_outbox','INSERT')]:
                c.execute('GRANT '+privileges+" ON career_matching."+table+" TO %s@'%%'",(account,))
        approver_path=BASE/'condition-review-approver.json'
        if approver_path.exists():raise ValueError('Existing approver settings require inspection')
        approver_path.write_text(json.dumps({'user':account,'password':password,'database':'career_matching','port':3308}));approver_path.chmod(0o600)
        report['stage']='mapping_and_consumer'
        engine.request('PUT','/'+sync['jobs_alias']+'/_mapping',json.loads((RELEASE/'infra/elasticsearch/config/conditions.mapping.json').read_text()))
        lines=old.decode().splitlines()
        if sum(x.startswith('ExecStart=') for x in lines)!=1:raise ValueError('Unexpected service unit')
        replacement='ExecStart=/opt/career/venv/bin/python '+str(RELEASE/'app/ingestion/search_index/sync_outbox.py')+' --config /opt/career/search-sync.json'
        UNIT.write_text(chr(10).join(replacement if x.startswith('ExecStart=') else x for x in lines)+chr(10));switched=True
        command(['systemctl','daemon-reload'])
        factory=lambda:pymysql.connect(**options,user=account,password=password)
        store=ConditionDraftStore(factory);published=[];report['stage']='reviewed_publication'
        for item in payload:
            draft=store.stage(item['job'],item['review'],item['usage'])
            store.verify(draft['draft_id'],item['approval'])
            publishing=True
            saved=store.publish(draft['draft_id'])
            published.append({'source_id':str(item['job']['source_id']),'draft_id':draft['draft_id'],'review_id':saved['review_id']})
        command(['systemctl','start','career-search-sync.service'])
        command(['systemctl','start','career-search-sync.timer'])
        report['stage']='es_readback'
        checked_count=0
        for item in payload:
            row=current[item['job']['job_id']]
            identity=json.dumps([row['source'],row['source_id']],ensure_ascii=False,separators=(',',':'))
            key=hashlib.sha256(identity.encode()).hexdigest()
            actual=engine.request('GET','/'+sync['jobs_alias']+'/_doc/'+key)['_source']
            expected=projection(row,item['review'])
            for field,value in expected.items():
                if actual.get(field)!=value:raise ValueError('ES classification readback mismatch')
            if actual['qualifications']!=row['qualifications'] or actual['preferred_requirements']!=row['preferred_requirements']:raise ValueError('ES original source changed')
            checked_count+=len(actual['classified_conditions'])
        after=fingerprint()
        if after!=before:raise ValueError('Original source fingerprint changed')
        report.update(status='published_and_verified',published=published,conditions=checked_count,source_unchanged=before,consumer_release=str(RELEASE),question_selection_enabled=False,ranking_enabled=False,independent_human_evaluation=False)
        MARKER.write_text(json.dumps(report,indent=2));MARKER.chmod(0o600)
    except Exception as exc:
        if switched and not publishing:
            UNIT.write_bytes(old);subprocess.run(['systemctl','daemon-reload'],capture_output=True)
        if account_created and not publishing:
            with root.cursor() as c:c.execute("DROP USER IF EXISTS %s@'%%'",(account,))
            path=BASE/'condition-review-approver.json'
            if path.exists() and json.loads(path.read_text()).get('user')==account:path.unlink()
        report.update(status='failed',error_type=type(exc).__name__,error_code=exc.args[0] if exc.args and type(exc.args[0]) is int else None,http_status=getattr(exc,'code',None),publication_may_be_partial=publishing,new_consumer_retained=bool(switched and publishing))
    finally:
        if paused:subprocess.run(['systemctl','start','career-search-sync.timer'],capture_output=True)
        if root:root.close()
        (RELEASE/'v2-result.json').write_text(json.dumps(report,indent=2))
    print(json.dumps(report));return 0 if report['status']=='published_and_verified' else 1
if __name__=='__main__':raise SystemExit(main())

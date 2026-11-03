"""Add selected-job SQL question cache, then enable only after the new worker code is deployed."""
import argparse,gzip,hashlib,json,os,shutil,stat,subprocess,sys,time
from pathlib import Path
BASE=Path('/opt/career');RELEASE=Path(__file__).resolve().parents[1]
MARKER=BASE/'on-demand-condition-install.json';CONFIG=BASE/'config.json'

def command(args):return subprocess.run(args,check=True,capture_output=True,text=True,timeout=120)
def protected(path,value,original=None):
    temporary=path.with_name(path.name+'.on-demand-next')
    temporary.write_text(json.dumps(value));temporary.chmod(stat.S_IMODE(original.st_mode) if original else 0o600)
    if original:os.chown(temporary,original.st_uid,original.st_gid)
    temporary.replace(path)
def fingerprint(db):
    with db.cursor() as c:
        c.execute('SELECT job_id,source_version,content_hash FROM job_postings ORDER BY job_id');jobs=c.fetchall()
        c.execute('SELECT offering_id,source_version,content_hash FROM training_offerings ORDER BY offering_id');training=c.fetchall()
    return {'jobs':len(jobs),'training':len(training),'sha256':hashlib.sha256(json.dumps([jobs,training],sort_keys=True,default=str).encode()).hexdigest()}
def credentials(config):
    os.environ['AWS_REGION']=config['AWS_REGION']
    from src.repositories.aws_secrets import read_secret
    return read_secret(config['MYSQL_SECRET_ARN'])
def runtime_probe(factory):
    from src.repositories.condition_question_cache import ConditionQuestionCache
    from src.services.deadlines import VISIBLE_SQL
    db=factory()
    try:
        with db.cursor() as c:
            c.execute('SELECT COUNT(*) AS n FROM job_condition_question_cache');count=c.fetchone()['n']
            c.execute("SELECT job_id,source_id,source_version,qualifications,preferred_requirements FROM job_postings WHERE recruitment_status IN ('active','unknown') AND "+VISIBLE_SQL+' ORDER BY job_id LIMIT 1');job=c.fetchone()
    finally:db.close()
    cache=ConditionQuestionCache(factory)
    if job:
        cache.get(job)
        with cache.claim(job) as first:
            if not first:raise ValueError('Unexpected busy deployment test lock')
            with cache.claim(job) as second:
                if second:raise ValueError('Duplicate selected-source lock')
    return count

def main():
    p=argparse.ArgumentParser();p.add_argument('--phase',choices=['prepare','enable'],default='prepare');args=p.parse_args()
    os.umask(0o077);report={'status':'starting','phase':args.phase,'model_calls':0};root=None;granted=[];changed_config=False;original=None
    try:
        sys.path.insert(0,str(RELEASE/'app/backend'))
        config=json.loads(CONFIG.read_text());original=CONFIG.read_bytes();config_stat=CONFIG.stat()
        import pymysql
        runtime=credentials(config)
        options=dict(host='127.0.0.1',port=3308,database='career_matching',charset='utf8mb4',autocommit=True,cursorclass=pymysql.cursors.DictCursor,connect_timeout=5,read_timeout=30,write_timeout=30)
        factory=lambda:pymysql.connect(**options,user=runtime['username'],password=runtime['password'])
        if args.phase=='prepare':
            if MARKER.exists():raise ValueError('Preparation already exists; inspect result')
            if str(config.get('ENABLE_ON_DEMAND_CONDITIONS','false')).lower()=='true':raise ValueError('Feature must be off while preparing')
            if shutil.disk_usage(BASE).free<512*1024*1024:raise ValueError('Insufficient backup space')
            backup=BASE/'backups'/('before-selected-question-cache-'+RELEASE.name+'.sql.gz');backup.parent.mkdir(exist_ok=True,mode=0o700)
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
            if size<1000:raise ValueError('Empty backup')
            report.update(backup_verified=True,backup_sha256=hashlib.sha256(backup.read_bytes()).hexdigest())
            secret=dict(line.split('=',1) for line in (BASE/'mysql-root.env').read_text().splitlines() if '=' in line)
            root=pymysql.connect(**options,user='root',password=secret['MYSQL_ROOT_PASSWORD'])
            before=fingerprint(root)
            with root.cursor() as c:
                c.execute((RELEASE/'app/backend/database/condition_question_cache_migration.sql').read_text())
                c.execute('SHOW COLUMNS FROM job_condition_question_cache');columns={x['Field'] for x in c.fetchall()}
                if not {'cache_id','job_id','condition_hash','review_policy','source_snapshot','classification','model_usage','validation_level'}<=columns:raise ValueError('Cache schema mismatch')
                user=runtime['username']
                if not user.isascii() or not all(x.isalnum() or x=='_' for x in user):raise ValueError('Unexpected runtime account')
                c.execute('SELECT Host FROM mysql.user WHERE User=%s',(user,))
                if [x['Host'] for x in c.fetchall()]!=['%']:raise ValueError('Unexpected runtime account host')
                for privilege in ('SELECT','INSERT'):
                    c.execute("SELECT COUNT(*) AS n FROM information_schema.table_privileges WHERE GRANTEE=%s AND TABLE_SCHEMA='career_matching' AND TABLE_NAME='job_condition_question_cache' AND PRIVILEGE_TYPE=%s",("'"+user+"'@'%'",privilege))
                    if not c.fetchone()['n']:
                        c.execute('GRANT '+privilege+" ON career_matching.job_condition_question_cache TO %s@'%%'",(user,));granted.append((user,privilege))
            count=runtime_probe(factory)
            after=fingerprint(root)
            if before!=after:raise ValueError('Source fingerprint changed during preparation')
            report.update(status='prepared',cache_rows=count,source_unchanged=before,runtime_select_insert_ready=True,feature_enabled=False,release=str(RELEASE))
            protected(MARKER,report)
        else:
            marker=json.loads(MARKER.read_text())
            if marker.get('status')!='prepared' or marker.get('release')!=str(RELEASE):raise ValueError('Expected this prepared release')
            for relative in ('src/handlers/dialogue.py','src/services/selected_condition_review.py','src/bedrock/question_reviewer.py','src/repositories/condition_question_cache.py'):
                if hashlib.sha256((BASE/'app'/relative).read_bytes()).digest()!=hashlib.sha256((RELEASE/'app/backend'/relative).read_bytes()).digest():raise ValueError('Deploy worker code before activation')
            cache_rows=runtime_probe(factory)
            (RELEASE/'previous-worker-config.json').write_bytes(original);(RELEASE/'previous-worker-config.json').chmod(0o600)
            config['ENABLE_ON_DEMAND_CONDITIONS']='true'
            protected(CONFIG,config,config_stat);changed_config=True
            command(['systemctl','restart','career-worker']);time.sleep(5)
            command(['systemctl','is-active','--quiet','career-worker'])
            report.update(status='enabled',cache_rows=cache_rows,feature_enabled=True,sql_only_cache=True,es_events_created=0,configured_live_setting=config.get('ENABLE_LIVE_BEDROCK','unset'),release=str(RELEASE))
            protected(MARKER,dict(marker,activation=report))
    except Exception as exc:
        if changed_config:
            protected(CONFIG,json.loads(original),config_stat)
            subprocess.run(['systemctl','restart','career-worker'],capture_output=True)
        if root:
            try:
                with root.cursor() as c:
                    for user,privilege in granted:c.execute('REVOKE '+privilege+" ON career_matching.job_condition_question_cache FROM %s@'%%'",(user,))
            except Exception:report['grant_cleanup_required']=True
        report.update(status='failed',error_type=type(exc).__name__,error_code=exc.args[0] if exc.args and type(exc.args[0]) is int else None,config_restored=changed_config,additive_table_may_remain=True)
    finally:
        if root:root.close()
        (RELEASE/('selected-question-'+args.phase+'-result.json')).write_text(json.dumps(report,indent=2))
    print(json.dumps(report));return 0 if report['status'] in {'prepared','enabled'} else 1
if __name__=='__main__':raise SystemExit(main())

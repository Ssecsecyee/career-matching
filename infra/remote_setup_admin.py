"""Run via SSM as host administrator. Never emit credentials or chat contents."""
import gzip,hashlib,importlib.util,json,os,pathlib,pwd,re,secrets,shutil,subprocess,sys
from datetime import datetime,timezone
from uuid import uuid4
import pymysql

def main():
 os.umask(0o077);base=pathlib.Path('/opt/career');folder=pathlib.Path(__file__).resolve().parent
 sys.path.insert(0,str(base/'app'))
 from src.handlers.bootstrap import sql_statements
 store_spec=importlib.util.spec_from_file_location('admin_setup_chat_store',folder/'mysql_chat.py');store_module=importlib.util.module_from_spec(store_spec);store_spec.loader.exec_module(store_module);MySQLChatStore=store_module.MySQLChatStore
 from src.services.dialogue import FlowError
 spec=importlib.util.spec_from_file_location('admin_setup_service',folder/'admin_service.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
 values=dict(x.split('=',1) for x in (base/'mysql-root.env').read_text().splitlines())
 opts=dict(host='127.0.0.1',port=3308,user='root',password=values['MYSQL_ROOT_PASSWORD'],charset='utf8mb4',autocommit=True,cursorclass=pymysql.cursors.DictCursor,init_command="SET time_zone='+00:00'")
 root=pymysql.connect(**opts);scratch='career_admin_verify_'+secrets.token_hex(6);assert re.fullmatch('career_admin_verify_[a-f0-9]{12}',scratch)
 checks=[]
 try:
  with root.cursor() as cur:cur.execute('CREATE DATABASE '+scratch+' CHARACTER SET utf8mb4')
  testopts=dict(opts,database=scratch)
  def factory():return pymysql.connect(**testopts)
  c=factory()
  try:
   with c.cursor() as cur:
    for sql in sql_statements((folder/'schema.sql').read_text()):cur.execute(sql)
    for sql in sql_statements((folder/'admin_migration.sql').read_text()):cur.execute(sql)
    cur.execute("INSERT INTO job_postings(source,source_id,source_url,title,company_name,recruitment_status,source_version,fetched_at) VALUES('jumpit','999999999','https://example.com','ADMIN TEST','ISOLATED','unknown',1,UTC_TIMESTAMP(6))")
   actor='f'*64
   p=dict(action='admin',operation='hide_job',request_id=str(uuid4()),job_id=1,source_version=1,reason='isolated hide verification')
   assert module.execute(factory,p,actor)['source_version']==2
   assert module.execute(factory,p,actor)['replayed'] is True
   assert module.execute(factory,dict(p,operation='restore_job',request_id=str(uuid4()),source_version=2),actor)['source_version']==3
   with c.cursor() as cur:
    cur.execute('SELECT recruitment_status,source_version FROM job_postings WHERE job_id=1');r=cur.fetchone();assert r['recruitment_status']=='unknown' and r['source_version']==3
    cur.execute('SELECT COUNT(*) AS n FROM admin_audit');assert cur.fetchone()['n']==2
    cur.execute('SELECT COUNT(*) AS n FROM search_outbox');assert cur.fetchone()['n']==2
   checks+=['hide_restore_and_outbox_atomic','idempotent_replay']
   module.execute(factory,dict(action='admin',operation='summary',request_id=str(uuid4())),actor)
   for table in module.TABLES:module.execute(factory,dict(action='admin',operation='rows',table=table,request_id=str(uuid4())),actor)
   checks.append('all_table_queries')
   sid=str(uuid4())
   with c.cursor() as cur:cur.execute("INSERT INTO chat_sessions(session_id,owner_scope,requirement_answers,model_call_count,expires_at) VALUES(%s,%s,'{}',13,UTC_TIMESTAMP()+INTERVAL 1 HOUR)",(sid,actor))
   payload=dict(action='search',session_id=sid,request_id=str(uuid4()),search_plan={'skills':['React']})
   try:MySQLChatStore(factory,retention_hours=1).begin(actor,payload);raise AssertionError('normal budget not enforced')
   except FlowError as exc:assert exc.code=='session_model_budget_exceeded'
   ticket=MySQLChatStore(factory,retention_hours=1,max_calls=None).begin(actor,payload)
   assert ticket['calls_remaining'] is None
   for n in range(13):MySQLChatStore(factory,retention_hours=1,max_calls=None).begin_invocation(ticket,'conversation','offline-fixture','test','test',[])
   checks.append('admin_unlimited_normal_12_no_model_calls')
  finally:c.close()
 finally:
  with root.cursor() as cur:cur.execute('DROP DATABASE '+scratch)
 # Production changes start only after isolated verification succeeds.
 backup=base/'backups'/('before-admin-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'.sql.gz')
 if shutil.disk_usage(base).free<256*1024*1024:raise RuntimeError('backup_space')
 with backup.open('xb') as out:
  p=subprocess.Popen(['docker','exec','career-mysql','sh','-c','MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysqldump --user=root --single-transaction --set-gtid-purged=OFF career_matching'],stdout=subprocess.PIPE,stderr=subprocess.DEVNULL)
  with gzip.GzipFile(fileobj=out,mode='wb') as packed:shutil.copyfileobj(p.stdout,packed)
  if p.wait()!=0:raise RuntimeError('backup_failed')
 with gzip.open(backup,'rb') as f:
  size=0
  while True:
   part=f.read(1048576)
   if not part:break
   size+=len(part)
 assert size>1000
 credential=base/'admin-db.json'
 if credential.exists():admin=json.loads(credential.read_text())
 else:admin={'username':'career_admin_'+secrets.token_hex(4),'password':secrets.token_hex(32)}
 assert re.fullmatch(r'career_admin_[a-f0-9]{8}',admin['username'])
 root.select_db('career_matching')
 with root.cursor() as cur:
  cur.execute('SELECT COUNT(*) AS n FROM job_postings');before=cur.fetchone()['n']
  for sql in sql_statements((folder/'admin_migration.sql').read_text()):cur.execute(sql)
  cur.execute("CREATE USER IF NOT EXISTS %s@'%%' IDENTIFIED BY %s",(admin['username'],admin['password']))
  for table in module.TABLES:cur.execute('GRANT SELECT ON career_matching.'+table+" TO %s@'%%'",(admin['username'],))
  cur.execute("GRANT UPDATE(recruitment_status,source_version,content_hash) ON career_matching.job_postings TO %s@'%%'",(admin['username'],))
  for table in ['search_outbox','admin_audit']:cur.execute('GRANT INSERT ON career_matching.'+table+" TO %s@'%%'",(admin['username'],))
  cur.execute('SELECT COUNT(*) AS n FROM job_postings');assert cur.fetchone()['n']==before
 temp=credential.with_suffix('.next');temp.write_text(json.dumps(admin));owner=pwd.getpwnam('career');os.chmod(temp,0o600);os.chown(temp,owner.pw_uid,owner.pw_gid);temp.replace(credential)
 # Verify actual minimal grants against every dashboard query.
 def prod_factory():return pymysql.connect(**dict(opts,database='career_matching',user=admin['username'],password=admin['password']))
 module.execute(prod_factory,dict(action='admin',operation='summary',request_id=str(uuid4())),'f'*64)
 for table in module.TABLES:module.execute(prod_factory,dict(action='admin',operation='rows',table=table,request_id=str(uuid4())),'f'*64)
 root.close()
 unit=subprocess.check_output(['systemctl','show','career-search-sync.service','-p','ExecStart','--value'],text=True)
 match=re.search(r'(/opt/career/[^ ;}]+/app/ingestion/search_index/sync_outbox.py)',unit);assert match
 target=pathlib.Path(match.group(1));shutil.copy2(target,folder/'previous_sync_outbox.py');st=target.stat()
 subprocess.run(['systemctl','stop','career-search-sync.timer'],check=True);subprocess.run(['systemctl','stop','career-search-sync.service'],check=True)
 try:
  tmp=target.with_suffix('.next');tmp.write_bytes((folder/'sync_outbox.py').read_bytes());os.chmod(tmp,st.st_mode);os.chown(tmp,st.st_uid,st.st_gid);tmp.replace(target)
  subprocess.run(['systemctl','start','career-search-sync.service'],check=True)
 except Exception:
  shutil.copy2(folder/'previous_sync_outbox.py',target);raise
 finally:subprocess.run(['systemctl','start','career-search-sync.timer'],check=True)
 print(json.dumps({'status':'prepared','isolated_checks':checks,'scratch_removed':True,'model_calls':0,'jobs_unchanged':before,'admin_audit_ready':True,'backup':str(backup),'backup_gzip_verified':True,'admin_db_credentials_protected':True,'search_consumer_updated':True}))

if __name__=='__main__':
 try:main()
 except Exception as exc:
  import traceback
  print(json.dumps({'status':'failed','error_type':type(exc).__name__,'locations':[{'file':pathlib.Path(x.filename).name,'line':x.lineno} for x in traceback.extract_tb(exc.__traceback__)][-5:],'numeric_code':exc.args[0] if exc.args and type(exc.args[0]) is int else None}));raise SystemExit(1)

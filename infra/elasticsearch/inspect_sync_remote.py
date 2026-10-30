"""Safe counters and service states, no credentials or user messages."""
import json,subprocess,sys
from pathlib import Path
from urllib.request import urlopen
import pymysql
sys.path.insert(0,'/opt/career/app')
from src.services.deadlines import VISIBLE_SQL
base=Path('/opt/career')
settings=json.loads((base/'search-sync.json').read_text())
conn=pymysql.connect(host='127.0.0.1',port=settings['port'],user=settings['user'],password=settings['password'],database=settings['database'],charset='utf8mb4',autocommit=True,cursorclass=pymysql.cursors.DictCursor,init_command="SET time_zone='+00:00'")
try:
    with conn.cursor() as cur:
        cur.execute('SELECT COUNT(*) AS total,SUM(processed_at IS NULL) AS pending,COALESCE(MAX(IF(processed_at IS NULL,attempt_count,0)),0) AS pending_max_attempts FROM search_outbox');outbox=cur.fetchone()
        cur.execute("SELECT COUNT(*) AS total,SUM(recruitment_status='closed') AS confirmed_closed FROM job_postings");jobs=cur.fetchone()
        cur.execute("SELECT COUNT(*) AS n FROM job_postings WHERE recruitment_status IN ('active','unknown') AND "+VISIBLE_SQL);jobs['visible_by_policy']=cur.fetchone()['n']
        cur.execute('SELECT COUNT(*) AS n FROM training_offerings');training=cur.fetchone()['n']
finally:conn.close()
def request(path):
    with urlopen('http://127.0.0.1:19200/'+path,timeout=10) as r:return json.load(r)
def service(name):
    return subprocess.run(['systemctl','show',name,'-p','ActiveState','-p','SubState','-p','Result','-p','ExecMainStatus','-p','LastTriggerUSec','-p','ExecMainExitTimestamp'],capture_output=True,text=True,check=True).stdout.strip()
config=json.loads((base/'config.json').read_text())
memory={s.split(':')[0]:int(s.split(':')[1].split()[0]) for s in open('/proc/meminfo')}
logs=subprocess.run(['journalctl','-u','career-search-sync.service','-n','25','--no-pager','-o','cat'],capture_output=True,text=True,check=True)
runs=[]
for line in logs.stdout.splitlines():
    if line.startswith('{'):
        try:
            value=json.loads(line)
            runs.append({k:value.get(k) for k in ('status','processed','failed','pending','expiry_events')})
        except ValueError:pass
print(json.dumps({'database_jobs':jobs,'training_rows':training,'outbox':outbox,'es_jobs':request('career-jobs-read/_count')['count'],'es_training':request('career-training-read/_count')['count'],'es_health':request('_cluster/health')['status'],'worker':service('career-worker'),'timer':service('career-search-sync.timer'),'sync_service':service('career-search-sync.service'),'recent_sync_runs':runs,'search_backends':{k:config.get(k) for k in ('JOB_SEARCH_BACKEND','TRAINING_SEARCH_BACKEND')},'available_memory_mib':memory['MemAvailable']//1024},default=str))

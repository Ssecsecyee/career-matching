"""Server-side new-only Work24 import and verified education-index publication."""
import ast,gzip,hashlib,json,os,re,shutil,subprocess,sys,time
from datetime import datetime,timezone
from pathlib import Path
from urllib.request import Request,urlopen

BASE=Path('/opt/career');RUN=Path(__file__).resolve().parent
sys.path.insert(0,str(RUN));sys.path.insert(0,str(RUN/'code'))
from ingest_work24 import insert_batch
from src.services.training_dates import effective_start,start_visibility
from src.repositories.elasticsearch_training import ElasticsearchTrainingRepository


def es(method,path,data=None):
    body=None if data is None else json.dumps(data,ensure_ascii=False).encode()
    with urlopen(Request('http://127.0.0.1:19200'+path,body,{'Content-Type':'application/json'},method=method),timeout=45) as response:return json.load(response)

def fingerprint(conn,table,key):
    with conn.cursor() as cur:
        cur.execute('SELECT '+key+',source_version,content_hash FROM '+table+' ORDER BY '+key)
        return hashlib.sha256(json.dumps(cur.fetchall(),sort_keys=True,default=str).encode()).hexdigest()

def backup():
    target=BASE/'backups'/('before-work24-'+RUN.name+'.sql.gz')
    target.parent.mkdir(exist_ok=True)
    if target.exists():return str(target)
    with target.open('xb') as out:
        proc=subprocess.Popen(['docker','exec','career-mysql','sh','-c','MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysqldump --user=root --single-transaction --set-gtid-purged=OFF career_matching'],stdout=subprocess.PIPE,stderr=subprocess.DEVNULL)
        with gzip.GzipFile(fileobj=out,mode='wb') as packed:shutil.copyfileobj(proc.stdout,packed)
        proc.stdout.close()
        if proc.wait()!=0:raise RuntimeError('backup_failed')
    size=0
    with gzip.open(target,'rb') as f:
        for block in iter(lambda:f.read(1048576),b''):size+=len(block)
    if size<1000:raise RuntimeError('backup_empty')
    return str(target)

def documents(row):
    names='source source_id source_version title provider_name curriculum eligibility preferred_conditions benefits selection_process application_notes recruitment_status delivery_mode'.split()
    doc={k:str(row.get(k) or '') for k in names}
    for key in ('learning_topics','tech_stacks'):
        value=row.get(key) or [];doc[key]=json.loads(value) if isinstance(value,str) else value
    doc['document_key']=json.dumps([row['source'],row['source_id']],ensure_ascii=False,separators=(',',':'))
    start=effective_start(row)
    if start is not None:doc['training_start_at']=start.isoformat()
    return hashlib.sha256(doc['document_key'].encode()).hexdigest(),doc

def main():
    os.umask(0o077);report={'status':'starting','inserted':0,'skipped':0,'published':False,'bedrock_calls':0,'stage':'preflight'};conn=None;timer=False;published=False
    try:
        if shutil.disk_usage(BASE).free<5*1024**3:raise RuntimeError('insufficient_disk')
        import pymysql
        values=dict(line.split('=',1) for line in (BASE/'mysql-root.env').read_text().splitlines() if '=' in line)
        options=dict(host='127.0.0.1',port=3308,user='root',password=values['MYSQL_ROOT_PASSWORD'],database='career_matching',charset='utf8mb4',cursorclass=pymysql.cursors.DictCursor,autocommit=True,connect_timeout=5,read_timeout=120,write_timeout=120,init_command="SET time_zone='+00:00'")
        conn=pymysql.connect(**options)
        jobs_before=fingerprint(conn,'job_postings','job_id')
        with conn.cursor() as cur:
            cur.execute("SELECT offering_id,source_version,content_hash FROM training_offerings WHERE source='boottent' ORDER BY offering_id");original=cur.fetchall()
            cur.execute("SELECT COALESCE(MAX(event_id),0) AS n FROM search_outbox");first_event=cur.fetchone()['n']+1
        report['backup']=backup();report['backup_gzip_verified']=True
        timer=subprocess.run(['systemctl','is-active','--quiet','career-search-sync.timer']).returncode==0
        subprocess.run(['systemctl','stop','career-search-sync.timer','career-search-sync.service'],check=True)
        report['stage']='pilot_rollback'
        with gzip.open(RUN/'training.jsonl.gz','rt',encoding='utf-8') as f:pilot=[json.loads(next(f)) for _ in range(20)]
        conn.begin();insert_batch(pilot,conn);conn.rollback()
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS n FROM training_offerings WHERE source='goyong24_training'");report['before']=cur.fetchone()['n']
        report['rollback_passed']=True
        report['stage']='pilot_commit';conn.begin();one=insert_batch(pilot,conn);again=insert_batch(pilot,conn)
        if again['inserted']!=0 or again['skipped']!=20:raise RuntimeError('idempotency_failed')
        conn.commit();report['inserted']+=one['inserted'];report['idempotency_passed']=True
        print(json.dumps({'stage':'pilot_passed','inserted':one['inserted'],'rollback':True,'idempotency':True}),flush=True)
        report['stage']='bulk_insert';batch=[];read=0;excluded=0
        with gzip.open(RUN/'training.jsonl.gz','rt',encoding='utf-8') as f:
            for line in f:
                row=json.loads(line);read+=1
                if not start_visibility(row)[0]:excluded+=1;continue
                batch.append(row)
                if len(batch)==200:
                    conn.begin();result=insert_batch(batch,conn);conn.commit();batch=[]
                    for key in ('inserted','skipped'):report[key]+=result[key]
                    if read%10000==0:
                        (RUN/'progress.json').write_text(json.dumps(report));print(json.dumps({'stage':'inserting','read':read,'inserted':report['inserted']}),flush=True)
            if batch:
                conn.begin();result=insert_batch(batch,conn);conn.commit()
                for key in ('inserted','skipped'):report[key]+=result[key]
        report.update(input_rows=read,excluded_started=excluded)
        if fingerprint(conn,'job_postings','job_id')!=jobs_before:raise RuntimeError('jobs_changed_during_import')
        with conn.cursor() as cur:
            cur.execute("SELECT offering_id,source_version,content_hash FROM training_offerings WHERE source='boottent' ORDER BY offering_id")
            if cur.fetchall()!=original:raise RuntimeError('boottent_changed')
            cur.execute("SELECT COUNT(*) AS n FROM training_offerings");expected=cur.fetchone()['n']
        report['stage']='build_education_index'
        alias=es('GET','/_alias/career-training-read')
        if len(alias)!=1:raise RuntimeError('invalid_alias')
        old=next(iter(alias));settings=es('GET','/'+old+'/_settings')[old]['settings']['index'];mapping=es('GET','/'+old+'/_mapping')[old]['mappings']
        mapping['properties']['training_start_at']={'type':'date'};mapping['properties']['delivery_mode']={'type':'keyword'}
        index='career-training-work24-'+datetime.now(timezone.utc).strftime('%Y%m%dt%H%M%Sz')
        es('PUT','/'+index,{'settings':{'number_of_shards':1,'number_of_replicas':0,'refresh_interval':'-1','analysis':settings['analysis']},'mappings':mapping})
        indexed=0
        with conn.cursor() as cur:
            last=0
            while True:
                cur.execute('SELECT * FROM training_offerings WHERE offering_id>%s ORDER BY offering_id LIMIT 500',(last,));rows=cur.fetchall()
                if not rows:break
                lines=[]
                for row in rows:
                    key,doc=documents(row)
                    lines.extend([json.dumps({'index':{'_index':index,'_id':key,'version':int(row['source_version']),'version_type':'external_gte'}}),json.dumps(doc,ensure_ascii=False)])
                body=('\n'.join(lines)+'\n').encode()
                with urlopen(Request('http://127.0.0.1:19200/_bulk',body,{'Content-Type':'application/x-ndjson'},method='POST'),timeout=60) as response:result=json.load(response)
                if result.get('errors'):raise RuntimeError('bulk_index_failed')
                indexed+=len(rows);last=rows[-1]['offering_id']
        es('PUT','/'+index+'/_settings',{'index':{'refresh_interval':'1s'}});es('POST','/'+index+'/_refresh')
        if es('GET','/'+index+'/_count')['count']!=expected or indexed!=expected:raise RuntimeError('index_count_mismatch')
        checks={};factory=lambda:pymysql.connect(**options)
        for topic in ['React','Python','디자인','회계']:
            cards=ElasticsearchTrainingRepository(factory,es,index=index).search([topic],candidates_only=True)
            if not cards:raise RuntimeError('expected_training_search_empty')
            if any(c['recommendation_eligible'] or not c['start_window_eligible'] for c in cards):raise RuntimeError('invalid_course_visibility')
            checks[topic]={'cards':len(cards),'sources':sorted({c['source'] for c in cards})}
        report['stage']='sync_code'
        unit=subprocess.run(['systemctl','show','career-search-sync.service','-p','ExecStart','--value'],capture_output=True,text=True,check=True).stdout
        match=re.search(r'(/opt/career/[^ ;{}]+/app/ingestion/search_index/sync_outbox.py)',unit)
        if not match:raise RuntimeError('sync_path_not_found')
        sync=Path(match.group(1)).resolve()
        if not str(sync).startswith('/opt/career/'):raise RuntimeError('unsafe_sync_path')
        old_source=sync.read_text();tree=ast.parse(old_source);node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='training_document')
        fresh=(RUN/'sync_outbox.py').read_text();new_tree=ast.parse(fresh);new_node=next(n for n in new_tree.body if isinstance(n,ast.FunctionDef) and n.name=='training_document')
        replacement='\n'.join(fresh.splitlines()[new_node.lineno-1:new_node.end_lineno]);lines=old_source.splitlines()
        shutil.copy2(sync,RUN/'previous_sync_outbox.py');sync.write_text('\n'.join(lines[:node.lineno-1]+[replacement]+lines[node.end_lineno:])+'\n')
        helper=sync.parents[3]/'app/backend/src/services/training_dates.py';helper.write_text((RUN/'code/src/services/training_dates.py').read_text());helper.chmod(0o644)
        compile(sync.read_text(),str(sync),'exec')
        report['stage']='publish'
        es('POST','/_aliases',{'actions':[{'remove':{'index':old,'alias':'career-training-read'}},{'add':{'index':index,'alias':'career-training-read'}}]});published=True;report['published']=True
        with conn.cursor() as cur:
            cur.execute("UPDATE search_outbox o JOIN training_offerings t ON t.offering_id=o.entity_id SET o.processed_at=UTC_TIMESTAMP(6),o.last_error=NULL WHERE o.entity_type='training' AND t.source='goyong24_training' AND o.operation='upsert' AND o.source_version=t.source_version AND o.event_id>=%s AND o.processed_at IS NULL",(first_event,));report['outbox_published']=cur.rowcount
            cur.execute('SELECT source,COUNT(*) AS n FROM training_offerings GROUP BY source');report['training']=cur.fetchall()
        report.update(status='success',index=index,previous_index=old,indexed=indexed,search_checks=checks,jobs_unchanged=True,boottent_unchanged=True)
    except Exception as exc:
        if conn:conn.rollback()
        report.update(status='failed',error_type=type(exc).__name__,driver_code=exc.args[0] if exc.args and type(exc.args[0]) is int else None)
    finally:
        if conn:conn.close()
        if timer and (published or report['inserted']==0):
            subprocess.run(['systemctl','start','career-search-sync.timer'],check=False);report['sync_timer_restored']=True
        elif timer:report['sync_timer_paused_for_recovery']=True
        (RUN/'result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
        print(json.dumps(report,ensure_ascii=False),flush=True)
    return 0 if report['status']=='success' else 1
if __name__=='__main__':raise SystemExit(main())

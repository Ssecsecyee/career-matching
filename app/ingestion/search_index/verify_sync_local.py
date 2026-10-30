"""Isolated integration against loopback MySQL/Elasticsearch; no AWS/model calls."""
from pathlib import Path
from datetime import datetime,timezone
import json,os,secrets,sys
ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'app/backend'))
sys.path.insert(0,str(Path(__file__).resolve().parent))
from src.config import load_local_settings
from src.repositories.mysql_connection import connect_mysql
from src.handlers.bootstrap import sql_statements
from sync_outbox import Consumer,Engine

def main():
    load_local_settings()
    assert os.environ.get('MYSQL_HOST')=='127.0.0.1' and os.environ.get('MYSQL_PORT')=='3308'
    token=secrets.token_hex(5)
    database='career_sync_verify_'+token
    aliases={'job':'career-sync-'+token+'-jobs-read','training':'career-sync-'+token+'-training-read'}
    engine=Engine(aliases['job'],aliases['training'])
    conn=connect_mysql(credentials=('root',os.environ['MYSQL_ADMIN_PASSWORD']))
    indexes=[];created=False
    try:
        with conn.cursor() as cur:
            cur.execute('SELECT COUNT(*) AS n FROM job_postings');before=cur.fetchone()['n']
            cur.execute('CREATE DATABASE '+database+' CHARACTER SET utf8mb4');created=True
        conn.select_db(database)
        with conn.cursor() as cur:
            for sql in sql_statements((ROOT/'app/backend/database/schema.sql').read_text(encoding='utf-8')):cur.execute(sql)
        for kind,source in [('job','career-jobs-local-read'),('training','career-training-local-read')]:
            original=engine.request('GET','/'+source)
            config=next(iter(original.values()))
            index=aliases[kind]+'-v1';indexes.append(index)
            engine.request('PUT','/'+index,{'settings':{'analysis':config['settings']['index']['analysis'],'number_of_replicas':0},'mappings':config['mappings']})
            engine.request('POST','/_aliases',{'actions':[{'add':{'index':index,'alias':aliases[kind]}}]})
        engine.verify_aliases()
        consumer=Consumer(conn,engine)
        with conn.cursor() as cur:
            cur.execute("INSERT INTO job_postings(source,source_id,source_url,title,company_name,tech_stacks,addresses,recruitment_status,source_version,fetched_at) VALUES('jumpit','999001','https://example.com','React test','Synthetic',JSON_ARRAY('React'),JSON_ARRAY(),'unknown',1,UTC_TIMESTAMP())")
            job=cur.lastrowid
        def event(version,operation='upsert'):
            with conn.cursor() as cur:cur.execute("INSERT INTO search_outbox(entity_type,entity_id,source_version,operation) VALUES('job',%s,%s,%s)",(job,version,operation))
        def count():
            engine.request('POST','/'+aliases['job']+'/_refresh')
            return engine.request('GET','/'+aliases['job']+'/_count')['count']
        event(1);assert consumer.run()['processed']==1;assert count()==1
        assert consumer.run()['processed']==0
        with conn.cursor() as cur:cur.execute('UPDATE job_postings SET source_version=2,title=%s WHERE job_id=%s',('Updated React',job))
        event(2);event(1,'close');assert consumer.run()['processed']==2
        hit=engine.request('POST','/'+aliases['job']+'/_search',{'query':{'match_all':{}}})['hits']['hits'][0]
        # Search can use the previous refresh generation; explicitly refresh.
        count();hit=engine.request('POST','/'+aliases['job']+'/_search',{'query':{'match_all':{}}})['hits']['hits'][0]
        assert hit['_source']['source_version']=='2'
        event(2,'delete');assert consumer.run()['processed']==1;assert count()==0
        with conn.cursor() as cur:
            cur.execute('UPDATE search_outbox SET processed_at=NULL WHERE entity_id=%s AND operation=%s',(job,'upsert'))
        assert consumer.run()['processed']==2;assert count()==0
        with conn.cursor() as cur:cur.execute('UPDATE job_postings SET source_version=3 WHERE job_id=%s',(job,))
        event(3)
        real_apply=engine.apply
        engine.apply=lambda *a,**k: (_ for _ in ()).throw(TimeoutError())
        failed=consumer.run();assert failed['failed']==1 and failed['pending']==1
        assert consumer.run()['processed']==0
        engine.apply=real_apply
        with conn.cursor() as cur:cur.execute('UPDATE search_outbox SET last_error=NULL WHERE processed_at IS NULL')
        assert consumer.run()['processed']==1;assert count()==1
        with conn.cursor() as cur:
            cur.execute('UPDATE job_postings SET source_version=4,additional_sections=%s WHERE job_id=%s',(json.dumps({'page_extraction':{'deadline':{'raw':'2000-01-01','precision':'date_only'}}}),job))
        result=consumer.run();assert result['expiry_events']==1 and result['processed']==1;assert count()==0
        with conn.cursor() as cur:
            cur.execute('SELECT recruitment_status FROM job_postings WHERE job_id=%s',(job,));assert cur.fetchone()['recruitment_status']=='unknown'
            cur.execute("INSERT INTO training_offerings(source,source_id,source_url,title,recruitment_status,fetched_at) VALUES('boottent','synthetic','https://example.com','React historical','closed',UTC_TIMESTAMP())")
            training=cur.lastrowid
            cur.execute("INSERT INTO search_outbox(entity_type,entity_id,source_version,operation) VALUES('training',%s,1,'upsert')",(training,))
        assert consumer.run()['processed']==1
        engine.request('POST','/'+aliases['training']+'/_refresh')
        assert engine.request('GET','/'+aliases['training']+'/_count')['count']==1
        with conn.cursor() as cur:
            cur.execute('SELECT COUNT(*) AS n FROM career_matching.job_postings');assert cur.fetchone()['n']==before
        print(json.dumps({'status':'passed','new_update_duplicate_reverse_delete_retry_expiry_training':True,'original_jobs_unchanged':True,'aws_calls':0,'model_calls':0}))
    finally:
        for index in indexes:
            engine.request('DELETE','/'+index)
        if created:
            with conn.cursor() as cur:cur.execute('DROP DATABASE '+database)
        conn.close()

if __name__=='__main__':main()

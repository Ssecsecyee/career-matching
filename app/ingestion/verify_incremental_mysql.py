"""Isolated MySQL verification only. Requires TEST_INGEST_MYSQL_* environment.
Creates a unique verification database on loopback, never the production database.
"""
import copy
from datetime import datetime,timezone,timedelta
import json
import os
from pathlib import Path
import re
import secrets
import sys

import pymysql
from incremental_jumpit import prepare,ingest,decoded


def main():
    port=int(os.environ['TEST_INGEST_MYSQL_PORT'])
    if port in {3306,3308,13308} or not 1024<=port<=65535:raise ValueError('Use a separate ephemeral test port')
    password=os.environ['TEST_INGEST_MYSQL_PASSWORD']
    database='career_ingestion_verify_'+secrets.token_hex(5)
    if not re.fullmatch(r'career_ingestion_verify_[0-9a-f]{10}',database):raise ValueError('Invalid verification database')
    options={'host':'127.0.0.1','port':port,'user':'root','password':password,'charset':'utf8mb4',
        'autocommit':True,'cursorclass':pymysql.cursors.DictCursor,'init_command':"SET time_zone='+00:00'"}
    root=pymysql.connect(**options)
    runtime=None
    try:
        with root.cursor() as cur:
            cur.execute('CREATE DATABASE '+database+' CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci')
        root.select_db(database)
        sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
        from src.handlers.bootstrap import sql_statements
        schema=Path(__file__).resolve().parents[1]/'backend/database/schema.sql'
        with root.cursor() as cur:
            for statement in sql_statements(schema.read_text(encoding='utf-8')):cur.execute(statement)
            cur.execute("CREATE USER 'career_ingest_verify'@'%%' IDENTIFIED BY %s",(password,))
            cur.execute('GRANT SELECT,INSERT,UPDATE ON '+database+".job_postings TO 'career_ingest_verify'@'%'")
            cur.execute('GRANT INSERT ON '+database+".search_outbox TO 'career_ingest_verify'@'%'")
        options.update(database=database,user='career_ingest_verify')
        runtime=pymysql.connect(**options)
        batch=Path(sys.argv[1])
        rows,_=prepare(batch)
        assert len(rows)==10
        preview=ingest(rows,runtime)
        assert preview['counts']=={'inserted':10}
        first=ingest(rows,runtime,apply=True)
        assert first['counts']=={'inserted':10}
        repeated=ingest(rows,runtime,apply=True)
        assert repeated['counts']=={'stale_or_replayed':10}
        refreshed=copy.deepcopy(rows)
        for row in refreshed:row['fetched_at']=(datetime.fromisoformat(row['fetched_at'])+timedelta(seconds=1)).isoformat();row['last_seen_at']=row['fetched_at']
        assert ingest(refreshed,runtime,apply=True)['counts']=={'unchanged':10}
        changed=copy.deepcopy(refreshed[:1])
        changed[0]['fetched_at']=(datetime.fromisoformat(changed[0]['fetched_at'])+timedelta(seconds=1)).isoformat()
        changed[0]['qualifications']+='\n[isolated verification change]'
        assert ingest(changed,runtime,apply=True)['counts']=={'updated':1}
        with root.cursor() as cur:
            cur.execute('SELECT COUNT(*) AS n FROM job_postings');assert cur.fetchone()['n']==10
            cur.execute('SELECT COUNT(*) AS n FROM search_outbox');assert cur.fetchone()['n']==11
            cur.execute('SELECT source_version,qualifications FROM job_postings WHERE source_id=%s',(changed[0]['source_id'],))
            before=cur.fetchone();assert before['source_version']==2
            cur.execute('REVOKE INSERT ON '+database+".search_outbox FROM 'career_ingest_verify'@'%'")
        broken=copy.deepcopy(changed)
        broken[0]['fetched_at']=(datetime.fromisoformat(broken[0]['fetched_at'])+timedelta(seconds=1)).isoformat()
        broken[0]['qualifications']+=' should roll back'
        failed=False
        try:ingest(broken,runtime,apply=True)
        except pymysql.err.OperationalError as exc:
            if exc.args[0]!=1142:raise
            failed=True
        assert failed
        with root.cursor() as cur:
            cur.execute('SELECT source_version,qualifications FROM job_postings WHERE source_id=%s',(changed[0]['source_id'],))
            assert cur.fetchone()==before
            cur.execute('SELECT COUNT(*) AS n FROM search_outbox');assert cur.fetchone()['n']==11
            cur.execute("SELECT COUNT(*) AS n FROM job_postings WHERE application_notes IS NOT NULL");combined=cur.fetchone()['n']
            cur.execute("SELECT COUNT(*) AS n FROM job_postings WHERE deadline_at IS NULL AND JSON_UNQUOTE(JSON_EXTRACT(additional_sections,'$.page_extraction.deadline.precision'))='date_only'");dated=cur.fetchone()['n']
        assert combined==8 and dated==10
        print(json.dumps({'status':'passed','isolated_mysql':True,'jobs':10,'combined_sections':combined,'date_only_preserved':dated,
            'duplicate_retry':'passed','newer_identical_version_stable':'passed','content_revision':'passed','outbox_failure_rollback':'passed','production_changes':0}))
    finally:
        if runtime:runtime.close()
        root.close()

if __name__=='__main__':main()

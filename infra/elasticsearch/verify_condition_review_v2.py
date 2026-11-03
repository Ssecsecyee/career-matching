"""Read-only DB/ES pilot reconciliation, including correctly excluded expired postings."""
import hashlib,json,subprocess,sys
from pathlib import Path
from urllib.error import HTTPError
BASE=Path('/opt/career');RELEASE=Path(__file__).resolve().parents[2]

def main():
    sys.path.insert(0,str(RELEASE/'app/backend'));sys.path.insert(0,str(RELEASE/'app/ingestion/search_index'))
    from src.services.condition_review import validated_envelope,projection,condition_hash
    from src.repositories.condition_drafts import decode,candidate_hash
    from src.schemas.condition_review import POLICY_VERSION
    from src.services.deadlines import expired
    from sync_outbox import Engine
    import pymysql
    def connect(settings):return pymysql.connect(host='127.0.0.1',port=3308,user=settings['user'],password=settings['password'],database=settings['database'],charset='utf8mb4',autocommit=True,cursorclass=pymysql.cursors.DictCursor,connect_timeout=5,read_timeout=30)
    settings=json.loads((BASE/'search-sync.json').read_text());engine=Engine(settings['jobs_alias'],settings['training_alias'])
    payload=json.loads((RELEASE/'reviewed-pilot.json').read_text());published=[];excluded=[];indexed=0
    with connect(settings) as reader,connect(json.loads((BASE/'condition-review-approver.json').read_text())) as approver:
        for item in payload:
            with reader.cursor() as c:
                c.execute('SELECT * FROM job_postings WHERE job_id=%s',(item['job']['job_id'],));row=c.fetchone()
            expected=validated_envelope(row,item['review'])
            with approver.cursor() as c:
                c.execute('SELECT review_id,classification FROM job_condition_reviews WHERE job_id=%s AND condition_hash=%s AND policy_version=%s',(row['job_id'],condition_hash(row),POLICY_VERSION));saved=c.fetchone()
                if not saved or validated_envelope(row,decode(saved['classification']))!=expected:raise ValueError('DB published review mismatch')
                c.execute("SELECT draft_id,status,review_id FROM job_condition_review_drafts WHERE job_id=%s AND candidate_hash=%s",(row['job_id'],candidate_hash(expected)));draft=c.fetchone()
                if not draft or draft['status']!='published' or draft['review_id']!=saved['review_id']:raise ValueError('Draft publication state mismatch')
            with reader.cursor() as c:
                c.execute('SELECT processed_at,last_error FROM search_outbox WHERE entity_type=%s AND entity_id=%s AND operation=%s',('job',row['job_id'],'r:'+str(saved['review_id'])));events=c.fetchall()
                if len(events)!=1 or events[0]['processed_at'] is None or events[0]['last_error'] is not None:raise ValueError('Projection event not successfully consumed')
            identity=json.dumps([row['source'],str(row['source_id'])],ensure_ascii=False,separators=(',',':'));key=hashlib.sha256(identity.encode()).hexdigest()
            if row['recruitment_status'] in {'closed','unavailable'} or expired(row):
                try:engine.request('GET','/'+settings['jobs_alias']+'/_doc/'+key)
                except HTTPError as exc:
                    if exc.code!=404:raise
                else:raise ValueError('Excluded source still indexed')
                excluded.append(str(row['source_id']))
            else:
                actual=engine.request('GET','/'+settings['jobs_alias']+'/_doc/'+key)['_source']
                for field,value in projection(row,expected).items():
                    if actual.get(field)!=value:raise ValueError('ES projection mismatch')
                if actual['qualifications']!=row['qualifications'] or actual['preferred_requirements']!=row['preferred_requirements']:raise ValueError('ES original text mismatch')
                indexed+=len(actual['classified_conditions'])
            published.append({'source_id':str(row['source_id']),'review_id':saved['review_id'],'draft_id':draft['draft_id']})
        with reader.cursor() as c:
            c.execute('SELECT job_id,source_version,content_hash FROM job_postings ORDER BY job_id');jobs=c.fetchall()
            c.execute('SELECT offering_id,source_version,content_hash FROM training_offerings ORDER BY offering_id');training=c.fetchall()
        fingerprint=hashlib.sha256(json.dumps([jobs,training],sort_keys=True,default=str).encode()).hexdigest()
        baseline=json.loads((BASE/'condition-review-install.json').read_text())['source_rows_unchanged']
        if baseline['hash']!=fingerprint:raise ValueError('Source fingerprint changed from connection baseline')
    active={name:subprocess.run(['systemctl','is-active','--quiet',name]).returncode==0 for name in ('career-worker','career-search-sync.timer')}
    if not all(active.values()):raise ValueError('Service inactive')
    report={'status':'published_and_verified','published':published,'conditions':sum(len(x['review']['conditions']) for x in payload),'indexed_conditions':indexed,'excluded_source_ids':excluded,'source_unchanged':True,'jobs':len(jobs),'training':len(training),'model_calls':0,'services':active,'independent_human_evaluation':False,'question_selection_enabled':False,'ranking_enabled':False}
    (BASE/'condition-review-v2-install.json').write_text(json.dumps(report,indent=2));(BASE/'condition-review-v2-install.json').chmod(0o600)
    print(json.dumps(report));return 0
if __name__=='__main__':
    try:raise SystemExit(main())
    except Exception as exc:
        print(json.dumps({'status':'failed','error_type':type(exc).__name__,'http_status':getattr(exc,'code',None)}));raise SystemExit(1)

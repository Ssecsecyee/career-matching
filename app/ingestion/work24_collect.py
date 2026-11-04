"""Resumable Work24 list inventory. No operational DB, ES, AWS or model calls."""
import argparse
from datetime import date, datetime, timedelta, timezone
import gzip
import hashlib
import json
import math
from pathlib import Path
import sqlite3
import time
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, build_opener, HTTPRedirectHandler
import xml.etree.ElementTree as ET

KST=timezone(timedelta(hours=9))
SERVICES={'card':(310,'WORK24_CARD_TRAINING_API_KEY'),'employer':(311,'WORK24_EMPLOYER_TRAINING_API_KEY'),'consortium':(312,'WORK24_CONSORTIUM_TRAINING_API_KEY'),'work_study':(313,'WORK24_WORK_STUDY_API_KEY')}


def canonical(value):return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'))
def digest(value):return hashlib.sha256(canonical(value).encode()).hexdigest()
def date_windows(start,end,days=7):
    if end<start or not 1<=days<=366:raise ValueError('invalid_date_window')
    while start<=end:
        stop=min(end,start+timedelta(days=days-1))
        yield start,stop
        start=stop+timedelta(days=1)

def identity(row):
    fields=['trprId','trprDegr','trainstCstId']
    if any(not isinstance(row.get(k),str) or not row[k].strip() for k in fields):raise ValueError('missing_identity')
    return canonical([row[k] for k in fields])
def start_state(row,today):
    try:start=date.fromisoformat(row.get('traStartDate',''))
    except (ValueError,TypeError):return 'unknown'
    return 'started' if start<=today else 'future'
def detail_fingerprint(row):
    # Mutable enrollment/rating/icon counters must not force expensive detail reads.
    names=['trprId','trprDegr','trainstCstId','title','subTitle','titleLink','traStartDate','traEndDate','ncsCd','trainTarget','trainTargetCd','address','telNo','courseMan','realMan','contents']
    return digest({k:row.get(k) for k in names})
def parse(raw):
    if b'<!DOCTYPE' in raw.upper() or b'<!ENTITY' in raw.upper():raise ValueError('invalid_xml')
    root=ET.fromstring(raw)
    if root.tag!='HRDNet':raise ValueError('unexpected_response')
    total=root.findtext('scn_cnt')
    if total is None or not total.isdigit():raise ValueError('provider_error_or_missing_count')
    rows=[{c.tag:c.text or '' for c in item} for item in root.findall('./srchList/scn_list')]
    return int(total),rows
class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None

def fetch(service,key,start,end,page):
    number=SERVICES[service][0]
    params=dict(authKey=key,returnType='XML',outType='1',pageNum=str(page),pageSize='100',sort='ASC',sortCol='2',srchTraStDt=start.replace('-',''),srchTraEndDt=end.replace('-',''))
    url=f'https://www.work24.go.kr/cm/openApi/call/hr/callOpenApiSvcInfo{number}L01.do'
    request=Request(url+'?'+urlencode(params),headers={'User-Agent':'CareerMatching-Work24-Inventory/1.0'})
    with build_opener(NoRedirect()).open(request,timeout=30) as response:
        raw=response.read(2*1024*1024+1)
    if len(raw)>2*1024*1024:raise ValueError('response_too_large')
    return raw

def init(db):
    db.executescript('''
    CREATE TABLE IF NOT EXISTS runs(id TEXT PRIMARY KEY,start TEXT,end TEXT,status TEXT);
    CREATE TABLE IF NOT EXISTS buckets(run TEXT,service TEXT,start TEXT,end TEXT,page INTEGER DEFAULT 1,total INTEGER,status TEXT DEFAULT 'pending',last_hash TEXT,PRIMARY KEY(run,service,start,end));
    CREATE TABLE IF NOT EXISTS records(service TEXT,identity TEXT,payload TEXT,hash TEXT,detail_hash TEXT,first_seen TEXT,last_seen TEXT,PRIMARY KEY(service,identity));
    CREATE TABLE IF NOT EXISTS seen(run TEXT,service TEXT,identity TEXT,change TEXT,PRIMARY KEY(run,service,identity));
    CREATE TABLE IF NOT EXISTS pages(run TEXT,service TEXT,start TEXT,end TEXT,page INTEGER,total INTEGER,rows INTEGER,hash TEXT,PRIMARY KEY(run,service,start,end,page));
    CREATE TABLE IF NOT EXISTS detail_cache(service TEXT,identity TEXT,detail_hash TEXT,checked_at TEXT,detail_path TEXT,PRIMARY KEY(service,identity));
    CREATE TABLE IF NOT EXISTS detail_queue(service TEXT,identity TEXT,detail_hash TEXT,reason TEXT,status TEXT DEFAULT 'pending',PRIMARY KEY(service,identity));
    ''')

def save_page(db,run,bucket,total,rows,raw_hash):
    service,start,end,page=bucket
    now=datetime.now(KST).isoformat()
    for row in rows:
        key=identity(row);hashed=digest(row);fingerprint=detail_fingerprint(row)
        old=db.execute('SELECT hash,detail_hash FROM records WHERE service=? AND identity=?',(service,key)).fetchone()
        change='new' if old is None else 'unchanged' if old[0]==hashed else 'changed'
        db.execute('INSERT INTO seen VALUES(?,?,?,?) ON CONFLICT DO NOTHING',(run,service,key,change))
        db.execute('INSERT INTO records VALUES(?,?,?,?,?,?,?) ON CONFLICT(service,identity) DO UPDATE SET payload=excluded.payload,hash=excluded.hash,detail_hash=excluded.detail_hash,last_seen=excluded.last_seen',(service,key,canonical(row),hashed,fingerprint,now,now))
        if start_state(row,datetime.now(KST).date())=='future':
            cached=db.execute('SELECT checked_at FROM detail_cache WHERE service=? AND identity=?',(service,key)).fetchone()
            stale=cached is not None and datetime.fromisoformat(cached[0]) < datetime.now(KST)-timedelta(days=3)
            reason='new' if old is None else 'list_changed' if old[1]!=fingerprint else 'recheck_due' if stale else None
            if reason:
                db.execute("INSERT INTO detail_queue VALUES(?,?,?,?,'pending') ON CONFLICT(service,identity) DO UPDATE SET detail_hash=excluded.detail_hash,reason=excluded.reason,status='pending'",(service,key,fingerprint,reason))
        else:
            db.execute("UPDATE detail_queue SET status='excluded_started_or_unknown' WHERE service=? AND identity=?",(service,key))
    db.execute('INSERT INTO pages VALUES(?,?,?,?,?,?,?,?)',(run,service,start,end,page,total,len(rows),raw_hash))
    db.execute('UPDATE buckets SET page=?,total=?,last_hash=? WHERE run=? AND service=? AND start=? AND end=?',(page+1,total,digest(rows),run,service,start,end))

def report(db,run,out):
    today=datetime.now(KST).date();services={}
    for service in SERVICES:
        counts={'unique_records':0,'future':0,'started':0,'unknown':0,'new':0,'changed':0,'unchanged':0,'outside_requested_range':0}
        bounds=db.execute('SELECT start,end FROM runs WHERE id=?',(run,)).fetchone()
        for payload,change in db.execute('SELECT r.payload,s.change FROM seen s JOIN records r USING(service,identity) WHERE s.run=? AND s.service=?',(run,service)):
            row=json.loads(payload);counts['unique_records']+=1;counts[start_state(row,today)]+=1;counts[change]+=1
            try:d=date.fromisoformat(row.get('traStartDate',''));counts['outside_requested_range']+=int(not date.fromisoformat(bounds[0])<=d<=date.fromisoformat(bounds[1]))
            except (ValueError,TypeError):pass
        counts['pages']=db.execute('SELECT COUNT(*) FROM pages WHERE run=? AND service=?',(run,service)).fetchone()[0]
        services[service]=counts
    pending=db.execute("SELECT COUNT(*) FROM buckets WHERE run=? AND status='pending'",(run,)).fetchone()[0]
    value={'run':run,'as_of_kst':datetime.now(KST).isoformat(),'status':db.execute('SELECT status FROM runs WHERE id=?',(run,)).fetchone()[0],'pending_buckets':pending,'services':services,'operational_database_writes':0,'es_writes':0,'model_calls':0,'scope':'start-date window; not all historical courses','snapshot_caveat':'Provider data can change while paginating; observed unique count is not a frozen provider snapshot.'}
    tmp=out/'report.tmp';tmp.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8');tmp.replace(out/'report.json')
    return value

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--env-path',type=Path,required=True);ap.add_argument('--output',type=Path,required=True);ap.add_argument('--start',type=date.fromisoformat,required=True);ap.add_argument('--end',type=date.fromisoformat,required=True);ap.add_argument('--resume',action='store_true');ap.add_argument('--catalog',type=Path);ap.add_argument('--run-id');ap.add_argument('--interval',type=float,default=1.25);ap.add_argument('--window-days',type=int,default=7)
    args=ap.parse_args()
    if args.end<args.start or args.interval<1.25 or not 1<=args.window_days<=366:raise ValueError('invalid_scope_or_interval')
    keys={}
    for line in args.env_path.read_text(encoding='utf-8-sig').splitlines():
        if line.lstrip().startswith('#') or '=' not in line:continue
        k,v=line.split('=',1);keys[k.strip()]=v.strip().strip('"').strip("'")
    if any(not keys.get(v[1]) for v in SERVICES.values()):raise ValueError('missing_service_key')
    if args.output.exists() and any(args.output.iterdir()) and not args.resume:raise ValueError('nonempty_output_requires_resume')
    args.output.mkdir(parents=True,exist_ok=True)
    catalog=args.catalog or args.output/'catalog.sqlite3'
    catalog.parent.mkdir(parents=True,exist_ok=True)
    db=sqlite3.connect(catalog);init(db)
    run=args.run_id or args.start.isoformat()+'_'+args.end.isoformat()
    prior=db.execute('SELECT status FROM runs WHERE id=?',(run,)).fetchone()
    if prior and not args.resume:raise ValueError('resume_required')
    if prior and db.execute('SELECT start,end FROM runs WHERE id=?',(run,)).fetchone()!=(args.start.isoformat(),args.end.isoformat()):raise ValueError('resume_scope_mismatch')
    if not prior:
        db.execute("INSERT INTO runs VALUES(?,?,?,'running')",(run,args.start.isoformat(),args.end.isoformat()))
        for service in SERVICES:
            for lo,hi in date_windows(args.start,args.end,args.window_days):db.execute('INSERT INTO buckets(run,service,start,end) VALUES(?,?,?,?)',(run,service,lo.isoformat(),hi.isoformat()))
        db.commit()
    db.execute("UPDATE runs SET status='running' WHERE id=?",(run,));db.commit()
    requests=0
    try:
        while True:
            b=db.execute("SELECT service,start,end,page,total,last_hash FROM buckets WHERE run=? AND status='pending' ORDER BY service,start LIMIT 1",(run,)).fetchone()
            if b is None:break
            service,start,end,page,old_total,last_hash=b
            if page>1000:raise ValueError('page_limit_requires_partition')
            raw=fetch(service,keys[SERVICES[service][1]],start,end,page);requests+=1
            total,rows=parse(raw)
            # Over-large windows are partitioned before consuming their pages.
            if page==1 and total>100000:
                a,z=date.fromisoformat(start),date.fromisoformat(end)
                if a==z:raise ValueError('single_day_over_page_cap_requires_ncs_partition')
                mid=a+(z-a)//2
                with db:
                    db.execute("UPDATE buckets SET status='split' WHERE run=? AND service=? AND start=? AND end=?",(run,service,start,end))
                    for lo,hi in [(a,mid),(mid+timedelta(days=1),z)]:db.execute('INSERT INTO buckets(run,service,start,end) VALUES(?,?,?,?)',(run,service,lo.isoformat(),hi.isoformat()))
                time.sleep(args.interval);continue
            if len(rows)>100 or (not rows and (page-1)*100<total):raise ValueError('page_incomplete')
            if rows and digest(rows)==last_hash:raise ValueError('repeated_page')
            for row in rows:identity(row)
            # Store raw pages only after all configured secrets are removed.
            safe=raw.decode('utf-8-sig')
            for secret in keys.values():
                if secret:safe=safe.replace(secret,'[REDACTED]')
            dest=args.output/'pages'/service/(start+'_'+end);dest.mkdir(parents=True,exist_ok=True)
            with gzip.open(dest/(str(page)+'.xml.gz'),'wt',encoding='utf-8') as stream:stream.write(safe)
            with db:
                save_page(db,run,(service,start,end,page),total,rows,hashlib.sha256(raw).hexdigest())
                if page*100>=total:db.execute("UPDATE buckets SET status='done' WHERE run=? AND service=? AND start=? AND end=?",(run,service,start,end))
            if requests%20==0:
                value=report(db,run,args.output)
                print(json.dumps({'status':'collecting','service':service,'requests':requests,'unique':sum(x['unique_records'] for x in value['services'].values())}),flush=True)
            time.sleep(args.interval)
        with db:db.execute("UPDATE runs SET status='collected_pending_reconciliation' WHERE id=?",(run,))
    except Exception as exc:
        with db:db.execute("UPDATE runs SET status='stopped' WHERE id=?",(run,))
        report(db,run,args.output)
        # Never print exception strings which may contain authenticated URLs.
        print(json.dumps({'status':'stopped','error_type':type(exc).__name__,'http_status':getattr(exc,'code',None),'resume':True}),flush=True)
        return 1
    finally:
        value=report(db,run,args.output);db.close()
    print(json.dumps({'status':value['status'],'services':value['services']},ensure_ascii=False),flush=True)
    return 0

if __name__=='__main__':raise SystemExit(main())

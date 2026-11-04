"""Bounded detail queue worker; writes local raw/cache/normalized batches only."""
import argparse
from datetime import date,datetime,timedelta
import gzip
import json
from pathlib import Path
import sqlite3
import time
from urllib.parse import urlencode,urlsplit,urlunsplit
from urllib.request import Request,build_opener
import xml.etree.ElementTree as ET
from work24_collect import SERVICES,KST,NoRedirect,canonical,digest,init,start_state,detail_fingerprint
from normalize_training import normalize_training


def xml_value(node):
    children=list(node)
    if not children:return node.text or ''
    value={}
    for child in children:
        item=xml_value(child)
        if child.tag not in value:value[child.tag]=item
        elif isinstance(value[child.tag],list):value[child.tag].append(item)
        else:value[child.tag]=[value[child.tag],item]
    return value

def read_response(raw):
    if b'<!DOCTYPE' in raw.upper() or b'<!ENTITY' in raw.upper():raise ValueError('invalid_xml')
    root=ET.fromstring(raw)
    if root.tag!='HRDNet':raise ValueError('unexpected_response')
    return xml_value(root)

def normalize_course(service,row,detail,schedule,observed_at):
    base=detail.get('inst_base_info') or {}
    values=schedule.get('scn_list') or []
    if isinstance(values,dict):values=[values]
    matches=[v for v in values if v.get('trprId')==row['trprId'] and v.get('trprDegr')==row['trprDegr']]
    if base.get('trprId')!=row['trprId'] or base.get('trprDegr')!=row['trprDegr'] or len(matches)!=1:raise ValueError('detail_identity_mismatch')
    if base.get('ncsCd') and row.get('ncsCd') and base['ncsCd']!=row['ncsCd']:raise ValueError('ncs_conflict')
    dates={}
    for output,list_key,detail_key in [('starts_at','traStartDate','trStaDt'),('ends_at','traEndDate','trEndDt')]:
        raw=row.get(list_key);other=matches[0].get(detail_key)
        if raw and other and raw.replace('-','')!=other.replace('-',''):raise ValueError('date_conflict')
        if raw:
            date.fromisoformat(raw)
            dates[output]={'raw':raw,'precision':'date_only'}
    url=row.get('titleLink','');parsed=urlsplit(url)
    if parsed.scheme=='http' and parsed.hostname=='www.work24.go.kr':url=urlunsplit(('https',parsed.netloc,parsed.path,parsed.query,''))
    identity=canonical([row['trprId'],row['trprDegr'],row['trainstCstId']])
    source_id=service+':'+digest(identity)
    record={'source':'goyong24_training','source_id':source_id,'source_url':url,'fetched_at':observed_at,
        'course_key':service+':'+row['trprId'],'cohort_name':row['trprDegr'],
        'title':row.get('title'),'provider_name':row.get('subTitle'),
        'curriculum':row.get('contents') or None,'eligibility':None,
        'dates':dates,'addresses':[row['address']] if row.get('address') else [],
        'recruitment_status':'unknown','delivery_mode':'unknown','tuition':None,
        'original_categories':[row['ncsCd']] if row.get('ncsCd') else [],
        'collection_metadata':{'retrieval_method':'official_work24_api','service':service,
            'course_id':row['trprId'],'round':row['trprDegr'],'institution_id':row['trainstCstId'],'list_detail_fingerprint':detail_fingerprint(row),
            'ncs_code':row.get('ncsCd'),'ncs_name':base.get('ncsNm'),
            'training_target':row.get('trainTarget'),'training_target_code':row.get('trainTargetCd'),
            'detail_sections':{k:v for k,v in detail.items() if k in ('inst_base_info','inst_detail_info')},
            'schedule':matches[0]}}
    normalized=normalize_training(record)
    normalized['additional_sections']['recommendation_eligible']=False
    normalized['additional_sections']['collection_metadata']=record['collection_metadata']
    normalized['content_hash']=digest({k:v for k,v in normalized.items() if k not in ('content_hash','fetched_at','last_seen_at','raw_detail')})
    return normalized

def request_detail(service,key,row,kind):
    number=SERVICES[service][0]
    suffix=('L02' if kind=='detail' else 'L03') if service=='card' else ('D01' if kind=='detail' else 'D02')
    params=dict(authKey=key,returnType='XML',outType='2',srchTrprId=row['trprId'],srchTrprDegr=row['trprDegr'])
    if kind=='detail' or service=='card':params['srchTorgId']=row['trainstCstId']
    url=f'https://www.work24.go.kr/cm/openApi/call/hr/callOpenApiSvcInfo{number}{suffix}.do'
    with build_opener(NoRedirect()).open(Request(url+'?'+urlencode(params),headers={'User-Agent':'CareerMatching-Work24-Detail/1.0'}),timeout=30) as response:raw=response.read(2*1024*1024+1)
    if len(raw)>2*1024*1024:raise ValueError('response_too_large')
    return raw

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--catalog',type=Path,required=True);ap.add_argument('--env-path',type=Path,required=True);ap.add_argument('--output',type=Path,required=True);ap.add_argument('--max-items',type=int,default=20);ap.add_argument('--live',action='store_true');args=ap.parse_args()
    if not 1<=args.max_items<=1000:raise ValueError('invalid_batch_size')
    if not args.catalog.is_file():raise ValueError('catalog_missing')
    db=sqlite3.connect(args.catalog);init(db)
    jobs=db.execute("SELECT q.service,q.identity,q.detail_hash,r.payload FROM detail_queue q JOIN records r USING(service,identity) WHERE q.status='pending' ORDER BY q.service,q.identity LIMIT ?",(args.max_items,)).fetchall()
    if not args.live:
        print(json.dumps({'status':'planned','jobs':len(jobs),'maximum_requests':len(jobs)*2,'network_requests':0,'database_writes':0}));return 0
    keys={}
    for line in args.env_path.read_text(encoding='utf-8-sig').splitlines():
        if line.lstrip().startswith('#') or '=' not in line:continue
        k,v=line.split('=',1);keys[k.strip()]=v.strip().strip('"').strip("'")
    args.output.mkdir(parents=True,exist_ok=False)
    report={'completed':0,'excluded':0,'failed':0,'superseded':0,'network_requests':0,'operational_database_writes':0,'es_writes':0,'model_calls':0,'accepted_files':[]}
    try:
        for service,identity,fingerprint,payload in jobs:
            row=json.loads(payload)
            if start_state(row,datetime.now(KST).date())!='future':
                with db:db.execute("UPDATE detail_queue SET status='excluded_started_or_unknown' WHERE service=? AND identity=?",(service,identity))
                report['excluded']+=1;continue
            folder=args.output/(service+'_'+digest(identity));folder.mkdir()
            try:
                responses={}
                for kind in ['detail','schedule']:
                    raw=request_detail(service,keys[SERVICES[service][1]],row,kind);report['network_requests']+=1
                    safe=raw.decode('utf-8-sig')
                    for secret in keys.values():
                        if secret:safe=safe.replace(secret,'[REDACTED]')
                    with gzip.open(folder/(kind+'.xml.gz'),'wt',encoding='utf-8') as out:out.write(safe)
                    responses[kind]=read_response(safe.encode())
                    time.sleep(1.25)
                normalized=normalize_course(service,row,responses['detail'],responses['schedule'],datetime.now(KST).isoformat())
                (folder/'normalized.json').write_text(json.dumps(normalized,ensure_ascii=False,indent=2),encoding='utf-8')
                with db:
                    current=db.execute('SELECT detail_hash FROM records WHERE service=? AND identity=?',(service,identity)).fetchone()
                    if current is None or current[0]!=fingerprint:report['superseded']+=1;continue
                    db.execute('INSERT INTO detail_cache VALUES(?,?,?,?,?) ON CONFLICT(service,identity) DO UPDATE SET detail_hash=excluded.detail_hash,checked_at=excluded.checked_at,detail_path=excluded.detail_path',(service,identity,fingerprint,datetime.now(KST).isoformat(),str(folder/'normalized.json')))
                    db.execute("UPDATE detail_queue SET status='completed' WHERE service=? AND identity=? AND detail_hash=?",(service,identity,fingerprint))
                report['completed']+=1;report['accepted_files'].append(str(folder/'normalized.json'))
            except Exception as exc:
                report['failed']+=1;report['error_type']=type(exc).__name__;report['http_status']=getattr(exc,'code',None)
                # Keep pending for a bounded later retry. Never echo URLs or raw errors.
                break
    finally:
        (args.output/'report.json').write_text(json.dumps(report,indent=2),encoding='utf-8');db.close()
    print(json.dumps(report),flush=True)
    return 1 if report['failed'] else 0

if __name__=='__main__':raise SystemExit(main())

"""Offline list-only common training export. Missing details remain unconfirmed."""
import argparse
from datetime import date,datetime
import json
from pathlib import Path
import sqlite3
from urllib.parse import urlsplit,urlunsplit
from work24_collect import identity,digest,start_state,KST,detail_fingerprint
from normalize_training import normalize_training


def canonical_stable(row):
    return json.dumps({k:v for k,v in row.items() if k not in ('content_hash','fetched_at','last_seen_at','raw_detail')},ensure_ascii=False)


def normalize_list(service,row,observed_at):
    url=row.get('titleLink','');parts=urlsplit(url)
    if parts.scheme=='http' and parts.hostname in ('work24.go.kr','www.work24.go.kr'):url=urlunsplit(('https',parts.netloc,parts.path,parts.query,''))
    dates={}
    for target,field in [('starts_at','traStartDate'),('ends_at','traEndDate')]:
        if row.get(field):
            date.fromisoformat(row[field]);dates[target]={'raw':row[field],'precision':'date_only'}
    metadata={'retrieval_method':'official_work24_api','validation_level':'list_schema_only','service':service,'course_id':row['trprId'],'round':row['trprDegr'],'institution_id':row['trainstCstId'],'ncs_code':row.get('ncsCd'),'list_record':row,'list_detail_fingerprint':detail_fingerprint(row)}
    record={'source':'goyong24_training','source_id':service+':'+digest(identity(row)),'source_url':url,'fetched_at':observed_at,'course_key':service+':'+row['trprId'],'cohort_name':row['trprDegr'],'title':row.get('title'),'provider_name':row.get('subTitle'),'curriculum':row.get('contents') or None,'recruitment_status':'unknown','delivery_mode':'unknown','tuition':None,'dates':dates,'addresses':[row['address']] if row.get('address') else [],'original_categories':[row['ncsCd']] if row.get('ncsCd') else [],'collection_metadata':metadata}
    result=normalize_training(record)
    result['additional_sections']['recommendation_eligible']=False
    result['additional_sections']['collection_metadata']=metadata
    stable=json.loads(canonical_stable(result))
    stable['additional_sections']['collection_metadata'].pop('list_record',None)
    result['content_hash']=digest(stable)
    return result

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--catalog',type=Path,required=True);ap.add_argument('--run-id',required=True);ap.add_argument('--output',type=Path,required=True);ap.add_argument('--db-inventory',type=Path);args=ap.parse_args()
    known=None
    if args.db_inventory:
        snapshot=json.loads(args.db_inventory.read_text(encoding='utf-8-sig'))
        generated=datetime.fromisoformat(snapshot['generated_at'])
        if snapshot.get('source')!='goyong24_training' or generated.tzinfo is None or not 0<=(datetime.now(KST)-generated).total_seconds()<=86400:raise ValueError('stale_or_invalid_db_inventory')
        known={r['source_id']:r for r in snapshot['records']}
        if len(known)!=len(snapshot['records']):raise ValueError('duplicate_db_inventory_id')
    args.output.mkdir(parents=True,exist_ok=False)
    db=sqlite3.connect(args.catalog.resolve().as_uri()+'?mode=ro',uri=True)
    state=db.execute('SELECT status FROM runs WHERE id=?',(args.run_id,)).fetchone()
    if state is None or state[0]!='collected_pending_reconciliation':raise ValueError('collection_not_finished')
    report={'normalized_future':0,'excluded_started':0,'excluded_unknown':0,'quarantined':0,'validation_level':'list_schema_only','database_writes':0,'network_requests':0,'db_new':0,'db_changed_review':0,'db_unchanged':0,'db_comparison':'performed' if known is not None else 'not_performed'}
    with (args.output/'training.future.normalized.jsonl').open('x',encoding='utf-8') as output,(args.output/'quarantine.jsonl').open('x',encoding='utf-8') as bad,(args.output/'training.changed.review.jsonl').open('x',encoding='utf-8') as changed:
        for service,raw,seen in db.execute('SELECT r.service,r.payload,r.last_seen FROM records r JOIN seen s USING(service,identity) WHERE s.run=? ORDER BY r.service,r.identity',(args.run_id,)):
            row=json.loads(raw);state=start_state(row,datetime.now(KST).date())
            if state!='future':report['excluded_'+state]+=1;continue
            try:
                value=normalize_list(service,row,seen)
                report['normalized_future']+=1
                previous=known.get(value['source_id']) if known is not None else None
                if previous is not None:
                    if previous['content_hash']==value['content_hash']:report['db_unchanged']+=1
                    else:
                        report['db_changed_review']+=1;changed.write(json.dumps(value,ensure_ascii=False)+'\n')
                    continue
                if known is not None:report['db_new']+=1
                output.write(json.dumps(value,ensure_ascii=False)+'\n')
            except (ValueError,TypeError,KeyError) as exc:
                report['quarantined']+=1;bad.write(json.dumps({'service':service,'identity':identity(row),'error_type':type(exc).__name__})+'\n')
    db.close()
    (args.output/'report.json').write_text(json.dumps(report,indent=2),encoding='utf-8');print(json.dumps(report))
    return 0
if __name__=='__main__':raise SystemExit(main())

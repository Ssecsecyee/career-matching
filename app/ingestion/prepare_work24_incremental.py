"""Offline card-only merge of verified base export and bounded recheck runs."""
import argparse,json,sqlite3
from pathlib import Path
from datetime import datetime
from work24_collect import KST,start_state
from work24_export import normalize_list
from ingest_work24 import validated

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--catalog',type=Path,required=True);ap.add_argument('--base-export',type=Path,required=True)
    ap.add_argument('--inventory',type=Path,required=True);ap.add_argument('--recheck-run',action='append',default=[])
    ap.add_argument('--output',type=Path,required=True);args=ap.parse_args()
    inventory=json.loads(args.inventory.read_text(encoding='utf-8-sig'))
    if inventory.get('source')!='goyong24_training':raise ValueError('invalid_inventory')
    generated=datetime.fromisoformat(inventory['generated_at'])
    if generated.tzinfo is None or not 0<=(datetime.now(KST)-generated).total_seconds()<=86400:raise ValueError('stale_inventory')
    known={r['source_id']:r for r in inventory['records']}
    rows={}
    for name in ('training.future.normalized.jsonl','training.changed.review.jsonl'):
        with (args.base_export/name).open(encoding='utf-8') as stream:
            for line in stream:
                value=json.loads(line)
                if value['source_id'] in rows:raise ValueError('duplicate_base_id')
                rows[value['source_id']]=value
    db=sqlite3.connect(args.catalog.resolve().as_uri()+'?mode=ro',uri=True)
    try:
        for run in args.recheck_run:
            status=db.execute('SELECT status FROM runs WHERE id=?',(run,)).fetchone()
            if status is None or status[0]!='collected_pending_reconciliation':raise ValueError('recheck_incomplete')
            records=db.execute('SELECT r.service,r.payload,r.last_seen FROM records r JOIN seen s USING(service,identity) WHERE s.run=?',(run,)).fetchall()
            for service,raw,last in records:
                if service!='card':raise ValueError('invalid_recheck_service')
                item=json.loads(raw)
                value=normalize_list(service,item,last)
                if start_state(item,datetime.now(KST).date())!='future':rows.pop(value['source_id'],None);continue
                rows[value['source_id']]=value
    finally:db.close()
    args.output.mkdir(parents=True,exist_ok=False)
    report={'new':0,'changed':0,'same_after_recheck':0,'preserved_enriched':0,'model_calls':0,'database_writes':0}
    with (args.output/'training.incremental.jsonl').open('x',encoding='utf-8') as out:
        for identity,value in sorted(rows.items()):
            checked=validated(value)
            if checked['raw_detail']['collection_metadata']['service']!='card':raise ValueError('card_only_scope')
            old=known.get(identity)
            if old and old['content_hash']==value['content_hash']:report['same_after_recheck']+=1;continue
            if old and old.get('validation_level')!='list_schema_only':report['preserved_enriched']+=1;continue
            if old:value['expected_previous_hash']=old['content_hash']
            report['changed' if old else 'new']+=1
            out.write(json.dumps(value,ensure_ascii=False)+'\n')
    (args.output/'report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report))
    return 0
if __name__=='__main__':raise SystemExit(main())

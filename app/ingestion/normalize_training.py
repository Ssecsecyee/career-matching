"""Offline common training contract. No crawler, API calls or database writes."""
import argparse
from datetime import date,datetime,timezone
from decimal import Decimal,InvalidOperation
import hashlib
import json
from pathlib import Path
from urllib.parse import urlsplit,parse_qsl

TEXT=['course_key','cohort_name','title','provider_name','curriculum','eligibility','preferred_conditions',
      'benefits','selection_process','application_notes','delivery_mode','currency','cost_description','subsidy_description']
ARRAYS=['original_categories','normalized_domains','learning_topics','tech_stacks','addresses']
DATES=['application_start','application_deadline','starts_at','ends_at']


def normalize_training(record):
    if not isinstance(record,dict):raise ValueError('training_record_required')
    source=record.get('source')
    if source not in {'fixture','boottent','goyong24_training'}:raise ValueError('unsupported_training_source')
    identity=record.get('source_id')
    if not isinstance(identity,str) or not 1<=len(identity)<=128:raise ValueError('invalid_training_id')
    url=record.get('source_url','');parsed=urlsplit(url)
    allowed={'fixture':{'example.invalid'},'boottent':{'boottent.com','www.boottent.com'},'goyong24_training':{'work24.go.kr','www.work24.go.kr'}}
    if parsed.scheme!='https' or parsed.hostname not in allowed[source] or parsed.username or parsed.password or any(k.casefold() in {'authkey','api_key','apikey','token','access_token','password','x-amz-signature','x-amz-credential','x-amz-security-token'} for k,v in parse_qsl(parsed.query)):
        raise ValueError('unverified_or_sensitive_training_source_url')
    fetched=datetime.fromisoformat(record['fetched_at'].replace('Z','+00:00'))
    if fetched.tzinfo is None:raise ValueError('training_collection_timezone_required')
    row={'source':source,'source_id':identity,'source_url':url,'source_version':1,
         'fetched_at':fetched.astimezone(timezone.utc).isoformat(),'last_seen_at':fetched.astimezone(timezone.utc).isoformat()}
    for key in TEXT:
        value=record.get(key)
        if value is not None and not isinstance(value,str):raise ValueError('invalid_training_text')
        row[key]=value.strip() if value and value.strip() else None
    if not row['title'] or not row['provider_name'] or not row['course_key']:
        raise ValueError('course_cohort_title_provider_required')
    for key in ('course_key','cohort_name','provider_name'):
        if row[key] is not None and len(row[key])>(128 if key=='course_key' else 255):raise ValueError('training_text_too_long')
    if row['delivery_mode'] not in {None,'online','offline','hybrid','unknown'}:raise ValueError('invalid_delivery_mode')
    for key in ARRAYS:
        values=record.get(key,[])
        if not isinstance(values,list) or len(values)>100 or any(not isinstance(v,str) or len(v)>500 for v in values):raise ValueError('invalid_training_array')
        row[key]=list(dict.fromkeys(v.strip() for v in values if v.strip()))
    row['additional_sections']={'date_precision':{},'is_fixture':source=='fixture','cohort_verified':row['cohort_name'] is not None}
    dates=record.get('dates',{})
    if not isinstance(dates,dict) or set(dates)-set(DATES):raise ValueError('invalid_training_dates')
    for key in DATES:
        row[key]=None
        value=dates.get(key)
        if value is None:continue
        if not isinstance(value,dict):raise ValueError('invalid_training_date_value')
        precision=value.get('precision');raw=value.get('raw')
        if precision=='date_only':
            date.fromisoformat(raw)
            row['additional_sections']['date_precision'][key]={'raw':raw,'precision':'date_only','timezone':None}
        elif precision=='timestamp':
            parsed_date=datetime.fromisoformat(raw.replace('Z','+00:00'))
            if parsed_date.tzinfo is None:raise ValueError('training_date_timezone_required')
            row[key]=parsed_date.astimezone(timezone.utc).isoformat()
        else:raise ValueError('unsupported_training_date_precision')
    for start,end in [('starts_at','ends_at'),('application_start','application_deadline')]:
        a,b=dates.get(start),dates.get(end)
        if a and b and a['precision']==b['precision']:
            if a['precision']=='date_only' and date.fromisoformat(a['raw'])>date.fromisoformat(b['raw']):raise ValueError('training_date_range_reversed')
            if a['precision']=='timestamp' and row[start]>row[end]:raise ValueError('training_date_range_reversed')
    value=record.get('tuition')
    row['tuition']=None
    if value is not None:
        try:amount=Decimal(str(value))
        except InvalidOperation:raise ValueError('invalid_tuition') from None
        if not amount.is_finite() or amount<0 or amount>Decimal('999999999999.99') or amount.as_tuple().exponent < -2:raise ValueError('invalid_tuition')
        if not row['currency']:raise ValueError('tuition_currency_required')
        row['tuition']=str(amount)
    # State is not inferred from an education start date or a generic funding claim.
    status=record.get('recruitment_status','unknown')
    if status not in {'unknown','active','closed','unavailable'}:raise ValueError('invalid_training_status')
    evidence=record.get('status_evidence')
    if status!='unknown' and (not isinstance(evidence,dict) or evidence.get('source_url')!=url or not evidence.get('quote')):
        raise ValueError('training_status_evidence_required')
    row['recruitment_status']=status
    row['field_status']={k:'present' if row[k] not in (None,[]) else 'not_provided' for k in TEXT+ARRAYS+DATES+['tuition']}
    for key in row['additional_sections']['date_precision']:row['field_status'][key]='date_only'
    row['raw_detail']=record;row['raw_object_key']=None
    stable={k:v for k,v in row.items() if k not in {'fetched_at','last_seen_at','raw_detail'}}
    row['content_hash']=hashlib.sha256(json.dumps(stable,ensure_ascii=False,sort_keys=True,allow_nan=False).encode()).hexdigest()
    return row


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    try:
        if args.input.stat().st_size>4*1024*1024 or args.output.exists():raise ValueError('invalid_input_size_or_existing_output')
        records=json.loads(args.input.read_text(encoding='utf-8-sig'))
        if not isinstance(records,list) or len(records)>100:raise ValueError('training_batch_limit')
        rows=[normalize_training(record) for record in records]
        if len({(r['source'],r['source_id']) for r in rows})!=len(rows):raise ValueError('duplicate_training_offering')
        args.output.parent.mkdir(parents=True,exist_ok=True)
        with args.output.open('x',encoding='utf-8') as output:json.dump(rows,output,ensure_ascii=False,indent=2)
        print(json.dumps({'normalized':len(rows),'fixture_count':sum(r['source']=='fixture' for r in rows),'network_requests':0,'database_writes':0}))
    except (ValueError,TypeError,KeyError,OSError) as exc:parser.exit(2,'Training normalization failed: '+type(exc).__name__+'\n')

if __name__=='__main__':main()

"""Validate trusted collector files, preview changes, and explicitly apply MySQL upserts.
No scraping, model calls, arbitrary SQL, automatic scheduling, or AWS calls.
"""
import argparse
from collections import Counter
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re

from normalize_jumpit import normalize
from page_extraction import apply_page_metadata
from normalize_all_jumpit import parse_time
from export_mysql_data import COLUMNS, JSON_COLUMNS, DATE_COLUMNS

UTC = timezone.utc
BUSINESS = [c for c in COLUMNS if c not in {'source','source_id','source_version','content_hash',
    'raw_detail','field_status','fetched_at','last_seen_at','source_updated_at'}]
WRITE_COLUMNS = [c for c in COLUMNS if c != 'source_updated_at']


def reject_duplicates(pairs):
    result = {}
    for key, value in pairs:
        if key in result:raise ValueError('duplicate_json_key')
        result[key] = value
    return result


def read_json(path, limit=4*1024*1024):
    if path.stat().st_size > limit:raise ValueError('file_too_large')
    return parse_json_bytes(path.read_bytes())


def parse_json_bytes(raw):
    return json.loads(raw.decode('utf-8-sig'), object_pairs_hook=reject_duplicates,
        parse_constant=lambda value: (_ for _ in ()).throw(ValueError('invalid_json_number')))


def timestamp(value):
    if not isinstance(value,str):raise ValueError('timestamp_required')
    parsed=datetime.fromisoformat(value.replace('Z','+00:00'))
    if parsed.tzinfo is None:raise ValueError('timestamp_timezone_required')
    return parsed.astimezone(UTC)


def sql_date(value):
    if value is None:return None
    if isinstance(value,datetime):
        return value.astimezone(UTC).replace(tzinfo=None) if value.tzinfo else value
    return timestamp(value).replace(tzinfo=None)


def canonical(value):
    return json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':'),allow_nan=False,
        default=lambda item:item.isoformat() if isinstance(item,datetime) else str(item))


def source_url(identity):return 'https://jumpit.saramin.co.kr/position/'+identity


def prepare(batch, *, now=None):
    now=now or datetime.now(UTC)
    root=Path(batch).resolve()
    manifest=read_json(root/'manifest.json',1024*1024)
    if type(manifest.get('schema_version')) is not int or manifest.get('schema_version')!=1 or manifest.get('complete') is not True:
        raise ValueError('unsupported_or_incomplete_manifest')
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,80}',manifest.get('batch_id','')):
        raise ValueError('invalid_batch_id')
    records=manifest.get('records')
    if not isinstance(records,list) or len(records)>100:raise ValueError('batch_limit_100')
    if not isinstance(manifest.get('failures',[]),list):raise ValueError('invalid_failures_list')
    identities=set();rows=[];total_bytes=0
    for item in records:
        if not isinstance(item,dict):raise ValueError('invalid_manifest_record')
        identity=item.get('source_id','')
        if not isinstance(identity,str) or not re.fullmatch(r'\d{1,128}',identity):raise ValueError('invalid_id')
        if identity in identities:raise ValueError('duplicate_source_id')
        identities.add(identity)
        if item.get('source_url')!=source_url(identity) or item.get('collection_status')!='success':
            raise ValueError('source_or_collection_status_invalid')
        relative=item.get('raw_file','')
        if not isinstance(relative,str) or not re.fullmatch(r'raw/details/\d{1,128}\.json',relative):
            raise ValueError('invalid_raw_path')
        path=(root/relative).resolve()
        if not path.is_relative_to(root) or path.stem!=identity:raise ValueError('raw_path_escape_or_id_mismatch')
        total_bytes+=path.stat().st_size
        if total_bytes>40*1024*1024:raise ValueError('batch_bytes_limit')
        if path.stat().st_size>4*1024*1024:raise ValueError('raw_file_too_large')
        with path.open('rb') as handle:raw=handle.read(4*1024*1024+1)
        if len(raw)>4*1024*1024:raise ValueError('raw_file_too_large')
        if hashlib.sha256(raw).hexdigest()!=item.get('sha256'):raise ValueError('raw_hash_mismatch')
        fetched=timestamp(item.get('fetched_at'))
        if fetched>now+timedelta(minutes=5):raise ValueError('future_collection_time')
        row=normalize(parse_json_bytes(raw))
        if row['source_id']!=identity:raise ValueError('detail_id_mismatch')
        apply_page_metadata(row)
        if not all(isinstance(row.get(k),str) and row[k].strip() for k in ('title','company_name')):
            raise ValueError('missing_title_or_company')
        if len(row['company_name'])>255:raise ValueError('company_name_too_long')
        row['fetched_at']=fetched.isoformat();row['last_seen_at']=row['fetched_at']
        for target,raw_key in [('published_at','published_at_raw'),('deadline_at','deadline_at_raw')]:
            parsed=parse_time(row.get(raw_key))
            row[target]=parsed.isoformat() if parsed else None
        if row['deadline_at'] and row['deadline_type']!='always_open':row['deadline_type']='fixed_date'
        # Do not infer active recruitment from mere successful HTTP access.
        evidence=item.get('status_evidence')
        if evidence is not None:
            if (not isinstance(evidence,dict) or evidence.get('source_url')!=source_url(identity) or
                evidence.get('kind')!='explicit_page_status' or evidence.get('status') not in {'active','closed','unavailable'} or
                not isinstance(evidence.get('quote'),str) or not 1<=len(evidence['quote'])<=500 or
                timestamp(evidence.get('observed_at'))!=fetched):raise ValueError('invalid_status_evidence')
            row['recruitment_status']=evidence['status']
        elif row.get('recruitment_status')!='unavailable' and row['deadline_at'] and timestamp(row['deadline_at'])<=fetched:
            row['recruitment_status']='closed'
        row['raw_detail']=dict(row['raw_detail'],_ingestion_provenance={'batch_id':manifest['batch_id'],
            'source_url':source_url(identity),'fetched_at':row['fetched_at'],'status_evidence':evidence,
            'raw_sha256':item['sha256']})
        row['_batch_id']=manifest['batch_id']
        canonical(row)  # Reject overflow/non-finite numbers before any DB access.
        rows.append(row)
    return rows,{'batch_id':manifest['batch_id'],'validated':len(rows),'failed_collection_records':len(manifest.get('failures',[])),
        'network_requests':0,'database_connections':0,'note':'Empty/missing fields cannot clear existing values. No active status inferred.'}


def decoded(row):
    row=dict(row)
    for key in JSON_COLUMNS:
        if isinstance(row.get(key),(str,bytes)):row[key]=json.loads(row[key])
    for key in DATE_COLUMNS:
        if row.get(key) is not None:row[key]=sql_date(row[key])
    return row


def merge(existing,incoming):
    new=decoded(incoming)
    if existing:
        old=decoded(existing)
        if new['fetched_at']<=old['fetched_at']:
            return old,'stale_or_replayed',[]
        merged=dict(old);preserved=[]
        for key in BUSINESS:
            value=new.get(key)
            missing=value is None or value=='' or value==[] or value=={} or (isinstance(value,dict) and all(v is None for v in value.values()))
            if key in {'deadline_type','recruitment_status'} and value=='unknown':missing=True
            if missing:
                if old.get(key) not in (None,'',[],{}):preserved.append(key)
            else:merged[key]=value
        # An observed fixed deadline explicitly replaces an always-open designation.
        if new.get('deadline_type')=='always_open':merged['deadline_at']=None
        for key in ('raw_detail','fetched_at','last_seen_at'):merged[key]=new[key]
        fields=dict(old.get('field_status') or {})
        fields.update({k:v for k,v in (new.get('field_status') or {}).items() if v in {'present','present_combined_source','date_only'}})
        merged['field_status']=fields
        changed=any(canonical(old.get(k))!=canonical(merged.get(k)) for k in BUSINESS)
        merged['source_version']=int(old['source_version'])+int(changed)
        decision='updated' if changed else 'unchanged'
    else:
        merged=new;merged['source_version']=1;decision='inserted';preserved=[]
    merged['content_hash']=hashlib.sha256(canonical({k:merged.get(k) for k in BUSINESS}).encode()).hexdigest()
    return merged,decision,preserved


def bind_value(column,value):
    if column in JSON_COLUMNS and value is not None:return canonical(value)
    if column in DATE_COLUMNS:return sql_date(value)
    return value


def ingest(rows,connection, *, apply=False, require_new=False):
    decisions=[]
    # Serialize ingestion batches without touching chat tables or creating schema.
    lock=False
    try:
        with connection.cursor() as cursor:
            if apply:
                cursor.execute("SELECT GET_LOCK('career_jumpit_ingestion_v1',0) AS acquired")
                if cursor.fetchone()['acquired']!=1:raise ValueError('another_ingestion_is_running')
                lock=True
        connection.begin()
        with connection.cursor() as cursor:
            for incoming in rows:
                cursor.execute('SELECT * FROM job_postings WHERE source=%s AND source_id=%s'+(' FOR UPDATE' if apply else ''),('jumpit',incoming['source_id']))
                old=cursor.fetchone()
                if require_new and old:raise ValueError('new_only_batch_contains_existing_job')
                merged,decision,preserved=merge(old,incoming)
                decisions.append({'source_id':incoming['source_id'],'decision':decision,'preserved_fields':preserved,
                    'source_version':merged.get('source_version')})
                if not apply or decision=='stale_or_replayed':continue
                columns=WRITE_COLUMNS
                if old:
                    mutable=[c for c in columns if c not in {'source','source_id'}]
                    cursor.execute('UPDATE job_postings SET '+','.join(c+'=%s' for c in mutable)+' WHERE job_id=%s',
                        [bind_value(c,merged.get(c)) for c in mutable]+[old['job_id']])
                    job_id=old['job_id']
                else:
                    cursor.execute('INSERT INTO job_postings ('+','.join(columns)+') VALUES ('+','.join(['%s']*len(columns))+')',
                        [bind_value(c,merged.get(c)) for c in columns])
                    job_id=cursor.lastrowid
                if decision in {'inserted','updated'}:
                    operation='close' if merged['recruitment_status'] in {'closed','unavailable'} else 'upsert'
                    cursor.execute('INSERT INTO search_outbox(entity_type,entity_id,source_version,operation) VALUES(%s,%s,%s,%s)',
                        ('job',job_id,merged['source_version'],operation))
        if apply:connection.commit()
        else:connection.rollback()
        return {'applied':apply,'counts':dict(Counter(x['decision'] for x in decisions)),'decisions':decisions,
            'search_index_updated':False,'note':'Outbox records changes only. Elasticsearch consumer and S3 upload are not connected.'}
    except Exception:
        connection.rollback();raise
    finally:
        if lock:
            with connection.cursor() as cursor:cursor.execute("SELECT RELEASE_LOCK('career_jumpit_ingestion_v1')")


def load_settings(path=None):
    path=Path(path) if path is not None else Path(__file__).resolve().parent/'.env'
    if path.exists():
        for line in path.read_text(encoding='utf-8-sig').splitlines():
            if not line.strip() or line.lstrip().startswith('#'):continue
            key,separator,value=line.partition('=')
            key=key.strip()
            if not separator or not re.fullmatch(r'INGEST_MYSQL_[A-Z_]+',key):
                raise ValueError('invalid_ingestion_env_key')
            os.environ.setdefault(key,value.strip())
    password=os.getenv('INGEST_MYSQL_PASSWORD','')
    if password.startswith('여기에_') or 'DbSecret의_password_입력' in password:
        raise ValueError('replace_ingestion_password_placeholder')


def connect():
    load_settings()
    import pymysql
    # Separate ingestion account, never reuse the chat runtime account implicitly.
    required=['INGEST_MYSQL_HOST','INGEST_MYSQL_PORT','INGEST_MYSQL_DATABASE','INGEST_MYSQL_USER','INGEST_MYSQL_PASSWORD']
    if not all(os.getenv(k) for k in required):raise ValueError('configure_ingestion_environment')
    host=os.environ['INGEST_MYSQL_HOST'];options={}
    if host not in {'127.0.0.1','localhost','::1'}:
        ca=os.getenv('INGEST_MYSQL_SSL_CA')
        if not ca:raise ValueError('remote_mysql_requires_verified_tls')
        options.update(ssl_ca=ca,ssl_verify_cert=True,ssl_verify_identity=True)
    return pymysql.connect(host=host,port=int(os.environ['INGEST_MYSQL_PORT']),database=os.environ['INGEST_MYSQL_DATABASE'],
        user=os.environ['INGEST_MYSQL_USER'],password=os.environ['INGEST_MYSQL_PASSWORD'],charset='utf8mb4',
        cursorclass=pymysql.cursors.DictCursor,autocommit=True,init_command="SET time_zone='+00:00'",
        connect_timeout=5,read_timeout=30,write_timeout=30,**options)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--batch',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True,help='New report directory outside Git')
    parser.add_argument('--preview-db',action='store_true',help='Read DB and rollback; no rows changed')
    parser.add_argument('--apply',action='store_true',help='Explicitly commit validated upserts and outbox')
    args=parser.parse_args()
    try:
        if args.output.exists():raise ValueError('output_already_exists')
        rows,report=prepare(args.batch)
        if args.preview_db or args.apply:
            connection=connect()
            try:report.update(ingest(rows,connection,apply=args.apply));report['database_connections']=1
            finally:connection.close()
        args.output.mkdir(parents=True,exist_ok=False)
        (args.output/'validated.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8')
        (args.output/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps({k:v for k,v in report.items() if k!='decisions'},ensure_ascii=False))
    except Exception as exc:
        # Original text, credentials, server error messages and SQL values are never printed.
        code=str(exc) if type(exc) is ValueError and re.fullmatch('[a-z0-9_]+',str(exc)) else type(exc).__name__
        numeric=exc.args[0] if exc.args and type(exc.args[0]) is int else None
        parser.exit(2,'Ingestion stopped: '+code+(' [code='+str(numeric)+']' if numeric is not None else '')+'\n')

if __name__=='__main__':main()

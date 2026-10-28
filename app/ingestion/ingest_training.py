"""New-only training ingestion. Caller owns transaction and credentials."""
import json
from datetime import datetime, timezone
from normalize_training import normalize_training

JSON_FIELDS={'original_categories','normalized_domains','learning_topics','tech_stacks','addresses','field_status','additional_sections','raw_detail'}
TIME_FIELDS={'application_start','application_deadline','starts_at','ends_at','fetched_at','last_seen_at'}

def prepare(records):
    if not isinstance(records,list) or not 1<=len(records)<=20:raise ValueError('training_batch_size')
    rows=[normalize_training(r) for r in records]
    if any(r['source']!='boottent' or r['recruitment_status']!='unknown' for r in rows):raise ValueError('sample_source_or_status')
    if len({r['source_id'] for r in rows})!=len(rows):raise ValueError('duplicate_batch_id')
    for row in rows:
        meta=row['raw_detail'].get('collection_metadata',{})
        if meta.get('retrieval_method')!='web_indexed_snapshot' or meta.get('live_page_verified') is not False:raise ValueError('snapshot_provenance_required')
        row['additional_sections']['collection_metadata']=meta
        row['additional_sections']['recommendation_eligible']=False
        # Hash includes provenance and the explicit recommendation exclusion.
        import hashlib
        stable={k:v for k,v in row.items() if k not in {'content_hash','fetched_at','last_seen_at','raw_detail'}}
        row['content_hash']=hashlib.sha256(json.dumps(stable,ensure_ascii=False,sort_keys=True).encode()).hexdigest()
    return rows

def insert_new(rows,conn):
    inserted=[];skipped=0
    with conn.cursor() as cur:
        for row in rows:
            # Existing rows are immutable here; the UNIQUE key arbitrates concurrent inserts.
            # No locking read or UPDATE privilege is needed for this new-only importer.
            cur.execute('SELECT offering_id,content_hash FROM training_offerings WHERE source=%s AND source_id=%s',(row['source'],row['source_id']))
            existing=cur.fetchone()
            if existing:
                if existing['content_hash']!=row['content_hash']:raise ValueError('existing_training_conflict')
                skipped+=1;continue
            columns=list(row)
            values=[]
            for key in columns:
                value=row[key]
                if key in JSON_FIELDS:value=json.dumps(value,ensure_ascii=False)
                elif key in TIME_FIELDS and value is not None:value=datetime.fromisoformat(value.replace('Z','+00:00')).astimezone(timezone.utc).replace(tzinfo=None)
                values.append(value)
            cur.execute('INSERT INTO training_offerings ('+','.join('`'+c+'`' for c in columns)+') VALUES ('+','.join(['%s']*len(columns))+')',values)
            identity=cur.lastrowid
            cur.execute("INSERT INTO search_outbox (entity_type,entity_id,source_version,operation) VALUES ('training',%s,%s,'upsert')",(identity,row['source_version']))
            inserted.append(identity)
    return {'inserted':len(inserted),'skipped':skipped,'offering_ids':inserted}

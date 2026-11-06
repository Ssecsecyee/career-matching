"""Validated new-only Work24 writes. Caller owns transaction."""
import json
from datetime import datetime,timezone
from work24_export import normalize_list
from ingest_training import JSON_FIELDS,TIME_FIELDS


def validated(row):
    raw=row.get('raw_detail',{});meta=raw.get('collection_metadata',{})
    if meta.get('validation_level')!='list_schema_only':raise ValueError('unsupported_work24_validation')
    checked=normalize_list(meta['service'],meta['list_record'],raw['fetched_at'])
    if checked['source_id']!=row.get('source_id') or checked['content_hash']!=row.get('content_hash'):raise ValueError('work24_content_mismatch')
    checked['additional_sections']['collection_metadata']=dict(checked['additional_sections']['collection_metadata'])
    checked['additional_sections']['collection_metadata'].pop('list_record',None)
    return checked


def insert_batch(rows,conn):
    rows=[validated(r) for r in rows]
    if not rows or len(rows)>200 or len({r['source_id'] for r in rows})!=len(rows):raise ValueError('invalid_work24_batch')
    ids=[r['source_id'] for r in rows];marks=','.join(['%s']*len(ids))
    with conn.cursor() as cur:
        cur.execute('SELECT source_id,content_hash FROM training_offerings WHERE source=%s AND source_id IN ('+marks+')',['goyong24_training']+ids)
        existing={r['source_id']:r['content_hash'] for r in cur.fetchall()}
        for row in rows:
            if row['source_id'] in existing and existing[row['source_id']]!=row['content_hash']:raise ValueError('existing_work24_conflict')
        fresh=[r for r in rows if r['source_id'] not in existing]
        if fresh:
            columns=list(fresh[0]);values=[]
            for row in fresh:
                value=[]
                for key in columns:
                    item=row[key]
                    if key in JSON_FIELDS:item=json.dumps(item,ensure_ascii=False)
                    elif key in TIME_FIELDS and item is not None:item=datetime.fromisoformat(item.replace('Z','+00:00')).astimezone(timezone.utc).replace(tzinfo=None)
                    value.append(item)
                values.append(value)
            cur.executemany('INSERT INTO training_offerings ('+','.join('`'+k+'`' for k in columns)+') VALUES ('+','.join(['%s']*len(columns))+')',values)
            fresh_ids=[r['source_id'] for r in fresh]
            cur.execute('SELECT offering_id,source_id,content_hash,title,recruitment_status,application_deadline,starts_at,additional_sections FROM training_offerings WHERE source=%s AND source_id IN ('+','.join(['%s']*len(fresh_ids))+')',['goyong24_training']+fresh_ids)
            stored={r['source_id']:r for r in cur.fetchall()}
            events=[]
            for row in fresh:
                actual=stored[row['source_id']];extra=actual['additional_sections']
                if isinstance(extra,str):extra=json.loads(extra)
                if actual['title']!=row['title'] or actual['content_hash']!=row['content_hash'] or actual['recruitment_status']!='unknown' or actual['application_deadline'] is not None or actual['starts_at'] is not None or extra.get('recommendation_eligible') is not False or extra.get('date_precision')!=row['additional_sections']['date_precision']:raise ValueError('work24_roundtrip_failed')
                events.append((actual['offering_id'],1))
            cur.executemany("INSERT INTO search_outbox(entity_type,entity_id,source_version,operation) VALUES('training',%s,%s,'upsert')",events)
    return {'inserted':len(fresh),'skipped':len(rows)-len(fresh)}


def apply_incremental(rows,conn):
    """Card-only updates with optimistic version/hash checks; caller commits."""
    if not rows or len(rows)>200 or len({r['source_id'] for r in rows})!=len(rows):raise ValueError('invalid_work24_batch')
    result={'inserted':0,'updated':0,'skipped':0}
    for raw in rows:
        row=validated(raw)
        if row['source']!='goyong24_training' or row['raw_detail']['collection_metadata']['service']!='card':raise ValueError('card_only_incremental_scope')
        with conn.cursor() as cur:
            cur.execute('SELECT offering_id,content_hash,source_version,raw_detail FROM training_offerings WHERE source=%s AND source_id=%s',(row['source'],row['source_id']))
            old=cur.fetchone()
            if old is None:
                if raw.get('expected_previous_hash'):raise ValueError('previous_work24_row_missing')
                part=insert_batch([raw],conn);result['inserted']+=part['inserted'];result['skipped']+=part['skipped'];continue
            if old['content_hash']==row['content_hash']:
                result['skipped']+=1;continue
            if raw.get('expected_previous_hash')!=old['content_hash']:raise ValueError('concurrent_work24_change')
            previous=old['raw_detail']
            if isinstance(previous,str):previous=json.loads(previous)
            meta=previous.get('collection_metadata',{})
            if meta.get('service')!='card' or meta.get('validation_level')!='list_schema_only':raise ValueError('preserve_enriched_work24_row')
            row['source_version']=int(old['source_version'])+1
            columns=[k for k in row if k not in ('source','source_id')]
            values=[]
            for key in columns:
                value=row[key]
                if key in JSON_FIELDS:value=json.dumps(value,ensure_ascii=False)
                elif key in TIME_FIELDS and value is not None:value=datetime.fromisoformat(value.replace('Z','+00:00')).astimezone(timezone.utc).replace(tzinfo=None)
                values.append(value)
            cur.execute('UPDATE training_offerings SET '+','.join(k+'=%s' for k in columns)+' WHERE offering_id=%s AND content_hash=%s AND source_version=%s',values+[old['offering_id'],old['content_hash'],old['source_version']])
            if cur.rowcount!=1:raise ValueError('concurrent_work24_change')
            cur.execute("INSERT INTO search_outbox(entity_type,entity_id,source_version,operation) VALUES('training',%s,%s,'upsert')",(old['offering_id'],row['source_version']))
            result['updated']+=1
    return result

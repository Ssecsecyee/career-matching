"""Single-host outbox consumer. No model calls, no public Elasticsearch access."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'app/backend'))
from src.services.deadlines import VISIBLE_SQL, effective_deadline, expired
from index_snapshot import document


def training_document(row):
    names = ('source', 'source_id', 'source_version', 'title', 'provider_name', 'curriculum',
             'eligibility', 'preferred_conditions', 'benefits', 'selection_process', 'application_notes', 'recruitment_status')
    doc = {key: str(row.get(key) or '') for key in names}
    for key in ('learning_topics', 'tech_stacks'):
        value = row.get(key) or []
        doc[key] = json.loads(value) if isinstance(value, (str, bytes)) else value
    doc['document_key'] = json.dumps([row['source'], row['source_id']], ensure_ascii=False, separators=(',', ':'))
    return hashlib.sha256(doc['document_key'].encode()).hexdigest(), doc


def job_document(row):
    value = dict(row)
    for key in ('tech_stacks', 'addresses', 'additional_sections'):
        if isinstance(value.get(key), (str, bytes)):
            value[key] = json.loads(value[key])
    extra = value.get('additional_sections') or {}
    value['deadline_at_raw'] = extra.get('page_extraction', {}).get('deadline', {}).get('raw') or ''
    value['deadline_at'] = effective_deadline(value)
    for key in ('deadline_at', 'published_at', 'last_seen_at'):
        if isinstance(value.get(key), datetime):
            dt = value[key]
            value[key] = (dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt).isoformat()
    return document(value)


class Engine:
    def __init__(self, jobs, training):
        if not all(re.fullmatch(r'career-[a-z0-9_-]+-read', x) for x in (jobs, training)):
            raise ValueError('invalid_search_alias')
        self.aliases = {'job': jobs, 'training': training}

    def request(self, method, path, data=None):
        body = None if data is None else json.dumps(data, ensure_ascii=False).encode()
        with urlopen(Request('http://127.0.0.1:19200' + path, body,
                             {'Content-Type': 'application/json'}, method=method), timeout=10) as response:
            return json.load(response)

    def verify_aliases(self):
        for alias in self.aliases.values():
            result = self.request('GET', '/_alias/' + alias)
            if len(result) != 1:
                raise RuntimeError('alias_must_have_one_index')

    def apply(self, kind, row, remove=False):
        key, doc = job_document(row) if kind == 'job' else training_document(row)
        # Latest DB version is loaded for every event. External version fencing
        # also protects against stale writes when the DB changes during a run.
        path = '/' + self.aliases[kind] + '/_doc/' + key
        query = '?version_type=external_gte&version=' + str(int(row['source_version']))
        if remove:
            try:
                self.request('DELETE', path + query)
            except HTTPError as exc:
                if exc.code == 404:
                    payload = json.loads(exc.read(65536))
                    if payload.get('result') == 'not_found':
                        return
                raise
        else:
            self.request('PUT', path + query + '&require_alias=true', doc)


class Consumer:
    def __init__(self, connection, engine, *, batch_size=200):
        self.db, self.engine, self.batch_size = connection, engine, batch_size

    def sweep_expired(self):
        # Derived visibility only: do not alter source recruitment_status or
        # pretend that a source page was revisited. One close event per version.
        with self.db.cursor() as cur:
            cur.execute("INSERT IGNORE INTO search_outbox(entity_type,entity_id,source_version,operation) "
                        "SELECT 'job',job_id,source_version,'close' FROM job_postings WHERE recruitment_status IN ('closed','unavailable') OR NOT " + VISIBLE_SQL)
            return cur.rowcount

    def process(self, event):
        kind = event['entity_type']
        if kind not in ('job', 'training') or event['operation'] not in ('upsert', 'close', 'delete'):
            raise ValueError('unsupported_event')
        table, identity = ('job_postings', 'job_id') if kind == 'job' else ('training_offerings', 'offering_id')
        with self.db.cursor() as cur:
            cur.execute('SELECT * FROM ' + table + ' WHERE ' + identity + '=%s', (event['entity_id'],))
            row = cur.fetchone()
        if not row:
            # A retained source identity/tombstone is required to delete an ES
            # document. Never acknowledge a missing row and leave it searchable.
            raise ValueError('missing_source_identity_restore_tombstone')
        if int(row['source_version']) < int(event['source_version']):
            raise ValueError('source_version_not_ready')
        current_event = int(row['source_version']) == int(event['source_version'])
        remove = current_event and event['operation'] == 'delete'
        with self.db.cursor() as cur:
            cur.execute("SELECT event_id FROM search_outbox WHERE entity_type=%s AND entity_id=%s AND source_version>=%s AND operation='delete' LIMIT 1", (kind, event['entity_id'], row['source_version']))
            remove = remove or bool(cur.fetchone())
        if kind == 'job':
            remove = remove or row['recruitment_status'] in {'closed','unavailable'} or expired(row)
            # A close event alone is not proof of actual source closure; current
            # DB status/expiry is authoritative even for old close events.
        self.engine.apply(kind, row, remove=remove)
        with self.db.cursor() as cur:
            cur.execute('UPDATE search_outbox SET processed_at=UTC_TIMESTAMP(6),attempt_count=attempt_count+1,last_error=NULL WHERE event_id=%s AND processed_at IS NULL', (event['event_id'],))

    def run(self):
        with self.db.cursor() as cur:
            cur.execute("SELECT GET_LOCK('career_search_sync',0) AS acquired")
            if cur.fetchone()['acquired'] != 1:
                return {'status': 'busy', 'processed': 0}
        try:
            self.engine.verify_aliases()
            swept = self.sweep_expired()
            with self.db.cursor() as cur:
                cur.execute("SELECT * FROM search_outbox WHERE processed_at IS NULL AND "
                            "(last_error IS NULL OR NOT JSON_VALID(last_error) OR "
                            "COALESCE(IF(JSON_VALID(last_error),JSON_EXTRACT(last_error,'$.retry_at'),0),0)<=UNIX_TIMESTAMP()) "
                            "ORDER BY event_id LIMIT %s", (self.batch_size,))
                events = cur.fetchall()
            good = failed = 0
            for event in events:
                try:
                    self.process(event)
                    good += 1
                except Exception as exc:
                    attempt = int(event['attempt_count']) + 1
                    detail = {'code': type(exc).__name__, 'retry_at': int(time.time()) + min(3600, 30 * 2 ** min(attempt - 1, 7))}
                    # Never log original SQL, user data, HTTP bodies or credentials.
                    with self.db.cursor() as cur:
                        cur.execute('UPDATE search_outbox SET attempt_count=attempt_count+1,last_error=%s WHERE event_id=%s AND processed_at IS NULL', (json.dumps(detail), event['event_id']))
                    failed += 1
            with self.db.cursor() as cur:
                cur.execute('SELECT COUNT(*) AS pending,COALESCE(MAX(attempt_count),0) AS max_attempts,MIN(created_at) AS oldest FROM search_outbox WHERE processed_at IS NULL')
                remaining = cur.fetchone()
            return {'status': 'degraded' if failed else 'ok', 'processed': good, 'failed': failed,
                    'expiry_events': swept, 'pending': remaining['pending'], 'max_attempts': remaining['max_attempts'],
                    'oldest_pending': str(remaining['oldest']) if remaining['oldest'] else None}
        finally:
            with self.db.cursor() as cur:
                cur.execute("SELECT RELEASE_LOCK('career_search_sync')")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', type=Path, required=True)
    args = parser.parse_args()
    settings = json.loads(args.config.read_text(encoding='utf-8'))
    import pymysql
    connection = pymysql.connect(host='127.0.0.1', port=int(settings.get('port', 3308)),
        user=settings['user'], password=settings['password'], database=settings['database'],
        charset='utf8mb4', cursorclass=pymysql.cursors.DictCursor, autocommit=True,
        init_command="SET time_zone='+00:00'", connect_timeout=5, read_timeout=20, write_timeout=20)
    try:
        result = Consumer(connection, Engine(settings['jobs_alias'], settings['training_alias'])).run()
        print(json.dumps(result), flush=True)
        return 1 if result.get('failed') else 0
    finally:
        connection.close()


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(json.dumps({'status': 'failed', 'error_type': type(exc).__name__}), flush=True)
        raise SystemExit(1)

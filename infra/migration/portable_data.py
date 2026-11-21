"""Typed JSONL backup; no credentials/content are printed. Restore into empty targets only."""
import argparse
import base64
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tarfile
import urllib.request

FORMAT = 'educare-portable-v1'


def ident(value):
    if not re.fullmatch(r'[A-Za-z0-9_-]+', value):
        raise ValueError('Unsafe identifier')
    return '`' + value + '`'


def encode(value):
    if isinstance(value, bytes): return {'$type': 'bytes', 'value': base64.b64encode(value).decode()}
    if isinstance(value, Decimal): return {'$type': 'decimal', 'value': str(value)}
    if isinstance(value, datetime): return {'$type': 'datetime', 'value': value.isoformat(' ')}
    if isinstance(value, date): return {'$type': 'date', 'value': value.isoformat()}
    if isinstance(value, time): return {'$type': 'time', 'value': value.isoformat()}
    if isinstance(value, timedelta): return {'$type': 'timedelta', 'value': str(value.total_seconds())}
    return value


def decode(value):
    if not isinstance(value, dict) or set(value) != {'$type', 'value'}: return value
    kind, text = value['$type'], value['value']
    if kind == 'bytes': return base64.b64decode(text, validate=True)
    if kind == 'decimal': return Decimal(text)
    if kind == 'datetime': return datetime.fromisoformat(text)
    if kind == 'date': return date.fromisoformat(text)
    if kind == 'time': return time.fromisoformat(text)
    if kind == 'timedelta': return timedelta(seconds=float(text))
    raise ValueError('Unknown typed value')


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''): h.update(block)
    return h.hexdigest()


def write_json(path, obj):
    Path(path).write_text(json.dumps(obj, ensure_ascii=False, indent=2, default=str), encoding='utf-8')


def es_request(base, path, payload=None, method=None, content_type='application/json'):
    if not base.startswith(('http://127.0.0.1:', 'http://localhost:', 'https://')):
        raise ValueError('Elasticsearch must use localhost or HTTPS')
    data = None if payload is None else (payload if isinstance(payload, bytes) else json.dumps(payload).encode())
    req = urllib.request.Request(base.rstrip('/') + '/' + path, data=data, method=method,
                                 headers={'Content-Type': content_type})
    with urllib.request.urlopen(req, timeout=120) as r: return json.load(r)


def mysql_connect(live=False):
    import pymysql
    if live:
        sys.path.insert(0, '/opt/career/app')
        from worker import configure
        configure()
    host = os.environ['MYSQL_HOST']
    opts = {}
    if host not in ('127.0.0.1', 'localhost', '::1'):
        opts.update(ssl_ca=os.environ['MYSQL_SSL_CA'], ssl_verify_cert=True, ssl_verify_identity=True)
    return pymysql.connect(host=host, port=int(os.getenv('MYSQL_PORT', '3306')),
        user=os.environ['MYSQL_USER'], password=os.environ['MYSQL_PASSWORD'],
        database=os.environ['MYSQL_DATABASE'], charset='utf8mb4', autocommit=False,
        cursorclass=pymysql.cursors.DictCursor, connect_timeout=10, read_timeout=180,
        write_timeout=180, init_command="SET time_zone='+00:00'", **opts)


def export(args):
    import pymysql
    root = Path(args.directory).resolve()
    root.mkdir(parents=True, exist_ok=False)
    os.chmod(root, 0o700)
    if shutil.disk_usage(root).free < 1024**3: raise RuntimeError('Need at least 1 GiB free')
    manifest = {'format': FORMAT, 'created_utc': datetime.now(timezone.utc).isoformat(),
                'tables': [], 'indices': [], 'files': {},
                'consistency': 'One MySQL consistent snapshot; each ES scroll separately. Cross-store cutover requires a final sync.'}
    c = mysql_connect(args.live_worker)
    try:
        with c.cursor() as q:
            q.execute('SET TRANSACTION READ ONLY'); q.execute('START TRANSACTION WITH CONSISTENT SNAPSHOT')
            q.execute('SELECT VERSION() version'); manifest['mysql_version'] = q.fetchone()['version']
            q.execute('SHOW FULL TABLES')
            entries = list(q.fetchall())
            if any(list(r.values())[1] != 'BASE TABLE' for r in entries):
                raise RuntimeError('Views require separate migration support')
            tables = [list(r.values())[0] for r in entries]
            q.execute("SELECT TRIGGER_NAME FROM information_schema.TRIGGERS WHERE TRIGGER_SCHEMA=DATABASE()")
            if q.fetchall(): raise RuntimeError('Triggers require separate migration support')
            q.execute("SELECT ROUTINE_NAME FROM information_schema.ROUTINES WHERE ROUTINE_SCHEMA=DATABASE()")
            if q.fetchall(): raise RuntimeError('Routines require separate migration support')
            q.execute("SELECT EVENT_NAME FROM information_schema.EVENTS WHERE EVENT_SCHEMA=DATABASE()")
            if q.fetchall(): raise RuntimeError('Events require separate migration support')
        for table in sorted(tables):
            with c.cursor() as q:
                q.execute('SHOW CREATE TABLE ' + ident(table)); ddl = list(q.fetchone().values())[1]
                q.execute('SHOW FULL COLUMNS FROM ' + ident(table)); columns = q.fetchall()
                q.execute('SELECT COUNT(*) n FROM ' + ident(table)); expected = int(q.fetchone()['n'])
            if 'ENGINE=InnoDB' not in ddl: raise RuntimeError('Consistent export requires InnoDB')
            folder = root / 'mysql'; folder.mkdir(exist_ok=True)
            (folder / (table + '.sql')).write_text(ddl, encoding='utf-8')
            count = 0
            with c.cursor(pymysql.cursors.SSCursor) as q, gzip.open(folder / (table + '.jsonl.gz'), 'wt', encoding='utf-8') as f:
                q.execute('SELECT * FROM ' + ident(table))
                for row in q:
                    f.write(json.dumps([encode(v) for v in row], ensure_ascii=False, separators=(',', ':')) + '\n'); count += 1
            if count != expected: raise RuntimeError('Snapshot row count mismatch')
            manifest['tables'].append({'name': table, 'rows': count, 'columns': columns})
        c.rollback()
    finally: c.close()
    base = args.elasticsearch
    if base:
        manifest['elasticsearch_version'] = es_request(base, '')['version']['number']
        listing = es_request(base, '_cat/indices?format=json&h=index')
        for entry in listing:
            name = entry['index']
            if not name.startswith('career-'): continue
            ident(name)
            meta = es_request(base, name)[name]
            settings = meta.get('settings', {}).get('index', {})
            for k in ('uuid', 'creation_date', 'version', 'provided_name', 'history'): settings.pop(k, None)
            folder = root / 'elasticsearch'; folder.mkdir(exist_ok=True)
            write_json(folder / (name + '.json'), {'settings': {'index': settings}, 'mappings': meta['mappings'], 'aliases': meta.get('aliases', {})})
            page = es_request(base, name + '/_search?scroll=5m', {'size': 500, 'track_total_hits': True, 'sort': ['_doc'], 'query': {'match_all': {}}})
            sid = page.get('_scroll_id'); count = 0
            try:
                with gzip.open(folder / (name + '.jsonl.gz'), 'wt', encoding='utf-8') as f:
                    while page['hits']['hits']:
                        for hit in page['hits']['hits']:
                            if '_source' not in hit: raise RuntimeError('Missing ES source')
                            f.write(json.dumps({'id': hit['_id'], 'routing': hit.get('_routing'), 'source': hit['_source']}, ensure_ascii=False, separators=(',', ':')) + '\n'); count += 1
                        page = es_request(base, '_search/scroll', {'scroll': '5m', 'scroll_id': sid}); sid = page.get('_scroll_id', sid)
            finally:
                if sid: es_request(base, '_search/scroll', {'scroll_id': [sid]}, 'DELETE')
            expected = page['hits']['total']
            if isinstance(expected, dict) and expected.get('relation') == 'eq' and count != expected['value']:
                raise RuntimeError('ES scroll count mismatch')
            manifest['indices'].append({'name': name, 'documents': count})
    # Configuration whitelist: never export passwords, secrets, tokens or AWS keys.
    if args.live_worker:
        folder = root / 'runtime'; folder.mkdir(exist_ok=True)
        allowed = ('JOB_SEARCH_BACKEND', 'TRAINING_SEARCH_BACKEND', 'ELASTICSEARCH_URL', 'ELASTICSEARCH_INDEX',
                   'ELASTICSEARCH_TRAINING_INDEX', 'ENABLE_TXT_VECTOR_SEARCH', 'ENABLE_ZERO_RESULT_VECTOR_FALLBACK',
                   'MODEL_ID', 'BEDROCK_REGION')
        write_json(folder / 'nonsecret-settings.json', {k: os.getenv(k) for k in allowed})
    for path in sorted(root.rglob('*')):
        if path.is_file(): manifest['files'][path.relative_to(root).as_posix()] = {'sha256': sha(path), 'bytes': path.stat().st_size}
    write_json(root / 'manifest.json', manifest)
    archive = root.with_suffix('.tar.gz')
    with tarfile.open(archive, 'w:gz') as t: t.add(root, arcname=root.name)
    os.chmod(archive, 0o600)
    print(json.dumps({'status': 'exported', 'archive': str(archive), 'sha256': sha(archive),
        'bytes': archive.stat().st_size, 'tables': [{k: v[k] for k in ('name', 'rows')} for v in manifest['tables']],
        'indices': manifest['indices']}))


def verify(root):
    root = Path(root).resolve(); m = json.loads((root / 'manifest.json').read_text(encoding='utf-8'))
    if m.get('format') != FORMAT: raise ValueError('Unsupported format')
    for name, info in m['files'].items():
        p = (root / name).resolve()
        if not p.is_relative_to(root) or not p.is_file() or p.stat().st_size != info['bytes'] or sha(p) != info['sha256']:
            raise ValueError('Manifest integrity mismatch')
    for group, field, folder in [('tables', 'rows', 'mysql'), ('indices', 'documents', 'elasticsearch')]:
        for item in m[group]:
            ident(item['name']); count = 0
            with gzip.open(root / folder / (item['name'] + '.jsonl.gz'), 'rt', encoding='utf-8') as f:
                for line in f: json.loads(line); count += 1
            if count != item[field]: raise ValueError('Record count mismatch')
    return m


def restore_mysql(args):
    m = verify(args.directory)
    if not args.confirm_empty_target: raise ValueError('Use --confirm-empty-target after review')
    c = mysql_connect()
    try:
        with c.cursor() as q:
            q.execute('SHOW TABLES')
            if q.fetchall(): raise ValueError('Target database must be empty; no DROP/overwrite supported')
            q.execute('SET FOREIGN_KEY_CHECKS=0')
            q.execute("SET SESSION sql_mode=CONCAT_WS(',',@@sql_mode,'NO_AUTO_VALUE_ON_ZERO')")
            for item in m['tables']:
                q.execute((Path(args.directory) / 'mysql' / (item['name'] + '.sql')).read_text(encoding='utf-8'))
            for item in m['tables']:
                columns = item['columns']; active = [i for i, col in enumerate(columns)
                    if not any(x in col.get('Extra', '') for x in ('VIRTUAL GENERATED', 'STORED GENERATED'))]
                names = [columns[i]['Field'] for i in active]
                sql = 'INSERT INTO ' + ident(item['name']) + ' (' + ','.join(map(ident, names)) + ') VALUES (' + ','.join(['%s'] * len(names)) + ')'
                batch = []
                with gzip.open(Path(args.directory) / 'mysql' / (item['name'] + '.jsonl.gz'), 'rt', encoding='utf-8') as f:
                    for line in f:
                        row = json.loads(line); batch.append(tuple(decode(row[i]) for i in active))
                        if len(batch) >= 250: q.executemany(sql, batch); batch = []
                    if batch: q.executemany(sql, batch)
                q.execute('SELECT COUNT(*) n FROM ' + ident(item['name']))
                if q.fetchone()['n'] != item['rows']: raise RuntimeError('Restore row count mismatch')
            # FOREIGN_KEY_CHECKS=1 does not retrospectively validate loaded rows.
            q.execute("SELECT TABLE_NAME,COLUMN_NAME,REFERENCED_TABLE_NAME,REFERENCED_COLUMN_NAME,CONSTRAINT_NAME,ORDINAL_POSITION FROM information_schema.KEY_COLUMN_USAGE WHERE TABLE_SCHEMA=DATABASE() AND REFERENCED_TABLE_NAME IS NOT NULL ORDER BY TABLE_NAME,CONSTRAINT_NAME,ORDINAL_POSITION")
            groups = {}
            for r in q.fetchall(): groups.setdefault((r['TABLE_NAME'], r['CONSTRAINT_NAME']), []).append(r)
            for (table, _), rows in groups.items():
                cond = ' AND '.join('c.' + ident(r['COLUMN_NAME']) + '=p.' + ident(r['REFERENCED_COLUMN_NAME']) for r in rows)
                present = ' AND '.join('c.' + ident(r['COLUMN_NAME']) + ' IS NOT NULL' for r in rows)
                sql = 'SELECT COUNT(*) n FROM ' + ident(table) + ' c WHERE ' + present + ' AND NOT EXISTS (SELECT 1 FROM ' + ident(rows[0]['REFERENCED_TABLE_NAME']) + ' p WHERE ' + cond + ')'
                q.execute(sql)
                if q.fetchone()['n']: raise RuntimeError('Foreign key validation failed')
            q.execute('SET FOREIGN_KEY_CHECKS=1')
        c.commit()
    except Exception:
        c.rollback(); raise
    finally: c.close()
    print(json.dumps({'status': 'mysql_restored', 'tables': len(m['tables'])}))


def restore_es(args):
    m = verify(args.directory)
    if not args.confirm_empty_target: raise ValueError('Use --confirm-empty-target after review')
    base = args.elasticsearch
    if es_request(base, '')['version']['number'] != m['elasticsearch_version']:
        raise ValueError('Use the same Elasticsearch version for initial restore')
    existing = {i['index'] for i in es_request(base, '_cat/indices?format=json&h=index')}
    if any(x.startswith('career-') for x in existing): raise ValueError('Target career indices must be absent')
    aliases = []
    for item in m['indices']:
        name = item['name']; meta = json.loads((Path(args.directory) / 'elasticsearch' / (name + '.json')).read_text(encoding='utf-8'))
        for alias, opts in meta.pop('aliases', {}).items(): aliases.append({'add': {'index': name, 'alias': alias, **opts}})
        es_request(base, name, meta, 'PUT')
        batch = []
        def flush():
            if not batch: return
            response = es_request(base, '_bulk', ('\n'.join(batch) + '\n').encode(), 'POST', 'application/x-ndjson')
            if response.get('errors'): raise RuntimeError('ES bulk restore failed; target requires inspection')
            batch.clear()
        with gzip.open(Path(args.directory) / 'elasticsearch' / (name + '.jsonl.gz'), 'rt', encoding='utf-8') as f:
            for line in f:
                row = json.loads(line); action = {'_index': name, '_id': row['id']}
                if row.get('routing') is not None: action['routing'] = row['routing']
                batch.extend([json.dumps({'index': action}), json.dumps(row['source'], ensure_ascii=False)])
                if len(batch) >= 500: flush()
            flush()
        es_request(base, name + '/_refresh', method='POST')
        if es_request(base, name + '/_count')['count'] != item['documents']: raise RuntimeError('ES count mismatch')
    if aliases: es_request(base, '_aliases', {'actions': aliases}, 'POST')
    print(json.dumps({'status': 'elasticsearch_restored', 'indices': len(m['indices'])}))


def main():
    p = argparse.ArgumentParser(); p.add_argument('action', choices=['export', 'verify', 'restore-mysql', 'restore-es'])
    p.add_argument('--directory', required=True); p.add_argument('--live-worker', action='store_true'); p.add_argument('--env')
    p.add_argument('--elasticsearch', default=''); p.add_argument('--confirm-empty-target', action='store_true')
    a = p.parse_args()
    if a.env:
        from dotenv import dotenv_values
        for key, value in dotenv_values(a.env).items():
            if value is not None: os.environ[key] = value
    if a.action == 'export': export(a)
    elif a.action == 'verify':
        m = verify(a.directory); print(json.dumps({'status': 'verified', 'tables': len(m['tables']), 'indices': len(m['indices'])}))
    elif a.action == 'restore-mysql': restore_mysql(a)
    else: restore_es(a)


if __name__ == '__main__': main()

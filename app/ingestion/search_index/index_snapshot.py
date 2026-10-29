"""Local snapshot full-index builder. No AWS/DB/model calls, source-neutral keys."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import secrets
import sys
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'app/backend'))
from src.repositories.elasticsearch_jobs import ElasticsearchJobRepository
from src.schemas.search import SearchPlan

BASE = 'http://127.0.0.1:19200'
ALIAS = 'career-jobs-local-read'

def request(method, path, body=None):
    data = None if body is None else json.dumps(body, ensure_ascii=False).encode('utf-8')
    with urlopen(Request(BASE + path, data, {'Content-Type': 'application/json'}, method=method), timeout=60) as r:
        return json.load(r)

def document(row):
    source, source_id = row.get('source'), str(row.get('source_id') or '')
    if not isinstance(source, str) or not source or not source_id:
        raise ValueError('source_and_source_id_required')
    key = json.dumps([source, source_id], ensure_ascii=False, separators=(',', ':'))
    doc = {f: row.get(f) or '' for f in ['title', 'company_name', 'source_url', 'responsibilities',
             'qualifications', 'preferred_requirements', 'benefits', 'hiring_process', 'application_notes']}
    for f, value in doc.items():
        if not isinstance(value, str):
            raise ValueError('text_field_must_be_string:' + f)
    skills = row.get('tech_stacks') or []
    addresses = row.get('addresses') or []
    if not isinstance(skills, list) or any(not isinstance(s, str) for s in skills):
        raise ValueError('invalid_skills')
    if not isinstance(addresses, list):
        raise ValueError('invalid_addresses')
    status = row.get('recruitment_status', 'unknown')
    if status not in ('active', 'closed', 'unknown'):
        raise ValueError('invalid_status')
    doc.update(source=source, source_id=source_id, document_key=key,
               source_version=str(row.get('source_version') or row.get('content_hash') or 'snapshot'),
               skills=skills, skills_text=' '.join(skills), addresses=addresses,
               location_search=json.dumps(addresses, ensure_ascii=False) + ' ' + (row.get('location_text') or ''),
               recruitment_status=status, deadline_type=row.get('deadline_type') or 'unknown',
               deadline_at=row.get('deadline_at'), published_at=row.get('published_at'),
               last_seen_at=row.get('last_seen_at'), deadline_at_raw=row.get('deadline_at_raw') or '')
    return hashlib.sha256(key.encode()).hexdigest(), doc

def run(path):
    raw = path.read_bytes()
    rows = json.loads(raw.decode('utf-8-sig'))
    if not isinstance(rows, list) or not rows:
        raise ValueError('nonempty_snapshot_array_required')
    documents = [document(row) for row in rows]
    if len({key for key, _ in documents}) != len(documents):
        raise ValueError('duplicate_source_and_id')
    mapping = json.loads((ROOT / 'infra/elasticsearch/config/jobs.local.json').read_text(encoding='utf-8'))
    properties = mapping['mappings']['properties']
    for f in ['company_name', 'responsibilities', 'preferred_requirements', 'skills_text']:
        properties[f] = {'type': 'text', 'analyzer': 'ko_text'}
    for f in ['document_key', 'source_url', 'deadline_type', 'deadline_at_raw']:
        properties[f] = {'type': 'keyword', 'index': f != 'source_url'}
    for f in ['benefits', 'hiring_process', 'application_notes']:
        properties[f] = {'type': 'text', 'index': False}
    properties['addresses'] = {'type': 'object', 'enabled': False} if any(isinstance(x, dict) for _, d in documents for x in d['addresses']) else {'type': 'keyword', 'index': False}
    properties['location_search'] = {'type': 'keyword'}
    for f in ['deadline_at', 'published_at', 'last_seen_at']:
        properties[f] = {'type': 'date'}
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ').lower()
    index = 'career-jobs-local-' + stamp + '-' + secrets.token_hex(3)
    request('PUT', '/' + index, mapping)
    # Bulk failures stop before alias switch. Keep the failed index for diagnosis.
    for start in range(0, len(documents), 100):
        lines = []
        for key, doc in documents[start:start + 100]:
            lines += [json.dumps({'index': {'_index': index, '_id': key}}), json.dumps(doc, ensure_ascii=False)]
        data = ('\n'.join(lines) + '\n').encode()
        with urlopen(Request(BASE + '/_bulk', data, {'Content-Type': 'application/x-ndjson'}, method='POST'), timeout=60) as r:
            result = json.load(r)
        if result.get('errors'):
            statuses = [v['index']['status'] for v in result['items'] if v['index']['status'] >= 300]
            raise RuntimeError('bulk_failed_statuses:' + str(statuses))
    request('POST', '/' + index + '/_refresh')
    assert request('GET', '/' + index + '/_count')['count'] == len(documents)
    repo = ElasticsearchJobRepository(request, index=index, include_unverified=True)
    cases = [('React', SearchPlan(skills=('React',))), ('react_ko', SearchPlan(skills=('리액트',))),
             ('react_typo', SearchPlan(skills=('리엑트',))),
             ('frontend', SearchPlan(keyword='프론트엔드 개발')),
             ('backend', SearchPlan(keyword='백엔드 서버 개발')),
             ('react_seoul', SearchPlan(skills=('React',), region='서울')),
             ('react_typescript', SearchPlan(skills=('React', 'TypeScript'))),
             ('negative', SearchPlan(skills=('NonexistentSkillXYZ918',)))]
    checks = {}
    for name, plan in cases:
        total, hits = repo.search(plan)
        checks[name] = {'total': total, 'top': [{'source': h['source'], 'id': h['source_id'], 'title': h['title']} for h in hits]}
        assert all(h['recruitment_status'] in ('active', 'unknown') for h in hits)
    assert checks['React']['total'] == checks['react_ko']['total'] == checks['react_typo']['total']
    assert checks['negative']['total'] == 0
    # Atomic alias switch, retaining old indexes for rollback.
    request('POST', '/_aliases', {'actions': [
        {'remove': {'index': 'career-jobs-local-*', 'alias': ALIAS, 'must_exist': False}},
        {'add': {'index': index, 'alias': ALIAS}}]})
    output = ROOT / 'workspace/search-index' / stamp
    output.mkdir(parents=True, exist_ok=True)
    report = {'status': 'indexed_local_only', 'records': len(rows), 'index': index, 'alias': ALIAS,
              'sha256': hashlib.sha256(raw).hexdigest(), 'mapping_sha256': hashlib.sha256(json.dumps(mapping, sort_keys=True).encode()).hexdigest(),
              'queries': checks, 'production_connected': False, 'db_status_recheck_connected': False,
              'note': 'Snapshot counts do not imply current hiring or judged relevance.'}
    (output / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'records': len(rows), 'report': str(output / 'report.json'), 'counts': {k: v['total'] for k, v in checks.items()}}))

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--input', type=Path, required=True)
    run(parser.parse_args().input)

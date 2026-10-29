"""Isolated retrieval experiment: no AWS, model calls, or existing DB access."""
import csv
import hashlib
import json
import os
from pathlib import Path
import random
import secrets
import statistics
import subprocess
import sys
import time
from datetime import datetime, timezone
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'app/backend'))
from src.repositories.mysql_jobs import MySQLJobRepository
from src.schemas.search import SearchPlan
import pymysql

ALIASES = {'리액트': 'React', '리엑트': 'React', 'react.js': 'React',
           '파이썬': 'Python', '마이에스큐엘': 'MySQL', 'postgres': 'PostgreSQL'}
QUERIES = [
    ('react', '', ['React'], ''), ('react_lower', '', ['react'], ''),
    ('react_ko', '', ['리액트'], ''), ('react_typo', '', ['리엑트'], ''),
    ('react_js', '', ['React.js'], ''), ('python', '', ['Python'], ''),
    ('python_ko', '', ['파이썬'], ''), ('mysql', '', ['MySQL'], ''),
    ('mysql_ko', '', ['마이에스큐엘'], ''), ('postgres', '', ['Postgres'], ''),
    ('react_seoul', '', ['React'], '서울'),
    ('react_typescript', '', ['React', 'TypeScript'], ''),
    ('frontend_phrase', '프론트엔드 개발', [], ''),
    ('backend_phrase', '백엔드 서버 개발', [], ''),
    ('ai_modeling', 'AI 모델링', [], ''),
    ('machine_learning', '머신러닝 모델', [], ''),
    ('negative_skill', '', ['NonexistentSkillXYZ918'], ''),
    ('sql_exact', '', ['SQL'], ''),
]

def docker(*args):
    return subprocess.check_output(['docker', *args], text=True, stderr=subprocess.STDOUT).strip()

def http(method, path, data=None):
    body = None if data is None else json.dumps(data).encode()
    with urlopen(Request('http://127.0.0.1:19200' + path, body,
                         {'Content-Type': 'application/json'}, method=method), timeout=30) as r:
        return json.load(r)

def main():
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    out = ROOT / 'workspace/search-eval' / stamp
    out.mkdir(parents=True)
    snapshot = ROOT / 'app/backend/local-data/jumpit_all_v3/jobs.normalized.json'
    raw = snapshot.read_bytes()
    jobs = json.loads(raw)
    assert isinstance(jobs, list)
    password = secrets.token_urlsafe(32)
    names = ['career-search-eval-mysql-' + stamp.lower(), 'career-search-eval-es-' + stamp.lower()]
    started = []
    def connect():
        return pymysql.connect(host='127.0.0.1', port=19208, user='root', password=password,
                               database='evaluation', charset='utf8mb4',
                               cursorclass=pymysql.cursors.DictCursor, autocommit=True)
    try:
        env = dict(os.environ, MYSQL_ROOT_PASSWORD=password)
        subprocess.run(['docker', 'run', '--rm', '-d', '--name', names[0],
                        '-p', '127.0.0.1:19208:3306', '-e', 'MYSQL_ROOT_PASSWORD',
                        '-e', 'MYSQL_DATABASE=evaluation', 'mysql:8.4'],
                       env=env, check=True, capture_output=True)
        started.append(names[0])
        docker('run', '--rm', '-d', '--name', names[1], '-p', '127.0.0.1:19200:9200',
               '-m', '2g', '-e', 'discovery.type=single-node', '-e', 'xpack.security.enabled=false',
               '-e', 'xpack.ml.enabled=false', '-e', 'xpack.license.self_generated.type=basic',
               '-e', 'node.store.allow_mmap=false', '-e', 'ES_JAVA_OPTS=-Xms512m -Xmx512m',
               'docker.elastic.co/elasticsearch/elasticsearch:9.5.5')
        started.append(names[1])
        for _ in range(90):
            try:
                c = connect()
                c.close()
                version = http('GET', '/')['version']['number']
                break
            except Exception:
                time.sleep(1)
        else:
            raise RuntimeError('isolated_engines_not_ready')
        fields = ['source', 'source_id', 'source_url', 'title', 'company_name', 'tech_stacks',
                  'addresses', 'recruitment_status', 'source_version', 'last_seen_at',
                  'deadline_type', 'deadline_at', 'published_at', 'responsibilities',
                  'qualifications', 'preferred_requirements', 'location_text']
        json_fields = {'tech_stacks', 'addresses'}
        dates = {'last_seen_at', 'deadline_at', 'published_at'}
        def date(v):
            return datetime.fromisoformat(v.replace('Z', '+00:00')).astimezone(timezone.utc).replace(tzinfo=None) if v else None
        with connect() as c, c.cursor() as cur:
            columns = ['job_id INT AUTO_INCREMENT PRIMARY KEY']
            columns += [f'`{f}` ' + ('JSON' if f in json_fields else 'DATETIME(6)' if f in dates else 'LONGTEXT') for f in fields]
            cur.execute('CREATE TABLE job_postings (' + ','.join(columns) + ') CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci')
            values = []
            for j in jobs:
                values.append([json.dumps(j.get(f) or [], ensure_ascii=False) if f in json_fields else date(j.get(f)) if f in dates else j.get(f) for f in fields])
            cur.executemany('INSERT INTO job_postings (' + ','.join(fields) + ') VALUES (' + ','.join(['%s'] * len(fields)) + ')', values)
        asof = datetime.now(timezone.utc)
        properties = {f: {'type': 'text'} for f in ['title', 'company_name', 'responsibilities', 'qualifications', 'preferred_requirements', 'tech_text']}
        properties.update({f: {'type': 'keyword'} for f in ['source_id', 'skills', 'region']})
        properties['eligible'] = {'type': 'boolean'}
        http('PUT', '/jobs', {'mappings': {'properties': properties}})
        eligible_ids = set()
        for j in jobs:
            deadline = date(j.get('deadline_at'))
            eligible = j.get('source') == 'jumpit' and j.get('recruitment_status') in ('active', 'unknown') and (j.get('deadline_type') == 'always_open' or deadline is None or deadline > asof.replace(tzinfo=None))
            if eligible:
                eligible_ids.add(j['source_id'])
            doc = {f: j.get(f) or '' for f in properties if f not in ('eligible', 'skills', 'region', 'tech_text')}
            doc.update(eligible=eligible, skills=[s.lower() for s in j.get('tech_stacks', [])],
                       region=json.dumps(j.get('addresses') or [], ensure_ascii=False) + ' ' + (j.get('location_text') or ''),
                       tech_text=' '.join(j.get('tech_stacks', [])))
            http('PUT', '/jobs/_doc/' + j['source_id'], doc)
        http('POST', '/jobs/_refresh')
        repository = MySQLJobRepository(connect, include_unverified=True)
        def normalized(plan):
            return SearchPlan(plan.keyword, plan.region, tuple(ALIASES.get(s.lower(), ALIASES.get(s, s)) for s in plan.skills), plan.limit)
        def search(arm, plan):
            if arm != 'sql_current':
                plan = normalized(plan)
            if arm.startswith('sql'):
                total, rows = repository.search(plan)
                return total, [r['source_id'] for r in rows]
            filters = [{'term': {'eligible': True}}] + [{'term': {'skills': s.lower()}} for s in plan.skills]
            if plan.region:
                escaped = plan.region.replace('\\', '\\\\').replace('*', '\\*').replace('?', '\\?')
                filters.append({'wildcard': {'region': '*' + escaped + '*'}})
            must = [{'multi_match': {'query': plan.keyword, 'fields': ['title^4', 'company_name', 'responsibilities', 'qualifications^2', 'preferred_requirements', 'tech_text^2'], 'type': 'cross_fields', 'operator': 'and'}}] if plan.keyword else []
            r = http('POST', '/jobs/_search', {'size': plan.limit, 'track_total_hits': True, 'query': {'bool': {'filter': filters, 'must': must}}, 'sort': ['_score', {'source_id': 'desc'}]})
            return r['hits']['total']['value'], [h['_id'] for h in r['hits']['hits']]
        results = []
        rng = random.Random(42)
        for qid, keyword, skills, region in QUERIES:
            plan = SearchPlan(keyword, region, tuple(skills), 10)
            for arm in ['sql_current', 'sql_aliases', 'elasticsearch']:
                total, ids = search(arm, plan)  # warmup
                elapsed = []
                for _ in range(5):
                    start = time.perf_counter()
                    total, ids = search(arm, plan)
                    elapsed.append((time.perf_counter() - start) * 1000)
                assert set(ids) <= eligible_ids
                results.append(dict(query_id=qid, arm=arm, plan=plan.to_dict(), total=total, ids=ids,
                                    latency_ms=elapsed, p50_ms=statistics.median(elapsed)))
            print(qid, flush=True)
        (out / 'results.json').write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
        pooled = sorted({(r['query_id'], i) for r in results for i in r['ids']})
        rng.shuffle(pooled)
        by_id = {j['source_id']: j for j in jobs}
        with (out / 'judgments.csv').open('w', newline='', encoding='utf-8-sig') as f:
            writer = csv.writer(f)
            writer.writerow(['query_id', 'source_id', 'title', 'company', 'skills', 'qualifications', 'url', 'grade_0_to_3'])
            for qid, i in pooled:
                j = by_id[i]
                writer.writerow([qid, i, j.get('title'), j.get('company_name'), ', '.join(j.get('tech_stacks', [])), j.get('qualifications'), j.get('source_url'), ''])
        manifest = dict(corpus=str(snapshot), corpus_sha256=hashlib.sha256(raw).hexdigest(), records=len(jobs),
                        eligible=len(eligible_ids), asof_utc=asof.isoformat(), elasticsearch_version=version,
                        queries=QUERIES, aliases=ALIASES, repetitions=5, hard_filter_violations=0,
                        limitations=['Fixed plans bypass Bedrock routing.', 'Unverified snapshots are included.',
                                     'Elasticsearch standard analyzer; no Nori, fuzzy or vector search.',
                                     'Human relevance judgments pending; counts are not relevance metrics.',
                                     'SQL sorts by recency; Elasticsearch by BM25 then source ID.',
                                     'Single-client warm latency; fixed arm order, not a throughput benchmark.'])
        (out / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
        lines = ['# Search quality pilot', '', f'Corpus: {len(jobs)}; eligible: {len(eligible_ids)}. Human relevance review pending.', '', '| query | SQL current | SQL aliases | Elasticsearch |', '|---|---:|---:|---:|']
        for q in QUERIES:
            rows = [r for r in results if r['query_id'] == q[0]]
            lines.append('| ' + q[0] + ' | ' + ' | '.join(str(r['total']) for r in rows) + ' |')
        lines += ['', 'Counts alone do not establish search quality. Grade judgments.csv before comparing precision or nDCG.', 'No AWS, Bedrock or production DB operations. Experiment containers removed after the run.']
        (out / 'REPORT.md').write_text('\n'.join(lines), encoding='utf-8')
        print(json.dumps({'status': 'complete', 'output': str(out), 'judgment_pairs': len(pooled)}))
    finally:
        for name in reversed(started):
            subprocess.run(['docker', 'rm', '-f', name], capture_output=True)

if __name__ == '__main__':
    main()

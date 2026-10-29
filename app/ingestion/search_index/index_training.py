"""Read-only local MySQL export -> independent local education index."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import secrets
import sys
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'app/backend'))
from src.config import load_local_settings
from src.repositories.mysql_connection import connect_mysql
from src.repositories.elasticsearch_training import TRAINING_FIELDS, ElasticsearchTrainingRepository
from src.repositories.job_search_factory import LocalElasticTransport
from src.repositories.mysql_training import decode


def mapping():
    config = json.loads((ROOT / 'infra/elasticsearch/config/jobs.local.json').read_text(encoding='utf-8'))
    config['settings']['analysis']['filter']['tech_synonyms']['synonyms'] += ['ui/ux, ui ux, uiux, 사용자 경험 디자인', 'figma, 피그마']
    properties = {k: {'type': 'keyword'} for k in ['source', 'source_id', 'source_version', 'document_key', 'recruitment_status']}
    for name in ['title', 'provider_name', 'curriculum', 'eligibility', 'preferred_conditions', 'benefits', 'selection_process', 'application_notes']:
        properties[name] = {'type': 'text', 'analyzer': 'ko_text'}
    for name in ['learning_topics', 'tech_stacks']:
        properties[name] = {'type': 'text', 'analyzer': 'tech_exact', 'search_analyzer': 'tech_query'}
    config['mappings'] = {'dynamic': 'strict', 'properties': properties}
    return config


def main():
    load_local_settings()
    request = LocalElasticTransport('http://127.0.0.1:19200')
    conn = connect_mysql()
    try:
        with conn.cursor() as cursor:
            cursor.execute('SELECT ' + TRAINING_FIELDS + " FROM training_offerings WHERE source IN ('boottent','goyong24_training') ORDER BY source,source_id")
            rows = cursor.fetchall()
    finally:
        conn.close()
    if not rows:
        raise ValueError('No education rows; keep existing alias')
    documents = []
    config = mapping()
    for row in rows:
        doc = {key: row.get(key) or '' for key in config['mappings']['properties']}
        for name in ['learning_topics', 'tech_stacks']:
            doc[name] = decode(row.get(name), [])
        doc['source_version'] = str(row['source_version'])
        doc['document_key'] = json.dumps([row['source'], row['source_id']], ensure_ascii=False, separators=(',', ':'))
        if any(not isinstance(doc[k], str) for k in doc if k not in ('learning_topics', 'tech_stacks')):
            raise ValueError('Invalid training text')
        documents.append(doc)
    if len({d['document_key'] for d in documents}) != len(documents):
        raise ValueError('Duplicate training source and ID')
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ').lower()
    index = 'career-training-local-' + stamp + '-' + secrets.token_hex(3)
    request('PUT', '/' + index, config)
    for doc in documents:
        key = hashlib.sha256(doc['document_key'].encode()).hexdigest()
        request('PUT', '/' + index + '/_doc/' + key, doc)
    request('POST', '/' + index + '/_refresh')
    assert request('POST', '/' + index + '/_count', {})['count'] == len(rows)
    repo = ElasticsearchTrainingRepository(connect_mysql, request, index=index)
    checks = {}
    for topic in ['React', '리액트', 'Python', 'UI/UX', 'NonexistentTrainingXYZ918']:
        courses = repo.search([topic])
        checks[topic] = {'cards': len(courses), 'titles': [c['title'] for c in courses],
                         'application_candidates': sum(c['recommendation_eligible'] for c in courses)}
    assert checks['React'] == checks['리액트']
    assert checks['NonexistentTrainingXYZ918']['cards'] == 0
    request('POST', '/_aliases', {'actions': [
        {'remove': {'index': 'career-training-local-*', 'alias': 'career-training-local-read', 'must_exist': False}},
        {'add': {'index': index, 'alias': 'career-training-local-read'}}]})
    output = ROOT / 'workspace/search-index' / ('training-' + stamp)
    output.mkdir(parents=True, exist_ok=False)
    report = {'status': 'passed', 'records': len(rows), 'index': index, 'queries': checks,
              'database_writes': 0, 'model_calls': 0, 'aws_operations': 0,
              'mapping_sha256': hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()}
    (output / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    (output / 'mapping.json').write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'status': 'passed', 'records': len(rows), 'report': str(output / 'report.json'),
                      'checks': {k: {'cards': v['cards'], 'application_candidates': v['application_candidates']} for k, v in checks.items()}}))

if __name__ == '__main__':
    main()

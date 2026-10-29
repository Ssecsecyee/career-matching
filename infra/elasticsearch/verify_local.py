"""Local-only analyzer smoke check. Uses an isolated synthetic index and deletes it."""
import json
from pathlib import Path
import secrets
from urllib.request import Request, urlopen

BASE = 'http://127.0.0.1:19200'
def request(method, path, body=None):
    data = None if body is None else json.dumps(body, ensure_ascii=False).encode('utf-8')
    with urlopen(Request(BASE + path, data=data, method=method,
                         headers={'Content-Type': 'application/json'}), timeout=20) as response:
        return json.load(response)

def main():
    index = 'career-analysis-smoke-' + secrets.token_hex(6)
    created = False
    try:
        plugins = request('GET', '/_nodes/plugins')
        assert all(any(p['name'] == 'analysis-nori' for p in node['plugins']) for node in plugins['nodes'].values())
        mapping = json.loads((Path(__file__).parent / 'config/jobs.local.json').read_text(encoding='utf-8'))
        request('PUT', '/' + index, mapping)
        created = True
        for i, source in enumerate(['jumpit', 'goyong24']):
            request('PUT', f'/{index}/_doc/{source}:same-id', {
                'source': source, 'source_id': 'same-id', 'source_version': '1',
                'title': '프론트엔드 개발자를 모집합니다', 'qualifications': '웹 개발 경험',
                'skills': ['React', 'C++', 'C#', 'Next.js', 'PostgreSQL'], 'recruitment_status': 'unknown'})
        request('POST', f'/{index}/_refresh')
        tests = 0
        for term in ['React', 'react', '리액트', '리엑트', 'React.js', 'C++', 'C#', 'Next.js', 'Postgres']:
            result = request('POST', f'/{index}/_search', {'query': {'match': {'skills': term}}})
            assert result['hits']['total']['value'] == 2, term
            tests += 1
        for term in ['C', 'Next', 'NonexistentSkillXYZ']:
            result = request('POST', f'/{index}/_search', {'query': {'match': {'skills': term}}})
            assert result['hits']['total']['value'] == 0, term
            tests += 1
        analysis = request('POST', f'/{index}/_analyze', {'analyzer': 'ko_text', 'text': '개발자를 모집합니다'})
        tokens = [item['token'] for item in analysis['tokens']]
        assert len(tokens) > 1
        result = request('POST', f'/{index}/_search', {'query': {'bool': {'must': [{'match': {'skills': '리액트'}}], 'filter': [{'term': {'source': 'goyong24'}}]}}})
        assert result['hits']['total']['value'] == 1
        print(json.dumps({'status': 'passed', 'engine': request('GET', '/')['version']['number'],
                          'technology_checks': tests, 'source_collision_check': 'passed',
                          'korean_tokens': tokens, 'synthetic_documents_only': True}, ensure_ascii=True))
    finally:
        if created:
            request('DELETE', '/' + index)

if __name__ == '__main__':
    main()

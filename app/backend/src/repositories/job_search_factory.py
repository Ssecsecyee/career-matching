"""Explicit backend selection; Elasticsearch connection is loopback-only for now."""
import json
import os
import re
import ssl
from urllib.error import HTTPError, URLError
from src.repositories.search_failover import SearchFailover, SearchUnavailable
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from src.repositories.mysql_jobs import MySQLJobRepository
from src.repositories.elasticsearch_jobs import build_query


class LocalElasticTransport:
    def __init__(self, endpoint):
        parsed = urlsplit(endpoint)
        if (parsed.scheme != 'http' or parsed.hostname != '127.0.0.1' or parsed.port != 19200
                or parsed.username or parsed.password or parsed.path not in ('', '/')
                or parsed.query or parsed.fragment):
            raise ValueError('local_elasticsearch_endpoint_required')
        self.endpoint = 'http://127.0.0.1:19200'

    def __call__(self, method, path, body=None):
        data = None if body is None else json.dumps(body).encode('utf-8')
        try:
            with urlopen(Request(self.endpoint + path, data, {'Content-Type': 'application/json'},
                                 method=method), timeout=10) as result:
                payload = result.read(8 * 1024 * 1024 + 1)
        except HTTPError as exc:
            if exc.code in (502,503,504):
                raise SearchUnavailable('elasticsearch_unavailable') from None
            raise
        except URLError as exc:
            if isinstance(exc.reason, ssl.SSLError):
                raise
            if isinstance(exc.reason, (ConnectionError, TimeoutError, OSError)):
                raise SearchUnavailable('elasticsearch_connection_failed') from None
            raise
        except ssl.SSLError:
            raise
        except (ConnectionError, TimeoutError):
            raise SearchUnavailable('elasticsearch_connection_failed') from None
        if len(payload) > 8 * 1024 * 1024:
            raise RuntimeError('search_response_too_large')
        return json.loads(payload)


class VerifiedElasticJobs:
    """Bounded pilot: recheck all matches in MySQL before counting/cards."""
    def __init__(self, request, database, *, index, include_unverified=False):
        if not re.fullmatch(r'[a-z][a-z0-9_-]{0,100}', index):
            raise ValueError('invalid_search_index')
        self.request, self.database, self.index = request, database, index
        self.include_unverified = include_unverified

    def get(self, source_id):
        return self.database.get(source_id)

    def search(self, plan):
        query = build_query(plan, include_unverified=self.include_unverified)
        # Current dialogue contract selects numeric Jumpit IDs. Do not merge
        # other sources until source-aware selection and DB lookup are implemented.
        query['query']['bool']['filter'].append({'term': {'source': 'jumpit'}})
        query['size'] = 1000
        query['_source'] = ['source', 'source_id', 'source_version']
        query['timeout'] = '5s'
        result = self.request('POST', '/' + self.index + '/_search', query)
        if result.get('timed_out'):
            raise SearchUnavailable('elasticsearch_query_timeout')
        if result.get('_shards', {}).get('failed', 0):
            raise RuntimeError('incomplete_search')
        hits = result['hits']
        if hits['total'].get('relation') != 'eq' or hits['total']['value'] > 1000:
            raise RuntimeError('search_verification_budget_exceeded')
        candidates = [hit['_source'] for hit in hits['hits']]
        if len(candidates) != hits['total']['value']:
            raise RuntimeError('incomplete_search')
        if any(c.get('source') != 'jumpit' for c in candidates):
            raise RuntimeError('unexpected_search_source')
        current = self.database.search_details([c['source_id'] for c in candidates])
        rows = []
        stale = 0
        for candidate in candidates:
            row = current.get(candidate['source_id'])
            if row is None or str(row['source_version']) != str(candidate['source_version']):
                stale += 1
                continue
            rows.append(row)
        self.last_verification = {'matched': len(candidates), 'verified': len(rows), 'excluded': stale}
        return len(rows), rows[:plan.limit]


def create_job_repository(connection_factory, *, include_unverified=False):
    database = MySQLJobRepository(connection_factory, include_unverified=include_unverified)
    backend = os.getenv('JOB_SEARCH_BACKEND', 'mysql')
    if backend == 'mysql':
        return database
    if backend != 'elasticsearch':
        raise ValueError('invalid_job_search_backend')
    primary = VerifiedElasticJobs(LocalElasticTransport(os.getenv('ELASTICSEARCH_URL', 'http://127.0.0.1:19200')),
                               database, index=os.getenv('ELASTICSEARCH_INDEX', 'career-jobs-local-read'),
                               include_unverified=include_unverified)
    return SearchFailover(primary, database, entity='job')

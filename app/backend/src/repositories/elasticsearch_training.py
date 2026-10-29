"""Separate education index, current facts and eligibility checked in MySQL."""
import os
import re
from src.repositories.search_failover import SearchFailover, SearchUnavailable
from src.repositories.job_search_factory import LocalElasticTransport
from src.repositories.mysql_training import MySQLTrainingRepository, card

TRAINING_FIELDS = ('offering_id,source,source_id,source_url,source_version,title,provider_name,'
                  'curriculum,learning_topics,tech_stacks,eligibility,preferred_conditions,benefits,'
                  'selection_process,application_notes,delivery_mode,addresses,tuition,currency,'
                  'cost_description,recruitment_status,additional_sections,application_deadline,content_hash')


def build_training_query(topics):
    if (not isinstance(topics, list) or not 1 <= len(topics) <= 8 or
            any(not isinstance(t, str) or not 1 <= len(t) <= 60 for t in topics)):
        raise ValueError('Invalid training topics')
    clauses = []
    for topic in topics:
        clauses.append({'bool': {'should': [
            {'match': {'tech_stacks': {'query': topic, 'boost': 4}}},
            {'match': {'learning_topics': {'query': topic, 'boost': 4}}},
            {'multi_match': {'query': topic, 'type': 'cross_fields', 'operator': 'and',
                'fields': ['title^4', 'curriculum^3', 'eligibility', 'preferred_conditions',
                           'benefits', 'selection_process', 'application_notes', 'provider_name']}}
        ], 'minimum_should_match': 1}})
    return {'size': 1000, 'track_total_hits': True, 'timeout': '5s',
            '_source': ['source', 'source_id', 'source_version'],
            'query': {'bool': {'filter': [{'terms': {'source': ['boottent', 'goyong24_training']}},
                                          {'terms': {'recruitment_status': ['active', 'unknown', 'closed']}}],
                               'should': clauses, 'minimum_should_match': 1}},
            'sort': ['_score', {'document_key': 'asc'}]}


class ElasticsearchTrainingRepository:
    def __init__(self, connection_factory, request, *, index='career-training-local-read'):
        if not re.fullmatch(r'[a-z][a-z0-9_-]{0,100}', index):
            raise ValueError('Invalid training index')
        self.factory, self.request, self.index = connection_factory, request, index

    def search(self, topics):
        result = self.request('POST', '/' + self.index + '/_search', build_training_query(topics))
        if result.get('timed_out'):
            raise SearchUnavailable('elasticsearch_query_timeout')
        if result.get('_shards', {}).get('failed', 0):
            raise RuntimeError('incomplete_training_search')
        hits = result['hits']
        if hits['total'].get('relation') != 'eq' or hits['total']['value'] > 1000 or len(hits['hits']) != hits['total']['value']:
            raise RuntimeError('training_verification_budget_exceeded')
        candidates = [h['_source'] for h in hits['hits']]
        if not candidates:
            return []
        if any(c.get('source') not in ('boottent', 'goyong24_training') or
               not isinstance(c.get('source_id'), str) or not 1 <= len(c['source_id']) <= 128 for c in candidates):
            raise RuntimeError('invalid_training_identity')
        current = {}
        conn = self.factory()
        try:
            with conn.cursor() as cursor:
                for start in range(0, len(candidates), 100):
                    batch = candidates[start:start + 100]
                    params = [v for c in batch for v in (c['source'], c['source_id'])]
                    cursor.execute('SELECT ' + TRAINING_FIELDS + ' FROM training_offerings WHERE (' +
                                   ' OR '.join(['(source=%s AND source_id=%s)'] * len(batch)) +
                                   ") AND recruitment_status IN ('active','unknown','closed')", params)
                    for row in cursor.fetchall():
                        current[row['source'], row['source_id']] = row
        finally:
            conn.close()
        courses = []
        for rank, candidate in enumerate(candidates):
            row = current.get((candidate['source'], candidate['source_id']))
            if row is None or str(row['source_version']) != str(candidate['source_version']):
                continue
            value = card(row, topics)
            value['retrieval_basis'] = 'elasticsearch_fulltext_and_topics_db_verified'
            courses.append((not value['recommendation_eligible'], rank, value))
        courses.sort(key=lambda value: value[:2])
        return [value[2] for value in courses[:3]]


def create_training_repository(connection_factory):
    selector = os.getenv('TRAINING_SEARCH_BACKEND', 'mysql')
    if selector == 'mysql':
        return MySQLTrainingRepository(connection_factory)
    if selector != 'elasticsearch':
        raise ValueError('invalid_training_search_backend')
    primary = ElasticsearchTrainingRepository(connection_factory,
        LocalElasticTransport(os.getenv('ELASTICSEARCH_URL', 'http://127.0.0.1:19200')),
        index=os.getenv('ELASTICSEARCH_TRAINING_INDEX', 'career-training-local-read'))
    return SearchFailover(primary, MySQLTrainingRepository(connection_factory), entity='training')

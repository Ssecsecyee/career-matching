"""Separate education index, current facts and eligibility checked in MySQL."""
import os
import re
from src.repositories.search_failover import SearchFailover, SearchUnavailable
from src.repositories.job_search_factory import LocalElasticTransport
from src.repositories.mysql_training import MySQLTrainingRepository, card

TRAINING_FIELDS = ('offering_id,course_key,cohort_name,source,source_id,source_url,source_version,title,provider_name,'
                  'curriculum,learning_topics,tech_stacks,eligibility,preferred_conditions,benefits,'
                  'selection_process,application_notes,delivery_mode,addresses,tuition,currency,'
                  'cost_description,recruitment_status,additional_sections,application_deadline,starts_at,ends_at,content_hash')


def build_training_query(topics, *, exclude_ids=(), delivery_mode=None, candidates_only=False, topic_operator="or", browse_all=False):
    from src.services.training_navigation import training_operator
    training_operator(topic_operator)
    if (not isinstance(topics, list) or not (0 if browse_all else 1) <= len(topics) <= 8 or
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
    from src.services.training_navigation import training_exclusions, training_mode
    excluded=training_exclusions(exclude_ids);training_mode(delivery_mode)
    extra=[]
    if excluded:
        extra.append({'bool':{'must_not':[{'bool':{'filter':[{'term':{'source':source}},{'term':{'source_id':identity}}]}} for source,identity in excluded]}})
    if candidates_only:
        extra.extend([{'range': {'training_start_at': {'gt': 'now'}}},
                      {'bool': {'must_not': [{'term': {'recruitment_status': 'closed'}}]}}])
    if delivery_mode:extra.append({'term':{'delivery_mode':delivery_mode}})
    return {'size': 100, 'track_total_hits': True, 'timeout': '5s',
            '_source': ['source', 'source_id', 'source_version'],
            'query': {'bool': {'filter': [{'terms': {'source': ['boottent', 'goyong24_training']}},
                                          {'terms': {'recruitment_status': ['active', 'unknown', 'closed']}}]+extra,
                               'should': clauses, 'minimum_should_match': (len(clauses) if topic_operator=='and' else 1) if clauses else 0}},
            'sort': ['_score', {'document_key': 'asc'}]}


class ElasticsearchTrainingRepository:
    def __init__(self, connection_factory, request, *, index='career-training-local-read'):
        if not re.fullmatch(r'[a-z][a-z0-9_-]{0,100}', index):
            raise ValueError('Invalid training index')
        self.factory, self.request, self.index = connection_factory, request, index

    def get(self, identity):
        return MySQLTrainingRepository(self.factory).get(identity)

    def search(self, topics, *, exclude_ids=(), delivery_mode=None, candidates_only=False, exclude_groups=(), topic_operator="or", browse_all=False):
        from src.services.training_groups import grouped,exclusions
        exclusions(exclude_groups)
        query = build_training_query(topics, exclude_ids=exclude_ids,
                                     delivery_mode=delivery_mode, candidates_only=candidates_only, topic_operator=topic_operator, browse_all=browse_all)
        self.search_limited = False
        self.last_candidate_total = None
        courses, seen = [], set()
        rank = 0
        for page in range(10):
            result = self.request('POST', '/' + self.index + '/_search', query)
            if result.get('timed_out'):
                raise SearchUnavailable('elasticsearch_query_timeout')
            if result.get('_shards', {}).get('failed', 0):
                raise RuntimeError('incomplete_training_search')
            hits = result['hits']
            if hits['total'].get('relation') != 'eq':
                raise RuntimeError('incomplete_training_search')
            if page==0:self.last_candidate_total=hits['total']['value']
            page_hits = hits['hits']
            if len(page_hits) != min(query['size'], max(0, hits['total']['value'] - rank)):
                raise RuntimeError('invalid_training_page')
            candidates = [hit['_source'] for hit in page_hits]
            if any(c.get('source') not in ('boottent', 'goyong24_training') or
                   not isinstance(c.get('source_id'), str) or not 1 <= len(c['source_id']) <= 128 for c in candidates):
                raise RuntimeError('invalid_training_identity')
            identities = [(c['source'], c['source_id']) for c in candidates]
            if len(set(identities)) != len(identities) or seen.intersection(identities):
                raise RuntimeError('repeated_training_page')
            seen.update(identities)
            if not candidates:
                break
            current = {}
            conn = self.factory()
            try:
                with conn.cursor() as cursor:
                    params = [v for pair in identities for v in pair]
                    cursor.execute('SELECT ' + TRAINING_FIELDS + ' FROM training_offerings WHERE (' +
                                   ' OR '.join(['(source=%s AND source_id=%s)'] * len(candidates)) +
                                   ") AND recruitment_status IN ('active','unknown','closed')", params)
                    for row in cursor.fetchall():current[row['source'], row['source_id']] = row
            finally:conn.close()
            for offset, candidate in enumerate(candidates):
                row = current.get((candidate['source'], candidate['source_id']))
                if row is None or str(row['source_version']) != str(candidate['source_version']):continue
                value = card(row, topics)
                if candidates_only and (not value['start_window_eligible'] or value['recruitment_status']=='closed'):continue
                value['retrieval_basis'] = 'elasticsearch_fulltext_and_topics_db_verified'
                courses.append((not value['recommendation_eligible'], rank + offset, value))
            rank += len(candidates)
            if len(grouped([v[2] for v in courses],exclude_groups=exclude_groups,limit=20 if browse_all else 3)) >= (20 if browse_all else 3) or len(page_hits) < query['size'] or rank >= hits['total']['value']:break
            after = page_hits[-1].get('sort')
            if not isinstance(after, list) or len(after)!=2 or after==query.get('search_after'):raise RuntimeError('invalid_training_cursor')
            query = dict(query, search_after=after)
        else:
            self.search_limited = True
        courses.sort(key=lambda value: value[:2])
        return grouped([value[2] for value in courses],exclude_groups=exclude_groups,limit=20 if browse_all else 3)



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

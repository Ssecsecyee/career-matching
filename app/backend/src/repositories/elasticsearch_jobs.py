"""Validated SearchPlan -> Elasticsearch query; not enabled by bootstrap yet."""
from src.schemas.search import SearchPlan


def build_query(plan, *, include_unverified=False):
    plan = SearchPlan.parse({**plan.to_dict(), 'skills': list(plan.skills)})
    filters = [{'terms': {'recruitment_status': ['active', 'unknown'] if include_unverified else ['active']}},
               {'bool': {'should': [
                   {'term': {'deadline_type': 'always_open'}},
                   {'bool': {'must_not': [{'exists': {'field': 'deadline_at'}}]}},
                   {'range': {'deadline_at': {'gt': 'now'}}}], 'minimum_should_match': 1}}]
    filters += [{'match': {'skills': {'query': s}}} for s in plan.skills]
    if plan.region:
        value = plan.region.replace('\\', '\\\\').replace('*', '\\*').replace('?', '\\?')
        filters.append({'wildcard': {'location_search': {'value': '*' + value + '*'}}})
    must = []
    if plan.keyword:
        must.append({'multi_match': {'query': plan.keyword, 'type': 'cross_fields', 'operator': 'and',
                     'fields': ['title^4', 'company_name', 'responsibilities', 'qualifications^2',
                                'preferred_requirements', 'skills_text']}})
    return {'size': plan.limit, 'track_total_hits': True,
            'query': {'bool': {'filter': filters, 'must': must}},
            'sort': ['_score', {'published_at': {'order': 'desc', 'missing': '_last'}},
                     {'document_key': 'asc'}]}


class ElasticsearchJobRepository:
    def __init__(self, request, *, index='career-jobs-local-read', include_unverified=False):
        self.request = request
        self.index = index
        self.include_unverified = include_unverified

    def search(self, plan):
        result = self.request('POST', '/' + self.index + '/_search',
                              build_query(plan, include_unverified=self.include_unverified))
        if result.get('timed_out') or result.get('_shards', {}).get('failed', 0):
            raise RuntimeError('incomplete_search')
        hits = result['hits']
        rows = []
        for hit in hits['hits']:
            row = dict(hit['_source'])
            row['tech_stacks'] = row.pop('skills')
            row['indexed_version'] = row['source_version']
            row['search_score'] = hit['_score']
            row['status_basis'] = 'stored_search_snapshot'
            rows.append(row)
        return hits['total']['value'], rows

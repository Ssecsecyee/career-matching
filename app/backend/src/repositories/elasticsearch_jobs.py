"""Validated SearchPlan -> Elasticsearch query; not enabled by bootstrap yet."""
import os
from src.schemas.search import SearchPlan


def build_query(plan, *, include_unverified=False, exclude_ids=()):
    plan = SearchPlan.parse({**plan.to_dict(), 'skills': list(plan.skills)})
    filters = [{'terms': {'recruitment_status': ['active', 'unknown'] if include_unverified else ['active']}},
               {'bool': {'should': [
                   {'term': {'deadline_type': 'always_open'}},
                   {'bool': {'must_not': [{'exists': {'field': 'deadline_at'}}]}},
                   {'range': {'deadline_at': {'gt': 'now'}}}], 'minimum_should_match': 1}}]
    from src.services.search_continuation import exclusion_ids
    excluded = exclusion_ids(exclude_ids)
    if excluded:
        filters.append({"bool": {"must_not": [{"terms": {"source_id": excluded}}]}})
    if plan.schema_version == 2:
        return structured_query(plan, filters)
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


def structured_query(plan, filters):
    from src.services.search_terms import region_terms, role_terms, skill_terms

    def skill(term, condition_anchor=False):
        if condition_anchor and os.getenv('ENABLE_AI_CONDITION_RANKING')=='true':
            return {'bool':{'should':[skill(term),{'multi_match':{'query':term,'fields':['required_condition_terms','preferred_condition_terms']}}],'minimum_should_match':1}}
        return {'bool': {'should': [{'match': {'skills': {'query': s}}} for s in skill_terms(term)],
                         'minimum_should_match': 1}}

    if plan.regions:
        clauses = []
        for region in region_terms(plan.regions):
            value = region.replace('\\', '\\\\').replace('*', '\\*').replace('?', '\\?')
            clauses.append({'wildcard': {'location_search': {'value': '*' + value + '*'}}})
        filters.append({'bool': {'should': clauses, 'minimum_should_match': 1}})
    if plan.roles:
        filters.append({'bool': {'should': [
            {'multi_match': {'query': role, 'type': 'cross_fields', 'operator': 'and',
              'fields': ['title^4', 'responsibilities', 'qualifications^2']}}
            for role in role_terms(plan.roles)], 'minimum_should_match': 1}})
    filters += [skill(s) for s in plan.required_skills]
    # Without a role or required skill, at least one owned skill anchors the search.
    if plan.owned_skills and not plan.roles and not plan.required_skills:
        filters.append({'bool': {'should': [skill(s,condition_anchor=True) for s in plan.owned_skills], 'minimum_should_match': 1}})
    should = [skill(s) for s in dict.fromkeys(plan.owned_skills + plan.preferred_skills)]
    if os.getenv('ENABLE_AI_CONDITION_RANKING')=='true':
        for term in dict.fromkeys(plan.owned_skills+plan.preferred_skills):
            should.append({'multi_match':{'query':term,'fields':['required_condition_terms^2','preferred_condition_terms'],'type':'best_fields'}})
    return {'size': plan.limit, 'track_total_hits': True,
            'query': {'bool': {'filter': filters, 'should': should, 'minimum_should_match': 0}},
            'sort': ['_score', {'published_at': {'order': 'desc', 'missing': '_last'}}, {'document_key': 'asc'}]}


class ElasticsearchJobRepository:
    def __init__(self, request, *, index='career-jobs-local-read', include_unverified=False):
        self.request = request
        self.index = index
        self.include_unverified = include_unverified

    def search(self, plan, *, exclude_ids=()):
        result = self.request('POST', '/' + self.index + '/_search',
                              build_query(plan, include_unverified=self.include_unverified, exclude_ids=exclude_ids))
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

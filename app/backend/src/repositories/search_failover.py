"""Fail over only for explicitly classified Elasticsearch availability failures."""
import logging


class SearchUnavailable(RuntimeError):
    pass


class SearchFailover:
    def __init__(self, primary, fallback, *, entity):
        self.primary, self.fallback, self.entity = primary, fallback, entity
        self.last_search_backend = 'elasticsearch'
        self.search_degraded = False

    def get(self, identity):
        return self.fallback.get(identity)

    def search(self, query, *, exclude_ids=(), delivery_mode=None, candidates_only=False, exclude_groups=()):
        kwargs = {'exclude_ids': exclude_ids} if exclude_ids else {}
        if delivery_mode is not None:kwargs['delivery_mode']=delivery_mode
        if candidates_only:
            if self.entity != 'training':raise ValueError('Candidate mode is for training only')
            kwargs['candidates_only']=True
        if exclude_groups:
            if self.entity != 'training':raise ValueError('Group exclusions are for training only')
            kwargs['exclude_groups']=exclude_groups
        self.last_search_backend = 'elasticsearch'
        self.search_degraded = False
        try:
            result=self.primary.search(query, **kwargs)
            self.last_candidate_total=getattr(self.primary,'last_candidate_total',None)
            self.search_limited=getattr(self.primary,'search_limited',False) is True
            return result
        except SearchUnavailable:
            self.last_candidate_total=None
            self.last_search_backend = 'mysql'
            self.search_degraded = True
            # Never include endpoints, credentials, query text, or raw exception text.
            logging.getLogger(__name__).warning('search_backend_fallback entity=%s reason=elasticsearch_unavailable', self.entity)
            result = self.fallback.search(query, **kwargs)
            self.search_limited=getattr(self.fallback,'search_limited',False) is True
            if self.entity == 'training':
                for course in result:
                    course['retrieval_basis'] = 'mysql_fallback_elasticsearch_unavailable'
            return result

import unittest
from src.repositories.elasticsearch_jobs import build_query, ElasticsearchJobRepository
from src.schemas.search import SearchPlan


class ElasticsearchQueryTests(unittest.TestCase):
    def test_default_excludes_unknown_and_checks_deadline(self):
        filters = build_query(SearchPlan())['query']['bool']['filter']
        self.assertEqual(filters[0], {'terms': {'recruitment_status': ['active']}})
        self.assertEqual(filters[1]['bool']['minimum_should_match'], 1)
        self.assertIn({'range': {'deadline_at': {'gt': 'now'}}}, filters[1]['bool']['should'])

    def test_unverified_requires_explicit_optin(self):
        filters = build_query(SearchPlan(), include_unverified=True)['query']['bool']['filter']
        self.assertEqual(filters[0]['terms']['recruitment_status'], ['active', 'unknown'])

    def test_skills_are_independent_required_filters(self):
        filters = build_query(SearchPlan(skills=('React', 'TypeScript')))['query']['bool']['filter']
        self.assertEqual(filters[2:], [{'match': {'skills': {'query': 'React'}}}, {'match': {'skills': {'query': 'TypeScript'}}}])

    def test_region_wildcards_are_literals(self):
        filters = build_query(SearchPlan(region='서울*?'))['query']['bool']['filter']
        self.assertEqual(filters[-1]['wildcard']['location_search']['value'], '*서울\\*\\?*')

    def test_invalid_limit_rejected_before_request(self):
        with self.assertRaises(ValueError):
            build_query(SearchPlan(limit=999))

    def test_partial_failure_is_not_zero_results(self):
        for response in [{'timed_out': True}, {'_shards': {'failed': 1}}]:
            repo = ElasticsearchJobRepository(lambda *args: response)
            with self.assertRaises(RuntimeError):
                repo.search(SearchPlan())

if __name__ == '__main__':
    unittest.main()

import ssl
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError, URLError
from src.repositories.search_failover import SearchFailover, SearchUnavailable
from src.repositories.job_search_factory import LocalElasticTransport


class SearchFailoverTests(unittest.TestCase):
    def test_unavailable_falls_back_once_then_next_request_tries_engine(self):
        primary=Mock();fallback=Mock()
        primary.search.side_effect=[SearchUnavailable(),(2,['es'])]
        fallback.search.return_value=(1,['db'])
        repo=SearchFailover(primary,fallback,entity='job')
        self.assertEqual(repo.search('query'),(1,['db']))
        self.assertTrue(repo.search_degraded)
        self.assertEqual(repo.last_search_backend,'mysql')
        self.assertEqual(repo.search('query'),(2,['es']))
        self.assertFalse(repo.search_degraded)
        fallback.search.assert_called_once_with('query')

    def test_zero_results_do_not_fallback(self):
        primary=Mock();fallback=Mock();primary.search.return_value=(0,[])
        self.assertEqual(SearchFailover(primary,fallback,entity='job').search('q'),(0,[]))
        fallback.search.assert_not_called()

    def test_query_and_db_errors_are_not_swallowed(self):
        primary=Mock();fallback=Mock();primary.search.side_effect=ValueError('bad query')
        with self.assertRaises(ValueError):SearchFailover(primary,fallback,entity='job').search('q')
        fallback.search.assert_not_called()
        primary.search.side_effect=SearchUnavailable();fallback.search.side_effect=RuntimeError('db failed')
        with self.assertRaises(RuntimeError):SearchFailover(primary,fallback,entity='job').search('q')

    def test_training_fallback_marks_basis(self):
        primary=Mock();fallback=Mock();primary.search.side_effect=SearchUnavailable()
        fallback.search.return_value=[{'recommendation_eligible':False}]
        result=SearchFailover(primary,fallback,entity='training').search(['React'])
        self.assertFalse(result[0]['recommendation_eligible'])
        self.assertEqual(result[0]['retrieval_basis'],'mysql_fallback_elasticsearch_unavailable')

    def test_transport_classifies_connection_timeout_and_gateway(self):
        transport=LocalElasticTransport('http://127.0.0.1:19200')
        for exc in [URLError(ConnectionRefusedError()),TimeoutError(),HTTPError('local',503,'unavailable',{},None)]:
            with patch('src.repositories.job_search_factory.urlopen',side_effect=exc):
                with self.assertRaises(SearchUnavailable):transport('POST','/test/_search',{})

    def test_http_settings_and_certificate_errors_not_masked(self):
        transport=LocalElasticTransport('http://127.0.0.1:19200')
        for code in [400,401,403,404,429]:
            with patch('src.repositories.job_search_factory.urlopen',side_effect=HTTPError('local',code,'error',{},None)):
                with self.assertRaises(HTTPError):transport('POST','/test/_search',{})
        with patch('src.repositories.job_search_factory.urlopen',side_effect=URLError(ssl.SSLError())):
            with self.assertRaises(URLError):transport('POST','/test/_search',{})

import json
import unittest
from unittest.mock import MagicMock

from src.repositories.mysql_jobs import MySQLJobRepository, literal_like
from src.schemas.search import SearchPlan


class MySQLRepositoryTests(unittest.TestCase):
    def connection(self):
        connection = MagicMock()
        cursor = connection.cursor.return_value.__enter__.return_value
        cursor.fetchone.return_value = {"total": 1}
        cursor.fetchall.return_value = [{"source_id": "42", "title": "fixture",
                                         "tech_stacks": json.dumps(["Python"]),
                                         "addresses": json.dumps(["서울"])}]
        return connection, cursor

    def test_untrusted_search_is_bound_not_sql(self):
        connection, cursor = self.connection()
        payload = "' OR 1=1 --"
        total, rows = MySQLJobRepository(lambda: connection, include_unverified=True).search(
            SearchPlan.parse({"keyword": payload, "skills": ["Python"], "limit": 3}))
        query, args = cursor.execute.call_args_list[1].args
        self.assertNotIn(payload, query)
        self.assertEqual(args[3], "%' OR 1==1 --%")
        self.assertEqual(args[-1], 3)
        self.assertEqual(total, 1)
        self.assertEqual(rows[0]["tech_stacks"], ["Python"])
        connection.close.assert_called_once()

    def test_like_wildcards_are_literal(self):
        self.assertEqual(literal_like("100%_="), "%100=%=_==%")

    def test_invalid_detail_id_never_opens_connection(self):
        factory = MagicMock()
        with self.assertRaises(ValueError):
            MySQLJobRepository(factory).get("42 OR 1=1")
        factory.assert_not_called()

    def test_connection_closes_on_database_failure(self):
        connection, cursor = self.connection()
        cursor.execute.side_effect = RuntimeError("test database unavailable")
        with self.assertRaises(RuntimeError):
            MySQLJobRepository(lambda: connection).search(SearchPlan.parse({}))
        connection.close.assert_called_once()


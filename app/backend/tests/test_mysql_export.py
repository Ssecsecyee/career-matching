from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "ingestion"))
from export_mysql_data import sql_text, sql_value, statement


class MySQLExportTests(unittest.TestCase):
    def test_quotes_are_data_in_hex_literal(self):
        malicious_text = "'; DROP TABLE job_postings; -- 한글"
        encoded = sql_text(malicious_text)
        self.assertNotIn("DROP TABLE", encoded)
        self.assertIn(malicious_text.encode("utf-8").hex(), encoded)

    def test_dates_require_timezone_and_convert_to_utc(self):
        self.assertEqual(sql_value("fetched_at", "2026-10-28T09:00:00+09:00"),
                         sql_text("2026-10-28 00:00:00.000000"))
        with self.assertRaises(ValueError):
            sql_value("fetched_at", "2026-10-28 09:00:00")

    def test_missing_provenance_rejected(self):
        with self.assertRaises(ValueError):
            statement({"source": "jumpit", "source_id": "42"})

    def test_duplicate_update_preserves_newer_database_snapshot(self):
        row = {"source": "jumpit", "source_id": "42", "source_url": "https://example.com/42",
               "title": "test", "company_name": "fixture", "fetched_at": "2026-10-28T00:00:00Z",
               "content_hash": "a" * 64, "recruitment_status": "unknown"}
        sql = statement(row)
        self.assertIn("IF(VALUES(fetched_at)>=fetched_at", sql)
        self.assertTrue(sql.endswith("fetched_at=GREATEST(fetched_at,VALUES(fetched_at));\n"))
        self.assertNotIn("DELETE", sql)


if __name__ == "__main__":
    unittest.main()

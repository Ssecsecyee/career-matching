import json
from datetime import datetime, timezone
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "ingestion"))
from normalize_all_jumpit import build_dataset, parse_time


class NormalizeAllTests(unittest.TestCase):
    def fixture(self, root, *, corrupt=False):
        merged = root / "merged"
        merged.mkdir()
        (merged / "jumpit_jobs_merged.json").write_text(
            json.dumps([{"공고 ID": "42", "카테고리": ["테스트"]}]), encoding="utf-8")
        for run_name, fetched, text in [("a", "2026-10-27T10:00:00+09:00", "old"),
                                         ("b", "2026-10-27T11:00:00+09:00", "new")]:
            run = root / "jumpit" / run_name
            details = run / "raw" / "details"
            details.mkdir(parents=True)
            (run / "provenance.json").write_text(json.dumps([
                {"position_id": "42", "fetched_at": fetched}]), encoding="utf-8")
            (details / "42.json").write_text(json.dumps({"result": {
                "id": 99 if corrupt else 42, "title": "fixture", "qualifications": text,
                "closedAt": "2026-10-27 23:59:59"}}), encoding="utf-8")
        return merged

    def test_latest_provenance_deduplicates_and_expired_status(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            merged = self.fixture(root)
            rows, report = build_dataset(root, merged, as_of=datetime(2026, 10, 28, tzinfo=timezone.utc))
        self.assertTrue(report["complete"])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["qualifications"], "new")
        self.assertEqual(rows[0]["fetched_at"], "2026-10-27T02:00:00+00:00")
        self.assertEqual(rows[0]["deadline_at"], "2026-10-27T14:59:59+00:00")
        self.assertEqual(rows[0]["recruitment_status"], "closed")
        self.assertEqual(rows[0]["source_version"], 2)
        self.assertEqual(report["field_completeness"]["application_notes"]["present"], 0)

    def test_mismatched_id_is_not_silently_imported(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            rows, report = build_dataset(root, self.fixture(root, corrupt=True),
                                         as_of=datetime(2026, 10, 28, tzinfo=timezone.utc))
        self.assertEqual(rows, [])
        self.assertFalse(report["complete"])
        self.assertEqual(report["missing_detail_ids"], ["42"])

    def test_local_snapshot_search_is_opt_in_and_preserves_status(self):
        from src.repositories.jobs import JsonJobRepository
        from src.schemas.search import SearchPlan
        rows = [{"recruitment_status": status, "title": "Python",
                 "tech_stacks": ["Python"]} for status in ("unknown", "closed", "unavailable")]
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "jobs.json"
            path.write_text(json.dumps(rows), encoding="utf-8")
            plan = SearchPlan.parse({"skills": ["Python"]})
            self.assertEqual(JsonJobRepository(path).search(plan)[0], 0)
            total, found = JsonJobRepository(path, include_unverified=True).search(plan)
        self.assertEqual(total, 1)
        self.assertEqual(found[0]["recruitment_status"], "unknown")

    def test_korean_naive_time_converts_to_utc(self):
        self.assertEqual(parse_time("2026-10-28 09:00:00").isoformat(), "2026-10-28T00:00:00+00:00")


if __name__ == "__main__":
    unittest.main()

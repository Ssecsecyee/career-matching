"""Join saved Jumpit details with collection provenance; no network or DB writes."""
import argparse
from collections import Counter
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

from normalize_jumpit import FIELDS, normalize

UTC = timezone.utc
KST = timezone(timedelta(hours=9))


def parse_time(value):
    if not value:
        return None
    if not isinstance(value, str):
        raise ValueError("Timestamp must be text")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed.replace(tzinfo=KST).astimezone(UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def build_dataset(data_root, merged_dir, *, as_of=None):
    as_of = as_of or datetime.now(UTC)
    if as_of.tzinfo is None:
        raise ValueError("as_of requires timezone")
    merged = read_json(merged_dir / "jumpit_jobs_merged.json")
    if not isinstance(merged, list):
        raise ValueError("Merged data must be an array")
    expected = {str(row["공고 ID"]): row for row in merged}
    if len(expected) != len(merged) or any(not key.isdigit() for key in expected):
        raise ValueError("Invalid or duplicate merged IDs")
    candidates = {}
    errors = []
    for run in sorted((data_root / "jumpit").iterdir()):
        if not run.is_dir() or not (run / "raw" / "details").is_dir():
            continue
        provenance_path = run / "provenance.json"
        if not provenance_path.is_file():
            errors.append({"run": run.name, "reason": "missing_provenance"})
            continue
        try:
            provenance = read_json(provenance_path)
            if not isinstance(provenance, list):
                raise ValueError("Invalid provenance")
            for record in provenance:
                identity = str(record.get("position_id", ""))
                if identity not in expected:
                    continue
                try:
                    fetched = parse_time(record.get("fetched_at"))
                    if fetched is None or fetched > as_of:
                        raise ValueError("Missing or future collection time")
                    raw_path = run / "raw" / "details" / (identity + ".json")
                    body = read_json(raw_path)
                    row = normalize(body)
                    if row["source_id"] != identity:
                        raise ValueError("Detail/provenance ID mismatch")
                    candidates.setdefault(identity, []).append((fetched, str(raw_path), row))
                except (ValueError, OSError, TypeError, KeyError, AttributeError):
                    errors.append({"run": run.name, "source_id": identity,
                                   "reason": "invalid_detail_or_provenance"})
        except (ValueError, OSError, TypeError, AttributeError):
            errors.append({"run": run.name, "reason": "invalid_provenance_file"})
    output = []
    date_errors = []
    missing = []
    for identity in sorted(expected):
        versions = sorted(candidates.get(identity, []), key=lambda item: (item[0], item[1]))
        if not versions:
            missing.append(identity)
            continue
        fetched, path, row = versions[-1]
        row["source_version"] = len(dict.fromkeys(item[2]["content_hash"] for item in versions))
        row["fetched_at"] = fetched.isoformat()
        row["last_seen_at"] = fetched.isoformat()
        row["first_seen_at"] = versions[0][0].isoformat()
        row["raw_file_path"] = path
        row["normalized_at"] = as_of.isoformat()
        row["status_checked_at"] = None
        row["status_basis"] = "saved_snapshot_only"
        row["merged_categories"] = expected[identity].get("카테고리", [])
        for raw_key, key in (("published_at_raw", "published_at"), ("deadline_at_raw", "deadline_at")):
            try:
                value = parse_time(row.get(raw_key))
                row[key] = value.isoformat() if value else None
            except (ValueError, TypeError):
                row[key] = None
                row["field_status"][key] = "parse_failed"
                date_errors.append({"source_id": identity, "field": key})
        deadline = parse_time(row["deadline_at"])
        if row["recruitment_status"] != "unavailable":
            if row["deadline_type"] != "always_open" and deadline and deadline <= as_of:
                row["recruitment_status"] = "closed"
                row["status_basis"] = "saved_deadline_passed"
            else:
                row["recruitment_status"] = "unknown"
        if row["deadline_type"] != "always_open" and deadline:
            row["deadline_type"] = "fixed_date"
        output.append(row)
    fields = list(FIELDS) + ["application_notes", "addresses"]
    completeness = {field: {"present": sum(bool(row.get(field)) for row in output),
                            "missing_or_unverified": sum(not bool(row.get(field)) for row in output)}
                    for field in fields}
    report = {"as_of": as_of.isoformat(), "expected": len(expected), "normalized": len(output),
              "missing_detail_ids": missing, "source_errors": errors, "date_errors": date_errors,
              "status_counts": dict(Counter(row["recruitment_status"] for row in output)),
              "field_completeness": completeness, "network_requests": 0,
              "complete": not missing and not errors and not date_errors,
              "notes": ["Latest saved snapshot selected by collection time, not filename.",
                        "unknown is not active. Use local snapshot opt-in only for search wiring.",
                        "source_version counts observed distinct snapshots; DB ingestion must assign durable revisions."]}
    return output, report


def main():
    root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, default=root / "workspace" / "api추출테스트" / "data")
    parser.add_argument("--merged-dir", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True, help="New directory; existing directories refused")
    args = parser.parse_args()
    merged_dir = args.merged_dir or args.data_root / "jumpit_merged" / "20261027_203553"
    if args.output_dir.exists():
        parser.error("Output directory already exists; choose a new name")
    rows, report = build_dataset(args.data_root, merged_dir)
    args.output_dir.mkdir(parents=True, exist_ok=False)
    for name, value in (("jobs.normalized.json", rows), ("normalization_report.json", report)):
        with (args.output_dir / name).open("x", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
    print(json.dumps({key: report[key] for key in
                      ("expected", "normalized", "complete", "status_counts", "network_requests")},
                     ensure_ascii=False))
    if not report["complete"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()

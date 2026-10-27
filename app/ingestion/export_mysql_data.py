"""Create a separate MySQL data import file. No network or database connection."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import re


JSON_COLUMNS = {"tech_stacks", "original_categories", "role_categories", "addresses",
                "education_source", "career_source", "field_status", "additional_sections", "raw_detail"}
DATE_COLUMNS = {"published_at", "deadline_at", "fetched_at", "last_seen_at", "source_updated_at"}
COLUMNS = ["source", "source_id", "source_url", "title", "company_name", "company_url",
           "service_info", "responsibilities", "qualifications", "preferred_requirements",
           "benefits", "hiring_process", "application_notes", "tech_stacks", "original_categories",
           "role_categories", "addresses", "location_text", "education_text", "education_source",
           "career_source", "published_at", "deadline_at", "deadline_type", "recruitment_status",
           "field_status", "additional_sections", "raw_detail", "content_hash", "source_version",
           "source_updated_at", "fetched_at", "last_seen_at"]


def sql_text(value):
    # Hex literals are independent of quote escaping and NO_BACKSLASH_ESCAPES mode.
    return "CONVERT(0x" + value.encode("utf-8").hex() + " USING utf8mb4)" if value else "''"


def sql_value(column, value):
    if value is None:
        return "NULL"
    if column in JSON_COLUMNS:
        return sql_text(json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":")))
    if column in DATE_COLUMNS:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError("Normalized timestamp must include timezone")
        return sql_text(parsed.astimezone(timezone.utc).replace(tzinfo=None).isoformat(sep=" ", timespec="microseconds"))
    if column == "source_version":
        return "1"  # A new database assigns its own revision sequence.
    if not isinstance(value, str):
        raise ValueError("Expected text: " + column)
    return sql_text(value)


def statement(row):
    if row.get("source") != "jumpit" or not re.fullmatch(r"\d{1,128}", row.get("source_id", "")):
        raise ValueError("Invalid source/ID")
    for field in ("source_url", "title", "company_name", "fetched_at"):
        if not isinstance(row.get(field), str) or not row[field].strip():
            raise ValueError("Missing required field: " + field)
    if not re.fullmatch(r"[0-9a-f]{64}", row.get("content_hash", "")):
        raise ValueError("Invalid content hash")
    if row.get("recruitment_status") not in {"active", "closed", "unknown", "unavailable"}:
        raise ValueError("Invalid recruitment status")
    values = [sql_value(column, 1 if column == "source_version" else row.get(column)) for column in COLUMNS]
    # Keep fetched_at last: all preceding guards compare against the old collection time.
    updates = ["source_version=IF(VALUES(fetched_at)>=fetched_at AND NOT(content_hash<=>VALUES(content_hash)),source_version+1,source_version)"]
    for column in COLUMNS:
        if column in {"source", "source_id", "source_version", "fetched_at"}:
            continue
        updates.append(f"{column}=IF(VALUES(fetched_at)>=fetched_at,VALUES({column}),{column})")
    updates.append("fetched_at=GREATEST(fetched_at,VALUES(fetched_at))")
    return ("INSERT INTO job_postings (" + ",".join(COLUMNS) + ") VALUES (" +
            ",".join(values) + ") ON DUPLICATE KEY UPDATE " + ",".join(updates) + ";\n")


def export_file(source, output):
    rows = json.loads(source.read_text(encoding="utf-8-sig"))
    if not isinstance(rows, list) or not rows:
        raise ValueError("Expected a non-empty normalized array")
    identities = [(row.get("source"), row.get("source_id")) for row in rows]
    if len(identities) != len(set(identities)):
        raise ValueError("Duplicate source IDs")
    # Validate all rows before opening a new output file.
    for row in rows:
        statement(row)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write("-- Data only. Run schema.sql first in the selected MySQL 8.0 database.\n")
        handle.write("-- Contains original snapshots; do not commit or publish this file.\n")
        handle.write("-- VALUES() is supported in MySQL 8.0/8.4, but deprecated; this is not a migration file.\n")
        handle.write("SET NAMES utf8mb4;\nSET time_zone='+00:00';\nSTART TRANSACTION;\n")
        for row in rows:
            handle.write(statement(row))
        handle.write("COMMIT;\n")
    return {"exported": len(rows), "status_counts": dict(Counter(r["recruitment_status"] for r in rows)),
            "database_connections": 0, "network_requests": 0,
            "note": "SQL file created only; job_requirements semantic extraction is not performed."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Output already exists; choose a new filename")
    try:
        result = export_file(args.input, args.output)
    except (ValueError, OSError, TypeError, KeyError) as exc:
        parser.exit(2, "Export failed: " + type(exc).__name__ + ". Check input and output paths/data.\n")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()

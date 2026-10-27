"""Offline normalization only. No network requests or database writes."""
import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

FIELDS = {"service_info": "serviceInfo", "responsibilities": "responsibility",
          "qualifications": "qualifications", "preferred_requirements": "preferredRequirements",
          "benefits": "welfares", "hiring_process": "recruitProcess"}


def normalize(body):
    detail = body.get("result")
    if not isinstance(detail, dict) or not detail.get("id"):
        raise ValueError("Missing detail result/id")
    source_id = str(detail["id"])
    if not source_id.isdigit():
        raise ValueError("Invalid source ID")
    row = {"source": "jumpit", "source_id": source_id,
           "source_url": "https://jumpit.saramin.co.kr/position/" + source_id,
           "title": detail.get("title"), "company_name": detail.get("companyName"),
           "company_url": detail.get("companyUrl"),
           "tech_stacks": list(dict.fromkeys(s["stack"] for s in detail.get("techStacks", [])
                                            if isinstance(s, dict) and s.get("stack"))),
           "original_categories": detail.get("jobCategories", []),
           "addresses": list(dict.fromkeys(p["address"] for p in detail.get("workingPlaces", [])
                                          if isinstance(p, dict) and p.get("address"))),
           "location_text": detail.get("location"),
           "education_text": detail.get("educationName"),
           "education_source": {k: detail.get(k) for k in ("education", "graduate")},
           "career_source": {k: detail.get(k) for k in ("newcomer", "minCareer", "maxCareer")},
           "published_at_raw": detail.get("publishedAt"),
           "deadline_at_raw": detail.get("closedAt"),
           "deadline_type": "always_open" if detail.get("alwaysOpen") else "unknown",
           "recruitment_status": "unknown", "source_version": 1,
           "application_notes": None,
           "raw_detail": detail}
    for target, key in FIELDS.items():
        value = detail.get(key)
        row[target] = value if isinstance(value, str) and value.strip() else None
    row["field_status"] = {key: "present" if row[key] else "not_provided"
                           for key in FIELDS}
    row["field_status"]["application_notes"] = "needs_page_verification"
    # Collection success says nothing about whether the posting is still open today.
    if detail.get("hiddenPosition") or detail.get("invisible"):
        row["recruitment_status"] = "unavailable"
    canonical = json.dumps(detail, ensure_ascii=False, sort_keys=True,
                           separators=(",", ":")).encode("utf-8")
    row["content_hash"] = hashlib.sha256(canonical).hexdigest()
    row["normalized_at"] = datetime.now(timezone.utc).isoformat()
    # fetched_at/last_seen_at require collector provenance, not file modification time.
    row["fetched_at"] = None
    row["last_seen_at"] = None
    return row


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True, help="Directory of detail JSON files")
    parser.add_argument("--output", type=Path, required=True, help="New output JSON, never overwrite")
    args = parser.parse_args()
    if not args.input.is_dir() or args.output.exists():
        parser.error("Input must exist; output must not already exist")
    rows = [normalize(json.loads(path.read_text(encoding="utf-8-sig")))
            for path in sorted(args.input.glob("*.json"))]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as handle:
        json.dump(rows, handle, ensure_ascii=False, indent=2)
    print(json.dumps({"normalized": len(rows), "network_requests": 0,
                      "note": "DB import requires verified status, provenance and dates"}))


if __name__ == "__main__":
    main()

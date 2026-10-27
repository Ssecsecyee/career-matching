"""Local JSON adapter. Not a durable session store or an AWS database."""
import json
from pathlib import Path
from typing import Protocol

from src.schemas.search import SearchPlan


class JobRepository(Protocol):
    def search(self, plan: SearchPlan) -> tuple[int, list[dict]]: ...


class JsonJobRepository:
    def __init__(self, path, *, include_unverified=False):
        self.include_unverified = include_unverified
        self.rows = json.loads(Path(path).read_text(encoding="utf-8-sig"))
        if not isinstance(self.rows, list) or any(not isinstance(r, dict) for r in self.rows):
            raise ValueError("Expected a normalized job array")

    def search(self, plan):
        results = []
        for row in self.rows:
            if row.get("recruitment_status") not in ({"active", "unknown"} if self.include_unverified else {"active"}):
                continue
            text = " ".join(str(row.get(k) or "") for k in
                            ("title", "company_name", "responsibilities", "qualifications",
                             "preferred_requirements")).casefold()
            address = " ".join(row.get("addresses") or []).casefold()
            stacks = {s.casefold() for s in row.get("tech_stacks", [])}
            if plan.keyword.casefold() not in text or plan.region.casefold() not in address:
                continue
            if not all(skill.casefold() in stacks for skill in plan.skills):
                continue
            results.append(row)
        return len(results), results[:plan.limit]


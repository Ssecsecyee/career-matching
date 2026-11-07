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

    def search(self, plan, *, exclude_ids=()):
        from src.services.search_continuation import exclusion_ids
        excluded = set(exclusion_ids(exclude_ids))
        results = []
        for row in self.rows:
            if row.get("source_id") in excluded:
                continue
            if row.get("recruitment_status") not in ({"active", "unknown"} if self.include_unverified else {"active"}):
                continue
            from src.services.deadlines import expired
            if expired(row):
                continue
            text = " ".join(str(row.get(k) or "") for k in
                            ("title", "company_name", "responsibilities", "qualifications",
                             "preferred_requirements")).casefold()
            address = (" ".join(row.get("addresses") or []) + " " + str(row.get("location_text") or "")).casefold()
            stacks = {s.casefold() for s in row.get("tech_stacks", [])}
            from src.services.search_terms import region_terms
            keyword_text=text if plan.text_field=='all' else (' '.join(row.get('tech_stacks') or []) if plan.text_field=='tech_stacks' else str(row.get(plan.text_field) or '')).casefold()
            if plan.keyword.casefold() not in keyword_text or (plan.region and not any(v.casefold() in address for v in region_terms([plan.region]))):
                continue
            if not all(skill.casefold() in stacks for skill in plan.skills):
                continue
            if plan.schema_version == 2:
                from src.services.search_terms import region_terms, role_terms, matches_skill
                if plan.regions and not any(s.casefold() in address for s in region_terms(plan.regions)):
                    continue
                if plan.roles and not any(s.casefold() in text for s in role_terms(plan.roles)):
                    continue
                if not all(matches_skill(stacks, s) for s in plan.required_skills):
                    continue
                if plan.owned_skills and not plan.roles and not plan.required_skills and not any(matches_skill(stacks, s) for s in plan.owned_skills):
                    continue
            results.append(row)
        if plan.schema_version == 2:
            from src.services.search_terms import matches_skill
            results.sort(key=lambda row: sum(matches_skill(row.get('tech_stacks', []), s)
                         for s in dict.fromkeys(plan.owned_skills + plan.preferred_skills)), reverse=True)
        from src.services.career_filter import filter_career
        results=filter_career(results,plan)
        from src.repositories.browse_order import shuffle_browse
        return len(results), shuffle_browse(results,plan)[:plan.limit]


"""Candidate selection only; qualification dialogue is a later service."""
import json


def search_candidates(repository, plan, *, input_char_budget=12000):
    total, rows = repository.search(plan)
    # A conservative character guard for local wiring, not a model tokenizer.
    approximate_chars = len(json.dumps(rows, ensure_ascii=False))
    choose = approximate_chars > input_char_budget
    cards = [{k: row.get(k) for k in
              ("source", "source_id", "title", "company_name", "tech_stacks",
               "addresses", "source_url", "source_version", "last_seen_at", "recruitment_status", "status_basis")}
             for row in rows]
    return {
        "stage": "choose_job" if choose else "candidates_ready",
        "total": total,
        "candidate_jobs": cards,
        "selection_recommended": choose,
        "budget_estimate": {"unit": "characters", "value": approximate_chars},
        "limitations": ["로컬 검색 연결 검증용",
                         "자격요건 추가 질문·DB 세션 저장·최종 추천은 아직 연결하지 않았습니다.",
                         "원본 스냅샷 기준이며 최신 모집 상태를 보장하지 않습니다."],
    }


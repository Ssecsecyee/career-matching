"""Parameterized structured intent clauses for the MySQL availability fallback."""
from src.services.search_terms import region_terms, role_terms, skill_terms

BODY = "LOWER(CONCAT_WS(' ',title,responsibilities,qualifications))"
LOCATION = "CONCAT_WS(' ',CAST(addresses AS CHAR CHARACTER SET utf8mb4) COLLATE utf8mb4_unicode_ci,location_text)"
TAG = "JSON_CONTAINS(LOWER(CAST(COALESCE(tech_stacks,JSON_ARRAY()) AS CHAR CHARACTER SET utf8mb4)),JSON_QUOTE(LOWER(%s)))"


def structured_clauses(plan):
    from src.repositories.mysql_jobs import literal_like
    clauses, params = [], []

    def group_skills(terms):
        pieces, values = [], []
        for term in terms:
            aliases = skill_terms(term)
            pieces.append('(' + ' OR '.join(TAG for _ in aliases) + ')')
            values.extend(aliases)
        return pieces, values

    if plan.regions:
        terms = region_terms(plan.regions)
        clauses.append('(' + ' OR '.join(LOCATION + " LIKE %s ESCAPE '='" for _ in terms) + ')')
        params.extend(literal_like(s) for s in terms)
    if plan.roles:
        terms = role_terms(plan.roles)
        clauses.append('(' + ' OR '.join(BODY + " LIKE LOWER(%s) ESCAPE '='" for _ in terms) + ')')
        params.extend(literal_like(s) for s in terms)
    pieces, values = group_skills(plan.required_skills)
    clauses.extend(pieces)
    params.extend(values)
    if plan.owned_skills and not plan.roles and not plan.required_skills:
        pieces, values = group_skills(plan.owned_skills)
        clauses.append('(' + ' OR '.join(pieces) + ')')
        params.extend(values)
    pieces, values = group_skills(tuple(dict.fromkeys(plan.owned_skills + plan.preferred_skills)))
    ranking = ' + '.join('CASE WHEN ' + s + ' THEN 1 ELSE 0 END' for s in pieces)
    return clauses, params, ranking, values

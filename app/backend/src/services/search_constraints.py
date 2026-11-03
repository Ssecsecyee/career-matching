"""Validate hard-filter provenance without natural-language routing expressions."""
from src.schemas.search import SearchPlan
from src.services.search_terms import skill_terms


def guard_required_skills(plan, previous, decision, message):
    inherited=set((previous or {}).get('required_skills',[]))
    accepted=[]; unsupported=[]
    for skill in plan.required_skills:
        valid=skill in inherited or any(
            e.skill==skill and e.quote in message and any(
                term.casefold() in e.quote.casefold() for term in skill_terms(skill))
            for e in decision.required_skill_evidence)
        (accepted if valid else unsupported).append(skill)
    audit={'basis':decision.search_basis,'unsupported_required_skills':unsupported,
           'evidence':[e.model_dump() for e in decision.required_skill_evidence]}
    if unsupported and decision.search_basis!='assessment':
        return None,audit
    values=plan.to_dict()
    values['required_skills']=accepted
    values['preferred_skills']=list(dict.fromkeys([*plan.preferred_skills,*unsupported]))
    return SearchPlan.parse(values),audit

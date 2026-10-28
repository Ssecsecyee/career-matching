"""Remove duplicated technology keywords and unrequested generic job labels."""
import re
from src.schemas.search import SearchPlan
from src.services.learning import ALIASES,topics_in

def normalize_model_search(plan,message):
    explicit={v.casefold() for v in topics_in(message)}
    represented=[skill for skill in plan.skills if skill.casefold() in explicit]
    if not plan.keyword or not represented:return plan
    residual=plan.keyword
    for skill in represented:
        canonical=next((k for k in ALIASES if k.casefold()==skill.casefold()),skill)
        for alias in sorted(ALIASES.get(canonical,[skill]),key=len,reverse=True):
            residual=re.sub(r'(?<![a-z0-9])'+re.escape(alias)+r'(?![a-z0-9])',' ',residual,flags=re.I)
    roles=('프론트엔드','백엔드','풀스택','개발자','엔지니어')
    for word in roles+('개발','관련','공고','채용','직무','포지션','분야'):
        residual=residual.replace(word,' ')
    # Domain-specific terms such as finance or security must remain explicit filters.
    if residual.strip(' ,/·-'):return plan
    role=next((r for r in roles if r in message and r in plan.keyword),'')
    return SearchPlan(keyword=role,region=plan.region,skills=plan.skills,limit=plan.limit)

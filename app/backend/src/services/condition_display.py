"""Readable source-derived labels, with no inferred eligibility or removed rules."""
import re
from src.services.learning import topics_in


def display_condition(quote):
    lines = [re.sub(r'^(?:[-*•●▪·]|\d+[.)])\s*', '', line.strip()) for line in quote.splitlines() if line.strip()]
    text = ' · '.join(lines)
    text = re.sub(r'\s+', ' ', text)
    if re.search(r'학력|학사|석사|박사|학위|대졸|졸업', text):
        category = '학력'
    elif re.search(r'경력|신입|[0-9]+\s*년', text):
        category = '경력'
    elif topics_in(text) or re.search(r'알고리즘|자료구조|객체지향|프로그래밍|API|데이터베이스', text):
        category = '직무 조건'
    elif re.search(r'소통|커뮤니케이션|책임감|열정|성장|공유|주도|협업', text):
        category = '협업·업무 방식'
    else:
        category = '직무 조건'
    # This is a compact excerpt, not a model rewrite. OR/AND clauses and
    # numbers remain in the original quote; no criteria are marked irrelevant.
    return {'summary': text[:180] + ('…' if len(text) > 180 else ''), 'category': category}

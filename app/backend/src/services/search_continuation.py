"""Bounded continuation intent and server-owned exposure tracking."""
import re


def is_more_request(text):
    value = re.sub(r'[\s.!?~…]', '', text).casefold()
    value = value.replace('딴', '다른')
    if value in {'다른거','다른것','다른공고','다음','다음거','다음공고','더보기','더보여줘','이거말고','다른것도'}:
        return True
    return bool(re.fullmatch(
        r'(?:(?:음|응|네|그럼|그러면))?(?:(?:이거|이것|그거|그것|아까거)말고)?'
        r'(?:(?:다른|다음)(?:거|것|공고|채용공고|기업|회사|목록|결과)|몇개|좀|공고)?'
        r'(?:도|들|를|을)?(?:몇개|조금|좀)?(?:더)?'
        r'(?:보여줘|보여주세요|추천해줘|추천해주세요|있어|없어|없나|볼래)', value)) and any(
            token in value for token in ('다른','다음','더','말고'))


def exclusion_ids(values):
    if not isinstance(values, (list, tuple)) or len(values) > 1000:
        raise ValueError('invalid_search_exclusions')
    if any(not isinstance(v, str) or not v.isdigit() or len(v) > 128 for v in values):
        raise ValueError('invalid_search_exclusions')
    return list(dict.fromkeys(values))


def mark_shown(state):
    page = state.get('search_navigation')
    if page is not None:
        page['shown_ids'] = list(dict.fromkeys(page['shown_ids'] + state.get('candidate_ids', [])))

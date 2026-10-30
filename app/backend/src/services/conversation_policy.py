"""Application-owned search focus and revocable assessment preferences."""
import re
from src.services.learning import requested, topics_in


def preferences(state):
    return state.setdefault('profile', {}).setdefault('assistant_preferences', {'ask_assessment': True})


def assessment_request(text):
    compact = re.sub(r'\s+', '', text)
    if (re.search(r'(?:역량|자격|조건|경력|경험|실력|스킬|기술).{0,30}(?:묻지|물어보지|질문하지|확인하지|평가하지|체크하지)', compact)
            or re.search(r'(?:질문|체크|문답).{0,10}(?:그만|하지마|생략|건너)', compact)
            or '그만물어' in compact):
        return False
    if re.search(r'(?:다시|이제).{0,12}(?:역량|자격|조건|경력).{0,16}(?:물어|확인|질문|체크)', compact):
        return True
    return None


def search_target(state, text):
    # Explicit switches override old focus. Education "공고" is not a job.
    current = re.split(r'말고|아니라|대신', text)[-1]
    education = requested(current)
    strong_job = bool(re.search(r'채용|구인|구직|일자리|취업|취직', current))
    education_listing = bool(re.search(r'(교육|훈련|부트캠프|강의)\s*(관련|모집|수강)?\s*공고', current))
    generic_job = '공고' in current and not education_listing
    if education and not generic_job and not re.search(r'채용|구인|구직|일자리', current):
        return 'training'
    if education and (strong_job or generic_job):
        if re.search(r'(들었|받았|수료했|마쳤)', current):
            return 'jobs'
        if re.search(r'둘\s*다|함께|같이|공고[와랑]|채용[과랑]', current):
            return 'clarify'
        # "React 공부할 교육 공고" stays in education. A bare job request
        # after a completed learning statement has already been handled above.
        return 'training' if education_listing or not strong_job else 'clarify'
    if education:
        return 'training'
    if strong_job or generic_job:
        return 'jobs'
    previous = state.get('learning_context') or {}
    if (state.get('conversation_target') == 'training' or previous) and topics_in(text) and len(text) <= 80:
        return 'training'
    return None


def respect_preferences(reply, state):
    if preferences(state)['ask_assessment']:
        return reply
    # Final enforcement as well as prompt guidance. Do not expose streamed
    # ability questions before this check when assessment is disabled.
    parts = re.split(r'(?<=[?？])\s*|\n+', reply)
    kept = [part for part in parts if not (
        re.search(r'역량|자격|경력|경험|실력|스킬|기술|보유|사용.*툴', part)
        and re.search(r'[?？]|알려\s*주|말씀해\s*주|궁금|여쭤|물어|있으신가', part))]
    return '\n'.join(kept).strip() or '추가 역량 질문 없이 이미 말씀하신 내용으로 안내하겠습니다.'

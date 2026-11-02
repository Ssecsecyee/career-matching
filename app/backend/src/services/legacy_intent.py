"""Deprecated expression-based routing and remaining legacy callers.

ContextRouter owns v2 free-text classification. Keep these rules isolated until
the compatibility path and its callers are retired after regression evaluation.
"""
import re
from src.services.learning import requested, topics_in


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


BUTTON_MESSAGES={
 '이미 답변한 경험을 이 공고의 이력서와 포트폴리오 준비에 연결해줘.':'prepare',
 '이 공고와 지금까지 답한 내용을 기준으로 면접 준비 방향을 알려줘. 새로운 역량 문답을 시작하지 말아줘.':'interview',
 '이 공고에서 미충족이라고 답한 조건을 기준으로 보완 방향을 정리해줘. 경력과 학위는 교육 수료로 대체하지 말아줘.':'learning_plan',
 '미확인으로 답한 조건을 쉽게 설명해줘. 추가 역량 질문 없이 원문과 이미 답한 내용으로 설명해줘.':'explain_unknown',
 '미확인 조건은 나중에 확인할게. 이미 답한 내용만 다시 정리해줘.':'defer'}


def legacy_task(message,focus=None):
    if message in BUTTON_MESSAGES:return BUTTON_MESSAGES[message]
    # New searches take priority even if resume/learning words also appear.
    if re.search(r'(?:공고|채용|기업|회사|교육|과정|부트캠프).*(?:찾|검색|보여|추천)|(?:찾|검색).{0,15}(?:공고|교육|과정)',message):
        return None
    if re.search(r'이력서|포트폴리오',message):return 'prepare'
    if '면접' in message:return 'interview'
    if re.search(r'보완\s*(?:방향|계획)|학습\s*(?:계획|루트|로드맵)|부족.{0,12}(?:보완|준비|설명)',message):return 'learning_plan'
    if re.search(r'미확인.{0,20}(?:쉽게|설명|뜻)',message):return 'explain_unknown'
    if focus and re.search(r'자세|구체|예시|예를|더\s*설명|다시\s*설명|이어서',message):return 'general'
    return None


def summary_requested(text):
    compact=re.sub(r'\s+','',text)
    if re.search(r'학습|공부|교육|이력서|포트폴리오|면접|지원서',compact):return False
    if re.search(r'(?:다른|새로운|새)공고.{0,12}(?:찾|검색)|교육.{0,10}(?:찾|추천)',compact):return False
    return bool(re.search(r'(?:답변|문답|체크|부족|미확인|지금까지|내가|근거|왜).{0,28}(?:정리|요약|부족|모자|근거|판단|설명했|미확인)|왜.{0,20}(?:정리|부족|충족)',compact)) and '쉽게설명' not in compact


def is_confirmation(text):
    return re.sub(r'[\s.!?。！？]', '', text).casefold() in {
        '응', '네', '예', 'ㅇㅇ', '좋아', '보여줘', '공고보여줘', '공고보기', '이기준으로공고보기', '이기준으로보여줘'}


def needs_review(plan, text, *, changing=False):
    # Review follows structured constraints, never an expression-based bypass.
    return (changing or len(plan.regions) > 1 or len(plan.roles) > 1 or
            len(plan.owned_skills) > 1 or bool(plan.required_skills) or bool(plan.career.levels) or
            plan.career.max_years is not None)


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
    if (state.get('conversation_target') == 'training' or previous) and (topics_in(text) or re.search(r'온라인|오프라인|다른\s*(?:거|것|과정)|더\s*(?:보여|추천)', text)) and len(text) <= 80:
        return 'training'
    return None

"""Application-owned counseling purposes; no retrieval or model intent classification."""
import json
import re
from src.services.memory import consultation_context

TASKS={'prepare','interview','learning_plan','explain_unknown','defer','general'}
INSTRUCTIONS={
 'prepare':'확인된 사용자 답변과 경험을 이력서·포트폴리오에 표현하는 예시와 준비할 증빙으로 연결하세요.',
 'interview':'선택한 공고와 저장 답변에 근거한 면접 준비 방향을 안내하세요.',
 'learning_plan':'필수 미충족부터 보완 방향을 안내하고 경력·학위·면허를 교육 수료로 대체하지 마세요.',
 'explain_unknown':'미확인 조건의 뜻과 확인할 증빙을 설명하세요. 미확인을 미충족으로 바꾸지 마세요.',
 'general':'선택한 공고의 원문·조건별 답변을 바탕으로 현재 상담 요청에 직접 답하세요.'}
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


def counseling_context(state,task):
    result=consultation_context(state)
    result['consultation_task']=task
    result['basis']='saved_job_version_and_user_self_assessments'
    result['evidence_policy']='충족 선택은 사용자 자기평가이며 실무 검증이 아니다. 충족한다고 답한 경험으로 표현하고 합격·탈락을 단정하지 않는다.'
    # Existing answers already include source quotes; never load current/new jobs here.
    answered={c.get('condition_id') for c in state.get('checks',[])}
    pending=[c for c in state.get('conditions',[]) if c['id'] not in answered]
    result['unanswered_conditions']=[{'condition_id':c['id'],'type':c['type'],'quote':c['quote'][:600],
        'quote_shortened':len(c['quote'])>600} for c in pending[:20]]
    result['unanswered_context_omitted']=len(pending)>20
    previous=state.get('learning_context') or {}
    if task=='learning_plan' and previous.get('courses'):
        result['previously_displayed_training']=previous
    if len(json.dumps(result,ensure_ascii=False))>60000:
        result.pop('previously_displayed_training',None)
        result['unanswered_conditions']=[];result['unanswered_context_omitted']=bool(pending)
    if len(json.dumps(result,ensure_ascii=False))>60000:raise ValueError('Counseling context exceeds budget')
    return result

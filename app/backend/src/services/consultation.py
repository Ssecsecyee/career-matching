"""Application-owned counseling purposes; no retrieval or model intent classification."""
import json
from src.services.memory import consultation_context

TASKS={'prepare','interview','learning_plan','explain_unknown','defer','general'}
INSTRUCTIONS={
 'prepare':'확인된 사용자 답변과 경험을 이력서·포트폴리오에 표현하는 예시와 준비할 증빙으로 연결하세요.',
 'interview':'선택한 공고와 저장 답변에 근거한 면접 준비 방향을 안내하세요.',
 'learning_plan':'필수 미충족부터 보완 방향을 안내하고 경력·학위·면허를 교육 수료로 대체하지 마세요.',
 'explain_unknown':'미확인 조건의 뜻과 확인할 증빙을 설명하세요. 미확인을 미충족으로 바꾸지 마세요.',
 'general':'선택한 공고의 원문·조건별 답변을 바탕으로 현재 상담 요청에 직접 답하세요.'}


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

# Compatibility imports; free-text v2 routing does not use these classifiers.
from src.services.legacy_intent import legacy_task, BUTTON_MESSAGES

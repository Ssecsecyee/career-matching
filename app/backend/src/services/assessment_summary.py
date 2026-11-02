"""Deterministic self-assessment summaries. No LLM, search, or eligibility scoring."""
from collections import Counter
from hashlib import sha256
import json
import re
from src.services.condition_display import display_condition
from src.services.condition_structure import source_notice

VERSION='answer-summary-v1'
STATUSES=('met','unmet','unknown')
LABELS={'required':'필수 자격요건','preferred':'우대조건'}


def build_summary(state, *, partial=False):
    selected=state.get('selected') or {}
    if not selected:return None
    conditions=state.get('conditions') or []
    checks=state.get('checks') or []
    # Upgrade legacy completed sessions from their own stored checks, never new source text.
    if not conditions:
        conditions=[{'id':c.get('condition_id') or f'legacy:{i}','type':c['type'],'quote':c['quote']} for i,c in enumerate(checks)]
    source={}
    for c in conditions:
        if not c.get('id') or c.get('type') not in LABELS:raise ValueError('Invalid summary source condition')
        if c['id'] in source:raise ValueError('Duplicate summary source condition')
        source[c['id']]=c
    answers={}
    for i,c in enumerate(checks):
        identity=c.get('condition_id') or f'legacy:{i}'
        if identity not in source or identity in answers or c.get('assessment') not in STATUSES:raise ValueError('Invalid summary answer identity')
        original=source[identity]
        if c['type']!=original['type'] or c['quote']!=original['quote']:raise ValueError('Summary answer source mismatch')
        answers[identity]=c
    groups={};items=[]
    for kind,label in LABELS.items():
        owned=[c for c in conditions if c['type']==kind]
        counts=Counter(answers[c['id']]['assessment'] for c in owned if c['id'] in answers)
        counts={status:counts[status] for status in STATUSES}
        counts.update(total=len(owned),unanswered=sum(c['id'] not in answers for c in owned))
        groups[kind]={'label':label,'counts':counts,'condition_ids':[c['id'] for c in owned]}
        for condition in owned:
            check=answers.get(condition['id'])
            if check:
                detail=check.get('detail') or ''
                items.append({'condition_id':condition['id'],'type':kind,'assessment':check['assessment'],
                    **display_condition(condition['quote'],condition.get('ai_review')),**source_notice(condition),'detail':detail[:300],'detail_shortened':len(detail)>300})
    total=len(conditions);answered=len(answers);unknown=sum(c['assessment']=='unknown' for c in answers.values())
    required=groups['required']['counts'];preferred=groups['preferred']['counts']
    partial=bool(partial or answered<total)
    if partial:
        kind='partial';headline=f'지금까지 답변한 {answered}개 조건을 정리했습니다. 아직 답하지 않은 조건은 별도로 남겼습니다.'
    elif not total:
        kind='no_conditions';headline='정리할 조건 답변이 아직 없습니다. 지원 자격 충족 여부를 판단하지 않았습니다.'
    elif unknown==answered:
        kind='all_unconfirmed';headline='모든 답변이 미확인입니다. 충족이나 미충족으로 판단하지 않았습니다.'
    elif required['unmet']:
        kind='required_gaps';headline='필수조건 중 미충족이라고 답한 내용이 있습니다. 충족한다고 답한 내용과 미확인도 나누어 정리했습니다.'
    elif required['unknown'] or required['unanswered']:
        kind='required_unconfirmed';headline='아직 확인하지 못한 필수조건이 있습니다. 문답 종료를 자격 충족으로 판단하지 않습니다.'
    elif not required['total']:
        kind='required_source_missing';headline='확인한 필수조건 자료가 없어 필수 자격 충족으로 판단하지 않았습니다.'
    elif preferred['unmet'] or preferred['unknown']:
        kind='preferred_to_review';headline='필수조건은 충족한다고 답하셨고, 우대조건에는 보완 또는 확인할 내용이 있습니다.'
    elif not preferred['total']:
        kind='required_self_reported';headline='확인한 필수조건은 충족한다고 답하셨습니다. 확인할 우대조건 자료는 없습니다.'
    else:
        kind='all_self_reported_met';headline='확인한 조건을 모두 충족한다고 답하셨습니다. 이 답변을 지원 준비에 연결할 수 있습니다.'
    # Detect a narrow, explicit conflict; do not claim to understand every contradiction.
    no_experience=r'(?:실무\s*)?경력(?:은|이|도|는)?\s*(?:전혀\s*)?(?:없|0\s*년)'
    has_career=r'경력|[0-9]+\s*년.*(?:근무|일했|개발)'
    statements=state.get('profile',{}).get('memory',{}).get('user_statements',[])
    latest_career=next((s for s in reversed(statements) if re.search(has_career,s.get('text',''))),None)
    conflicts=[]
    for identity,check in answers.items():
        if check['assessment']!='met' or not re.search(r'경력.{0,25}[1-9][0-9]*\s*년|[1-9][0-9]*\s*년.{0,15}경력',check['quote']):continue
        detail=check.get('detail','')
        basis={'kind':'answer_detail','quote':detail[:300]} if re.search(no_experience,detail) else None
        if basis is None and latest_career and re.search(no_experience,latest_career['text']):
            basis={'kind':'user_statement','statement_id':latest_career.get('id'),'quote':latest_career['text'][:300]}
        if basis:conflicts.append({'condition_id':identity,'reason':'career_statement_and_met_selection_need_review','basis':basis})
    if conflicts:headline+=' 경력에 관한 이전 진술과 선택이 다른 항목은 추가 확인 대상으로 표시했습니다.'
    if kind in {'required_gaps','preferred_to_review'}:
        actions=[('learning_plan','보완 방향 정리','이 공고에서 미충족이라고 답한 조건을 기준으로 보완 방향을 정리해줘. 경력과 학위는 교육 수료로 대체하지 말아줘.'),('prepare','이력서에 연결','이미 답변한 경험을 이 공고의 이력서와 포트폴리오 준비에 연결해줘.'),('similar_jobs','다른 공고 찾기','비슷한 다른 채용공고를 찾아줘.')]
    elif kind in {'required_unconfirmed','all_unconfirmed','partial','required_source_missing','no_conditions'}:
        actions=[('explain_unknown','미확인 조건 설명','미확인으로 답한 조건을 쉽게 설명해줘. 추가 역량 질문 없이 원문과 이미 답한 내용으로 설명해줘.'),('defer','나중에 확인','미확인 조건은 나중에 확인할게. 이미 답한 내용만 다시 정리해줘.'),('similar_jobs','다른 공고 찾기','추가 역량 질문 없이 비슷한 다른 채용공고를 찾아줘.')]
    else:
        actions=[('prepare','이력서에 연결','이미 답변한 경험을 이 공고의 이력서와 포트폴리오 준비에 연결해줘.'),('interview','면접 준비','이 공고와 지금까지 답한 내용을 기준으로 면접 준비 방향을 알려줘. 새로운 역량 문답을 시작하지 말아줘.'),('similar_jobs','다른 공고 찾기','비슷한 다른 채용공고를 찾아줘.')]
    snapshot={'source':{k:selected.get(k) for k in ('source_id','source_version')},'conditions':conditions,
              'answers':[{k:c.get(k) for k in ('condition_id','type','assessment','quote','detail')} for c in checks],
              'conflicts':conflicts,'partial':partial}
    return {'version':VERSION,'summary_id':sha256(json.dumps(snapshot,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest(),
        'kind':kind,'headline':headline,'basis':'explicit_user_self_assessment','not_a_hiring_decision':True,
        'source':{k:selected.get(k) for k in ('source_id','source_version','source_url','company_name','title')},
        'reference_count':len(state.get('reference_conditions',[])),'total':total,'answered':answered,'unanswered':total-answered,'partial':partial,'groups':groups,'items':items,
        'conflicts':conflicts,'next_actions':[{'id':i,'label':label,'message':message} for i,label,message in actions],
        'limitations':['사용자의 자기 평가이며 실무 역량 검증이나 합격 판정이 아닙니다.','미확인과 미답변은 미충족과 구분합니다.']}


def summary_context(summary):
    if not summary:return None
    return {k:summary[k] for k in ('version','summary_id','kind','headline','basis','not_a_hiring_decision','source','total','answered','unanswered','partial','groups','conflicts')}

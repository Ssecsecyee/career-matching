"""Owner-scoped saved answer review and optimistic single-condition correction."""
import hashlib
import json
from src.services.dialogue import FlowError
from src.services.memory import memory, record
from src.services.assessment_summary import build_summary
from src.services.condition_structure import source_notice

PAGE_SIZE=10


def review_version(state):
    selected=state.get('selected') or {}
    value={'source':{k:selected.get(k) for k in ('source_id','source_version')},
           'conditions':[{k:c.get(k) for k in ('id','type','quote')} for c in state.get('conditions',[])],
           'answers':[{k:c.get(k) for k in ('condition_id','type','assessment','detail','quote')} for c in state.get('checks',[])]}
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def review(state,offset=0):
    selected=state.get('selected') or {}
    checks={c.get('condition_id'):c for c in state.get('checks',[]) if c.get('condition_id')}
    conditions=state.get('conditions',[])
    items=[]
    for condition in conditions[offset:offset+PAGE_SIZE]:
        check=checks.get(condition.get('id'))
        items.append({'condition_id':condition.get('id'),'type':condition['type'],'quote':condition['quote'],
                      'assessment':check['assessment'] if check else 'unanswered','detail':(check.get('detail') or '') if check else '',
                      'editable':bool(check and selected.get('job_id') and all(k in condition for k in ('id','key','section'))),
                      **source_notice(condition)})
    value=memory(state)
    history=value.get('user_statements') or [item for item in value['statements'] if item['kind'] in {'search','statement','correction','answer_detail','consult'}]
    statements=[];size=0
    for item in reversed(history[-40:]):
        text=item.get('text','');encoded=len(text.encode('utf-8'))
        if size+encoded>32000:break
        statements.insert(0,{k:item.get(k) for k in ('id','kind','text')});size+=encoded
    counts={kind:{status:sum(c['type']==kind and c['assessment']==status for c in checks.values()) for status in ('met','unmet','unknown')} for kind in ('required','preferred')}
    return {'scope':'current_session_selected_job','source':{k:selected.get(k) for k in ('source_id','source_version','title','company_name','source_url')},
            'items':items,'total':len(conditions),'answered':len(checks),'counts':counts,'offset':offset,'page_size':PAGE_SIZE,
            'review_version':review_version(state),'statements':statements,'history_truncated':len(statements)<len(history),
            'unmapped_answer_count':sum(not c.get('condition_id') or c['condition_id'] not in {q.get('id') for q in conditions} for c in state.get('checks',[]))}


def revise(flow,state,payload):
    if not state.get('selected'):raise FlowError('saved_answer_requires_selected_job',409)
    if payload['review_version']!=review_version(state):raise FlowError('saved_answers_changed_refresh',409)
    identity=payload['condition_id']
    condition=next((c for c in state.get('conditions',[]) if c.get('id')==identity),None)
    old=next((c for c in state.get('checks',[]) if c.get('condition_id')==identity),None)
    if condition is None or old is None:raise FlowError('saved_answer_not_found',409)
    if not state['selected'].get('job_id') or any(k not in condition for k in ('key','section')):raise FlowError('saved_answer_legacy_readonly',409)
    before={k:old.get(k) for k in ('assessment','detail')}
    changed=flow.make_check(condition,payload['assessment'],payload.get('detail',''))
    state['checks']=[changed if c.get('condition_id')==identity else c for c in state['checks']]
    value=memory(state)
    value['facts']=[]
    if changed['assessment']=='unknown':value['confirmed'].pop(condition['key'],None)
    else:value['confirmed'][condition['key']]=dict(changed,source_id=state['selected']['source_id'],source_version=state['selected']['source_version'])
    record(state,f"조건 답변 정정 ({identity})\n이전 선택: {before['assessment']}\n현재 선택: {changed['assessment']}\n현재 보충 설명: {changed['detail']}\n조건 원문 일부 (전체는 저장 답변에서 확인): {condition['quote'][:1000]}",'correction')
    if state.get('stage') in {'completed','gap_guidance'}:
        state['stage']='gap_guidance' if any(c['type']=='required' and c['assessment']=='unmet' for c in state['checks']) else 'completed'
    summary=build_summary(state)
    if summary:state['answer_summary']=summary
    if state.get('stage') in {'checking_required','checking_preferred'}:
        result=flow.batch_response(state) if state.get('grouped') else flow.question_response(state)
    elif state.get('stage')=='assessment_checkpoint':result={'stage':'assessment_checkpoint'}
    else:result={'stage':'conversation'}
    result.update(message='선택한 조건의 답변만 수정했습니다. 다른 답변은 유지하며 이후 상담에 수정 내용을 반영합니다.',
                  saved_answers=review(state,payload.get('offset',0)),
                  answer_revision={'condition_id':identity,'source_id':state['selected']['source_id'],'source_version':state['selected']['source_version'],'before':before,'after':{k:changed.get(k) for k in ('assessment','detail')}})
    return state,result,[{'job':state['selected'],'check':changed,'section':condition['section']}]

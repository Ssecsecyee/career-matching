"""Session-scoped, source-backed memory. No inferred eligibility or cross-user cache."""
import hashlib
import json
import re


def memory(state):
    profile = state.setdefault('profile', {})
    return profile.setdefault('memory', {'version': 1, 'statements': [], 'facts': [], 'confirmed': {}})


def record(state, text, kind='statement'):
    if not text or not text.strip():
        return
    value = memory(state)
    seq = value.get('sequence', 0) + 1
    value['sequence'] = seq
    item = {'id': str(seq), 'kind': kind, 'text': text[:4000]}
    value['statements'] = (value['statements'] + [item])[-20:]
    if kind in {'search', 'statement', 'correction', 'answer_detail', 'consult'}:
        retain_user_statement(value, item)



def context(state):
    value = memory(state)
    # Keep original messages in chat_messages; only bounded relevant memory goes to the model.
    recent = []
    size = 0
    for item in reversed(value['statements']):
        if size + len(item['text']) > 6000:
            break
        recent.insert(0, item)
        size += len(item['text'])
        if len(recent) == 6:
            break
    return {'facts': value['facts'][-16:], 'recent_statements': recent,
            'condition_answers': [{'quote': c['quote'][:600], 'assessment': c['assessment'], 'detail': c['detail'][:300]}
                                  for c in state.get('checks', [])[-4:]]}


def apply_facts(state, facts):
    value = memory(state)
    latest = {(f['category'], f['subject'].casefold()): f for f in value['facts']}
    for fact in facts:
        latest[(fact['category'], fact['subject'].casefold())] = dict(fact, basis='user_statement')
    value['facts'] = list(latest.values())[-32:]


def condition_key(kind, quote):
    # Only exactly equal original criteria can reuse a user's explicit answer.
    return hashlib.sha256((kind + ':' + quote).encode()).hexdigest()


def split_conditions(text, kind, source_id, version):
    from src.services.condition_structure import structure_conditions
    return structure_conditions(text, kind, source_id, version)


def public_memory(state):
    value = memory(state)
    return {'facts': value['facts'], 'statement_count': len(value['statements']),
            'scope': 'current_session', 'basis': 'user_statement'}


def retain_user_statement(value, item):
    """Keep original user statements separately from checklist/assistant chatter."""
    items = value.setdefault('user_statements', [])
    items.append(dict(item, text=item['text'][:1200]))
    while len(items) > 40 or sum(len(x['text']) for x in items) > 12000:
        items.pop(0)


def restore_user_statements(state, payloads):
    """Upgrade older sessions using their own persisted user payloads only."""
    value = memory(state)
    value['user_statements'] = []
    for sequence, payload in payloads:
        action = payload.get('action')
        texts = []
        if action in {'search', 'remember', 'consult'}:
            texts.append((payload.get('message', ''), 'correction' if action == 'remember' else ('consult' if action == 'consult' else 'search')))
            profile = payload.get('profile', {})
            if isinstance(profile, dict):texts.append((profile.get('user_statement', ''), 'statement'))
        elif action == 'answer':
            texts.append((payload.get('detail', ''), 'answer_detail'))
        elif action == 'answer_batch':
            texts.extend((item.get('detail', ''), 'answer_detail') for item in payload.get('answers', []) if isinstance(item, dict))
        for index, (text, kind) in enumerate(texts):
            if isinstance(text, str) and text.strip():
                retain_user_statement(value, {'id':f'h{sequence}:{index}', 'kind':kind, 'text':text})
    value['user_history_version'] = 1


def consultation_context(state):
    """Bounded counseling evidence: every current assessment, not just the last four."""
    value = memory(state)
    selected = state.get('selected') or {}
    checks = state.get('checks', [])
    counts = {kind:{status:sum(c['type']==kind and c['assessment']==status for c in checks)
                    for status in ('met','unmet','unknown')} for kind in ('required','preferred')}
    result = context(state)
    result['assistant_preferences'] = state.get('profile',{}).get('assistant_preferences', {'ask_assessment':True})
    result['conversation_target'] = state.get('conversation_target')
    search = state.get('search_context') or {}
    if search:
        result['search_preferences'] = search['executed_plan']
        result['last_search'] = {'search_id': search['search_id'], 'summary': search['summary'],
                                 'total': search['total'], 'observed_at': search['observed_at']}
        result['displayed_job_candidates'] = state.get('candidate_jobs', []) if state.get('stage') != 'search_review' else []
    # These are user statements, not model-generated facts or inferred eligibility.
    result['user_statements'] = value.get('user_statements', [s for s in value['statements']
        if s['kind'] in {'search','statement','correction','answer_detail'}])[-40:]
    result['selected_job'] = {k:selected.get(k) for k in ('source_id','source_version','title','company_name','source_url','recruitment_status')}
    result['assessment_summary'] = {'counts':counts, 'answered':len(checks),
        'total':len(state.get('conditions', [])), 'basis':'explicit_user_self_assessment',
        'stage':state.get('stage'), 'not_a_hiring_decision':True}
    result['condition_answers'] = [{k:c.get(k) for k in ('condition_id','type','assessment','quote','detail','source_notice','parse_status','parser_version')} for c in checks]
    references=state.get('reference_conditions',[])
    if references:
        result['reference_conditions']=[{'type':c['type'],'quote':c['quote'][:400],'reason':c['ai_review']['reason'][:200]} for c in references[:20]]
        result['reference_conditions_omitted']=len(references)>20
        result['reference_policy']='질문에서 생략한 참고항목이며 사용자 충족·미충족 답변이 아닙니다.'
    if state.get('answer_summary'):
        from src.services.assessment_summary import summary_context
        result['answer_summary']=summary_context(state['answer_summary'])
    result['context_limits'] = {'user_history_window':40,'user_history_chars':12000,
        'older_user_statements_may_be_omitted':True, 'condition_text_shortened':False}
    # Preserve all assessments even for unusually long source/detail text.
    if len(json.dumps(result,ensure_ascii=False)) > 48000:
        for item in result['condition_answers']:
            item['quote'] = (item.get('quote') or '')[:200]
            item['detail'] = (item.get('detail') or '')[:100]
        result['context_limits']['condition_text_shortened'] = True
    if len(json.dumps(result,ensure_ascii=False)) > 60000:
        raise ValueError('Counseling context exceeds budget')
    return result

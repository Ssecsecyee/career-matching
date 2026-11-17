"""Explicit TXT similarity search; never an eligibility decision or keyword fallback."""
import hashlib
import json
import os
import subprocess
from src.services.dialogue import FlowError, ensure_selectable

def validate_text(text):
    if not isinstance(text,str) or not text.strip() or '\x00' in text or len(text.encode('utf-8'))>20000:
        raise ValueError('invalid_vector_text')
    return text

def audit_payload(payload):
    if payload.get('action')!='vector_search':return payload
    text=validate_text(payload['text'])
    return {k:v for k,v in payload.items() if k!='text'} | {'text_sha256':hashlib.sha256(text.encode()).hexdigest(), 'text_bytes':len(text.encode())}

def local_query(text):
    if os.getenv('ENABLE_TXT_VECTOR_SEARCH')!='true':
        raise FlowError('vector_search_not_enabled',503)
    root='/opt/career/vector-pilot-20261114'
    try:
        p=subprocess.run([root+'/venv/bin/python',root+'/txt_query.py'],input=json.dumps({'text':validate_text(text)},ensure_ascii=False),text=True,capture_output=True,timeout=90,check=False)
        if p.returncode or len(p.stdout)>100000:raise ValueError()
        result=json.loads(p.stdout)
    except (ValueError,OSError,subprocess.TimeoutExpired):
        raise FlowError('vector_search_unavailable',503) from None
    if result.get('error'):
        raise FlowError(result['error'] if result['error'] in {'vector_capacity_busy','vector_input_or_contract_invalid'} else 'vector_search_unavailable',503)
    return result

def run(state,text,jobs,*,include_unverified=False,query=local_query,candidate_filter=None):
    result=query(validate_text(text));cards=[];excluded=0;filtered=0
    candidates=result.get('results',[])
    if not isinstance(candidates,list) or len(candidates)>20:raise FlowError('vector_search_unavailable',503)
    for candidate in candidates:
        if candidate.get('source')!='jumpit':continue
        row=jobs.get(candidate['source_id'])
        try:ensure_selectable(row,include_unverified)
        except FlowError:excluded+=1;continue
        hashes=candidate.get('section_hashes',{})
        if str(row['source_version'])!=str(candidate['source_version']) or any(hashlib.sha256((row.get(section) or '').encode()).hexdigest()!=hashes.get(section+'_hash') for section in ('qualifications','preferred_requirements')):
            excluded+=1;continue
        if candidate_filter is not None and not candidate_filter(row):
            filtered+=1;continue
        card={key:row.get(key) for key in ('source','source_id','source_version','title','company_name','tech_stacks','addresses','source_url','recruitment_status','last_seen_at')}
        card['similarity_scores']=candidate.get('scores',{})
        cards.append(card)
    # Keep the selected job and assessment answers; only replace candidate navigation.
    for key in ('search_context','pending_candidate_jobs','search_navigation'):state.pop(key,None)
    state.update(stage='choose_job' if cards else 'no_results',candidate_jobs=cards,candidate_ids=[c['source_id'] for c in cards],total=len(cards))
    state['vector_navigation']={'shown_ids':[c['source_id'] for c in cards]}
    return state,{'stage':state['stage'],'candidate_jobs':cards,'total':len(cards),'retrieval_mode':'section_vector','message':f'TXT 내용과 유사한 공고 {len(cards)}건입니다. 최대 20건의 관련 후보이며 전체 일치 건수나 지원 자격 충족 결과가 아닙니다. 공고를 선택해 내 역량을 확인해 보세요.','vector_metadata':{'input_tokens':result.get('input_tokens'),'stale_excluded':excluded,'constraint_excluded':filtered,'ranking':'max_section_cosine_baseline'}},[]

"""Bounded routing snapshots and basic audit redaction; no source documents or credentials."""
import re
import json
from src.schemas.intent import INTENT_VERSION


def redact(value):
    if isinstance(value,dict):
        return {k:('[REDACTED]' if re.search(r'token|password|secret|authorization|api_key',k,re.I) else redact(v)) for k,v in value.items()}
    if isinstance(value,(list,tuple)):return [redact(v) for v in value]
    if not isinstance(value,str):return value
    if value.lstrip().startswith(('{','[')):
        try:
            parsed=json.loads(value)
            if isinstance(parsed,(dict,list)):return json.dumps(redact(parsed),ensure_ascii=False)
        except (ValueError,TypeError):pass
    value=re.sub(r'(?i)([\"\'](?:api[_ -]?key|password|secret|token|authorization)[\"\']\s*:\s*[\"\'])[^\"\']*',r'\1[REDACTED]',value)
    value=re.sub(r'(?i)bearer\s+[^\s"\\]+','Bearer [REDACTED]',value)
    value=re.sub(r'[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}','[EMAIL]',value)
    value=re.sub(r'(?<!\d)01[016789][- ]?\d{3,4}[- ]?\d{4}(?!\d)','[PHONE]',value)
    value=re.sub(r'(?i)((?:api[_ -]?key|password|secret|token)\s*[=:]\s*)[^\s,;"}]+',r'\1[REDACTED]',value)
    return value


def routing_context(state):
    selected=state.get('selected') or {}
    search=state.get('search_context') or {}
    navigation=state.get('search_navigation') or {}
    learning=state.get('learning_context') or {}
    history=state.get('profile',{}).get('memory',{}).get('statements',[])
    return redact({'contract_version':INTENT_VERSION,'stage':state.get('stage','new'),
        'conversation_target':state.get('conversation_target'),
        'selected_job':{k:selected.get(k) for k in ('source_id','source_version','title','company_name')},
        'search_plan':navigation.get('plan') or search.get('executed_plan'),
        'search_review_pending':state.get('stage')=='search_review',
        'last_job_ids':[r['source_id'] for r in state.get('candidate_jobs',[])][:30],
        'shown_job_count':len(navigation.get('shown_ids',[])),
        'training':{'status':learning.get('status'),'topics':learning.get('topics',[]),
                    'delivery_mode':learning.get('delivery_mode'),
                    'displayed_courses':[{k:c.get(k) for k in ('source','source_id','title')} for c in learning.get('courses',[])][:10]},
        'assessment':{'ask_assessment':state.get('profile',{}).get('assistant_preferences',{}).get('ask_assessment',True),
                      'answered':len(state.get('checks',[])),'total':len(state.get('conditions',[]))},
        'pending_clarification':state.get('intent_clarification'),
        'recent_messages':[{'kind':r.get('kind'),'text':r.get('text','')[:500]} for r in history[-8:]]})

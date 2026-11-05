"""Server-owned education review; unseen cards stay private until confirmation."""
from datetime import datetime,timezone
from uuid import uuid4


def signatures(courses):
    return [(c['source'],c['source_id'],str(c.get('source_version')),c.get('content_hash')) for course in courses for c in (course.get('cohorts') or [course])]


def remember_review(state,topics,mode,courses,repository,*,learning_goals=()):
    count=getattr(repository,'last_candidate_total',None)
    if type(count) is not int or count<0:count=None
    backend=getattr(repository,'last_search_backend',None)
    if not isinstance(backend,str):backend='unknown'
    filters=['주제·기관 검색어: '+', '.join(topics),'교육 시작일 이전 자료만 조회']
    if mode:filters.append('수강 방식: '+{'online':'온라인','offline':'오프라인'}[mode])
    limitations=['검색 후보 수에는 같은 과정의 여러 회차가 포함되며, 서로 다른 과정 수나 신청 가능·지원 자격 확인 건수가 아닙니다.',
        '신청 기간·현재 모집 여부·지원 대상은 고용24 또는 교육기관에서 확인해야 합니다.',
        '목록 중심 자료로 상세 커리큘럼·수강 방식이 미확인인 과정이 있습니다.']
    if learning_goals:limitations.append('학습 목표: '+', '.join(learning_goals)+' — 희망 목표로 기록하며, 과정에서 지원하는지는 저장 자료로 확인되지 않았습니다. 목표만으로 다른 분야까지 검색하지 않습니다.')
    if getattr(repository,'search_degraded',False) is True:limitations.append('검색엔진 장애로 MySQL에서 조회했으며 후보 수와 순위는 다를 수 있습니다.')
    context={'search_id':str(uuid4()),'topics':list(topics),'delivery_mode':mode,
        'learning_goals':list(learning_goals),'observed_at':datetime.now(timezone.utc).isoformat(),'candidate_total':count,
        'preview_count':len(courses),'candidate_versions':signatures(courses),'confirmed_at':None,
        'summary':{'filters':filters,'ranking':['교육명·주제·기관명 등 저장 정보의 관련성'],
                   'limitations':limitations,'candidate_total':count,'preview_count':len(courses),
                   'count_scope':'search_engine_candidates' if count is not None else 'verified_preview_only','backend':backend}}
    state['training_search_context']=context;state['conversation_target']='training'
    state['stage']='training_search_review' if courses else 'training_no_results'
    return review_response(state)


def review_response(state):
    data=state['training_search_context'];pending=state['stage']=='training_search_review'
    return {'stage':state['stage'],'search_target':'training','search_id':data['search_id'],
        'search_summary':data['summary'],'learning_opportunities':[],
        'learning_search':{'status':'review_pending' if pending else 'no_match','topics':data['topics'],'learning_goals':data.get('learning_goals',[]),'delivery_mode':data['delivery_mode']},
        'message':'이런 기준으로 교육을 찾아봤습니다. 이 기준으로 교육 목록을 보여드릴까요?' if pending else '해당 기준에서 확인 가능한 저장 교육을 찾지 못했습니다. 주제나 수강 방식을 바꿔볼까요? 실제 개설 과정이 없다는 뜻은 아닙니다.'}

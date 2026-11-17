"""AND zero -> bounded semantic candidates; never OR replanning."""
import os
from src.services.dialogue import FlowError
from src.services.search_review import remember_search
from src.services.search_terms import region_terms,matches_skill
from src.services.career_filter import filter_career
from src.services.vector_search import run,local_query

def embedding_text(plan):
    # A bounded, server-authored description, not model instructions or invented facts.
    fields=[('검색 내용',plan.text_query or plan.keyword),('직무',' / '.join(plan.roles)),
            ('필수 기술',' / '.join(plan.required_skills or plan.skills)),
            ('경험 기술',' / '.join(plan.owned_skills)),('선호 기술',' / '.join(plan.preferred_skills))]
    return '\n'.join(label+': '+value for label,value in fields if value)

def hard_constraints(row,plan,exclude_ids):
    if row.get('source_id') in exclude_ids:return False
    regions=plan.regions or ([plan.region] if plan.region else [])
    location=(' '.join(row.get('addresses') or [])+' '+str(row.get('location_text') or '')).casefold()
    if not all(any(alias.casefold() in location for alias in region_terms([term])) for term in regions):return False
    if not all(matches_skill(row.get('tech_stacks') or [],term) for term in (plan.required_skills or plan.skills)):return False
    if not filter_career([row],plan):return False
    if plan.text_field=='company_name':
        query=(plan.text_query or plan.keyword).casefold()
        if query not in (row.get('company_name') or '').casefold():return False
    return True

def fallback(flow,state,plan,raw_plan,payload,*,exclude_ids=(),query=local_query):
    if os.getenv('ENABLE_ZERO_RESULT_VECTOR_FALLBACK')!='true':return None
    text=embedding_text(plan)
    if not text:return None
    context=remember_search(state,plan,raw_plan,payload,0,[])
    original={'exact_match_total':0,'original_plan':plan.to_dict(),'original_summary':context['summary'],
              'maintained_filters':['모집 상태·마감·원문 버전','지역','명시적 필수 기술','기존 신입 확인 정책'],
              'semantic_fields':['직무·검색 문구','보유·선호 경험'],'candidate_limit':20}
    try:
        state,result,evidence=run(state,text,flow.jobs,include_unverified=flow.include_unverified,query=query,
            candidate_filter=lambda row:hard_constraints(row,plan,set(exclude_ids)))
    except FlowError as error:
        context['vector_fallback']={**original,'status':'unavailable','error_code':error.code}
        return {'status':'unavailable','metadata':context['vector_fallback']}
    context['vector_fallback']={**original,'status':'used' if result['total'] else 'no_candidates',
                                'candidate_count':result['total'],'metadata':result.get('vector_metadata',{})}
    context['candidate_versions']={c['source_id']:c['source_version'] for c in result['candidate_jobs']}
    state['search_context']=context
    state['conversation_target']='jobs'
    state['vector_navigation']['original_plan']=plan.to_dict()
    result.update(retrieval_mode='section_vector_fallback',exact_match_total=0,
                  search_id=context['search_id'],vector_fallback=context['vector_fallback'])
    result['message']=('AND 조건에 모두 일치하는 공고는 0건입니다. OR로 바꾸지 않고 같은 검색 내용의 의미를 비교해 '
                       f'유사 후보 {result["total"]}건을 찾았습니다. 지역·명시적 필수 기술과 기존 신입 확인 정책은 유지했습니다. '
                       '유사 후보는 모든 문구 일치나 지원 자격 충족을 뜻하지 않습니다. 공고별 조건을 확인해 주세요.' if result['total'] else
                       'AND 조건 일치 공고는 0건이며, 벡터 유사 검색에서도 유지한 필터를 통과한 후보를 찾지 못했습니다. OR로 완화하지 않았습니다. 변경할 조건을 알려주세요.')
    return state,result,evidence

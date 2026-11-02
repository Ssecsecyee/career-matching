"""Server-authored, factual search explanations; no extra model call."""
from datetime import datetime, timezone
from uuid import uuid4
from src.services.search_terms import POLICY_VERSION




def execution_summary(plan, total, backend, degraded):
    if plan.schema_version == 1:
        return {'filters': [], 'ranking': [], 'limitations': ['이전 검색 형식의 조건입니다.']}
    filters, ranking, limits = [], [], []
    if plan.regions:
        filters.append('근무지역: ' + ' 또는 '.join(plan.regions))
    if plan.roles:
        filters.append('희망직무 관련 내용: ' + ' 또는 '.join(plan.roles))
    if plan.required_skills:
        filters.append('공고에 모두 필요한 기술: ' + ', '.join(plan.required_skills))
    if plan.owned_skills:
        ranking.append('보유 기술의 태그 일치: ' + ', '.join(plan.owned_skills))
        if not plan.roles and not plan.required_skills:
            filters.append('보유 기술 중 하나 이상 태그 일치')
    if plan.preferred_skills:
        ranking.append('선호 기술의 태그 일치: ' + ', '.join(plan.preferred_skills))
    if plan.career.levels or plan.career.max_years is not None:
        labels = {'entry': '신입', 'junior': '주니어', 'experienced': '경력'}
        desired = ', '.join(labels[v] for v in plan.career.levels)
        if plan.career.max_years is not None:
            desired += (' / ' if desired else '') + str(plan.career.max_years) + '년 이하'
        limits.append('희망 경력: ' + desired + '. 현재 경력 자동 필터는 적용하지 않았으며 공고별 요건을 확인해야 합니다.')
    limits.append('전공·기술 경험은 지원 자격 충족을 뜻하지 않습니다. 저장된 자료의 현재 모집 여부는 원문 확인이 필요합니다.')
    if degraded:
        limits.append('검색엔진 연결 장애로 MySQL에서 조회했습니다. 조건 의미는 유지하지만 검색 분석·순위는 다를 수 있습니다.')
    return {'filters': filters, 'ranking': ranking, 'limitations': limits,
            'verified_total': total, 'backend': backend, 'policy_version': POLICY_VERSION}


def remember_search(state, plan, raw_plan, payload, total, jobs):
    data = {'search_id': str(uuid4()), 'policy_version': POLICY_VERSION,
            'request_id': payload.get('request_id'), 'user_message': payload.get('message', '')[:4000],
            'observed_at': datetime.now(timezone.utc).isoformat(),
            'raw_plan': raw_plan, 'executed_plan': plan.to_dict(),
            'total': total, 'candidate_versions': {j['source_id']: j['source_version'] for j in jobs},
            'summary': execution_summary(plan, total, state['search_backend'], state['search_degraded'])}
    state['search_context'] = data
    return data


def review_response(state):
    data = state['search_context']
    return {'stage': state['stage'], 'search_id': data['search_id'], 'total': data['total'],
            'search_summary': data['summary'], 'candidate_jobs': [],
            'message': ('검색 기준을 확인해 주세요. 이 기준으로 공고를 보여드릴까요?' if data['total'] else
                        '이 검색 기준에 맞는 저장 공고를 찾지 못했습니다. 적용한 조건을 확인하고 변경할 항목을 말씀해 주세요.'),
            'search_backend': state.get('search_backend'), 'search_degraded': state.get('search_degraded', False)}

# Compatibility imports; free-text v2 routing does not use these classifiers.
from src.services.legacy_intent import is_confirmation, needs_review

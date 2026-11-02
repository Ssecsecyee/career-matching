const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const validation = new Set(['pending', 'validated', 'invalid']);
const execution = new Set(['pending', 'succeeded', 'failed']);
export function intentRowsRequest(filters = {}, offset = 0) {
  if (!Number.isInteger(offset) || offset < 0 || offset > 1000000) throw new Error('페이지 범위를 확인해 주세요.');
  const result = {operation: 'intent_rows', offset};
  for (const key of ['session_id', 'filter_request_id']) {
    const value = (filters[key] || '').trim();
    if (value && !uuid.test(value)) throw new Error('세션·요청 ID는 UUID 형식으로 입력해 주세요.');
    if (value) result[key] = value.toLowerCase();
  }
  for (const [key, values] of [['validation_status', validation], ['execution_status', execution]]) {
    if (filters[key]) {
      if (!values.has(filters[key])) throw new Error('조회 상태를 확인해 주세요.');
      result[key] = filters[key];
    }
  }
  return result;
}
export function intentDetailRequest(id, includeRaw = false) {
  if (!uuid.test(id) || typeof includeRaw !== 'boolean') throw new Error('조회할 기록을 다시 선택해 주세요.');
  return {operation: 'intent_detail', decision_id: id.toLowerCase(), include_raw: includeRaw};
}
export function intentLabel(kind, value) {
  const labels = {
    target: {jobs:'채용',training:'교육',selected:'선택 공고',general:'일반 대화',unspecified:'미정'},
    action: {search:'새 검색',refine_search:'조건 변경',next_results:'다음 목록',consult:'상담',assessment_control:'문답 제어',clarify:'대상 확인',confirm_search:'검색 확인',summary:'답변 요약',chat:'일반 대화',select:'공고 선택',answer:'조건 답변',answer_batch:'조건 묶음 답변',remember:'경험 수정'},
    validation: {pending:'대기',validated:'검증 통과',invalid:'형식 오류'},
    execution: {pending:'대기',succeeded:'완료',failed:'실패'},
    source: {model:'모델 판단',direct:'버튼·폼'},
  };
  return labels[kind]?.[value] || value || '—';
}
export function intentTokens(value) {
  if (value == null) return '미기록';
  const number = Number(value);
  return Number.isFinite(number) ? number.toLocaleString() : '미기록';
}

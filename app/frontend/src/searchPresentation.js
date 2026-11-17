// Presentation only: execution plans and administrative diagnostics stay unchanged.
export function publicSearchFilter(value) {
  if (typeof value !== 'string') return '';
  return value.replace(/주제·기관 검색어\s*\(모두 포함 · AND\)\s*:/g, '검색어:')
    .replace(/\s+AND\s+/g, ' · ');
}
export function publicSearchFilters(summary) {
  return (summary?.filters || []).map(publicSearchFilter).filter(Boolean);
}
export function publicSearchNotices(summary) {
  return (summary?.limitations || []).filter(t => typeof t === 'string'
    && !/보정|검색엔진|MySQL|Elasticsearch|\bAND\b|\bOR\b|정책 버전|벡터/.test(t));
}

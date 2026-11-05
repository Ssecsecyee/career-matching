import React from 'react';
import { safeSourceUrl } from './api.js';
import { TrainingStatus } from './TrainingStatus.jsx';

export function TrainingCohorts({ course }) {
  const cohorts=course.cohorts || [];
  return <details><summary>조회된 회차·일정 {cohorts.length}개{course.cohorts_truncated ? ' 이상' : ''} 보기</summary>
    <p className="fine">이번 검색에서 확인한 일정입니다. 기관의 전체 개설 일정은 아닙니다. 비용과 신청 조건은 회차별로 확인해 주세요.</p>
    {cohorts.map(c=><section key={`${c.source}:${c.source_id}`} className="check">
      <h4>{c.cohort_name ? `${c.cohort_name}회차` : '회차 미확인'}</h4>
      <TrainingStatus course={c}/>
      <p>교육 일정: {c.dates?.starts_at?.raw || c.starts_at || '미확인'} ~ {c.dates?.ends_at?.raw || c.ends_at || '미확인'}</p>
      <p className="fine">페이지 표시 자부담: {c.tuition == null ? '미확인' : `${Number(c.tuition).toLocaleString()} ${c.currency || ''}`} · 최종 비용과 수강 자격은 기관 확인 필요</p>
      <a className="source-link" href={safeSourceUrl(c.source_url)} target="_blank" rel="noreferrer">이 회차 원문 확인 ↗</a>
    </section>)}
  </details>;
}

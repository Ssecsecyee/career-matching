import React from 'react';
import {publicSearchFilters,publicSearchNotices} from './searchPresentation.js';

export function SearchReview({ data, active, busy, onConfirm, onModify }) {
  const summary = data.search_summary;
  if (!summary) return null;
  const filters = publicSearchFilters(summary);
  const notices = publicSearchNotices(summary);
  const training = data.search_target === 'training';
  const related = data.retrieval_mode?.startsWith('section_vector');
  const pending = ['search_review', 'training_search_review'].includes(data.stage);
  return <section className="source search-review" aria-label="검색 기준 확인">
    <h3>{training ? '교육 검색 기준과 결과' : '검색 기준과 결과'}</h3>
    {training && (typeof summary.candidate_total === 'number' ? <p>검색한 교육 후보: <strong>{summary.candidate_total}회차</strong></p> : <p>우선 확인한 후보: <strong>{summary.preview_count}건</strong> · 전체 건수 미집계</p>)}
    {!training && related && typeof data.total === 'number' && <p>관련 공고 후보: <strong>{data.total}건</strong></p>}
    {!training && !related && typeof summary.verified_total === 'number' && <p>검색 시점의 노출 가능한 후보: <strong>{summary.verified_total}건</strong></p>}
    <h4>적용한 조건</h4>
    {filters.length ? <ul>{filters.map(t => <li key={t}>{t}</li>)}</ul> : <p>{training ? '별도로 제한한 교육 조건이 없습니다.' : '별도로 제한한 지역·직무·필수 기술이 없습니다.'}</p>}
    {notices.length > 0 && <details className="fine"><summary>자료 확인 안내</summary><ul>{notices.map(t => <li key={t}>{t}</li>)}</ul></details>}
    {active && pending && <div className="choices">
      <button disabled={busy} onClick={() => onConfirm(data.search_id, training ? 'training' : 'jobs')}>{training ? '이 기준으로 교육 보기' : '이 기준으로 공고 보기'}</button>
      <button className="quiet" disabled={busy} onClick={onModify}>조건 수정</button>
    </div>}
    {active && ['no_results', 'training_no_results'].includes(data.stage) && (!data.search_changed || training) && <button className="quiet" disabled={busy} onClick={onModify}>조건 수정</button>}
  </section>;
}

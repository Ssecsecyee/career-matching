import React from 'react';
import {safeSourceUrl} from './api.js';
export function ConditionReferences({data}) {
  const rows=data.reference_conditions||[];
  if (!rows.length) return null;
  return <details className="source"><summary>질문 대신 참고할 공고 내용 {rows.length}개</summary>
    <p className="fine">AI가 질문 필요성을 분류한 결과입니다. 생략한 질문을 충족한 것으로 계산하지 않습니다. 원문과 이유를 확인해 주세요.</p>
    {rows.map(row=><article className="check" key={row.condition_id}><strong>{row.type==='required'?'자격요건':'우대조건'} · 참고사항</strong><pre>{row.quote}</pre><p>{row.reason}</p></article>)}
    {data.condition_source_url&&<a href={safeSourceUrl(data.condition_source_url)} target="_blank" rel="noreferrer">공고 원문 ↗</a>}
  </details>;
}

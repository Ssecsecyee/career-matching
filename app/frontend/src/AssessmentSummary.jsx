import React from 'react';
import {safeSourceUrl} from './api.js';

const states={met:'충족한다고 답한 내용',unmet:'미충족이라고 답한 내용',unknown:'아직 확인하지 못한 내용'};
const kindLabel={required:'필수',preferred:'우대'};
export function AssessmentSummary({summary,checks=[],active,busy,onContinue,paused=false}) {
 const originals=new Map(checks.map(c=>[c.condition_id,c]));
 return <section className="assessment-summary" aria-label="사용자 답변 정리">
  <div className="summary-heading"><span className="pill">{summary.partial?'부분 답변 정리':'답변 정리'}</span><span>사용자 자기 평가 기준</span></div>
  <h3>{summary.source.company_name} · {summary.source.title}</h3>
  <p className="summary-headline">{summary.headline}</p>
  {paused&&<p className="summary-warning">역량 확인 질문 중단을 유지합니다. 답변한 항목만 정리했습니다.</p>}
  <div className="summary-counts"><table><caption className="sr-only">필수 자격요건과 우대조건의 사용자 답변 집계</caption><thead><tr><th scope="col">조건</th><th scope="col">충족</th><th scope="col">미충족</th><th scope="col">미확인</th><th scope="col">미답변</th></tr></thead><tbody>{Object.entries(summary.groups).map(([kind,group])=><tr key={kind}><th scope="row">{group.label}<small>{group.counts.total}개 조건</small></th>{['met','unmet','unknown','unanswered'].map(status=><td key={status}>{group.counts[status]}</td>)}</tr>)}</tbody></table></div>
  {!summary.groups.preferred.counts.total&&<p className="summary-note">우대조건 자료가 없습니다. 우대조건을 모두 충족한 것으로 계산하지 않습니다.</p>}
  <div className="summary-highlights">{Object.entries(states).map(([status,label])=>{
   const items=summary.items.filter(item=>item.assessment===status);
   return <div key={status} className={`summary-highlight summary-highlight-${status}`}><strong>{label}</strong><p>{items.length?items.slice(0,2).map(item=>`[${kindLabel[item.type]}] ${item.summary}`).join(' · '):'해당 답변 없음'}{items.length>2&&` 외 ${items.length-2}개`}</p></div>;
  })}</div>
  {summary.conflicts.length>0&&<div className="summary-warning"><strong>진술과 선택을 함께 확인할 내용</strong>{summary.conflicts.map((c,i)=><p key={i}>{summary.items.find(item=>item.condition_id===c.condition_id)?.summary} — 충족을 선택했지만 “{c.basis.quote}”라는 설명도 있습니다. 어느 쪽도 검증된 사실로 확정하지 않았습니다.</p>)}</div>}
  <details className="summary-evidence"><summary>전체 답변·보충 설명·원문 근거 보기 ({summary.answered}개)</summary><ol>{summary.items.map(item=>{
   const check=originals.get(item.condition_id);
   return <li key={item.condition_id}><span className="summary-evidence-label">{kindLabel[item.type]} · {states[item.assessment]}</span><p>{item.summary}</p>{(item.source_notice||check?.source_notice)&&<p className="summary-note">{item.source_notice||check.source_notice}</p>}{(check?.detail||item.detail)&&<p className="summary-user-detail">남긴 설명: {check?.detail||item.detail}</p>}<details><summary>이 조건의 원문</summary>{check?.quote?<pre>{check.quote}</pre>:<p>이 응답에서 원문 근거를 확인할 수 없습니다.</p>}</details></li>;
  })}</ol></details>
  <div className="summary-source"><a href={safeSourceUrl(summary.source.source_url)} target="_blank" rel="noreferrer">공고 원문 ↗</a><span>확인한 공고 버전 {summary.source.source_version} · 당시 조건 기준</span></div>
  <p className="summary-note">선택과 보충 설명을 정리한 결과입니다. 실무 역량 검증·합격 판정·현재 모집 여부 확인이 아닙니다. 미확인과 미답변을 미충족으로 처리하지 않습니다.</p>
  {active&&<div className="summary-next-actions"><h4>다음에는 무엇을 준비할까요?</h4><div>{summary.next_actions.map(action=><button type="button" key={action.id} disabled={busy} onClick={()=>onContinue(action.message)}>{action.label} →</button>)}</div><p>아래 입력창에서 자유롭게 이어서 물어봐도 됩니다.</p></div>}
 </section>;
}

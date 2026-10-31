import React from 'react';
import {summarizeUsage,usagePricing} from './adminUsage.js';
const n = value => value == null ? '—' : Number(value).toLocaleString('ko-KR', {maximumFractionDigits:0});
const usd = (value, digits=4) => value == null ? '산정 보류' : `$${Number(value).toFixed(digits)}`;
const labels = {succeeded:'성공',failed:'실패',pending:'처리 중',timed_out:'시간 초과'};

export function UsageOverview({summary,busy,onRefresh}) {
 const stats=summarizeUsage(summary.model_usage);
 return <section className="admin-section" aria-labelledby="usage-heading">
  <div className="admin-section-heading"><div><span className="admin-eyebrow">MODEL USAGE</span><h2 id="usage-heading">모델 사용량</h2></div><button disabled={busy} onClick={onRefresh}>사용량 새로고침</button></div>
  <p className="admin-description">현재 DB에 남아 있는 모델 호출 기록입니다. 입력에는 프롬프트·대화 문맥이 포함되며, 사용자 질문 한 번과 모델 호출 한 번은 다를 수 있습니다.</p>
  <div className="admin-usage-cards">
   <div><span>기록된 모델 호출</span><strong>{n(stats.calls)}<small>회</small></strong><p>성공 {n(stats.succeeded)} · 실패/시간 초과 {n(stats.failed)}</p></div>
   <div><span>기록된 입출력 토큰</span><strong>{n(stats.total)}</strong><p>입력 {n(stats.input)} · 출력 {n(stats.output)}</p></div>
   <div><span>모델 호출당 평균 토큰</span><strong>{n(stats.averageTokens)}</strong><p>기록된 입출력 합계 ÷ 전체 호출 수</p></div>
   <div><span>호출당 추정 모델 비용</span><strong>{usd(stats.averageCost)}<small>USD</small></strong><p>기록 합계 추정 {usd(stats.estimatedCost)}</p></div>
  </div>
  <div className="admin-scroll admin-usage-table"><table><caption className="sr-only">모델·성공 상태별 호출과 토큰 평균 비교</caption><thead><tr>{['모델','결과','호출 수','입력 토큰','출력 토큰','호출당 입력','호출당 출력','호출당 합계','호출당 추정 USD'].map(x=><th key={x} scope="col">{x}</th>)}</tr></thead><tbody>{stats.rows.map((v,i)=><tr key={i}><td><span className="admin-model-name">{v.model_id===usagePricing.model?'Claude Sonnet 4.6':v.model_id}</span><small className="admin-cell-note">{v.model_id.startsWith('global.')?'Global inference':v.model_id}</small></td><td><span className={`admin-state admin-state-${v.status}`}>{labels[v.status]||v.status}</span></td>{[v.calls,v.input,v.output,v.averageInput,v.averageOutput,v.averageTokens].map((x,k)=><td className="admin-number" key={k}>{n(x)}</td>)}<td className="admin-number">{usd(v.averageCost,6)}</td></tr>)}</tbody><tfoot><tr><th scope="row" colSpan={2}>전체 기록 합계 / 가중 평균</th>{[stats.calls,stats.input,stats.output,stats.calls?stats.input/stats.calls:null,stats.calls?stats.output/stats.calls:null,stats.averageTokens].map((x,k)=><td className="admin-number" key={k}>{n(x)}</td>)}<td className="admin-number">{usd(stats.averageCost,6)}</td></tr></tfoot></table>{!stats.rows.length&&<p className="admin-empty">아직 모델 호출 기록이 없습니다.</p>}</div>
  <details className="admin-usage-notes"><summary>평균·비용 계산 기준과 캐시 기록</summary><p>실패 호출도 기록된 토큰이 있으면 합산합니다. 사용량이 미기록된 호출의 추가 소비량은 확인되지 않으므로 실제 사용량·청구액과 차이가 날 수 있습니다. 데이터 보존·삭제 후에는 집계 범위도 달라집니다.</p><p>캐시 읽기 {n(stats.cacheRead)}토큰 · 캐시 쓰기 {n(stats.cacheWrite)}토큰. 입출력 평균은 별도 캐시 토큰을 합산하지 않습니다.</p><p>추정 단가: Sonnet 4.6 Global, 입력 100만 토큰당 ${usagePricing.inputPerMillion}, 출력 ${usagePricing.outputPerMillion}. 확인일 {usagePricing.checkedAt}. 다른 모델·캐시 사용은 단가 확정 전 산정을 보류합니다. 세금·환율·크레딧·할인·서버 비용을 포함하지 않습니다. <a href={usagePricing.source} target="_blank" rel="noreferrer">공식 요금표 ↗</a></p></details>
  <div className="admin-sync-summary"><strong>검색 동기화</strong><span>대기 {n(summary.sync.pending)}건</span><span>대기 작업 최대 시도 {n(summary.sync.max_attempts)}회</span><span>가장 오래된 대기 {summary.sync.oldest||'없음'}</span></div>
 </section>;
}

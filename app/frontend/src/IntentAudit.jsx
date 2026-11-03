import React, {useRef,useState} from 'react';
import {intentRowsRequest,intentDetailRequest,intentLabel,intentTokens} from './intentAudit.js';

export function IntentAuditList({data,busy,onDetail,onPage}) {
 return <><p>{data.total}건 · {data.rows.length ? `${data.offset+1}~${data.offset+data.rows.length}번째` : '표시할 기록 없음'} · 만료되지 않은 기록</p>
 <div className="admin-scroll"><table><thead><tr><th>생성 시각 (UTC)</th><th>대상 · 판단 행동</th><th>실제 실행</th><th>검증 · 실행 상태</th><th>모델 · 토큰</th><th>상세</th></tr></thead><tbody>
 {data.rows.map(row=><tr key={row.decision_id}><td>{row.created_at}<small className="admin-cell-note">{row.policy_version} · {intentLabel('source',row.decision_source)}</small></td><td>{intentLabel('target',row.target)} · {intentLabel('action',row.decision_action || row.executed_action)}<small className="admin-cell-note">{row.decision_reason || '명시적 버튼·폼 요청'}</small></td><td>{intentLabel('action',row.executed_action)}{row.error_code&&<small className="admin-cell-note">{row.error_code}</small>}</td><td>{intentLabel('validation',row.validation_status)}<br/><span className={`admin-state admin-state-${row.execution_status}`}>{intentLabel('execution',row.execution_status)}</span></td><td>{row.model_id || '연결된 분류 호출 없음'}<small className="admin-cell-note">호출 {intentLabel('execution',row.model_status)} · 입력 {intentTokens(row.input_tokens)} / 출력 {intentTokens(row.output_tokens)} · {row.latency_ms == null ? '지연 미기록' : `${row.latency_ms}ms`}</small></td><td><button disabled={busy} onClick={()=>onDetail(row.decision_id)}>상세 보기</button></td></tr>)}
 </tbody></table></div><div className="admin-paging"><button disabled={busy||data.offset===0} onClick={()=>onPage(Math.max(0,data.offset-25))}>이전</button><button disabled={busy||data.offset+25>=data.total} onClick={()=>onPage(data.offset+25)}>다음</button></div></>;
}

export function SearchDebug({record}) {
 if(!record)return <section className="admin-search-debug"><h4>검색 실행 비교</h4><p>이 요청에 연결된 검색 실행 기록이 없습니다. 과거 기록·확인 질문·검색 외 요청은 미기록일 수 있습니다.</p></section>;
 if(record.truncated)return <section><h4>검색 실행 비교</h4><p>기록이 표시 한도를 넘었습니다. 일부 미리보기이며 전체 조건으로 해석하지 마세요.</p><pre>{record.preview}</pre></section>;
 const guard=record.constraint_guard;
 const fields=[['직무','roles'],['지역','regions'],['보유 기술','owned_skills'],['필수 기술','required_skills'],['선호 기술','preferred_skills']];
 const terms=(plan,key)=>Array.isArray(plan?.[key])?(plan[key].join(', ')||'없음'):'미기록';
 return <section className="admin-search-debug" aria-label="검색 조건 디버깅"><h4>검색 실행 비교</h4>
 <p>검색 ID: {record.search_id || '미기록'} · 후보: {record.total ?? '미기록'}건 · 엔진: {record.summary?.backend || '미기록'}</p>
 <p>추천 기준: {guard?.basis==='assessment'?'문답 기반 자기보고 경험':guard?.basis==='user_request'?'사용자 직접 검색':'미기록'} · 관측 시각: {record.observed_at || '미기록'}</p>
 <div className="admin-scroll"><table><thead><tr><th>구분</th><th>AI 제안</th><th>실제 실행</th></tr></thead><tbody>{fields.map(([label,key])=><tr key={key}><th>{label}</th><td>{terms(record.raw_plan,key)}</td><td>{terms(record.executed_plan,key)}</td></tr>)}</tbody></table></div>
 <h5>필수 필터 검증</h5><p>{guard ? guard.unsupported_required_skills?.length ? `필수에서 선호로 전환: ${guard.unsupported_required_skills.join(', ')}` : '필수에서 선호로 전환한 조건 없음' : '검증 정보 미기록 (과거 검색일 수 있음)'}</p>
 <ul>{record.summary?.limitations?.map((text,i)=><li key={i}>{text}</li>)}</ul>
 <details><summary>필수 검색 조건의 사용자 인용 근거</summary><pre>{JSON.stringify(guard?.evidence ?? [],null,2)}</pre></details>
 <h5>추천에 참고한 문답</h5><p>원본 공고 {record.assessment_basis?.source_id || '미기록'} · 버전 {record.assessment_basis?.source_version ?? '미기록'} · 자기보고이며 검증된 역량이 아닙니다.</p>
 {(record.assessment_basis?.items?.length>0)?<ul>{record.assessment_basis.items.map((item,i)=><li key={i}><b>{item.type==='required'?'필수':'우대'} · {({met:'충족 답변',unmet:'미충족 답변',unknown:'미확인'})[item.assessment] || '미기록'}</b><p>{item.quote}</p></li>)}</ul>:<p>문답 근거 없음 또는 미기록</p>}
 {record.assessment_basis?.omitted_count>0&&<p>길이 제한으로 {record.assessment_basis.omitted_count}개 항목 생략</p>}
 <details><summary>저장된 검색 기록 JSON</summary><pre>{JSON.stringify(record,null,2)}</pre></details></section>;
}

export function IntentAuditDetail({data,busy,onRaw,onClose}) {
 const row=data.record;
 return <section className="admin-intent-detail" aria-label="선택한 의도 기록 상세"><div className="admin-section-heading"><h3>선택한 판단 기록</h3><button disabled={busy} onClick={onClose}>상세 닫기</button></div>
 <dl><dt>판단 ID</dt><dd>{row.decision_id}</dd><dt>세션 ID</dt><dd>{row.session_id}</dd><dt>요청 ID</dt><dd>{row.request_id}</dd><dt>분류 호출 ID</dt><dd>{row.model_invocation_id || '없음 (직접 행동 또는 호출 시작 전 실패)'}</dd><dt>오류 코드</dt><dd>{row.error_code || '없음'}</dd><dt>검증 · 실행</dt><dd>{intentLabel('validation',row.validation_status)} · {intentLabel('execution',row.execution_status)}</dd><dt>정책 · 시도</dt><dd>{row.policy_version} · {row.attempt_no}회차</dd><dt>모델 호출</dt><dd>{row.model_id || '연결된 호출 없음'} · {row.model_purpose || '—'} · {intentLabel('execution',row.model_status)}</dd><dt>사용 토큰</dt><dd>입력 {intentTokens(row.input_tokens)} / 출력 {intentTokens(row.output_tokens)}</dd></dl>
 <SearchDebug record={row.search_record}/>
 <div className="admin-intent-panels">{[['당시 문맥','context_snapshot'],['검증된 판단','validated_decision'],['실행 결과','result_summary']].map(([label,key])=><section key={key}><h4>{label}</h4><pre>{JSON.stringify(row[key],null,2)}</pre></section>)}</div>
 {data.truncated_fields?.length>0&&<p className="admin-intent-note">일부 내용은 표시 한도로 잘렸습니다: {data.truncated_fields.join(', ')}. 전체 원본으로 해석하지 마세요.</p>}
 <p className="admin-intent-note">분류 출력에는 대화 일부가 포함될 수 있습니다. 필요한 기록만 확인하세요. 기본 마스킹은 모든 개인정보 제거를 보장하지 않습니다.</p>
 {!data.raw_included?<button disabled={busy} onClick={()=>onRaw(row.decision_id)}>마스킹된 분류 출력 보기</button>:<section><h4>마스킹된 분류 출력</h4><pre>{typeof row.raw_output === 'string' ? row.raw_output : JSON.stringify(row.raw_output,null,2)}</pre></section>}
 </section>;
}

export function IntentAudit({request,busy}) {
 const empty={session_id:'',filter_request_id:'',validation_status:'',execution_status:''};
 const [filters,setFilters]=useState(empty),[applied,setApplied]=useState(empty),[data,setData]=useState(null),[detail,setDetail]=useState(null),[error,setError]=useState('');
 const sequence=useRef(0);
 async function load(values=filters,offset=0) {
  setError('');setDetail(null);const ticket=++sequence.current;
  try {const payload=intentRowsRequest(values,offset);const result=await request(payload);if(result&&ticket===sequence.current){setData(result);setApplied({...values});}}
  catch(e){setError(e.message);}
 }
 async function inspect(id,raw=false) {
  setError('');const ticket=++sequence.current;
  if(!raw)setDetail(null);
  try {const result=await request(intentDetailRequest(id,raw));if(result&&ticket===sequence.current)setDetail(result);}
  catch(e){setError(e.message);}
 }
 return <section className="admin-section"><div className="admin-section-heading"><div><span className="admin-eyebrow">CONTEXT · INTENT AUDIT</span><h2>문맥·의도 기록</h2></div></div>
 <p>요청 당시의 문맥, 모델 판단, 실제 실행을 연결해 확인합니다. 목록에는 대화 문맥과 분류 원문을 불러오지 않습니다.</p>
 <form className="admin-intent-filters" onSubmit={e=>{e.preventDefault();load();}}>
 <label>세션 ID<input disabled={busy} value={filters.session_id} onChange={e=>setFilters({...filters,session_id:e.target.value})} placeholder="session_id (선택)"/></label>
 <label>요청 ID<input disabled={busy} value={filters.filter_request_id} onChange={e=>setFilters({...filters,filter_request_id:e.target.value})} placeholder="request_id (선택)"/></label>
 <label>검증 상태<select disabled={busy} value={filters.validation_status} onChange={e=>setFilters({...filters,validation_status:e.target.value})}><option value="">전체</option><option value="validated">검증 통과</option><option value="invalid">형식 오류</option><option value="pending">대기</option></select></label>
 <label>실행 상태<select disabled={busy} value={filters.execution_status} onChange={e=>setFilters({...filters,execution_status:e.target.value})}><option value="">전체</option><option value="succeeded">완료</option><option value="failed">실패</option><option value="pending">대기</option></select></label>
 <button disabled={busy} type="submit">조회 / 새로고침</button><button disabled={busy} type="button" onClick={()=>{setFilters(empty);load(empty);}}>필터 초기화 후 조회</button>
 </form>
 {error&&<p role="alert" className="error">{error}</p>}
 {data&&<><p className="admin-intent-note">표시 중인 조건: 세션 {applied.session_id || '전체'} · 요청 {applied.filter_request_id || '전체'} · 검증 {intentLabel('validation',applied.validation_status) === '—' ? '전체' : intentLabel('validation',applied.validation_status)} · 실행 {intentLabel('execution',applied.execution_status) === '—' ? '전체' : intentLabel('execution',applied.execution_status)}</p><IntentAuditList data={data} busy={busy} onDetail={inspect} onPage={offset=>load(applied,offset)}/></>}
 {detail&&<IntentAuditDetail data={detail} busy={busy} onRaw={id=>inspect(id,true)} onClose={()=>{sequence.current++;setDetail(null);}}/>}
 </section>;
}

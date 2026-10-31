import React, {useRef,useState} from 'react';
import {clientToken,postChat,requestPayload} from './api.js';

export function Admin() {
 const [token,setToken]=useState('');const owner=useRef(clientToken());
 const [summary,setSummary]=useState(null),[data,setData]=useState(null),[table,setTable]=useState('job_postings');
 const [busy,setBusy]=useState(false),[error,setError]=useState(''),[notice,setNotice]=useState('');
 const [session,setSession]=useState(''),[selected,setSelected]=useState(null),[reason,setReason]=useState('');
 async function request(values){
  setBusy(true);setError('');
  try {
   const result=await postChat({payload:requestPayload('admin',values),accessCode:token,ownerToken:owner.current});
   if(!result.ok)throw new Error(({unauthorized:'관리자 토큰을 확인해 주세요.',admin_required:'일반 접속 코드는 관리자 기능을 사용할 수 없습니다.',admin_source_changed_refresh:'다른 작업에서 변경한 공고입니다. 새로고침 후 다시 선택하세요.',admin_restore_not_available:'관리자 화면에서 숨긴 공고만 복구할 수 있습니다.'})[result.body.status]||`처리 실패: ${result.body.status}`);
   return result.body;
  }catch(e){setError(e.message);return null;}finally{setBusy(false);}
 }
 async function loadSummary(){const v=await request({operation:'summary'});if(v)setSummary(v);}
 async function rows(name=table,offset=0){setSelected(null);const v=await request({operation:'rows',table:name,offset,...(session&&['chat_sessions','chat_messages','model_invocations'].includes(name)?{session_id:session}:{})});if(v){setData(v);setTable(name);}}
 async function change(event){
  event.preventDefault();if(!selected)return;
  const v=await request({operation:selected.recruitment_status==='unavailable'?'restore_job':'hide_job',job_id:selected.job_id,source_version:selected.source_version,reason});
  if(v){setNotice('변경을 저장했습니다. 검색 색인은 약 1분 후 반영됩니다. 마감된 공고는 복구해도 노출되지 않습니다.');setSelected(null);setReason('');await rows(table,data.offset);await loadSummary();}
 }
 return <main className="admin-shell"><header><div><h1>운영 관리</h1><p>MySQL 데이터 · 대화 기록 · 모델 사용량 · 검색 동기화</p></div><nav><a href="/#admin-chat">관리자 채팅 ↗</a> · <a href="/">사용자 화면</a>{summary&&<button onClick={()=>{setToken('');setSummary(null);setData(null);setSelected(null);owner.current=clientToken();}}>로그아웃</button>}</nav></header>
 {!summary?<form className="admin-login" onSubmit={e=>{e.preventDefault();loadSummary();}}><h2>관리자 로그인</h2><label>관리자 전용 토큰<input type="password" autoComplete="off" required minLength={32} value={token} onChange={e=>setToken(e.target.value)}/></label><button disabled={busy}>관리 화면 열기</button><p>토큰은 현재 화면의 메모리에서만 사용합니다.</p></form>:<>
 <div className="admin-cards">{[['채용공고',summary.counts.job_postings],['교육',summary.counts.training_offerings],['검색 노출 대상',summary.visible_jobs],['대화 세션',summary.counts.chat_sessions],['모델 호출',summary.counts.model_invocations],['동기화 대기',summary.sync.pending]].map(([k,v])=><section key={k}><span>{k}</span><strong>{Number(v).toLocaleString()}</strong></section>)}</div>
 <section><h2>모델 사용량 <button disabled={busy} onClick={loadSummary}>새로고침</button></h2><p>{summary.billing_note} 관리자도 호출·토큰 사용량이 기록됩니다.</p><div className="admin-scroll"><table><thead><tr>{['모델','상태','호출','입력 토큰','출력 토큰','캐시 읽기','캐시 쓰기'].map(x=><th key={x}>{x}</th>)}</tr></thead><tbody>{summary.model_usage.map((v,i)=><tr key={i}>{['model_id','status','calls','input_tokens','output_tokens','cache_read_input_tokens','cache_write_input_tokens'].map(k=><td key={k}>{v[k]}</td>)}</tr>)}</tbody></table></div><p>동기화 최대 시도: {summary.sync.max_attempts} · 가장 오래된 대기: {summary.sync.oldest||'없음'}</p></section>
 <section><h2>테이블 탐색</h2><div className="admin-tabs">{summary.tables.map(t=><button key={t.name} disabled={busy} aria-pressed={table===t.name&&!!data} onClick={()=>rows(t.name)}>{t.description}<small>{t.name} · {summary.counts[t.name]}</small></button>)}</div>
 <label>대화 세션 ID로 필터 (대화·메시지·모델 기록)<input value={session} onChange={e=>setSession(e.target.value)} placeholder="session_id — 비워두면 전체"/></label><button disabled={busy} onClick={()=>rows()}>조회 / 새로고침</button>
 {data&&<><p>{data.total}건 중 {data.offset+1}~{Math.min(data.offset+data.rows.length,data.total)} · 페이지당 25건</p><details><summary>컬럼 정보</summary>{data.columns.map(c=><p key={c.name}><b>{c.name}</b> · {c.type} {c.description}</p>)}</details><div className="admin-scroll"><table><thead><tr><th>상세</th>{(data.columns||[]).slice(0,7).map(c=><th key={c.name}>{c.name}</th>)}</tr></thead><tbody>{data.rows.map((r,i)=><tr key={i}><td><details><summary>전체 필드</summary><pre>{JSON.stringify(r,null,2)}</pre>{table==='job_postings'&&<button disabled={busy} onClick={()=>{setSelected(r);setReason('');}}>{r.recruitment_status==='unavailable'?'숨김 복구 검토':'공고 숨김 검토'}</button>}{r.session_id&&<button onClick={()=>setSession(r.session_id)}>이 대화로 필터</button>}</details></td>{data.columns.slice(0,7).map(c=><td key={c.name}>{String(r[c.name]??'').slice(0,180)}</td>)}</tr>)}</tbody></table></div><div className="admin-paging"><button disabled={busy||data.offset===0} onClick={()=>rows(table,Math.max(0,data.offset-25))}>이전</button><button disabled={busy||data.offset+25>=data.total} onClick={()=>rows(table,data.offset+25)}>다음</button></div></>}
 {selected&&<form className="admin-change" onSubmit={change}><h3>{selected.title} · {selected.recruitment_status==='unavailable'?'숨김 복구':'검색 노출 중단'}</h3><p>원본은 삭제하지 않습니다. 변경 전후 상태와 사유가 감사 기록에 저장됩니다.</p><label>변경 사유<input required minLength={3} maxLength={500} value={reason} onChange={e=>setReason(e.target.value)}/></label><button disabled={busy}>확인한 내용으로 변경 저장</button><button type="button" onClick={()=>setSelected(null)}>취소</button></form>}
 </section>{notice&&<p role="status">{notice}</p>}
 </>}{busy&&<p role="status">불러오고 있습니다…</p>}{error&&<p className="error" role="alert">{error}</p>}</main>;
}

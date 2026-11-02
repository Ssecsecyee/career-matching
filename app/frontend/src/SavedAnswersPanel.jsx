import React,{useEffect,useRef,useState} from 'react';
import {safeSourceUrl} from './api.js';
import {reviseSavedAnswer} from './savedAnswers.js';
const labels={met:'충족한다고 답함',unmet:'미충족이라고 답함',unknown:'모름·미확인',unanswered:'아직 답하지 않음'};

export function SavedAnswerItems({data,busy,onEdit}) {
 return <><p>{data.answered}개 답변 저장 · 현재 공고 조건 {data.total}개</p>{data.items.map((item,index)=><article className="saved-answer-item" key={item.condition_id || index}><strong>{item.type==='required'?'필수':'우대'} · {labels[item.assessment]}</strong><pre>{item.quote}</pre>{item.source_notice&&<p>{item.source_notice}</p>}<p>보충 설명: {item.detail || '없음'}</p>{item.editable&&<button disabled={busy} onClick={()=>onEdit(item)}>이 답변만 수정</button>}</article>)}{!data.items.length&&<p>현재 공고에 저장된 조건이 없습니다. 아래에서 이 대화에 직접 말한 내용은 확인할 수 있습니다.</p>}</>;
}

export function SavedAnswersPanel({data,busy,error,onClose,onRefresh,onRevise,onRemember}) {
 const panel=useRef(null),callbacks=useRef({busy,onClose});callbacks.current={busy,onClose};
 const [editing,setEditing]=useState(null),[assessment,setAssessment]=useState('unknown'),[detail,setDetail]=useState(''),[correction,setCorrection]=useState(''),[notice,setNotice]=useState('');
 useEffect(()=>{setEditing(null);},[data?.review_version,data?.offset]);
 useEffect(()=>{
  const previous=document.activeElement;panel.current?.focus();
  const keys=e=>{
   if(e.key==='Escape'&&!callbacks.current.busy){e.preventDefault();callbacks.current.onClose();}
   if(e.key==='Tab'){
    const items=[...panel.current.querySelectorAll('button:not(:disabled),a[href],textarea:not(:disabled),select:not(:disabled)')];
    if(!items.length){e.preventDefault();return;}
    if(e.shiftKey&&(document.activeElement===items[0]||document.activeElement===panel.current)){e.preventDefault();items.at(-1).focus();}
    else if(!e.shiftKey&&(document.activeElement===items.at(-1)||document.activeElement===panel.current)){e.preventDefault();items[0].focus();}
   }
  };
  document.addEventListener('keydown',keys);return()=>{document.removeEventListener('keydown',keys);if(previous?.isConnected)previous.focus();};
 },[]);
 function edit(item){setEditing(item);setAssessment(item.assessment);setDetail(item.detail);setNotice('');}
 async function save(e){e.preventDefault();try{const next=reviseSavedAnswer(editing,assessment,detail,data);if(await onRevise(next)){setEditing(null);setNotice('선택한 답변을 저장했습니다. 다른 답변은 그대로입니다.');}}catch(e){setNotice(e.message);}}
 return <div className="saved-answers-backdrop"><section className="saved-answers-panel" role="dialog" aria-modal="true" aria-labelledby="saved-answers-title" tabIndex={-1} ref={panel}>
 <header><h2 id="saved-answers-title">내 답변 보기·수정</h2><button disabled={busy} onClick={onClose}>닫기</button></header>
 <p>현재 대화에 말한 내용과 현재 선택 공고의 저장 답변을 확인합니다. 다른 대화나 과거에 선택한 모든 공고의 기록을 모아 보는 화면은 아닙니다.</p>
 {error&&<p className="error" role="alert">{error}</p>}{notice&&<p role="status">{notice}</p>}{busy&&<p role="status">저장 내용을 확인하고 있습니다…</p>}
 {data&&<><h3>{data.source.title ? `${data.source.company_name} · ${data.source.title}` : '현재 선택한 공고 없음'}</h3>{data.source.source_id&&<p>저장된 공고 버전 {data.source.source_version} 기준 · 현재 모집 여부 확인은 아닙니다. <a href={safeSourceUrl(data.source.source_url)} target="_blank" rel="noreferrer">공고 원문</a></p>}
 <SavedAnswerItems data={data} busy={busy||!!editing} onEdit={edit}/>
 {data.unmapped_answer_count>0&&<p>이전 형식의 답변 {data.unmapped_answer_count}개는 현재 조건과 연결되지 않아 여기서 수정할 수 없습니다.</p>}
 <div className="saved-answer-paging"><button disabled={busy||!!editing||data.offset===0} onClick={()=>onRefresh(Math.max(0,data.offset-data.page_size))}>이전 조건</button><span>{data.total ? `${data.offset+1}~${Math.min(data.offset+data.items.length,data.total)} / ${data.total}` : '0개'}</span><button disabled={busy||!!editing||data.offset+data.page_size>=data.total} onClick={()=>onRefresh(data.offset+data.page_size)}>다음 조건</button><button disabled={busy||!!editing} onClick={()=>onRefresh(data.offset)}>다시 조회</button></div>
 {editing&&<form className="saved-answer-edit" onSubmit={save}><h3>선택한 답변 수정</h3><pre>{editing.quote}</pre><label>내 선택<select value={assessment} disabled={busy} onChange={e=>setAssessment(e.target.value)}>{['met','unmet','unknown'].map(value=><option key={value} value={value}>{labels[value]}</option>)}</select></label><label>보충 설명<textarea value={detail} maxLength={2000} disabled={busy} onChange={e=>setDetail(e.target.value)}/></label><p>이 조건 하나만 바뀝니다. 원문과 이전 이력은 보존됩니다.</p><button disabled={busy||(assessment===editing.assessment&&detail===editing.detail)}>이 답변만 저장</button><button type="button" disabled={busy} onClick={()=>setEditing(null)}>수정 취소</button></form>}
 <details className="saved-statements"><summary>이 대화에 직접 말한 내용 ({data.statements.length}개)</summary>{data.statements.map((item,index)=><article key={item.id||index}><small>{item.kind==='correction'?'정정한 내용':item.kind==='answer_detail'?'답변 보충 설명':'직접 말한 내용'}</small><pre>{item.text}</pre></article>)}{!data.statements.length&&<p>아직 저장된 경험 설명이 없습니다.</p>}{data.history_truncated&&<p>최근 표시 범위만 보여줍니다. 과거 원문 기록을 삭제한 것은 아닙니다.</p>}</details>
 <details className="saved-whole-correction"><summary>경험 전체를 문장으로 정정하기</summary><p>이 기능은 기존 기억과 현재 공고의 조건 답변을 초기화하고 다시 확인합니다. 한 조건만 바꾸려면 위의 ‘이 답변만 수정’을 사용하세요.</p><form onSubmit={async e=>{e.preventDefault();if(await onRemember(correction.trim()))setCorrection('');}}><label>정정할 내용<textarea required maxLength={2000} value={correction} disabled={busy} onChange={e=>setCorrection(e.target.value)} placeholder="예: 앞서 말한 내용을 정정할게요. Linux는 아직 사용해본 적이 없어요."/></label><button disabled={busy||!!editing||!correction.trim()}>경험 전체 정정·조건 답변 재확인</button></form></details>
 </>}
 </section></div>;
}

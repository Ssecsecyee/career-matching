import React,{useEffect,useRef,useState} from 'react';
import {safeSourceUrl} from './api.js';
import {assessmentLabels,createAssessmentDraft,chooseAssessment,explainAssessment,moveAssessment,assessmentReady,assessmentPayload} from './assessmentDraft.js';
const preview = text => (text||'').split('\n').map(line=>line.trim().replace(/^[-*•●▪·]\s*/,'')).filter(Boolean).join(' · ').slice(0,180);

export function AssessmentStepper({data,active,busy,onBatch,onAssessment}) {
 const [draft,setDraft]=useState(()=>createAssessmentDraft(data.questions));
 const heading=useRef(null),submitting=useRef(false);
 const item=data.questions[draft.index],selected=draft.answers[item.question_id];
 const answered=draft.ids.filter(id=>Object.hasOwn(draft.answers,id)).length;
 const last=draft.index===draft.ids.length-1;
 const label=data.requirement_type==='required'?'자격요건':'우대조건';
 useEffect(()=>{if(active)heading.current?.focus({preventScroll:true});},[draft.index,active]);
 useEffect(()=>{if(!busy)submitting.current=false;},[busy]);
 function submit(){
  if(!active||busy||submitting.current||!assessmentReady(draft)||!last)return;
  submitting.current=true;onBatch(assessmentPayload(draft));
 }
 function skip(){
  if(!active||busy)return;
  setDraft(old=>{const next=chooseAssessment(old,item.question_id,'unknown');return last?next:moveAssessment(next,1);});
 }
 if(!active)return <details className="assessment-history"><summary>{label} 문답 · {draft.ids.length}개 조건 보기</summary><p className="fine">이전 문답 화면입니다. DB 반영 여부는 이후 저장 결과를 확인하세요.</p><ol>{data.questions.map(q=><li key={q.question_id}><strong>{q.summary||preview(q.quote)}</strong><span>{assessmentLabels[draft.answers[q.question_id]]||'선택 없음'}</span>{draft.details[q.question_id]&&<p>{draft.details[q.question_id]}</p>}<details><summary>원문 보기</summary><pre>{q.quote}</pre></details></li>)}</ol><a href={safeSourceUrl(data.source_url)} target="_blank" rel="noreferrer">공고 원문 ↗</a></details>;
 return <section className="assessment-stepper" aria-label={`${label} 순차 확인`}>
  <div className="assessment-step-header"><span className="pill">{label} 확인</span><span className="assessment-step-count" aria-live="polite">이번 묶음 {draft.index+1} / {draft.ids.length}</span></div>
  <div className="assessment-progress" role="progressbar" aria-label="이번 묶음 답변 선택 진행" aria-valuemin={0} aria-valuemax={draft.ids.length} aria-valuenow={answered}><span style={{width:`${answered/draft.ids.length*100}%`}}/></div>
  <p className="assessment-step-hint">조건을 하나씩 확인한 뒤, 마지막에 답변을 모아 저장합니다.</p>
  <div className="assessment-step-body" key={item.question_id}>
   <span className="assessment-category">{item.category||'직무 조건'}</span>
   <h3 ref={heading} tabIndex={-1}>{item.summary||preview(item.quote)}</h3>
   <details className="source"><summary>정확한 조건 원문 보기</summary><pre>{item.quote}</pre><a href={safeSourceUrl(data.source_url)} target="_blank" rel="noreferrer">공고 원문 ↗</a></details>
   <div className="assessment-options" role="group" aria-label="현재 조건 답변">{Object.entries(assessmentLabels).map(([value,text])=><button type="button" key={value} aria-pressed={selected===value} disabled={busy} onClick={()=>setDraft(old=>chooseAssessment(old,item.question_id,value))}>{selected===value&&<span aria-hidden="true">✓ </span>}{text}</button>)}</div>
   <details className="assessment-detail-disclosure"><summary>보충 설명 (선택)</summary><label className="assessment-detail">경험이나 참고할 내용<input aria-label="현재 조건 보충 설명" placeholder="경험이나 참고할 내용을 적어 주세요" maxLength={300} disabled={busy} value={draft.details[item.question_id]||''} onChange={e=>setDraft(old=>explainAssessment(old,item.question_id,e.target.value))}/></label></details>
  </div>
  <div className="assessment-navigation"><button type="button" disabled={busy||draft.index===0} onClick={()=>setDraft(old=>moveAssessment(old,-1))}>← 이전</button>{last?<button type="button" className="assessment-primary" disabled={busy||!assessmentReady(draft)} onClick={submit}>{busy?'저장 중…':`답변 ${draft.ids.length}개 한 번에 저장 →`}</button>:<button type="button" className="assessment-primary" disabled={busy||!selected} onClick={()=>setDraft(old=>moveAssessment(old,1))}>다음 조건 →</button>}</div>
  <div className="assessment-secondary"><button type="button" disabled={busy} onClick={skip}>{last?'이 조건은 모름으로 선택':'모름으로 넘기기'}</button><button type="button" disabled={busy} onClick={()=>onAssessment('역량 확인 질문은 그만해줘')}>질문 그만하기</button></div>
  <p className="assessment-save-note" role="status">{answered} / {draft.ids.length}개 선택 · 아직 저장되지 않았습니다.</p>
  <details className="assessment-draft-note"><summary>전체 {data.progress?.answered||0} / {data.progress?.total||draft.ids.length}개 확인됨 · 저장 전 안내</summary><p>이전으로 돌아가 수정할 수 있습니다. 새로고침·새 대화·질문 중단 시 미저장 답변은 보존되지 않을 수 있습니다. 합격 여부를 판정하지 않습니다.</p></details>
 </section>;
}

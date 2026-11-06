import React, { useEffect, useRef, useState } from 'react';
import {needsStepRecovery,recoveryMessage} from './requestRecovery.js';
import { clientToken, postChat, requestPayload, safeSourceUrl } from './api.js';
import {latestSearchResults} from './workspaceRoute.js';
import {WorkspaceNavigation} from './WorkspaceNavigation.jsx';
import {ExplorationPreview} from './ExplorationPreview.jsx';
import { TypingText } from './TypingText.jsx';
import { AssessmentStepper } from './AssessmentStepper.jsx';
import { AssessmentSummary } from './AssessmentSummary.jsx';
import { SearchReview } from './SearchReview.jsx';
import { TrainingStatus } from './TrainingStatus.jsx';
import { TrainingCohorts } from './TrainingCohorts.jsx';
import { TrainingExplainButton } from './TrainingExplainButton.jsx';
import { trainingExplainRequest } from './trainingExplain.js';
import { summaryActionRequest } from './consultationRequest.js';
import { controlRequest } from './controlRequest.js';
import { ConditionReferences } from './ConditionReferences.jsx';
import { SavedAnswersPanel } from './SavedAnswersPanel.jsx';
import { savedAnswersRequest } from './savedAnswers.js';

const names = { met: '충족해요', unmet: '미충족이에요', unknown: '아직 모르겠어요' };
const conditionPreview = text => text.split('\n').map(line => line.trim().replace(/^[-*•●▪·]\s*/, '')).filter(Boolean).join(' · ').slice(0, 180);
const isQuestion = data => ['checking_required', 'checking_preferred'].includes(data?.stage);

function Reply({ data, active, busy, onSelect, onAnswer, onBatch, onAssessment, onConfirm, onModify, onContinue, onExplain, compact=false }) {
  return <>
    <ConditionReferences data={data}/>
    {data.message && !data.answer_summary && <TypingText text={data.message} animate={active && !data.cached} streaming={data.stage === 'streaming'} />}
    {data.search_summary && ['search_review', 'no_results', 'training_search_review', 'training_no_results'].includes(data.stage) && <SearchReview data={data} active={active} busy={busy} onConfirm={onConfirm} onModify={onModify} />}
    {!compact && data.stage === 'choose_job' && <>{!data.message && <p>{data.search_continuation ? `앞서 보여드린 공고를 제외한 후보 ${data.remaining_total}건 중 ${data.candidate_jobs.length}건입니다.` : `조건에 맞는 공고가 총 ${data.total}건 있습니다. 먼저 살펴볼 공고를 골라 주세요.`}</p>}<div className="job-list">{data.candidate_jobs.map(job => <article className="job" key={job.source_id}>
      <p className="muted">{job.company_name}</p><h3>{job.title}</h3><p className="muted">{(job.addresses || []).join(' · ')}</p>
      <div className="tags">{(job.tech_stacks || []).slice(0, 8).map(skill => <span key={skill}>{skill}</span>)}</div>
      <div className="job-bottom"><a href={safeSourceUrl(job.source_url)} target="_blank" rel="noreferrer">공고 원문 ↗</a><button disabled={!active || busy} onClick={() => onSelect(job)}>이 공고 확인하기 →</button></div>
    </article>)}</div>{active && <button className="quiet" disabled={busy} onClick={() => onAssessment('next_jobs')}>다음 공고 보기</button>}</>}
    {data.stage === 'assessment_checkpoint' && active && <div className="choices"><button disabled={busy} onClick={() => onAssessment('assessment_preferred')}>우대조건 확인</button><button disabled={busy} onClick={() => onAssessment('consult_gaps')}>현재 답변으로 상담</button><button disabled={busy} onClick={() => onAssessment('next_jobs')}>다른 공고 보기</button></div>}
    {data.assessment_paused && active && <button className="quiet" disabled={busy} onClick={() => onAssessment('assessment_resume')}>원할 때 역량 확인 재개</button>}
    {data.job_overview && <section className="source"><h3>{data.job_overview.title}</h3><details><summary>자격요건·우대조건 원문 보기</summary><h4>자격요건</h4><pre>{data.job_overview.qualifications}</pre><h4>우대조건</h4><pre>{data.job_overview.preferred_requirements}</pre></details><a href={safeSourceUrl(data.job_overview.source_url)} target="_blank" rel="noreferrer">공고 원문 ↗</a></section>}
    {isQuestion(data) && data.grouped && <AssessmentStepper key={data.questions.map(q => q.question_id).join("|")} data={data} active={active} busy={busy} onBatch={onBatch} onAssessment={onAssessment} />}
    {isQuestion(data) && !data.grouped && <><span className="pill">{data.requirement_type === 'required' ? '자격요건 확인' : '우대조건 확인'}</span><p>{data.question}</p>{data.progress && <p className="fine">{data.progress.answered + 1} / {data.progress.total}번째 조건</p>}
      {data.source_notice&&<p className="fine">{data.source_notice}</p>}<details className="source"><summary>조건 원문 확인하기</summary><pre>{data.quote}</pre><a href={safeSourceUrl(data.source_url)} target="_blank" rel="noreferrer">공고 원문 ↗</a></details>
      {active && <><p className="fine">아래에서 답을 고르세요. 보충 설명은 입력창에 먼저 적을 수 있습니다.</p><div className="choices">{Object.entries(names).map(([value, label]) => <button key={value} disabled={busy} onClick={() => onAnswer(value)}>{label}</button>)}</div></>}
      <p className="fine">원문 목록 항목별로 확인하며, 합격 여부를 판정하지 않습니다.</p></>}
    {data.answer_summary && <AssessmentSummary summary={data.answer_summary} checks={data.checks} active={active} busy={busy} onContinue={onContinue} paused={data.assessment_paused}/> }
    {!data.answer_summary && ['completed', 'gap_guidance'].includes(data.stage) && <><p>{data.stage === 'completed' ? '지원 조건 확인을 마쳤습니다.' : '보완이 필요한 조건을 확인했습니다.'} 답변하신 내용을 정리해 드릴게요.</p>{data.unconfirmed_count > 0 && <p className="muted">아직 확인하지 못한 조건이 {data.unconfirmed_count}개 있습니다.</p>}
      {data.checks.map((check, i) => <div className="check" key={i}><strong>{check.type === 'required' ? '자격요건' : '우대조건'} · {names[check.assessment]}</strong><p>{check.summary || conditionPreview(check.quote)}</p><details className="source"><summary>조건 원문 보기</summary><pre>{check.quote}</pre></details><p>{check.explanation}</p>{check.detail && <p>남긴 설명: {check.detail}</p>}</div>)}
      <p className="fine">사용자가 확인한 답변에 따른 결과입니다. 교육은 학습 참고 자료와 신청 후보를 구분하며, 모집 여부와 지원 자격은 원문에서 다시 확인해 주세요.</p></>}
    {!compact && data.learning_search && !['training_search_review', 'training_no_results'].includes(data.stage) && <section className="source"><h3>학습 루트 참고 교육</h3>
      {data.learning_search.status === 'no_match' && <p>저장된 자료에서 해당 주제·수강 방식에 맞는 과정을 찾지 못했습니다. 실제 개설·모집 과정이 없다는 뜻은 아닙니다.</p>}
      {data.learning_search.status === 'need_topic' && <p>배우고 싶은 기술이나 분야를 알려주세요.</p>}
      {(data.learning_opportunities || []).map(course => <article className="check" key={`${course.source}:${course.source_id}`}>
        <TrainingStatus course={course}/>
        <h3>{course.title}</h3><p>{course.provider_name} · {course.delivery_mode === 'online' ? '온라인' : course.delivery_mode === 'offline' ? '오프라인' : '혼합/미확인'}</p>
        <p>연결된 주제: {(course.matched_topics || []).join(' · ')}</p><p>{course.curriculum}</p>
        {course.cohorts?.length ? <TrainingCohorts course={course}/> : <>
        <p className="fine">페이지 표시 자부담: {course.tuition == null ? '미확인' : `${Number(course.tuition).toLocaleString()} ${course.currency || ''}`} · 최종 비용과 수강 자격은 기관 확인 필요</p>
        {course.dates?.starts_at?.raw && <p className="fine">저장된 교육 일정: {course.dates.starts_at.raw} ~ {course.dates.ends_at?.raw || '미확인'}</p>}
        </>}
        {course.warning && <p className="fine">{course.warning}</p>}
        <div className="job-bottom"><a className="source-link" href={safeSourceUrl(course.source_url)} target="_blank" rel="noreferrer">교육 정보 출처 ↗</a><TrainingExplainButton course={course} active={active} busy={busy} onExplain={onExplain}/></div>
      </article>)}
      {active && data.learning_opportunities?.length > 0 && <button className="quiet" disabled={busy} onClick={() => onAssessment('next_training')}>다음 교육 보기</button>}
    </section>}
    {compact && !data.message && data.stage==='choose_job' && <p className="fine">찾은 공고는 오른쪽 공고 목록에서 살펴보세요.</p>}
    {compact && data.stage==='choose_job' && active && <button className="quiet" disabled={busy} onClick={()=>onAssessment('next_jobs')}>다른 공고 보기 →</button>}
    {compact && data.learning_opportunities?.length>0 && !['training_search_review','training_no_results'].includes(data.stage) && <><p className="fine">찾은 교육은 오른쪽 교육 목록에서 살펴보세요.</p>{active && <button className="quiet" disabled={busy} onClick={()=>onAssessment('next_training')}>다른 교육 보기 →</button>}</>}
    {data.training_navigation_available && !data.learning_search && active && <button className="quiet" disabled={busy} onClick={() => onAssessment('next_training')}>다음 교육 보기</button>}
    {data.stage === 'no_results' && !data.message && <p>조건에 맞는 공고를 찾지 못했습니다. 기술이나 지역 조건을 조금 줄여 다시 말씀해 주세요.</p>}
    {data.cached && <span className="fine">저장된 응답</span>}
  </>;
}

export function CareerApp({page='chat',adminChat=false}) {
  const [copilotOpen,setCopilotOpen]=useState(false);
  function revealConsultation(){setCopilotOpen(true);document.getElementById('message')?.focus();}
  const [apiEnabled, setApiEnabled] = useState(null);
  useEffect(() => { let active = true; fetch('/deploy-config.json', { cache: 'no-store' }).then(r => { if (!r.ok) throw new Error('Configuration unavailable'); return r.json(); }).then(config => { if (active) setApiEnabled(config.apiEnabled === true); }).catch(() => { if (active) setApiEnabled(false); }); return () => { active = false; }; }, []);
  const [code, setCode] = useState('');
  const [unlocked, setUnlocked] = useState(false);
  const owner = useRef(clientToken());
  const [session, setSession] = useState(null);
  const [messages, setMessages] = useState([]);
  const [result, setResult] = useState(null);
  const [draft, setDraft] = useState('');
  const [jobDetails,setJobDetails]=useState({}),[detailError,setDetailError]=useState('');
  const [trainingDetails,setTrainingDetails]=useState({});
  async function loadTrainingDetail(course){
    if(!session || inFlight.current)return;
    setDetailError('');inFlight.current=true;setBusy(true);
    try{const r=await postChat({payload:requestPayload('view_training',{source:course.source,source_id:course.source_id,source_version:String(course.source_version)},session),accessCode:code,ownerToken:owner.current});if(!r.ok)throw new Error();setTrainingDetails(old=>({...old,[course.source+':'+course.source_id]:r.body.training_detail}));}
    catch{setDetailError('교육 상세 정보를 불러오지 못했습니다. 원문을 확인하거나 목록에서 다시 선택해 주세요.');}
    finally{inFlight.current=false;setBusy(false);}
  }
  const detailRequest=useRef(null);
  async function loadJobDetail(job){
    if(!session || inFlight.current)return;
    const id=job.source_id;detailRequest.current=id;setDetailError('');inFlight.current=true;setBusy(true);
    try{const r=await postChat({payload:requestPayload('view_job',{source_id:id},session),accessCode:code,ownerToken:owner.current});if(!r.ok)throw new Error();if(detailRequest.current===id)setJobDetails(old=>({...old,[id]:r.body.job_detail}));}
    catch{setDetailError('상세 정보를 불러오지 못했습니다. 원문을 확인하거나 다시 선택해 주세요.');}
    finally{inFlight.current=false;setBusy(false);}
  }
  const [savedOpen,setSavedOpen]=useState(false),[savedData,setSavedData]=useState(null),[savedError,setSavedError]=useState('');
  const [busy, setBusy] = useState(false);
  const [busyAction, setBusyAction] = useState(null);
  const inFlight = useRef(false);
  const [error, setError] = useState(null);
  const [stepRecovery,setStepRecovery]=useState(null);
  const [pending, setPending] = useState(null);
  const bottom = useRef(null);
  const conversation = useRef(null);
  const initialBrowse=useRef(false);
  const initialTraining=useRef(false);
  useEffect(()=>{
    if(unlocked && apiEnabled && !adminChat && page==='training' && !initialTraining.current && !inFlight.current){
      initialTraining.current=true;
      if(!messages.some(m=>m.data?.learning_search || ['training_search_review','training_no_results'].includes(m.data?.stage)))send(requestPayload('browse_training',{},session));
    }
  },[unlocked,apiEnabled,page,session,adminChat,busy]);
  useEffect(()=>{
    if(unlocked && apiEnabled && !adminChat && page==='jobs' && !initialBrowse.current && !messages.some(m=>m.data?.stage==='choose_job' || (m.data?.stage==='no_results' && m.data?.search_summary)) && !inFlight.current){
      initialBrowse.current=true;
      send(requestPayload('search',{search_plan:{keyword:'',region:'',skills:[],limit:20}},session));
    }
  },[unlocked,apiEnabled,page,session,adminChat,busy]);
  useEffect(() => {
    if(page!=='chat' && (busyAction==='next_results' || messages.at(-1)?.data?.search_continuation || messages.at(-1)?.data?.training_continuation))return;
    const stepper=conversation.current?.querySelector('.assessment-stepper');
    const summary=conversation.current?.querySelector('.message:last-of-type .assessment-summary');
    const review=conversation.current?.querySelector('.message:last-of-type .search-review');
    if(review)review.scrollIntoView({behavior:'smooth',block:'start'});
    else if(stepper)stepper.scrollIntoView({behavior:'smooth',block:'start'});
    else if(summary)summary.scrollIntoView({behavior:'smooth',block:'start'});
    else bottom.current?.scrollIntoView({behavior:'smooth',block:'end'});
  }, [messages,busy,error,page]);

  function reset() {
    initialBrowse.current=false;initialTraining.current=false; setJobDetails({});setTrainingDetails({});setDetailError('');detailRequest.current=null; setSession(null); setMessages([]); setResult(null); setDraft(''); setSavedOpen(false); setSavedData(null); setSavedError(''); setError(null);setStepRecovery(null); setPending(null);
  }

  async function send(payload, text) {
    if (inFlight.current) return;
    if(payload.action==='search' && !payload.search_plan && new URLSearchParams(window.location.search).get('agentcore')==='1')payload={...payload,engine:'agentcore'};
    if(payload.action==='search' && !adminChat && window.location.hash==='#jobs')payload={...payload,page_size:20};
    inFlight.current = true; setBusy(true); setBusyAction(payload.action); setError(null);setStepRecovery(null); setPending(null);
    if (text) setMessages(old => [...old, { role: 'user', text, id: crypto.randomUUID() }]);
    try {
      let response = await postChat({ payload, accessCode: code, ownerToken: owner.current, onProgress: ({ text: partial }) => {
        setMessages(old => {
          const draft = { role: 'assistant', data: { stage: 'streaming', message: partial }, id: payload.request_id, partial: true };
          return old.some(m => m.id === payload.request_id) ? old.map(m => m.id === payload.request_id ? draft : m) : [...old, draft];
        });
      } });
      let data = response.body;
      // Explorer explicitly opts into immediate list application. Keep chat-only consent unchanged.
      if(response.ok && !adminChat && ['#jobs','#training'].includes(window.location.hash) && ['search_review','training_search_review'].includes(data.stage) && data.search_id){
        const confirmed=await postChat({payload:requestPayload('confirm_search',{search_id:data.search_id},data.session_id || session),accessCode:code,ownerToken:owner.current});
        if(!confirmed.ok){setSession(data.session_id || session);setResult(data);setMessages(old=>[...old,{role:'assistant',data,id:payload.request_id}]);setError('검색 기준 적용에 실패했습니다. 표시된 검색 기준에서 다시 확인해 주세요.');return;}
        data={...confirmed.body,...(data.engine?{engine:data.engine}:{}),message:data.engine==='agentcore'?data.message:'말씀하신 검색 기준으로 목록을 갱신했습니다. 적용한 조건을 확인하고 추가하거나 해제할 조건을 말씀해 주세요.'};
      }
      if (data.session_id) setSession(data.session_id);
      if (!response.ok) {
        setMessages(old => old.filter(m => m.id !== payload.request_id));
        const hints = { agentcore_experiment_admin_only:'AgentCore 실험은 관리자 접속 코드로만 사용할 수 있습니다.',agentcore_experiment_budget_reached:'승인된 실험 호출 한도에 도달했습니다. 추가 비용 승인 전까지 중단합니다.',conversation_engine_changed_start_new:'실행 방식을 바꾸려면 새 대화를 시작해 주세요.',training_reference_changed:'교육 목록이 바뀌었습니다. 최신 목록에서 다시 선택해 주세요.', stale_training_search:'교육 검색 기준이 바뀌었습니다. 최신 교육 검색 설명을 확인해 주세요.', unauthorized: '접속 코드를 다시 확인해 주세요.', session_busy_retry_later: '이전 요청을 처리 중입니다. 잠시 뒤 다시 확인해 주세요.', session_not_found_or_expired: '대화가 만료됐습니다. 새 대화를 시작해 주세요.', source_changed_reselect_job: '공고 원문이 바뀌었습니다. 새 대화에서 다시 검색해 주세요.', session_model_budget_exceeded: '이 대화의 모델 호출 한도에 도달했습니다. 새 대화를 시작해 주세요.', search_confirmation_changed: '검색 기준이 바뀌었습니다. 최신 검색 설명을 확인해 주세요.', consultation_summary_changed: '답변 정리가 바뀌었습니다. 최신 요약에서 다시 선택해 주세요.', consultation_requires_selected_job: '상담할 공고를 먼저 선택해 주세요.', saved_answers_changed_refresh:'다른 답변이 저장돼 내용이 바뀌었습니다. 다시 조회한 뒤 수정해 주세요.',saved_answer_not_found:'수정할 답변을 다시 조회해 주세요.',saved_answer_legacy_readonly:'이전 형식의 답변은 여기서 수정할 수 없습니다.',ModelOutputFormatError: '요청을 처리하는 중 답변 구성을 확인하지 못했습니다. 기존 대화와 답변은 유지됩니다. 먼저 진행할 단계 하나를 선택해 주세요.' };
        const hint=hints[data.status] || hints[data.error_code] || data.message || `요청을 처리하지 못했습니다. (${response.status})`;
        setError(hint);
        if(needsStepRecovery(data))setStepRecovery({message:payload.message || text || ''});
        if(['revise_answer','remember'].includes(payload.action))setSavedError(hint);
        if (data.retryable) setPending({ payload: { ...payload, request_id: crypto.randomUUID(), ...(data.session_id ? { session_id: data.session_id } : {}) }, retryAt: Date.now() + 10000 });
        else if (data.status === 'session_busy_retry_later') setPending({ payload, retryAt: Date.now() + 10000 });
        if (response.status === 401) setUnlocked(false);
        return;
      }
      if(data.learning_search || ['training_search_review','training_no_results'].includes(data.stage))initialTraining.current=true;
      if(!adminChat && ['#jobs','#training'].includes(window.location.hash)){
        if(data.stage==='choose_job')window.location.hash='#jobs';
        else if(data.learning_search && !['training_search_review','training_no_results'].includes(data.stage))window.location.hash='#training';
      }
      const backgroundList=payload.action==='next_results' && ['#jobs','#training'].includes(window.location.hash);
      if(!backgroundList)setResult(data);
      setMessages(old => {
        const finished = { role: 'assistant', data, id: payload.request_id, backgroundList };
        return old.some(m => m.id === payload.request_id) ? old.map(m => m.id === payload.request_id ? finished : m) : [...old, finished];
      });
      return data;
    } catch {
      if(['revise_answer','remember'].includes(payload.action))setSavedError('연결이 끊겼습니다. 저장 결과를 다시 확인해 주세요.');
      setMessages(old => old.filter(m => m.id !== payload.request_id));
      setError('연결이 끊겼습니다. 같은 요청의 처리 결과를 다시 확인할 수 있습니다.');
      setPending({ payload, retryAt: 0 });
    } finally { inFlight.current = false; setBusy(false); }
  }

  function retryList(target){
    if(pending && Date.now()<pending.retryAt){setError('잠시 기다린 뒤 다시 시도해 주세요.');return;}
    send(pending?.payload || requestPayload('next_results',{target},session));
  }

  async function loadSavedAnswers(offset=0) {
    if(inFlight.current || !session || pending)return;
    inFlight.current=true;setBusy(true);setBusyAction('review_answers');setSavedOpen(true);setSavedData(null);setSavedError('');
    try{
      const next=savedAnswersRequest(offset);
      const response=await postChat({payload:requestPayload(next.action,next.values,session),accessCode:code,ownerToken:owner.current});
      if(!response.ok)throw new Error(response.body.status==='session_not_found_or_expired'?'대화가 만료돼 저장 내용을 조회할 수 없습니다.': '저장 내용을 조회하지 못했습니다. 잠시 뒤 다시 확인해 주세요.');
      setSavedData(response.body.saved_answers);
    }catch(e){setSavedError(e.message);}finally{inFlight.current=false;setBusy(false);}
  }
  async function reviseSaved(next){
    setSavedError('');
    const data=await send(requestPayload(next.action,next.values,session),'저장한 조건 답변 하나를 수정할게요.');
    if(data?.saved_answers){setSavedData(data.saved_answers);return true;}return false;
  }
  async function rememberAll(message){
    setSavedError('');
    const data=await send(requestPayload('remember',{message},session),'경험 전체를 정정할게요: '+message);
    if(data){setSavedOpen(false);setSavedData(null);return true;}return false;
  }

  function search(event) {
    event.preventDefault();
    if (!draft.trim() || busy || pending) return;
    const text = draft.trim(); setDraft('');
    send(requestPayload('search', { message: text, profile: {} }, session), text);
  }
  function continueSummary(message, id, summaryId) {
    const next = summaryActionRequest({ id, message }, summaryId);
    send(requestPayload(next.action, next.values, session), message);
  }
  function explainTraining(course) {
    const next=trainingExplainRequest(course);
    send(requestPayload(next.action,next.values,session),next.label);
  }
  function select(job) {
    send(requestPayload('select', { source_id: job.source_id, grouped: true, assessment_checkpoint: true }, session), `${job.company_name} · ${job.title} 공고를 확인할게요.`);
  }
  function answer(value) {
    const detail = draft.trim(); setDraft('');
    send(requestPayload('answer', { question_id: result.question_id, assessment: value, detail }, session), `${names[value]}${detail ? '\n' + detail : ''}`);
  }
  function assessmentControl(id) {
    const next = controlRequest(id);
    send(requestPayload(next.action, next.values, session), next.label);
  }
  function answerBatch(answers) {
    send(requestPayload('answer_batch', { answers }, session), '조건별 답변을 저장할게요.');
  }
  const question = isQuestion(result) && !result.grouped;
  const sequential = isQuestion(result) && result.grouped;
  const compactComposer = sequential || !!result?.answer_summary;
  const noteOnly = false; // Free conversation and stopping questions stay available during assessments.
  const exploring=unlocked && !adminChat && page!=='chat';
  return <div className={`app${exploring?' explorer-layout':''}${copilotOpen?' copilot-open':''}`}>
    {savedOpen&&<SavedAnswersPanel data={savedData} busy={busy} error={savedError} onClose={()=>{if(!busy){setSavedOpen(false);setSavedData(null);}}} onRefresh={loadSavedAnswers} onRevise={reviseSaved} onRemember={rememberAll}/>}
    <aside className="sidebar"><a className="brand" href={adminChat?'#admin-chat':'#jobs'}>ROUNDUP<span>CAREER</span></a><nav className="rail-nav" aria-label="빠른 이동"><a href="#jobs" aria-label="공고 탐색">▣<small>공고</small></a><a href="#training" aria-label="교육 탐색">▤<small>교육</small></a><button type="button" onClick={revealConsultation} aria-label="AI 상담">✳<small>상담</small></button></nav><button disabled={busy} onClick={()=>{reset();if(!adminChat)revealConsultation();window.location.hash=adminChat?'#admin-chat':'#jobs';}}>＋ 새 대화</button><div className="sidebar-bottom">내 조건에 맞는 다음 기회<p>공고 검색 · 지원 조건 확인</p></div></aside>
    <div className="workspace"><header><span>커리어 도우미 <span className="model">Sonnet</span></span>{unlocked && !adminChat && <WorkspaceNavigation page={page}/>}{unlocked && <button className="quiet" disabled={busy} onClick={() => { reset(); setCode(''); setUnlocked(false); owner.current = clientToken(); }}>잠금</button>}</header>
      {apiEnabled !== true ? <main className="access"><h1>{apiEnabled === null ? '연결을 확인하고 있어요.' : '다음 기회를 준비하고 있어요.'}</h1><p className="muted">{apiEnabled === null ? '잠시만 기다려 주세요.' : '웹 호스팅이 준비되었습니다. 공고 검색과 대화 기능은 백엔드 연결 후 제공됩니다.'}</p></main> : !unlocked ? <main className="access"><h1>함께 다음 기회를 찾아봐요.</h1><p className="muted">{adminChat ? '관리자 전용 토큰을 입력하세요. 관리자 세션은 호출 횟수 제한 없이 사용량을 기록합니다.' : '공유받은 테스트 접속 코드를 입력해 주세요.'}</p><form onSubmit={event => { event.preventDefault(); setUnlocked(true); }}><label htmlFor="access-code">접속 코드</label><input id="access-code" type="password" value={code} onChange={event => setCode(event.target.value)} autoComplete="off" minLength={32} required /><button className="primary">대화 시작하기 →</button></form></main> : <>
        <div className="workspace-body"><button className="copilot-toggle" type="button" aria-expanded={copilotOpen} onClick={()=>setCopilotOpen(!copilotOpen)}>{copilotOpen?'AI 패널 닫기':'AI에게 조건 말하기'}</button><div className="chat-view"><div className="copilot-heading"><strong>{new URLSearchParams(window.location.search).get('agentcore')==='1'?'AgentCore 관리자 실험':'AI 검색 도우미'}</strong><span>조건을 말하고 함께 찾아보세요</span></div>
        <main ref={conversation} className="conversation" aria-label="대화 내용" aria-live="polite">
          {!messages.length && <section className="welcome"><div className="spark">✳</div><h1>어떤 일을 찾고 계신가요?</h1><p>희망하는 직무, 기술, 지역을 편하게 말씀해 주세요.<br />채용공고나 교육 과정을 찾고, 원할 때 지원 조건을 확인할 수 있어요.</p></section>}
          {result?.active_job && <aside className="source" aria-label="현재 상담 공고"><strong>현재 상담 공고</strong><p>{result.active_job.company_name} · {result.active_job.title}</p><small>확인한 버전 {result.active_job.source_version} · 다른 목록을 보아도 새 공고 선택 전까지 이 공고의 답변을 유지합니다.</small></aside>}
          {messages.map((message, index) => message.backgroundList ? null : <article key={message.id} className={`message ${message.role}`} aria-label={message.role === 'user' ? '내 메시지' : '도우미 응답'}>{message.role === 'assistant' && <div className="avatar">✳</div>}<div className="message-content">{message.text ? <p className="user-text">{message.text}</p> : <Reply data={message.data} active={!pending && (!messages.slice(index + 1).some(m => !m.backgroundList) || (result?.stage === 'conversation' && message.data?.stage === 'choose_job' && !messages.slice(index + 1).some(m => !m.backgroundList && m.data && m.data.stage !== 'conversation')))} busy={busy} onConfirm={(searchId, target) => send(requestPayload('confirm_search', { search_id: searchId }, session), target === 'training' ? '이 검색 기준으로 교육을 보여줘.' : '이 검색 기준으로 공고를 보여줘.')} onModify={() => { setDraft('검색 조건 수정: '); document.getElementById('message')?.focus(); }} onContinue={continueSummary} compact={exploring} onExplain={explainTraining} onSelect={select} onAnswer={answer} onBatch={answerBatch} onAssessment={assessmentControl} />}</div></article>)}
          {busy && busyAction!=='next_results' && !messages.some(m => m.partial) && <div className="thinking" role="status">✳ {busyAction === 'select' ? '선택한 공고의 조건을 불러오고 있어요' : ['answer', 'answer_batch'].includes(busyAction) ? '답변을 저장하고 있어요' : busyAction === 'remember' ? '말씀하신 내용을 반영하고 있어요' : '답변을 준비하고 있어요'}<span>…</span></div>}
          {error && <div className="error" role="alert"><p>{error}</p>{pending && <button disabled={busy} onClick={() => { if (Date.now() < pending.retryAt) { setError('잠시 기다린 뒤 다시 시도해 주세요.'); return; } send(pending.payload); }}>다시 확인하기</button>}{stepRecovery?<div className="choices"><button disabled={busy} onClick={()=>{const message=recoveryMessage(stepRecovery.message,'assessment');send(requestPayload('search',{message},session),message);}}>역량 확인부터</button><button disabled={busy} onClick={()=>{const message=recoveryMessage(stepRecovery.message,'training');send(requestPayload('search',{message},session),message);}}>교육 찾기부터</button></div>:<button className="quiet" disabled={busy} onClick={reset}>새 대화</button>}</div>}
          <div ref={bottom} />
        </main>
        <div className={`composer-area${compactComposer ? " assessment-mode" : ""}`}>{session && <div className="memory-tools"><button className="quiet" type="button" disabled={busy || !!pending} onClick={() => loadSavedAnswers(0)}>내 답변 보기·수정</button><span className="fine">현재 대화 안에서 기억합니다</span></div>}{result?.memory?.facts?.length > 0 && <details className="memory-summary"><summary>기억한 내용 {result.memory.facts.length}개</summary>{result.memory.facts.map((fact, i) => <p key={i}><strong>{fact.subject}</strong> · {fact.quote}</p>)}</details>}<form className="composer" onSubmit={search}><label className="sr-only" htmlFor="message">{noteOnly ? '답변 보충 설명' : '찾고 싶은 공고'}</label><textarea id="message" value={draft} maxLength={question ? 2000 : 4000} disabled={busy || !!pending} onChange={event => setDraft(event.target.value)} onKeyDown={event => { if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing && !noteOnly) { event.preventDefault(); event.currentTarget.form.requestSubmit(); } }} placeholder={noteOnly ? '보충 설명을 적고 대화 속 답변 버튼을 눌러 주세요.' : '예: React 교육을 찾아줘. 또는 역량 질문은 그만해줘.'} rows={compactComposer ? 1 : 2} />
          <div className="composer-bottom"><span>{noteOnly ? '설명은 선택 사항입니다' : '원하는 조건을 자연스럽게 입력하세요'}</span>{!noteOnly && <button className="send" aria-label="메시지 보내기" disabled={busy || !!pending || !draft.trim()}>↑</button>}</div></form>
          <p className="disclaimer">수집된 공고로 테스트 중입니다. 현재 모집 여부는 원문에서 확인해 주세요.</p></div>
      </div>
      <div hidden={page!=='jobs'}><ExplorationPreview target="jobs" loadError={busyAction==='next_results'?error:null} onRetry={()=>retryList('jobs')} loading={(busy && !pending) || (!session && !error && !pending)} details={jobDetails} detailError={detailError} onRead={loadJobDetail} active={page==='jobs'} busy={busy || !!pending} onNext={()=>send(requestPayload('next_results',{target:'jobs'},session))} onReset={()=>send(requestPayload('search',{search_plan:{keyword:'',region:'',skills:[],limit:20}},session),'검색 조건을 초기화하고 전체 공고를 볼게요.')} onChat={revealConsultation} onAssess={job=>{revealConsultation();select(job);}} results={latestSearchResults(messages,'jobs')}/></div>
      <div hidden={page!=='training'}><ExplorationPreview target="training" loadError={busyAction==='next_results'?error:null} onRetry={()=>retryList('training')} trainingDetails={trainingDetails} detailError={detailError} onRead={loadTrainingDetail} loading={(busy && !pending) || (!initialTraining.current && !error)} active={page==='training'} onNext={()=>send(requestPayload('next_results',{target:'training'},session))} onReset={()=>send(requestPayload('browse_training',{},session))} busy={busy || !!pending} onChat={revealConsultation} onExplain={course=>{revealConsultation();explainTraining(course);}} results={latestSearchResults(messages,'training')}/></div>
      </div>
      </>}
    </div>
  </div>;
}


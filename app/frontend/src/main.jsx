import React, { useEffect, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { clientToken, postChat, requestPayload, safeSourceUrl } from './api.js';
import './style.css';

const names = { met: '충족해요', unmet: '미충족이에요', unknown: '아직 모르겠어요' };
const isQuestion = data => ['checking_required', 'checking_preferred'].includes(data?.stage);

function Reply({ data, active, busy, onSelect, onAnswer }) {
  return <>
    {data.message && <p className="muted">{data.message}</p>}
    {data.stage === 'choose_job' && <><p>조건에 맞는 공고가 총 {data.total}건 있습니다. 먼저 살펴볼 공고를 골라 주세요.</p><div className="job-list">{data.candidate_jobs.map(job => <article className="job" key={job.source_id}>
      <p className="muted">{job.company_name}</p><h3>{job.title}</h3><p className="muted">{(job.addresses || []).join(' · ')}</p>
      <div className="tags">{(job.tech_stacks || []).slice(0, 8).map(skill => <span key={skill}>{skill}</span>)}</div>
      <div className="job-bottom"><a href={safeSourceUrl(job.source_url)} target="_blank" rel="noreferrer">공고 원문 ↗</a><button disabled={!active || busy} onClick={() => onSelect(job)}>이 공고 확인하기 →</button></div>
    </article>)}</div></>}
    {isQuestion(data) && <><span className="pill">{data.requirement_type === 'required' ? '자격요건 확인' : '우대조건 확인'}</span><p>{data.question}</p>{data.progress && <p className="fine">{data.progress.answered + 1} / {data.progress.total}번째 조건</p>}
      <details className="source"><summary>조건 원문 확인하기</summary><pre>{data.quote}</pre><a href={safeSourceUrl(data.source_url)} target="_blank" rel="noreferrer">공고 원문 ↗</a></details>
      {active && <><p className="fine">아래에서 답을 고르세요. 보충 설명은 입력창에 먼저 적을 수 있습니다.</p><div className="choices">{Object.entries(names).map(([value, label]) => <button key={value} disabled={busy} onClick={() => onAnswer(value)}>{label}</button>)}</div></>}
      <p className="fine">원문 목록 항목별로 확인하며, 합격 여부를 판정하지 않습니다.</p></>}
    {['completed', 'gap_guidance'].includes(data.stage) && <><p>{data.stage === 'completed' ? '지원 조건 확인을 마쳤습니다.' : '보완이 필요한 조건을 확인했습니다.'} 답변하신 내용을 정리해 드릴게요.</p>{data.unconfirmed_count > 0 && <p className="muted">아직 확인하지 못한 조건이 {data.unconfirmed_count}개 있습니다.</p>}
      {data.checks.map((check, i) => <div className="check" key={i}><strong>{check.type === 'required' ? '자격요건' : '우대조건'} · {names[check.assessment]}</strong><pre>{check.quote}</pre><p>{check.explanation}</p>{check.detail && <p>남긴 설명: {check.detail}</p>}</div>)}
      <p className="fine">사용자가 확인한 답변에 따른 결과입니다. 교육 추천과 자유로운 학습 상담은 아직 연결되지 않았습니다.</p></>}
    {data.stage === 'no_results' && <p>조건에 맞는 공고를 찾지 못했습니다. 기술이나 지역 조건을 조금 줄여 다시 말씀해 주세요.</p>}
    {data.cached && <span className="fine">저장된 응답</span>}
  </>;
}

function App() {
  const [apiEnabled, setApiEnabled] = useState(null);
  useEffect(() => { let active = true; fetch('/deploy-config.json', { cache: 'no-store' }).then(r => { if (!r.ok) throw new Error('Configuration unavailable'); return r.json(); }).then(config => { if (active) setApiEnabled(config.apiEnabled === true); }).catch(() => { if (active) setApiEnabled(false); }); return () => { active = false; }; }, []);
  const [code, setCode] = useState('');
  const [unlocked, setUnlocked] = useState(false);
  const owner = useRef(clientToken());
  const [session, setSession] = useState(null);
  const [messages, setMessages] = useState([]);
  const [result, setResult] = useState(null);
  const [draft, setDraft] = useState('');
  const [memoryMode, setMemoryMode] = useState(false);
  const [busy, setBusy] = useState(false);
  const inFlight = useRef(false);
  const [error, setError] = useState(null);
  const [pending, setPending] = useState(null);
  const bottom = useRef(null);
  useEffect(() => { bottom.current?.scrollIntoView({ behavior: 'smooth', block: 'end' }); }, [messages, busy, error]);

  function reset() {
    setSession(null); setMessages([]); setResult(null); setDraft(''); setMemoryMode(false); setError(null); setPending(null);
  }

  async function send(payload, text) {
    if (inFlight.current) return;
    inFlight.current = true; setBusy(true); setError(null); setPending(null);
    if (text) setMessages(old => [...old, { role: 'user', text, id: crypto.randomUUID() }]);
    try {
      const response = await postChat({ payload, accessCode: code, ownerToken: owner.current });
      const data = response.body;
      if (data.session_id) setSession(data.session_id);
      if (!response.ok) {
        const hints = { unauthorized: '접속 코드를 다시 확인해 주세요.', session_busy_retry_later: '이전 요청을 처리 중입니다. 잠시 뒤 다시 확인해 주세요.', session_not_found_or_expired: '대화가 만료됐습니다. 새 대화를 시작해 주세요.', source_changed_reselect_job: '공고 원문이 바뀌었습니다. 새 대화에서 다시 검색해 주세요.', session_model_budget_exceeded: '이 대화의 모델 호출 한도에 도달했습니다. 새 대화를 시작해 주세요.', ModelOutputFormatError: '응답 형식을 확인하지 못했습니다.' };
        setError(hints[data.status] || hints[data.error_code] || data.message || `요청을 처리하지 못했습니다. (${response.status})`);
        if (data.retryable) setPending({ payload: { ...payload, request_id: crypto.randomUUID(), ...(data.session_id ? { session_id: data.session_id } : {}) }, retryAt: Date.now() + 10000 });
        else if (data.status === 'session_busy_retry_later') setPending({ payload, retryAt: Date.now() + 10000 });
        if (response.status === 401) setUnlocked(false);
        return;
      }
      setResult(data);
      setMessages(old => [...old, { role: 'assistant', data, id: crypto.randomUUID() }]);
    } catch {
      setError('연결이 끊겼습니다. 같은 요청의 처리 결과를 다시 확인할 수 있습니다.');
      setPending({ payload, retryAt: 0 });
    } finally { inFlight.current = false; setBusy(false); }
  }

  function search(event) {
    event.preventDefault();
    if (!draft.trim() || busy || pending) return;
    if (memoryMode && session) {
      const text = draft.trim(); setDraft(''); setMemoryMode(false);
      send(requestPayload('remember', { message: text }, session), text); return;
    }
    if (isQuestion(result)) { setError('입력한 설명과 함께 아래 답변 버튼을 선택해 주세요.'); return; }
    const text = draft.trim(); setDraft('');
    send(requestPayload('search', { message: text, profile: {} }, session), text);
  }
  function select(job) {
    send(requestPayload('select', { source_id: job.source_id }, session), `${job.company_name} · ${job.title} 공고를 확인할게요.`);
  }
  function answer(value) {
    const detail = draft.trim(); setDraft('');
    send(requestPayload('answer', { question_id: result.question_id, assessment: value, detail }, session), `${names[value]}${detail ? '\n' + detail : ''}`);
  }
  const question = isQuestion(result);
  const noteOnly = question && !memoryMode;
  return <div className="app">
    <aside className="sidebar"><a className="brand" href="/">ROUNDUP<span>CAREER</span></a><button disabled={busy} onClick={reset}>＋ 새 대화</button><div className="sidebar-bottom">내 조건에 맞는 다음 기회<p>공고 검색 · 지원 조건 확인</p></div></aside>
    <div className="workspace"><header><span>커리어 도우미 <span className="model">Sonnet</span></span>{unlocked && <button className="quiet" disabled={busy} onClick={() => { reset(); setCode(''); setUnlocked(false); owner.current = clientToken(); }}>잠금</button>}</header>
      {apiEnabled !== true ? <main className="access"><h1>{apiEnabled === null ? '연결을 확인하고 있어요.' : '다음 기회를 준비하고 있어요.'}</h1><p className="muted">{apiEnabled === null ? '잠시만 기다려 주세요.' : '웹 호스팅이 준비되었습니다. 공고 검색과 대화 기능은 백엔드 연결 후 제공됩니다.'}</p></main> : !unlocked ? <main className="access"><h1>함께 다음 기회를 찾아봐요.</h1><p className="muted">공유받은 테스트 접속 코드를 입력해 주세요.</p><form onSubmit={event => { event.preventDefault(); setUnlocked(true); }}><label htmlFor="access-code">접속 코드</label><input id="access-code" type="password" value={code} onChange={event => setCode(event.target.value)} autoComplete="off" minLength={32} required /><button className="primary">대화 시작하기 →</button></form></main> : <>
        <main className="conversation" aria-label="대화 내용" aria-live="polite">
          {!messages.length && <section className="welcome"><div className="spark">✳</div><h1>어떤 일을 찾고 계신가요?</h1><p>희망하는 직무, 기술, 지역을 편하게 말씀해 주세요.<br />공고를 찾은 뒤 지원 조건을 함께 확인할게요.</p></section>}
          {messages.map((message, index) => <article key={message.id} className={`message ${message.role}`} aria-label={message.role === 'user' ? '내 메시지' : '도우미 응답'}>{message.role === 'assistant' && <div className="avatar">✳</div>}<div className="message-content">{message.text ? <p className="user-text">{message.text}</p> : <Reply data={message.data} active={index === messages.length - 1 && !pending} busy={busy} onSelect={select} onAnswer={answer} />}</div></article>)}
          {busy && <div className="thinking" role="status">✳ 공고와 조건을 확인하고 있어요<span>…</span></div>}
          {error && <div className="error" role="alert"><p>{error}</p>{pending && <button disabled={busy} onClick={() => { if (Date.now() < pending.retryAt) { setError('잠시 기다린 뒤 다시 시도해 주세요.'); return; } send(pending.payload); }}>다시 확인하기</button>}<button className="quiet" disabled={busy} onClick={reset}>새 대화</button></div>}
          <div ref={bottom} />
        </main>
        <div className="composer-area">{session && <div className="memory-tools"><button className="quiet" type="button" disabled={busy || !!pending} onClick={() => setMemoryMode(old => !old)}>{memoryMode ? '경험 수정 취소' : '기억한 경험 수정'}</button><span className="fine">현재 대화 안에서 기억합니다</span></div>}{result?.memory?.facts?.length > 0 && <details className="memory-summary"><summary>기억한 내용 {result.memory.facts.length}개</summary>{result.memory.facts.map((fact, i) => <p key={i}><strong>{fact.subject}</strong> · {fact.quote}</p>)}</details>}<form className="composer" onSubmit={search}><label className="sr-only" htmlFor="message">{memoryMode ? '경험 수정' : noteOnly ? '답변 보충 설명' : '찾고 싶은 공고'}</label><textarea id="message" value={draft} maxLength={question || memoryMode ? 2000 : 4000} disabled={busy || !!pending} onChange={event => setDraft(event.target.value)} onKeyDown={event => { if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing && !noteOnly) { event.preventDefault(); event.currentTarget.form.requestSubmit(); } }} placeholder={memoryMode ? '예: 앞서 말한 경험을 정정할게요. Linux는 아직 사용해 본 적 없어요.' : noteOnly ? '보충 설명을 적고 대화 속 답변 버튼을 눌러 주세요.' : '예: 서울에서 MySQL을 사용하는 백엔드 공고를 찾고 있어요.'} rows={2} />
          <div className="composer-bottom"><span>{memoryMode ? '수정 시 이전 조건 답변을 다시 확인합니다' : noteOnly ? '설명은 선택 사항입니다' : '원하는 조건을 자연스럽게 입력하세요'}</span>{!noteOnly && <button className="send" aria-label="메시지 보내기" disabled={busy || !!pending || !draft.trim()}>↑</button>}</div></form>
          <p className="disclaimer">수집된 공고로 테스트 중입니다. 현재 모집 여부는 원문에서 확인해 주세요.</p></div>
      </>}
    </div>
  </div>;
}

createRoot(document.getElementById('root')).render(<App />);

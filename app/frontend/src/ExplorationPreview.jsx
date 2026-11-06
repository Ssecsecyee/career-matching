import React, {useEffect,useRef,useState} from 'react';
import {safeSourceUrl} from './api.js';
import {TrainingStatus} from './TrainingStatus.jsx';
import {TrainingCohorts} from './TrainingCohorts.jsx';
import {filterItems} from './browseFilters.js';
import {CompanyBadge} from './CompanyBadge.jsx';

function regionOf(item){return (item.addresses || [])[0]?.trim().split(/\s+/)[0] || '';}
export function ExplorationPreview({target,results,busy=false,loading=false,loadError=null,onRetry,onChat,onExplain,onAssess,onNext,onReset,active=true,details={},trainingDetails={},detailError='',onRead,onSave,isSaved=()=>false,personal=false}) {
 const [selected,setSelected]=useState(null),[keyword,setKeyword]=useState(''),[region,setRegion]=useState(''),[extra,setExtra]=useState('');
 const scrollArmed=useRef(false);
 const jobs=target==='jobs';
 const initialLoading=active && loading && !results.items.length;
 useEffect(()=>{if(!selected || !active)return;const close=e=>{if(e.key==='Escape')setSelected(null);};window.addEventListener('keydown',close);return()=>window.removeEventListener('keydown',close);},[selected,active]);
 const current=results.items.find(item=>`${item.source || 'jumpit'}:${item.source_id}`===selected);
 const trainingDetail=current && trainingDetails[current.source+':'+current.source_id];
 const regions=[...new Set(results.items.map(regionOf).filter(Boolean))];
 const filtered=filterItems(results.items,{keyword,region,extra,jobs});
 const visible=filtered;
 const scrollSentinel=useRef(null);
 useEffect(()=>{
   if(personal || !active || busy || loadError || keyword || region || extra || !results.hasMore || !onNext || typeof IntersectionObserver==='undefined')return;
   let near=false,requested=false;
   const request=()=>{if(near && scrollArmed.current && !requested){requested=true;onNext();}};
   const onScroll=event=>{if(event.target?.closest?.('.chat-view,.browse-detail'))return;if(event.type==='wheel' && event.deltaY<=0)return;scrollArmed.current=true;request();};
   const observer=new IntersectionObserver(entries=>{near=entries.some(e=>e.isIntersecting);request();},{rootMargin:'0px 0px 120px 0px'});
   if(scrollSentinel.current)observer.observe(scrollSentinel.current);
   window.addEventListener('scroll',onScroll,true);
   window.addEventListener('wheel',onScroll,{capture:true,passive:true});
   window.addEventListener('touchmove',onScroll,{capture:true,passive:true});
   return()=>{observer.disconnect();window.removeEventListener('scroll',onScroll,true);window.removeEventListener('wheel',onScroll,true);window.removeEventListener('touchmove',onScroll,true);};
 },[personal,active,busy,loadError,keyword,region,extra,results.hasMore,results.items.length,onNext]);
 return <main className="browse-page" aria-label={jobs?'채용공고 탐색':'교육과정 탐색'} aria-busy={loading}>
  {!personal && <><div className="browse-toolbar"><label className="list-search"><span className="sr-only">현재 목록에서 검색</span><input type="search" value={keyword} onChange={e=>setKeyword(e.target.value)} placeholder="현재 목록에서 검색"/></label>
   <label className="list-region"><span>지역</span><select aria-label="현재 목록 지역" value={region} onChange={e=>setRegion(e.target.value)}><option value="">전체 지역</option>{regions.map(r=><option key={r} value={r}>{r}</option>)}</select></label>
   {!jobs && <label className="list-region"><span>수강 방식</span><select aria-label="현재 목록 수강 방식" value={extra} onChange={e=>setExtra(e.target.value)}><option value="">전체 방식</option><option value="online">온라인</option><option value="offline">오프라인</option><option value="unknown">미확인</option></select></label>}
   {(keyword || region || extra) && <button type="button" className="quiet" onClick={()=>{setKeyword('');setRegion('');setExtra('');}}>필터 초기화</button>}
  </div>
  <div className="browse-heading"><h1>{'탐색 가능한'} {jobs?'공고':'교육'} <em>{initialLoading?'불러오는 중':typeof results.total==='number'?results.total.toLocaleString()+(jobs?'건':'회차'):'전체 건수 미집계'}</em></h1>
   <p>{initialLoading?'잠시만 기다려 주세요. 목록을 준비하고 있어요.':jobs?'현재 '+results.items.length+'개를 불러왔습니다. AI에게 조건을 말하면 전체 검색 대상에서 좁혀집니다.':'전체 건수는 검색 대상 회차 수이며, 현재 '+results.items.length+'개 과정 카드를 불러왔습니다. 같은 과정의 여러 회차는 한 카드로 묶습니다.'} 현재 모집 여부는 원문에서 확인해 주세요.</p>
  </div>
  </>}
  {jobs && results.summary && <section className="source" aria-label="현재 적용한 검색 조건"><strong>현재 적용한 조건</strong>{results.summary.filters?.length?<ul>{results.summary.filters.map(t=><li key={t}>{t}</li>)}</ul>:<p>지역·직무·필수 기술 제한 없음</p>}{results.summary.ranking?.length>0 && <p>관련성 순위: {results.summary.ranking.join(' · ')}</p>}</section>}
  {jobs && results.continuation && <p className="fine">앞서 본 공고를 제외한 남은 후보 수입니다.</p>}
  {initialLoading ? <section className="browse-initial-loading" role="status" aria-label="목록 불러오는 중"><div className="loading-caption"><span className="loading-dot"/><strong>{jobs?'공고':'교육'}를 불러오고 있어요</strong><p>목록이 준비되면 이곳에 표시됩니다.</p></div><div className="browse-card-grid" aria-hidden="true">{Array.from({length:6},(_,i)=><div className="explore-card skeleton-card" key={i}><div className="skeleton-brand"><span className="skeleton-avatar"/><div><span className="skeleton-line short"/><span className="skeleton-line tiny"/></div></div><span className="skeleton-line"/><span className="skeleton-line"/><span className="skeleton-line short"/><div className="skeleton-footer"/></div>)}</div></section> : !results.items.length ? <section className="browse-empty"><span className="browse-empty-symbol">⌕</span><h2>{jobs?'현재 조건에서 표시할 공고가 없습니다':'상담창에서 원하는 조건을 알려주세요'}</h2><p>{jobs?'관심 직무·기술·지역으로 공고를 찾아보세요.':'배우고 싶은 분야와 필요한 조건으로 교육을 찾아보세요.'}</p><button type="button" className="source-link" onClick={onChat}>상담창 열기 →</button></section> :
   !filtered.length ? <section className="browse-empty"><h2>현재 목록에 맞는 항목이 없어요</h2><p>필터를 바꾸거나 상담창에서 새로운 검색을 시작해 주세요.</p></section> :
   <section className="browse-card-grid" aria-label="최근 검색 결과">{visible.map(item=>{
    const key=`${item.source || 'jumpit'}:${item.source_id}`,name=jobs?item.company_name:item.provider_name;
    return <article className="explore-card" key={key}>
     <button type="button" className="browse-result" aria-pressed={selected===key} onClick={()=>{setSelected(key);onRead?.(item);}}>
      <div className="explore-card-brand"><CompanyBadge name={name}/><div><span className="explore-company">{name}</span><small>{regionOf(item) || '지역 미확인'}{!jobs?' · '+(item.delivery_mode==='online'?'온라인':item.delivery_mode==='offline'?'오프라인':'방식 미확인'):''}</small></div></div>
      <h2>{item.title}</h2><p className="explore-card-description">{jobs?(item.tech_stacks || []).slice(0,7).join(' · ') || '상세 조건은 원문에서 확인해 주세요.':item.curriculum || (item.source==='goyong24_training'?'API 자료에 상세 교육 내용이 없습니다. 고용24 원문에서 확인해 주세요.':'세부 커리큘럼은 교육 원문에서 확인해 주세요.')}</p>
     </button>
     <div className="explore-card-footer"><a className="original-button" href={safeSourceUrl(item.source_url)} target="_blank" rel="noopener noreferrer">{jobs?'모집 원문 확인 ↗':'교육 원문 ↗'}</a><button type="button" aria-label={isSaved(item)?'스크랩 해제':'스크랩 저장'} aria-pressed={isSaved(item)} onClick={()=>onSave?.(item)}>{isSaved(item)?'♥ 저장됨':'♡ 스크랩'}</button></div>
    </article>;
   })}</section>}
  {!personal && !initialLoading && <div className="browse-pagination"><button type="button" className="quiet" disabled={busy} onClick={()=>{setKeyword('');setRegion('');setExtra('');onReset?.();}}>전체 {jobs?'공고':'교육'}로 초기화</button><small>필터는 불러온 목록에 적용됩니다. 전체 데이터 검색은 AI 상담을 이용하세요.</small></div>}
  {!personal && <div ref={scrollSentinel} className="browse-scroll-sentinel" aria-hidden="true"/>}
  {!personal && results.hasMore && <p className="fine" role="status">{busy?'목록을 더 불러오고 있어요…':'아래로 스크롤하면 더 불러옵니다'}</p>}
  {loadError && <div role="alert"><p>다음 목록을 불러오지 못했습니다.</p><button disabled={busy} onClick={onRetry}>다시 불러오기</button></div>}
  {active && current && <button className="detail-backdrop" aria-label="빈 공간을 눌러 상세 닫기" onClick={()=>setSelected(null)}/>}
  {active && current && <section className="browse-detail" role="dialog" aria-modal="false" aria-label="선택한 항목 정보">
   <header className="detail-header"><strong>{jobs?'공고 상세':'교육 상세'}</strong><button type="button" className="detail-close" onClick={()=>setSelected(null)} aria-label="상세 닫기">×</button></header>
   <CompanyBadge name={jobs?current.company_name:current.provider_name}/><p className="muted">{jobs?current.company_name:current.provider_name}</p><h2>{current.title}</h2>
   <p>{(current.addresses || []).join(' · ') || '지역 미확인'}</p>
   {jobs?<><div className="tags">{(current.tech_stacks || []).map(skill=><span key={skill}>{skill}</span>)}</div><p className="fine">검색 요약을 보고 있습니다. 상세 지원조건은 공고 원문에서 확인해 주세요. 읽기만으로 역량 문답이 시작되지는 않습니다.</p></>:<><TrainingStatus course={current}/>{detailError && <p role="alert">{detailError}</p>}{busy && !trainingDetail && <p role="status">상세 내용을 불러오고 있어요…</p>}{!trainingDetail && current.curriculum&&<><h3>교육 내용</h3><p className="training-detail-text">{current.curriculum}</p></>}{!trainingDetail && current.eligibility&&<><h3>지원 대상</h3><p className="training-detail-text">{current.eligibility}</p></>}{!trainingDetail && current.cost_description&&<><h3>비용 안내</h3><p>{current.cost_description}</p></>}{current.cohorts?.length?<TrainingCohorts course={current}/>:<p>상세 일정은 원문에서 확인해 주세요.</p>}{current.warning&&<p className="fine">{current.warning}</p>}</>}
   {!jobs && trainingDetail && <div className="job-detail-sections">{[['curriculum','교육 내용'],['eligibility','지원 대상·자격'],['preferred_conditions','우대 대상'],['benefits','지원 혜택'],['selection_process','선발 절차'],['application_notes','신청 유의사항'],['cost_description','비용 안내']].map(([field,label])=><section key={field}><h3>{label}</h3><p>{trainingDetail[field] || (field==='curriculum' && current.source==='goyong24_training'?'현재 연동된 API 자료에는 상세 교육 내용이 포함되어 있지 않습니다. 자세한 커리큘럼과 신청 조건은 고용24 원문 또는 교육기관에서 확인해 주세요.':'현재 연동된 자료에 해당 정보가 없습니다. 자세한 내용은 원문 또는 교육기관에서 확인해 주세요.')}</p></section>)}<p className="fine">선택한 회차의 저장 원문입니다. 다른 회차의 비용과 자격 조건은 해당 원문에서 확인해 주세요.</p></div>}
   {jobs && <div className="job-detail-sections">{detailError && <p role="alert">{detailError}</p>}{!details[current.source_id] && !detailError && <p role="status">{busy?'상세 내용을 불러오고 있어요…':'공고를 다시 선택해 상세 내용을 불러오세요.'}</p>}{[['responsibilities','주요업무'],['qualifications','자격요건'],['preferred_requirements','우대사항'],['benefits','복지·혜택'],['hiring_process','채용절차'],['application_notes','지원 유의사항'],['service_info','서비스 소개']].map(([field,label])=>details[current.source_id]?.[field] && <section key={field}><h3>{label}</h3><p>{details[current.source_id][field]}</p></section>)}<p className="fine">저장된 원문 기준입니다. 현재 모집 여부와 최신 조건은 원문에서 확인해 주세요.</p></div>}
   <div className="browse-actions"><button type="button" aria-pressed={isSaved(current)} onClick={()=>onSave?.(current)}>{isSaved(current)?'♥ 스크랩 해제':'♡ 스크랩 저장'}</button><a className="source-link" href={safeSourceUrl(current.source_url)} target="_blank" rel="noopener noreferrer">원본보기 ↗</a>{jobs ? onAssess && <button type="button" disabled={busy} onClick={()=>{onAssess(current);setSelected(null);}}>내 역량 확인하기</button> : onExplain && <button type="button" disabled={busy} onClick={()=>{onExplain(current);setSelected(null);}}>이 교육 설명해줘</button>}</div>
  </section>}
 </main>;
}
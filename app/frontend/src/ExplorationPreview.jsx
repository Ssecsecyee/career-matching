import React, {useEffect,useRef,useState} from 'react';
import {safeSourceUrl} from './api.js';
import {TrainingStatus} from './TrainingStatus.jsx';
import {TrainingCohorts} from './TrainingCohorts.jsx';
import {CompanyBadge} from './CompanyBadge.jsx';

function regionOf(item){return (item.addresses || [])[0]?.trim().split(/\s+/)[0] || '';}
function hostOf(url){try{return new URL(url).hostname;}catch{return '원문 보기';}}
export function ExplorationPreview({target,results,busy=false,onExplain,onAssess,onNext,onReset,active=true,details={},detailError='',onRead}) {
 const [selected,setSelected]=useState(null),[keyword,setKeyword]=useState(''),[region,setRegion]=useState('');
 const jobs=target==='jobs';
 const sentinel=useRef(null);
 useEffect(()=>{
   if(!active || !jobs || busy || !results.hasMore || keyword || region || !onNext || typeof IntersectionObserver==='undefined')return;
   const observer=new IntersectionObserver(entries=>{if(entries.some(e=>e.isIntersecting)){observer.disconnect();onNext();}},{rootMargin:'0px 0px 200px 0px'});
   if(sentinel.current)observer.observe(sentinel.current);
   return ()=>observer.disconnect();
 },[active,jobs,busy,results.items.length,results.hasMore,keyword,region,onNext]);
 const current=results.items.find(item=>`${item.source || 'jumpit'}:${item.source_id}`===selected);
 const regions=[...new Set(results.items.map(regionOf).filter(Boolean))];
 const filtered=results.items.filter(item=>(!region || regionOf(item)===region) &&
   (!keyword.trim() || [item.title,item.company_name,item.provider_name,...(item.tech_stacks || [])].filter(Boolean).join(' ').toLocaleLowerCase().includes(keyword.trim().toLocaleLowerCase())));
 return <main className="browse-page" aria-label={jobs?'채용공고 탐색':'교육과정 탐색'}>
  <div className="browse-toolbar"><label className="list-search"><span className="sr-only">현재 목록에서 검색</span><input type="search" value={keyword} onChange={e=>setKeyword(e.target.value)} placeholder="현재 목록에서 검색"/></label>
   <label className="list-region"><span>지역</span><select aria-label="현재 목록 지역" value={region} onChange={e=>setRegion(e.target.value)}><option value="">전체 지역</option>{regions.map(r=><option key={r} value={r}>{r}</option>)}</select></label>
   {(keyword || region) && <button type="button" className="quiet" onClick={()=>{setKeyword('');setRegion('');}}>필터 초기화</button>}
  </div>
  <div className="browse-heading"><h1>{jobs?'탐색 가능한':'최근 검색'} {jobs?'공고':'교육'} <em>{jobs?(results.total ?? filtered.length):filtered.length}개</em></h1>
   <p>{jobs?'현재 '+results.items.length+'개를 불러왔습니다. AI에게 조건을 말하면 전체 검색 대상에서 좁혀집니다.':'AI 검색에서 확인한 목록 '+results.items.length+'개 중 표시합니다.'} 현재 모집 여부는 원문에서 확인해 주세요.</p>
  </div>
  {jobs && results.summary && <section className="source" aria-label="현재 적용한 검색 조건"><strong>현재 적용한 조건</strong>{results.summary.filters?.length?<ul>{results.summary.filters.map(t=><li key={t}>{t}</li>)}</ul>:<p>지역·직무·필수 기술 제한 없음</p>}{results.summary.ranking?.length>0 && <p>관련성 순위: {results.summary.ranking.join(' · ')}</p>}</section>}
  {jobs && results.continuation && <p className="fine">앞서 본 공고를 제외한 남은 후보 수입니다.</p>}
  {!results.items.length ? <section className="browse-empty"><span className="browse-empty-symbol">⌕</span><h2>{jobs?'현재 조건에서 표시할 공고가 없습니다':'왼쪽 AI에게 원하는 조건을 알려주세요'}</h2><p>{jobs?'관심 직무·기술·지역으로 공고를 찾아보세요.':'배우고 싶은 분야와 필요한 조건으로 교육을 찾아보세요.'}</p><a href="#chat" className="source-link">AI 상담으로 시작하기 →</a></section> :
   !filtered.length ? <section className="browse-empty"><h2>현재 목록에 맞는 항목이 없어요</h2><p>필터를 바꾸거나 왼쪽 AI에서 새로운 검색을 시작해 주세요.</p></section> :
   <section className="browse-card-grid" aria-label="최근 검색 결과">{filtered.map(item=>{
    const key=`${item.source || 'jumpit'}:${item.source_id}`,name=jobs?item.company_name:item.provider_name;
    return <article className="explore-card" key={key}>
     <button type="button" className="browse-result" aria-pressed={selected===key} onClick={()=>{setSelected(key);if(jobs)onRead?.(item);}}>
      <div className="explore-card-brand"><CompanyBadge name={name}/><div><span className="explore-company">{name}</span><small>{regionOf(item) || '지역 미확인'}{!jobs?' · '+(item.delivery_mode==='online'?'온라인':item.delivery_mode==='offline'?'오프라인':'방식 미확인'):''}</small></div></div>
      <h2>{item.title}</h2><p className="explore-card-description">{jobs?(item.tech_stacks || []).slice(0,7).join(' · ') || '상세 조건은 원문에서 확인해 주세요.':item.curriculum || '세부 커리큘럼은 교육 원문에서 확인해 주세요.'}</p>
     </button>
     <div className="explore-card-footer"><a href={safeSourceUrl(item.source_url)} target="_blank" rel="noopener noreferrer">↗ {hostOf(item.source_url)}</a><span>{jobs?'모집 원문 확인':item.schedule_label || '일정 미확인'}</span></div>
    </article>;
   })}</section>}
  {jobs && <div className="browse-pagination"><button type="button" className="quiet" disabled={busy} onClick={()=>{setKeyword('');setRegion('');onReset?.();}}>전체 공고로 초기화</button>{results.hasMore && <button type="button" disabled={busy} onClick={()=>{setSelected(null);setKeyword('');setRegion('');onNext?.();}}>다음 공고 보기 →</button>}<small>입력창·지역 필터는 현재 페이지에만 적용됩니다. 전체 검색은 AI 상담을 이용하세요.</small></div>}
  {jobs && <div ref={sentinel} className="browse-load-status" role="status">{busy?'공고를 불러오고 있어요…':results.hasMore?'아래로 스크롤하면 더 불러옵니다':'현재 조건의 목록을 모두 확인했습니다'}</div>}
  {current && <section className="browse-detail" role="dialog" aria-modal="false" aria-label="선택한 항목 정보">
   <button type="button" className="detail-close" onClick={()=>setSelected(null)} aria-label="상세 닫기">×</button>
   <CompanyBadge name={jobs?current.company_name:current.provider_name}/><p className="muted">{jobs?current.company_name:current.provider_name}</p><h2>{current.title}</h2>
   <p>{(current.addresses || []).join(' · ') || '지역 미확인'}</p>
   {jobs?<><div className="tags">{(current.tech_stacks || []).map(skill=><span key={skill}>{skill}</span>)}</div><p className="fine">검색 요약을 보고 있습니다. 상세 지원조건은 공고 원문에서 확인해 주세요. 읽기만으로 역량 문답이 시작되지는 않습니다.</p></>:<><TrainingStatus course={current}/>{current.curriculum&&<p>{current.curriculum}</p>}{current.cohorts?.length?<TrainingCohorts course={current}/>:<p>상세 일정은 원문에서 확인해 주세요.</p>}{current.warning&&<p className="fine">{current.warning}</p>}</>}
   {jobs && <div className="job-detail-sections">{detailError && <p role="alert">{detailError}</p>}{!details[current.source_id] && !detailError && <p role="status">{busy?'상세 내용을 불러오고 있어요…':'공고를 다시 선택해 상세 내용을 불러오세요.'}</p>}{[['responsibilities','주요업무'],['qualifications','자격요건'],['preferred_requirements','우대사항'],['benefits','복지·혜택'],['hiring_process','채용절차'],['application_notes','지원 유의사항'],['service_info','서비스 소개']].map(([field,label])=>details[current.source_id]?.[field] && <section key={field}><h3>{label}</h3><p>{details[current.source_id][field]}</p></section>)}<p className="fine">저장된 원문 기준입니다. 현재 모집 여부와 최신 조건은 원문에서 확인해 주세요.</p></div>}
   <div className="browse-actions">{jobs ? onAssess && <button type="button" disabled={busy} onClick={()=>{onAssess(current);setSelected(null);}}>지원조건 확인하기</button> : onExplain && <button type="button" disabled={busy} onClick={()=>{onExplain(current);setSelected(null);}}>이 교육 설명해줘</button>}<a className="source-link" href={safeSourceUrl(current.source_url)} target="_blank" rel="noopener noreferrer">{jobs?'공고':'교육'} 원문 보기 ↗</a><a className="source-link" href="#chat">AI 상담에서 이어가기 →</a></div>
  </section>}
 </main>;
}

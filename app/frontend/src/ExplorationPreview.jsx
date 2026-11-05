import React, {useState} from 'react';
import {safeSourceUrl} from './api.js';
import {TrainingStatus} from './TrainingStatus.jsx';
import {TrainingCohorts} from './TrainingCohorts.jsx';

export function ExplorationPreview({target,results}) {
  const [selected,setSelected]=useState(null);
  const jobs=target==='jobs';
  const current=results.items.find(item=>`${item.source || 'jumpit'}:${item.source_id}`===selected);
  return <main className="browse-page" aria-label={jobs?'채용공고 탐색':'교육과정 탐색'}>
    <div className="browse-heading"><span className="pill">최근 검색 목록</span>
      <h1>{jobs?'관심 있는 공고를 살펴보세요':'배울 수 있는 과정을 살펴보세요'}</h1>
      <p>AI 상담에서 검색하고 확인한 최근 목록입니다. 목록을 눌러 정보를 살펴보세요.</p>
      <a href="#chat" className="source-link">AI 상담에서 검색하기 →</a>
    </div>
    {!results.items.length ? <section className="browse-empty"><h2>아직 표시할 {jobs?'공고':'교육'}가 없어요</h2>
      <p>AI 상담에서 원하는 조건으로 검색한 뒤, 결과 목록을 확인해 주세요.</p></section> :
    <div className="browse-columns"><section className="browse-list" aria-label="최근 검색 결과">
      <p className="fine">표시된 {jobs?'공고':'과정'} {results.items.length}개 · 현재 모집 여부는 원문에서 확인해 주세요.</p>
      {results.items.map(item=>{
        const key=`${item.source || 'jumpit'}:${item.source_id}`;
        return <button type="button" key={key} className="browse-result" aria-pressed={selected===key} onClick={()=>setSelected(key)}>
          <span>{jobs?item.company_name:item.provider_name}</span><strong>{item.title}</strong>
          <small>{(item.addresses || []).join(' · ') || '지역 미확인'}</small>
        </button>;
      })}
    </section><section className="browse-detail" aria-label="선택한 항목 정보">
      {!current ? <div className="browse-empty"><h2>목록에서 하나를 선택해 주세요</h2><p>항목을 읽는 것만으로 역량 문답이 시작되지는 않습니다.</p></div> : <>
        <p className="muted">{jobs?current.company_name:current.provider_name}</p><h2>{current.title}</h2>
        <p>{(current.addresses || []).join(' · ') || '지역 미확인'}</p>
        {jobs ? <><div className="tags">{(current.tech_stacks || []).map(skill=><span key={skill}>{skill}</span>)}</div>
          <p className="fine">현재 저장된 검색 요약입니다. 상세 지원조건은 공고 원문에서 확인할 수 있습니다.</p></> : <>
          <TrainingStatus course={current}/>{current.curriculum && <p>{current.curriculum}</p>}
          {current.cohorts?.length ? <TrainingCohorts course={current}/> : <p>상세 일정은 교육 원문에서 확인해 주세요.</p>}
          {current.warning && <p className="fine">{current.warning}</p>}</>}
        <div className="browse-actions"><a className="source-link" href={safeSourceUrl(current.source_url)} target="_blank" rel="noopener noreferrer">{jobs?'공고':'교육'} 원문 보기 ↗</a>
          <a className="source-link" href="#chat">상담으로 돌아가기 →</a></div>
      </>}
    </section></div>}
  </main>;
}

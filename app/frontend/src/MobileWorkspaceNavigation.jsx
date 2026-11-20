import React from 'react';

function Icon({kind}) {
  return <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{kind==='chat'?<path d="M5 4h14a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H9l-6 4V6a2 2 0 0 1 2-2Z"/>:kind==='results'?<><rect x="4" y="3" width="16" height="18" rx="3"/><path d="M8 8h8M8 12h8M8 16h5"/></>:<><circle cx="12" cy="8" r="4"/><path d="M4 21v-2a8 8 0 0 1 16 0v2"/></>}</svg>;
}

export function MobileWorkspaceNavigation({screen,onChange}) {
  return <nav className="mobile-workspace-nav" aria-label="모바일 화면 전환">
    {[['chat','상담'],['results','검색 결과'],['my','내 페이지']].map(([id,label])=><button key={id} type="button" aria-label={label+' 보기'} aria-current={screen===id?'page':undefined} onClick={()=>onChange(id)}><Icon kind={id}/><span>{label}</span></button>)}
  </nav>;
}

export function MobileResultTabs({target,onChange,onHelp}) {
  return <div className="mobile-results-heading"><div><span className="fine">찾은 결과를 살펴보세요</span><strong>검색 결과</strong>{onHelp&&<button className="guide-launch-compact" type="button" onClick={onHelp}>사용 방법</button>}</div><div role="group" aria-label="모바일 검색 결과 종류"><button type="button" aria-pressed={target==='jobs'} onClick={()=>onChange('jobs')}>공고</button><button type="button" aria-pressed={target==='training'} onClick={()=>onChange('training')}>교육</button></div></div>;
}

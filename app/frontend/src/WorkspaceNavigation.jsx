import React from 'react';
export function WorkspaceNavigation({page}) {
  return <nav className="workspace-tabs" aria-label="서비스 메뉴">
    {[['jobs','공고'],['training','교육'],...(page==='chat'?[['chat','AI 상담']]:[])].map(([id,label])=>
      <a key={id} href={`#${id}`} aria-current={page===id?'page':undefined}>{label}</a>)}
  </nav>;
}

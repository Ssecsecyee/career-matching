import React,{useEffect,useLayoutEffect,useRef,useState,useId} from 'react';
import {createPortal} from 'react-dom';
import {placeGuide} from './workspaceGuide.js';
const steps=[
 {title:'CAPI바라에게 물어보세요',description:'원하는 직무나 보유 기술을 말씀해 주세요. 공고·교육 탐색과 준비 방향을 함께 찾아드립니다.'},
 {title:'직접 검색하고 조건을 골라보세요',description:'검색창에 직무·회사·기술을 입력하거나 카테고리로 공고를 좁힐 수 있습니다. 교육은 배우고 싶은 분야나 과정명으로 검색하세요.'},
 {title:'결과를 확인하고 화면을 이동하세요',description:'공고·교육 메뉴를 전환하고 아래 목록에서 상세 내용을 확인하세요. 공고의 ‘내 역량 확인하기’로 문답을 시작하고, 내 페이지에서 최근 본 항목과 스크랩을 볼 수 있습니다.'}
];
export function WorkspaceGuide({step,mobile,onStep,onClose}){
 const card=useRef(null),next=useRef(null),[layout,setLayout]=useState(null),id=useId().replace(/:/g,'');
 useEffect(()=>{const app=document.querySelector('.app'),previous=document.activeElement,wasInert=app?.inert;
  if(app)app.inert=true;
  const key=e=>{if(e.key==='Escape'){e.preventDefault();onClose();}else if(e.key==='Tab'){const buttons=[...card.current.querySelectorAll('button:not(:disabled)')];const first=buttons[0],last=buttons.at(-1);if(!card.current.contains(document.activeElement)){e.preventDefault();first?.focus();}else if(e.shiftKey&&document.activeElement===first){e.preventDefault();last.focus();}else if(!e.shiftKey&&document.activeElement===last){e.preventDefault();first.focus();}}};
  document.addEventListener('keydown',key,true);return()=>{if(app)app.inert=wasInert;document.removeEventListener('keydown',key,true);window.requestAnimationFrame(()=>{if(previous?.isConnected)previous.focus({preventScroll:true});});};
 },[]);
 useEffect(()=>{next.current?.focus({preventScroll:true});},[step]);
 useLayoutEffect(()=>{let frame=0;const observer=new window.ResizeObserver(schedule);
  function measure(){const vv=window.visualViewport,v={left:vv?.offsetLeft||0,top:vv?.offsetTop||0,width:vv?.width||window.innerWidth,height:vv?.height||window.innerHeight};
   const compact=mobile&&v.height<520&&v.width>600;
   const selectors=compact&&step===0?['.chat-view .copilot-heading strong','.chat-view button[aria-label="메시지 보내기"]']:compact&&step===1?['.catalog-panel:not([hidden]) .filter-trigger:first-child','.catalog-panel:not([hidden]) .catalog-query button[type=submit]']:step===0?['.chat-view .copilot-heading','.chat-view .composer']:step===1?['.catalog-panel:not([hidden]) .catalog-search']:mobile?['.mobile-results-heading','.mobile-workspace-nav']:['.workspace-tabs','.catalog-panel:not([hidden]) .browse-heading'];
   const rects=selectors.flatMap(selector=>{const el=document.querySelector(selector);if(!el||!el.getClientRects().length)return [];const r=el.getBoundingClientRect();if(r.width<=0||r.height<=0)return [];const left=Math.max(v.left+4,r.left-5),top=Math.max(v.top+4,r.top-5),right=Math.min(v.left+v.width-4,r.right+5),bottom=Math.min(v.top+v.height-4,r.bottom+5);return right>left&&bottom>top?[{left,top,right,bottom,width:right-left,height:bottom-top}]:[];});
   const box=card.current?.getBoundingClientRect();if(!box)return;const position=placeGuide(rects,box.width,box.height,v);setLayout({rects,position,v});
  }
  function schedule(){window.cancelAnimationFrame(frame);frame=window.requestAnimationFrame(measure);}
  observer.observe(card.current);const app=document.querySelector('.app');if(app)observer.observe(app);
  document.querySelectorAll('.catalog-search,.composer,.copilot-heading,.workspace-tabs,.mobile-results-heading,.mobile-workspace-nav').forEach(el=>observer.observe(el));
  window.addEventListener('resize',schedule);window.addEventListener('scroll',schedule,true);window.visualViewport?.addEventListener('resize',schedule);window.visualViewport?.addEventListener('scroll',schedule);schedule();
  return()=>{window.cancelAnimationFrame(frame);observer.disconnect();window.removeEventListener('resize',schedule);window.removeEventListener('scroll',schedule,true);window.visualViewport?.removeEventListener('resize',schedule);window.visualViewport?.removeEventListener('scroll',schedule);};
 },[step,mobile]);
 return createPortal(<div className="workspace-guide-layer">
  <svg className="workspace-guide-shade" width="100%" height="100%" aria-hidden="true"><defs><mask id={'guide-mask-'+id}><rect width="100%" height="100%" fill="white"/>{layout?.rects.map((r,i)=><rect key={i} x={r.left} y={r.top} width={r.width} height={r.height} rx="10" fill="black"/>)}</mask></defs><rect width="100%" height="100%" fill="#10233d" fillOpacity=".58" mask={`url(#guide-mask-${id})`}/></svg>
  {layout?.rects.map((r,i)=><div className="workspace-guide-ring" key={i} style={{left:r.left,top:r.top,width:r.width,height:r.height}}/>)}
  <section className="workspace-guide-card" role="dialog" aria-modal="true" aria-labelledby={'guide-title-'+id} aria-describedby={'guide-description-'+id} ref={card} style={{left:layout?.position.x??12,top:layout?.position.y??12,width:Math.min(360,(layout?.v.width||window.innerWidth)-24),maxHeight:Math.max(150,Math.min((layout?.v.height||window.innerHeight)-24,mobile&&(layout?.v.height||window.innerHeight)<520?230:430))}}>
   <div className="workspace-guide-meta"><span aria-live="polite">사용 방법 · {step+1} / 3</span><button type="button" onClick={onClose}>건너뛰기</button></div>
   <h2 id={'guide-title-'+id}>{steps[step].title}</h2><p id={'guide-description-'+id}>{steps[step].description}</p>
   <div className="workspace-guide-actions"><button type="button" disabled={step===0} onClick={()=>onStep(step-1)}>이전</button><button ref={next} type="button" className="guide-next" onClick={()=>step===2?onClose():onStep(step+1)}>{step===2?'시작하기':'확인·다음'}</button></div>
  </section>
 </div>,document.body);
}

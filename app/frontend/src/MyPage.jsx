import React,{useState} from 'react';
import {ExplorationPreview} from './ExplorationPreview.jsx';
import {emptyLibrary} from './personalLibrary.js';
export function MyPage({library,onChange,...browse}){
 const [tab,setTab]=useState('saved'),[target,setTarget]=useState('jobs');
 const items=library[tab].filter(x=>x.target===target);
 return <section className="my-page"><h1>내 페이지</h1><p className="fine">이 브라우저에 저장됩니다. 같은 브라우저 프로필을 쓰는 사람과 공유될 수 있으며 다른 기기와 동기화되지 않습니다.</p>
 <div className="personal-tabs"><button aria-pressed={tab==='recent'} onClick={()=>setTab('recent')}>최근 본 항목 ({library.recent.length})</button><button aria-pressed={tab==='saved'} onClick={()=>setTab('saved')}>스크랩 ({library.saved.length})</button><button onClick={()=>{if(window.confirm('이 브라우저의 최근 본 항목·스크랩을 모두 삭제할까요?'))onChange(emptyLibrary());}}>로컬 기록 전체 삭제</button></div>
 <div className="personal-tabs"><button aria-pressed={target==='jobs'} onClick={()=>setTarget('jobs')}>공고</button><button aria-pressed={target==='training'} onClick={()=>setTarget('training')}>교육</button></div>
 {!items.length?<p>아직 저장된 항목이 없습니다. 공고·교육을 열거나 하트 버튼을 눌러보세요.</p>:<ExplorationPreview key={target} {...browse} target={target} results={{items,total:items.length,hasMore:false}}/>}
 </section>;
}

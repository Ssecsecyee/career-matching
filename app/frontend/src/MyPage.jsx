import React,{useState} from 'react';
import {ExplorationPreview} from './ExplorationPreview.jsx';
import {emptyLibrary} from './personalLibrary.js';
export function MyPage({library,onChange,...browse}){
 const [tab,setTab]=useState('recent'),[target,setTarget]=useState('jobs'),[notice,setNotice]=useState('');
 const items=library[tab].filter(x=>x.target===target);
 async function importText(event){const file=event.target.files?.[0];if(!file)return;if(file.size>100000){setNotice('100KB 이하 텍스트 파일을 선택해 주세요.');return;}const text=await file.text();onChange({...library,resume:text.slice(0,1000),useResume:false});setNotice('첫 1,000자를 가져왔습니다. 내용을 확인하고 상담 참고 여부를 선택해 주세요.');event.target.value='';}
 return <section className="my-page"><h1>내 페이지</h1><p className="fine">이 브라우저에 저장됩니다. 같은 브라우저 프로필을 쓰는 사람과 공유될 수 있으며 다른 기기와 동기화되지 않습니다.</p>
 <section className="resume-editor"><h2>상담용 이력서</h2><p>핵심 경험·기술을 1,000자 이내로 저장하세요. 비밀번호·주민등록번호 등 민감정보는 제외해 주세요.</p><textarea aria-label="상담용 이력서" maxLength={1000} value={library.resume} onChange={e=>onChange({...library,resume:e.target.value})} placeholder="전공, 경력, 프로젝트, 사용 기술 등을 정리해 주세요."/><small>{library.resume.length} / 1,000자 · 변경 시 자동 저장</small><label>텍스트 파일 가져오기 <input type="file" accept=".txt,text/plain" onChange={importText}/></label><label><input type="checkbox" checked={library.useResume} onChange={e=>onChange({...library,useResume:e.target.checked})}/> 이후 상담 질문에 이력서 참고 자료를 함께 전달</label><p className="fine">선택한 경우 AWS의 대화 기록과 모델 입력에 포함됩니다. 체크 해제·로컬 삭제가 이미 보낸 대화 기록까지 지우지는 않습니다.</p>{notice&&<p role="status">{notice}</p>}<button onClick={()=>onChange({...library,resume:'',useResume:false})}>이력서 삭제</button></section>
 <div className="personal-tabs"><button aria-pressed={tab==='recent'} onClick={()=>setTab('recent')}>최근 본 항목 ({library.recent.length})</button><button aria-pressed={tab==='saved'} onClick={()=>setTab('saved')}>스크랩 ({library.saved.length})</button><button onClick={()=>{if(window.confirm('이 브라우저의 최근 본 항목·스크랩·이력서를 모두 삭제할까요?'))onChange(emptyLibrary());}}>로컬 기록 전체 삭제</button></div>
 <div className="personal-tabs"><button aria-pressed={target==='jobs'} onClick={()=>setTarget('jobs')}>공고</button><button aria-pressed={target==='training'} onClick={()=>setTarget('training')}>교육</button></div>
 {!items.length?<p>아직 저장된 항목이 없습니다. 공고·교육을 열거나 하트 버튼을 눌러보세요.</p>:<ExplorationPreview key={target} {...browse} target={target} results={{items,total:items.length,hasMore:false}}/>}
 </section>;
}

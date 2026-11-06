import React,{useState} from 'react';
const REGIONS=['서울','경기','인천','부산','대구','대전','광주','울산','세종','강원','충북','충남','전북','전남','경북','경남','제주'];
export function catalogRequest(target,value){
 if(target==='jobs')return {action:'search',values:{page_size:20,preserve_current:!value.keyword.trim(),search_plan:{keyword:value.keyword.trim(),text_field:value.field,region:value.region,skills:value.skills.split(',').map(x=>x.trim()).filter(Boolean),limit:20}}};
 return {action:'browse_training',values:{filters:{keyword:value.keyword.trim(),field:value.field,region:value.region,delivery_mode:value.mode,service:value.service}}};
}
export function CatalogSearch({target,busy,onSearch,onReset}){
 const empty=()=>({keyword:'',field:'all',region:'',skills:'',mode:'any',service:'any'});
 const [value,setValue]=useState(empty);
 const jobs=target==='jobs';const set=(key,event)=>setValue(old=>({...old,[key]:event.target.value}));
 const fields=jobs?[['all','전체 내용'],['title','공고 제목'],['company_name','회사명'],['responsibilities','주요업무'],['qualifications','자격요건'],['preferred_requirements','우대사항'],['tech_stacks','기술']]:[['all','전체 내용'],['title','교육 과정명'],['provider_name','교육기관'],['curriculum','교육내용'],['learning_topics','학습 주제'],['ncs_code','NCS 코드']];
 return <form className="catalog-search" aria-label={jobs?'공고 직접 검색':'교육 직접 검색'} onSubmit={e=>{e.preventDefault();onSearch(catalogRequest(target,value));}}>
 <div className="catalog-query"><select aria-label="검색 컬럼" value={value.field} onChange={e=>set('field',e)}>{fields.map(([id,label])=><option key={id} value={id}>{label}</option>)}</select><input type="search" aria-label="전체 데이터 검색어" value={value.keyword} onChange={e=>set('keyword',e)} maxLength={120} placeholder={jobs?'제목·회사·자격요건 등으로 검색':'과정명·기관·NCS 코드 등으로 검색'}/><button type="submit" disabled={busy}>{busy?'조회 중…':'검색'}</button></div>
 <div className="catalog-options"><label>지역<select aria-label="지역" value={value.region} onChange={e=>set('region',e)}><option value="">전국</option>{REGIONS.map(r=><option key={r} value={r}>{r}</option>)}</select></label>
 {jobs?<label>필수 기술<input aria-label="필수 기술" value={value.skills} onChange={e=>set('skills',e)} maxLength={300} placeholder="쉼표로 구분 · 모두 포함"/></label>:<><label>수강 방식<select aria-label="수강 방식" value={value.mode} onChange={e=>set('mode',e)}><option value="any">전체</option><option value="online">온라인</option><option value="offline">오프라인</option><option value="unknown">미확인</option></select></label><label>훈련 종류<select aria-label="훈련 종류" value={value.service} onChange={e=>set('service',e)}>{[['any','전체'],['card','내일배움카드'],['employer','사업주훈련'],['consortium','컨소시엄'],['work_study','일학습병행'],['boottent','부트캠프 참고자료']].map(([id,label])=><option key={id} value={id}>{label}</option>)}</select></label></>}
 <button type="button" disabled={busy} onClick={()=>{setValue(empty());onReset?.();}}>초기화</button></div>
 <p className="fine">검색어 없이 필터를 적용하면 현재 검색 조건을 유지합니다. 전체 검색은 초기화를 누르세요. AI를 호출하지 않습니다.</p></form>;
}

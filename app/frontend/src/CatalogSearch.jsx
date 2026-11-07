import React,{useState,useEffect} from 'react';
import {categoryValues,categoryRequest} from './categoryState.js';
const REGIONS=['서울','경기','인천','부산','대구','대전','광주','울산','세종','강원','충북','충남','전북','전남','경북','경남','제주'];
const ROLES=['프론트엔드','백엔드','풀스택','데이터 엔지니어','데이터 분석','AI','인프라','보안','모바일','임베디드','QA'];
export function catalogRequest(target,value){
 if(target==='jobs')return {action:'search',values:{page_size:20,preserve_current:!value.keyword.trim(),search_plan:{keyword:value.keyword.trim(),text_field:value.field,region:value.region,skills:value.skills.split(',').map(x=>x.trim()).filter(Boolean),limit:20}}};
 return {action:'browse_training',values:{filters:{keyword:value.keyword.trim(),field:'all',region:'',delivery_mode:'any',service:'any'}}};
}

export function CatalogSearch({target,busy,onSearch,onReset,currentPlan,items=[]}){
 const jobs=target==='jobs';
 const [value,setValue]=useState(()=>categoryValues(currentPlan)),[open,setOpen]=useState(null),[tag,setTag]=useState('');
 const signature=JSON.stringify(currentPlan || null);
 useEffect(()=>{if(jobs)setValue(categoryValues(currentPlan));},[signature,jobs]);
 const toggle=(key,item)=>setValue(v=>({...v,[key]:v[key].includes(item)?v[key].filter(x=>x!==item):v[key].length<10?[...v[key],item]:v[key]}));
 const submit=(next=value)=>{setOpen(null);onSearch(jobs?categoryRequest(next,currentPlan):catalogRequest(target,{keyword:next.keyword}));};
 const clear=()=>{const next=categoryValues(null);setValue(next);setOpen(null);onReset?.();};
 if(!jobs)return <form className="catalog-search education-query-only" aria-label="교육 직접 검색" onSubmit={e=>{e.preventDefault();submit();}}>
 <div className="catalog-query"><input type="search" aria-label="전체 데이터 검색어" value={value.keyword} onChange={e=>setValue(v=>({...v,keyword:e.target.value}))} maxLength={120} placeholder="배우고 싶은 분야·과정명·교육기관으로 검색"/><button type="submit" disabled={busy}>{busy?'조회 중…':'검색'}</button><button type="button" disabled={busy} onClick={clear}>초기화</button></div>
 <p className="fine">전체 교육 자료를 검색합니다. AI를 호출하지 않습니다.</p></form>;
 const tags=[...new Set(items.flatMap(i=>i.tech_stacks || []))].sort((a,b)=>a.localeCompare(b)).slice(0,60);
 const groups=[['roles','직무',value.roles.length],['regions','지역',value.regions.length],['entry','신입 조건',value.entry?1:0],['skills','기술',value.skills.length]];
 const remove=(key,item)=>{const next={...value,[key]:key==='entry'?false:value[key].filter(x=>x!==item)};setValue(next);submit(next);};
 const chips=[...value.roles.map(x=>['roles',x]),...value.regions.map(x=>['regions',x]),...(value.entry?[['entry','신입 지원 가능']]:[]),...value.skills.map(x=>['skills',x])];
 return <form className="catalog-search job-category-search" aria-label="공고 직접 검색" onSubmit={e=>{e.preventDefault();submit();}}>
 <div className="category-main-query"><span aria-hidden="true">⌕</span><input type="search" aria-label="전체 데이터 검색어" value={value.keyword} onChange={e=>setValue(v=>({...v,keyword:e.target.value}))} maxLength={120} placeholder="직무, 회사, 기술로 원하는 공고를 찾아보세요"/><button className="category-submit" disabled={busy} type="submit">{busy?'검색 중…':'검색'}</button></div>
 <div className="category-toolbar" aria-label="채용공고 카테고리">{groups.map(([id,label,n])=><button className={open===id?'filter-trigger expanded':n?'filter-trigger selected':'filter-trigger'} type="button" aria-expanded={open===id} key={id} onClick={()=>setOpen(open===id?null:id)}>{label}{n>0&&<b>{n}</b>}<span aria-hidden="true">{open===id?'⌃':'⌄'}</span></button>)}<button className="category-reset" type="button" disabled={busy} onClick={clear}>전체 초기화</button></div>
 {open&&<section className="category-panel" aria-label={groups.find(g=>g[0]===open)[1]+' 선택'}>
 <div className="category-panel-heading"><strong>{open==='roles'?'어떤 일을 찾고 있나요?':open==='regions'?'어디에서 일하고 싶나요?':open==='entry'?'신입 지원 가능 공고': '공고에서 요구하는 기술'}</strong><button type="button" className="category-dismiss" onClick={()=>setOpen(null)} aria-label="필터 닫기">×</button></div>
 <p className="category-help">{open==='skills'?'실제 공고의 기술 태그입니다. 여러 기술은 모두 포함하는 조건입니다.':open==='entry'?'원문에 신입 지원 가능 또는 경력무관이 확인된 공고만 표시합니다. 미확인 정보는 제외됩니다.':'같은 카테고리는 하나 이상, 다른 카테고리와는 함께 적용합니다.'}</p>
 <div className="category-option-grid">{open==='entry'?<><button type="button" aria-pressed={!value.entry} onClick={()=>setValue(v=>({...v,entry:false}))}>전체 경력</button><button type="button" aria-pressed={value.entry} onClick={()=>setValue(v=>({...v,entry:true}))}>신입 지원 가능</button></>:(open==='roles'?ROLES:open==='regions'?REGIONS:tags).map(item=><button type="button" key={item} aria-pressed={value[open].includes(item)} onClick={()=>toggle(open,item)}>{item}{value[open].includes(item)&&<span aria-hidden="true"> ✓</span>}</button>)}</div>
 {open==='skills'&&<div className="category-custom-tag"><input aria-label="기술 태그 추가" value={tag} maxLength={80} placeholder="다른 기술 입력" onChange={e=>setTag(e.target.value)} onKeyDown={e=>{if(e.key==='Enter'){e.preventDefault();if(tag.trim()&&!value.skills.includes(tag.trim()))toggle('skills',tag.trim());setTag('');}}}/><button type="button" onClick={()=>{if(tag.trim()&&!value.skills.includes(tag.trim()))toggle('skills',tag.trim());setTag('');}}>추가</button></div>}
 <div className="category-panel-footer"><span>{open==='entry'?(value.entry?'신입 조건 선택':'전체 경력'):`${value[open].length}개 선택`}</span><button className="category-submit" type="button" disabled={busy} onClick={()=>submit()}>선택 적용</button></div></section>}
 {chips.length>0&&<div className="category-chips" aria-label="선택한 검색 조건">{chips.map(([key,item])=><button key={key+item} type="button" disabled={busy} onClick={()=>remove(key,item)} aria-label={item+' 조건 해제'}>{item}<span aria-hidden="true">×</span></button>)}</div>}
 <p className="category-footnote">저장된 공고를 직접 검색합니다. 카테고리 검색에는 AI 호출이 발생하지 않습니다.</p></form>;
}

import assert from 'node:assert/strict';
import test from 'node:test';
import {fileURLToPath} from 'node:url';
import {build} from 'esbuild';
import {Window} from 'happy-dom';
import React,{act} from 'react';
test('actual tab changes preserve conversation draft and list selection without requests',async()=>{
 const window=new Window({url:'http://localhost/#chat'});
 for(const key of ['window','document','navigator','HTMLElement','HTMLInputElement','HTMLTextAreaElement','Event','MouseEvent'])Object.defineProperty(globalThis,key,{value:window[key] || window,configurable:true,writable:true});
 globalThis.IS_REACT_ACT_ENVIRONMENT=true;window.HTMLElement.prototype.scrollIntoView=function(){};
 let requests=0;globalThis.fetch=async(url,options)=>options?.body && JSON.parse(options.body).action==='browse_training'?{ok:true,status:200,json:async()=>({stage:'conversation',cached:true,learning_search:{status:'found'},learning_opportunities:[],training_has_more:false})}:options?.body && JSON.parse(options.body).action==='view_job'?{ok:true,status:200,json:async()=>({stage:'job_detail',job_detail:{source_id:'42',responsibilities:'Build software',qualifications:'React experience'}})}:url==='/deploy-config.json'?{ok:true,json:async()=>({apiEnabled:true})}:(requests++,{ok:true,status:200,json:async()=>({stage:'choose_job',cached:true,session_id:'11111111-1111-4111-8111-111111111111',total:2,candidate_jobs:[{source:'jumpit',source_id:'42',title:'Synthetic developer',company_name:'Synthetic company',addresses:['서울 강남구'],tech_stacks:['React'],source_url:'https://example.com/job'},{source:'jumpit',source_id:'43',title:'Python developer',company_name:'Other company',addresses:['부산 해운대구'],tech_stacks:['Python'],source_url:'https://example.com/other'}]})});
 const {createRoot}=await import('react-dom/client');
 const built=await build({entryPoints:[fileURLToPath(new URL('./AppRouter.jsx',import.meta.url))],bundle:true,write:false,format:'esm',platform:'browser',define:{'process.env.NODE_ENV':'"development"'},plugins:[{name:'shared-react',setup(b){b.onResolve({filter:/^(react|react-dom)(\/.*)?$/},a=>({path:import.meta.resolve(a.path),external:true}));}}]});
 const {AppRouter}=await import('data:text/javascript;base64,'+Buffer.from(built.outputFiles[0].text).toString('base64'));
 const container=document.createElement('div');document.body.append(container);const root=createRoot(container);
 const change=async hash=>act(async()=>{window.location.hash=hash;window.dispatchEvent(new window.Event('hashchange'));});
 const fill=async(el,value)=>act(async()=>{const proto=el.tagName==='INPUT'?window.HTMLInputElement.prototype:window.HTMLTextAreaElement.prototype;Object.getOwnPropertyDescriptor(proto,'value').set.call(el,value);el.dispatchEvent(new window.Event('input',{bubbles:true}));el.dispatchEvent(new window.Event('change',{bubbles:true}));});
 const submit=async form=>act(async()=>{form.dispatchEvent(new window.Event('submit',{bubbles:true,cancelable:true}));});
 try{
 await act(async()=>{root.render(React.createElement(AppRouter));});
 await fill(container.querySelector('#access-code'),'x'.repeat(32));await submit(container.querySelector('form'));
 const textarea=container.querySelector('#message');assert.ok(textarea);await fill(textarea,'React jobs');await submit(textarea.closest('form'));
 assert.equal(requests,2);assert.match(container.textContent,/Synthetic developer/);
 await fill(textarea,'Keep my draft');await change('#jobs');assert.equal(container.querySelector('#message'),textarea);assert.equal(textarea.value,'Keep my draft');assert.ok(!container.querySelector('.chat-view').hidden);assert.ok(container.querySelector('.app').classList.contains('explorer-layout'));
 await change('#my');assert.doesNotMatch(container.querySelector('.my-page').textContent,/상담용 이력서/);assert.match(container.querySelector('.my-page').textContent,/최근 본 항목/);await change('#jobs');
 const searchField=container.querySelector('main[aria-label="채용공고 탐색"] input[type="search"]');
 await fill(searchField,'Python');assert.equal(container.querySelectorAll('.explore-card').length,1);
 assert.match(container.querySelector('.explore-card').textContent,/Python developer/);
 await fill(searchField,'');
 const region=container.querySelector('main[aria-label="채용공고 탐색"] select');
 await act(async()=>{region.value='부산';region.dispatchEvent(new window.Event('change',{bubbles:true}));});
 assert.equal(container.querySelectorAll('.explore-card').length,1);
 await act(async()=>{container.querySelector('.browse-toolbar .quiet').click();});
 assert.equal(container.querySelectorAll('.explore-card').length,2);assert.equal(requests,2);
 const item=container.querySelector('.browse-result');assert.ok(item);await act(async()=>item.click());assert.match(container.querySelector('.browse-detail').textContent,/Synthetic developer/);assert.match(container.querySelector('.job-detail-sections').textContent,/Build software/);assert.ok(container.querySelector('.detail-header'));assert.equal(container.querySelector('.detail-header .detail-close'),null);assert.match(container.querySelector('.browse-actions').textContent,/내 역량 확인하기/);assert.equal(container.querySelectorAll('.browse-actions button,.browse-actions a').length,3);assert.doesNotMatch(container.querySelector('.browse-actions').textContent,/내 스크랩 보기|상담창에서 이어가기/);
 await act(async()=>{container.querySelector('.detail-backdrop').click();});assert.equal(container.querySelector('.browse-detail'),null);
 await act(async()=>{container.querySelector('[aria-label="스크랩 저장"]').click();});
 await change('#my');assert.ok(container.querySelector('.my-page-host'));assert.match(container.querySelector('.my-page').textContent,/Synthetic developer/);assert.match(container.querySelector('.personal-tabs').textContent,/최근 본 항목 \(1\)/);assert.match(container.querySelector('.personal-tabs').textContent,/스크랩 \(1\)/);
 await change('#jobs');await act(async()=>item.click());
 await change('#training');await change('#jobs');assert.equal(item.getAttribute('aria-pressed'),'true');await change('#chat');assert.equal(container.querySelector('#message'),textarea);assert.equal(textarea.value,'Keep my draft');assert.equal(requests,2);assert.match(container.querySelector('.conversation').textContent,/React jobs/);
 globalThis.fetch=async(url,options)=>{if(options?.body && JSON.parse(options.body).action==='browse_training')return {ok:true,status:200,json:async()=>({stage:'conversation',cached:true,learning_search:{status:'found'},learning_opportunities:[],training_has_more:false})};if(url==='/deploy-config.json')return {ok:true,json:async()=>({apiEnabled:true})};requests++;return {ok:true,status:200,json:async()=>({stage:'checking_required',grouped:true,cached:true,session_id:'11111111-1111-4111-8111-111111111111',requirement_type:'required',source_url:'https://example.com/job',questions:[{question_id:'q1',quote:'React experience'},{question_id:'q2',quote:'Git experience'}],progress:{answered:0,total:2}})};};
 await change('#jobs');
 await act(async()=>{container.querySelector('.browse-actions button:not([aria-pressed])').click();});
 const stepper=container.querySelector('.assessment-stepper');assert.ok(stepper);
 const met=stepper.querySelector('.assessment-options button');await act(async()=>met.click());
 const detail=stepper.querySelector('input');await fill(detail,'Keep this answer detail');
 assert.ok(container.querySelector('.assessment-modal[role="dialog"]'));assert.equal(container.querySelector('dialog.assessment-modal-backdrop').open,true);assert.doesNotMatch(stepper.textContent,/모름으로 넘기기|이 조건은 모름으로 선택/);
 await act(async()=>container.querySelector('[aria-label="문답 창 닫기"]').click());
 assert.equal(container.querySelector('.assessment-modal-backdrop').hidden,true);assert.equal(container.querySelector('dialog.assessment-modal-backdrop').open,false);
 assert.equal(container.querySelector('.assessment-stepper'),stepper);assert.equal(detail.value,'Keep this answer detail');
 await act(async()=>container.querySelector('.assessment-resume button').click());
 assert.equal(container.querySelector('.assessment-modal-backdrop').hidden,false);assert.equal(met.getAttribute('aria-pressed'),'true');
 await change('#jobs');await change('#training');await change('#chat');
 assert.equal(container.querySelector('.assessment-stepper'),stepper);
 assert.equal(met.getAttribute('aria-pressed'),'true');assert.equal(detail.value,'Keep this answer detail');assert.equal(requests,3);
 assert.equal(container.querySelector('.popup-open'),null);assert.equal(container.querySelector('.chat-launcher'),null);assert.equal(container.querySelector('[aria-label="상담창 고정"]'),null);
 assert.equal(container.querySelector('.sidebar'),null);
 const splitter=container.querySelector('[role="separator"]');assert.ok(splitter);
 await act(async()=>splitter.dispatchEvent(new window.KeyboardEvent('keydown',{key:'ArrowRight',bubbles:true})));
 assert.equal(container.querySelector('.app').style.getPropertyValue('--chat-width'),'360px');
 await act(async()=>{splitter.dispatchEvent(new window.PointerEvent('pointerdown',{button:0,clientX:100,pointerId:1,bubbles:true}));splitter.dispatchEvent(new window.PointerEvent('pointermove',{clientX:180,pointerId:1,bubbles:true}));splitter.dispatchEvent(new window.PointerEvent('pointerup',{pointerId:1,bubbles:true}));});
 assert.equal(container.querySelector('.app').style.getPropertyValue('--chat-width'),Math.min(440,window.innerWidth-(2*Math.max(280,(window.innerWidth-416)/3)+62))+'px');
 await act(async()=>{splitter.dispatchEvent(new window.PointerEvent('pointerdown',{button:0,clientX:0,pointerId:2,bubbles:true}));splitter.dispatchEvent(new window.PointerEvent('pointermove',{clientX:10000,pointerId:2,bubbles:true}));splitter.dispatchEvent(new window.PointerEvent('pointerup',{pointerId:2,bubbles:true}));});
 assert.ok(Number(container.querySelector('.app').style.getPropertyValue('--chat-width').replace('px',''))<=window.innerWidth-(2*Math.max(280,(window.innerWidth-416)/3)+62));

 assert.equal(window.location.hash,'#jobs');assert.equal(container.querySelector('#message'),textarea);assert.equal(detail.value,'Keep this answer detail');assert.equal(met.getAttribute('aria-pressed'),'true');
 await change('#admin-chat');assert.ok(container.querySelector('#access-code'));assert.equal(container.querySelector('#access-code').value,'');
 // A fresh explorer session loads bounded all-jobs data without asking the model.
 let sent=[];globalThis.fetch=async(url,options)=>{if(url==='/deploy-config.json')return {ok:true,json:async()=>({apiEnabled:true})};const payload=JSON.parse(options.body);sent.push(payload);return {ok:true,status:200,json:async()=>payload.action==='confirm_search'?{stage:'choose_job',cached:true,session_id:'22222222-2222-4222-8222-222222222222',total:1,candidate_jobs:[{source_id:'44',title:'Filtered React job',company_name:'Test',tech_stacks:['React']}],search_summary:{filters:['React'],ranking:[],limitations:[]}}:payload.search_plan?{stage:'choose_job',cached:true,session_id:'22222222-2222-4222-8222-222222222222',total:50,candidate_jobs:[{source_id:'43',title:'Initial all jobs',company_name:'Test'}]}:{stage:'search_review',cached:true,search_id:'33333333-3333-4333-8333-333333333333',session_id:'22222222-2222-4222-8222-222222222222',search_summary:{filters:['React'],ranking:[],limitations:[]}}};};
 await change('#jobs');await fill(container.querySelector('#access-code'),'x'.repeat(32));await submit(container.querySelector('form'));
 assert.equal(sent.length,1);assert.equal(sent[0].search_plan.limit,20);assert.equal(sent[0].search_plan.keyword,'');assert.match(container.querySelector('.browse-heading').textContent,/50/);
 await fill(container.querySelector('#message'),'React jobs');await submit(container.querySelector('#message').closest('form'));
 assert.equal(sent.length,3);assert.equal(sent[2].action,'confirm_search');assert.equal(sent[2].session_id,'22222222-2222-4222-8222-222222222222');assert.match(container.querySelector('.browse-card-grid').textContent,/Filtered React job/);assert.match(container.querySelector('[aria-label="현재 적용한 검색 조건"]').textContent,/React/);
 // A filtered training transition must not be overwritten by browse_training.
 const transition=[];
 globalThis.fetch=async(url,options)=>{if(url==='/deploy-config.json')return {ok:true,json:async()=>({apiEnabled:true})};const payload=JSON.parse(options.body);transition.push(payload.action);return {ok:true,status:200,json:async()=>payload.action==='confirm_search'?{stage:'conversation',cached:true,session_id:'22222222-2222-4222-8222-222222222222',learning_search:{status:'found',topics:['Windows']},learning_opportunities:[{source:'goyong24_training',source_id:'win-course',source_version:'1',title:'Windows basics',provider_name:'Test'}],training_has_more:false}:{stage:'training_search_review',cached:true,search_target:'training',search_id:'55555555-5555-4555-8555-555555555555',session_id:'22222222-2222-4222-8222-222222222222',learning_search:{status:'review_pending'},search_summary:{filters:['Windows'],ranking:[],limitations:[]}}};};
 await fill(container.querySelector('#message'),'내 부족한 점을 채울 Windows 교육');await submit(container.querySelector('#message').closest('form'));
 assert.equal(window.location.hash,'#training');assert.deepEqual(transition,['search','confirm_search']);assert.match(container.querySelector('main[aria-label="교육과정 탐색"]').textContent,/Windows basics/);
 // Education-first sessions must still fetch jobs when entering the jobs tab.
 await change('#admin-chat');await change('#training');
 globalThis.fetch=async(url,options)=>{if(url==='/deploy-config.json')return {ok:true,json:async()=>({apiEnabled:true})};const payload=JSON.parse(options.body);sent.push(payload);return {ok:true,status:200,json:async()=>payload.action==='browse_training'?{stage:'conversation',cached:true,session_id:'44444444-4444-4444-8444-444444444444',learning_search:{status:'found'},learning_opportunities:[],training_has_more:false}:{stage:'choose_job',cached:true,session_id:'44444444-4444-4444-8444-444444444444',total:1,candidate_jobs:[{source_id:'45',title:'Jobs after training',company_name:'Test'}]}};};
 await fill(container.querySelector('#access-code'),'x'.repeat(32));await submit(container.querySelector('form'));
 assert.equal(sent.at(-1).action,'browse_training');
 await change('#jobs');assert.equal(sent.at(-1).action,'search');assert.equal(sent.at(-1).session_id,'44444444-4444-4444-8444-444444444444');assert.match(container.querySelector('.browse-card-grid').textContent,/Jobs after training/);
 const count=sent.length;await change('#training');await change('#jobs');assert.equal(sent.length,count);


 }finally{await act(async()=>root.unmount());window.happyDOM.abort();}
});

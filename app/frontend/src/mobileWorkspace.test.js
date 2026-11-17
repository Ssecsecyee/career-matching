import assert from 'node:assert/strict';
import test from 'node:test';
import {fileURLToPath} from 'node:url';
import {build} from 'esbuild';
import {Window} from 'happy-dom';
import React,{act} from 'react';
test('mobile switching preserves draft, scroll and panels without extra requests',async()=>{
 const window=new Window({url:'http://localhost/#jobs'});
 Object.defineProperty(window,'innerWidth',{value:390,writable:true});Object.defineProperty(window,'innerHeight',{value:844,writable:true});
 const coarse=new window.EventTarget();coarse.matches=true;const matchMedia=window.matchMedia.bind(window);window.matchMedia=query=>query==='(pointer: coarse)'?coarse:matchMedia(query);
 const visual=new window.EventTarget();visual.height=844;visual.offsetTop=0;Object.defineProperty(window,'visualViewport',{value:visual});
 for(const key of ['window','document','navigator','HTMLElement','HTMLInputElement','HTMLTextAreaElement','Event','MouseEvent'])Object.defineProperty(globalThis,key,{value:window[key] || window,configurable:true,writable:true});
 globalThis.IS_REACT_ACT_ENVIRONMENT=true;window.HTMLElement.prototype.scrollIntoView=function(){};
 let requests=0;globalThis.fetch=async(url,options)=>url==='/deploy-config.json'?{ok:true,json:async()=>({apiEnabled:true,publicAccess:true})}:(requests++,{ok:true,status:200,json:async()=>({cached:true,stage:'choose_job',session_id:'11111111-1111-4111-8111-111111111111',candidate_jobs:[{source:'jumpit',source_id:'42',title:'Test job',company_name:'Example',tech_stacks:['React'],source_url:'https://example.com'}],total:1})});
 const {createRoot}=await import('react-dom/client');
 const built=await build({entryPoints:[fileURLToPath(new URL('./AppRouter.jsx',import.meta.url))],bundle:true,write:false,format:'esm',platform:'browser',define:{'process.env.NODE_ENV':'"development"'},plugins:[{name:'shared-react',setup(b){b.onResolve({filter:/^(react|react-dom)(\/.*)?$/},a=>({path:import.meta.resolve(a.path),external:true}));}}]});
 const {AppRouter}=await import('data:text/javascript;base64,'+Buffer.from(built.outputFiles[0].text).toString('base64'));
 const container=document.createElement('div');document.body.append(container);const root=createRoot(container);
 const press=async label=>act(async()=>{[...container.querySelectorAll('.mobile-workspace-nav button')].find(b=>b.getAttribute('aria-label')===label).click();window.dispatchEvent(new window.Event('hashchange'));});
 try{
  await act(async()=>root.render(React.createElement(AppRouter)));
  assert.ok(container.querySelector('.mobile-screen-chat'));assert.ok(container.querySelector('.welcome'));
  const textarea=container.querySelector('#message'),conversation=container.querySelector('.conversation');
  await act(async()=>{Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype,'value').set.call(textarea,'Keep mobile draft');textarea.dispatchEvent(new window.Event('input',{bubbles:true}));textarea.dispatchEvent(new window.Event('change',{bubbles:true}));});
  conversation.scrollTop=37;const baseline=requests,jobs=container.querySelector('.catalog-panel-jobs'),my=container.querySelector('.my-page-host');
  await press('검색 결과 보기');assert.ok(container.querySelector('.mobile-screen-results'));assert.equal(container.querySelector('.chat-view').inert,true);
  await press('내 페이지 보기');assert.ok(container.querySelector('.mobile-screen-my'));assert.equal(container.querySelector('.my-page-host'),my);
  await press('상담 보기');assert.ok(container.querySelector('.mobile-screen-chat'));assert.equal(container.querySelector('#message'),textarea);assert.equal(textarea.value,'Keep mobile draft');assert.equal(conversation.scrollTop,37);assert.equal(container.querySelector('.catalog-panel-jobs'),jobs);assert.equal(requests,baseline);
  await act(async()=>{visual.height=440;visual.dispatchEvent(new window.Event('resize'));});
  assert.ok(container.querySelector('.mobile-keyboard-open'));assert.ok(container.querySelector('.mobile-compact-height'));assert.equal(container.querySelector('.app').style.getPropertyValue('--mobile-height'),'440px');
  await act(async()=>{window.innerWidth=844;window.innerHeight=390;visual.height=390;window.dispatchEvent(new window.Event('resize'));});
  assert.ok(container.querySelector('.mobile-workspace-nav'));assert.ok(container.querySelector('.mobile-compact-height'));assert.equal(container.querySelector('.mobile-keyboard-open'),null);
  await act(async()=>{window.innerWidth=1440;window.innerHeight=1000;visual.height=1000;window.dispatchEvent(new window.Event('resize'));});
  assert.equal(container.querySelector('.mobile-workspace-nav'),null);assert.equal(container.querySelector('.mobile-workspace'),null);assert.ok(container.querySelector('.workspace-tabs'));
 }finally{await act(async()=>root.unmount());window.happyDOM.abort();}
});

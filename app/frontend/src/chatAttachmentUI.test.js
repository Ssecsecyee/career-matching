import assert from 'node:assert/strict';
import test from 'node:test';
import {fileURLToPath} from 'node:url';
import {build} from 'esbuild';
import {Window} from 'happy-dom';
import React,{act} from 'react';
test('TXT attachment submits vector search from the chat composer without uploading filename',async()=>{
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
 const sent=[];const originalFetch=globalThis.fetch;globalThis.fetch=(url,options)=>{if(options?.body)sent.push(JSON.parse(options.body));return originalFetch(url,options);};
 assert.ok(container.querySelector('button[aria-label="TXT 파일 첨부"]'));
 assert.equal(container.querySelector('.txt-similarity'),null);
 const input=container.querySelector('.chat-attachment input[type="file"]');
 const text='Python 또는 Java\nDocker 개발 경험';
 Object.defineProperty(input,'files',{value:[{name:'private-name.txt',size:new TextEncoder().encode(text).length,arrayBuffer:async()=>new TextEncoder().encode(text).buffer}],configurable:true});
 await act(async()=>{input.dispatchEvent(new window.Event('change',{bubbles:true}));});
 assert.match(container.querySelector('.attachment-chip').textContent,/private-name.txt/);
 assert.equal(container.querySelector('button[aria-label="메시지 보내기"]').disabled,false);
 await submit(container.querySelector('form.composer'));
 assert.equal(sent.at(-1).action,'vector_search');assert.equal(sent.at(-1).text,text);
 assert.ok(!JSON.stringify(sent.at(-1)).includes('private-name.txt'));
 assert.equal(container.querySelector('.attachment-chip'),null);
 assert.match(container.querySelector('.conversation').textContent,/첨부한 TXT/);
 }finally{await act(async()=>root.unmount());window.happyDOM.abort();}
});

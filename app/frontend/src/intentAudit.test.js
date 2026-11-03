import assert from 'node:assert/strict';
import test from 'node:test';
import {readFileSync} from 'node:fs';
import {createRequire} from 'node:module';
import {transformSync} from 'esbuild';
import React from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
import * as helpers from './intentAudit.js';
const code=transformSync(readFileSync(new URL('./IntentAudit.jsx',import.meta.url),'utf8'),{loader:'jsx',format:'cjs'}).code;
const module={exports:{}};
const require=createRequire(import.meta.url);
new Function('require','module','exports',code)(name=>name==='./intentAudit.js'?helpers:require(name),module,module.exports);
const {IntentAuditList,IntentAuditDetail,IntentAudit}=module.exports;
const id='11111111-1111-4111-8111-111111111111';
const render=(component,props)=>renderToStaticMarkup(React.createElement(component,props));

test('intent filters and detail use explicit read-only operations and strict references',()=>{
 assert.deepEqual(helpers.intentRowsRequest({session_id:id,execution_status:'failed'},25),{operation:'intent_rows',offset:25,session_id:id,execution_status:'failed'});
 assert.deepEqual(helpers.intentDetailRequest(id),{operation:'intent_detail',decision_id:id,include_raw:false});
 for(const input of [{session_id:'bad'},{filter_request_id:'SELECT 1'},{execution_status:'all'},{validation_status:'delete'}]) assert.throws(()=>helpers.intentRowsRequest(input));
 assert.throws(()=>helpers.intentRowsRequest({},-1));assert.throws(()=>helpers.intentDetailRequest(id,'true'));
});
test('list renders statuses and model usage without context or raw output',()=>{
 const data={total:1,offset:0,rows:[{decision_id:id,created_at:'2026-11-02',policy_version:'context-intent-v2',decision_source:'model',target:'jobs',decision_action:'search',executed_action:'search',validation_status:'invalid',execution_status:'failed',model_id:'synthetic-model',input_tokens:123,output_tokens:45,decision_reason:'<script>alert(1)</script>',context_snapshot:'PRIVATE_CONTEXT',raw_output:'PRIVATE_RAW'}]};
 const html=render(IntentAuditList,{data,busy:false});
 assert.match(html,/형식 오류/);assert.match(html,/실패/);assert.match(html,/123/);assert.match(html,/45/);
 assert.doesNotMatch(html,/PRIVATE_CONTEXT|PRIVATE_RAW|<script>/);assert.match(html,/&lt;script&gt;/);
});
test('detail loads stored context separately and hides raw until explicit request',()=>{
 const data={record:{decision_id:id,session_id:id,request_id:id,context_snapshot:{stage:'choose_job'},validated_decision:{action:'next_results'},result_summary:{total:80},raw_output:'PRIVATE_RAW'},raw_included:false,truncated_fields:[]};
 let html=render(IntentAuditDetail,{data,busy:false});
 assert.match(html,/choose_job/);assert.match(html,/next_results/);assert.match(html,/마스킹된 분류 출력 보기/);assert.doesNotMatch(html,/PRIVATE_RAW/);
 html=render(IntentAuditDetail,{data:{...data,raw_included:true,record:{...data.record,raw_output:'<img src=x onerror=alert(1)>'},truncated_fields:['raw_output']},busy:false});
 assert.match(html,/표시 한도로 잘렸습니다/);assert.match(html,/&lt;img/);assert.doesNotMatch(html,/<img/);
});
test('initial panel requests no private rows and busy paging is disabled',()=>{
 let html=render(IntentAudit,{busy:false});
 assert.match(html,/문맥·의도 기록/);assert.match(html,/요청 ID/);assert.doesNotMatch(html,/당시 문맥|선택한 판단 기록/);
 html=render(IntentAuditList,{data:{total:60,offset:25,rows:[]},busy:true});
 assert.equal((html.match(/disabled=""/g)||[]).length,2);
 assert.equal(helpers.intentTokens(null),'미기록');assert.equal(helpers.intentLabel('source','direct'),'버튼·폼');
});

test('search debug compares stored plans and self reports with safe old-record fallback',()=>{
 const base={record:{decision_id:id},raw_included:false,truncated_fields:[]};
 let html=render(IntentAuditDetail,{data:base,busy:false});
 assert.match(html,/검색 실행 기록이 없습니다/);
 const search_record={total:18,raw_plan:{required_skills:['commerce']},executed_plan:{required_skills:[],preferred_skills:['commerce']},
 constraint_guard:{basis:'assessment',unsupported_required_skills:['commerce'],evidence:[]},
 assessment_basis:{source_id:'42',source_version:2,items:[{type:'required',assessment:'unknown',quote:'<script>private</script>'}]}};
 html=render(IntentAuditDetail,{data:{...base,record:{...base.record,search_record}},busy:false});
 assert.match(html,/AI 제안/);assert.match(html,/실제 실행/);assert.match(html,/필수에서 선호로 전환/);
 assert.match(html,/미확인/);assert.match(html,/18건/);assert.doesNotMatch(html,/<script>/);
});

import assert from 'node:assert/strict';
import test from 'node:test';
import {readFileSync} from 'node:fs';
import {createRequire} from 'node:module';
import {transformSync} from 'esbuild';
import React from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
import * as helpers from './savedAnswers.js';
import {safeSourceUrl} from './api.js';
const require=createRequire(import.meta.url),module={exports:{}};
const code=transformSync(readFileSync(new URL('./SavedAnswersPanel.jsx',import.meta.url),'utf8'),{loader:'jsx',format:'cjs'}).code;
new Function('require','module','exports',code)(name=>name==='./savedAnswers.js'?helpers:name==='./api.js'?{safeSourceUrl}:require(name),module,module.exports);
const {SavedAnswerItems,SavedAnswersPanel}=module.exports;
const data={scope:'current_session_selected_job',source:{title:'합성 공고',company_name:'QA',source_id:'42',source_version:2,source_url:'https://example.test/42'},review_version:'a'.repeat(64),offset:0,page_size:10,total:2,answered:1,statements:[{id:'1',kind:'statement',text:'Python 개인 프로젝트를 해봤어요.'}],items:[{condition_id:'one',type:'required',quote:'Python 또는 Java 경험',assessment:'unknown',detail:'<script>개인 실습만 했어요.</script>',editable:true},{condition_id:'two',type:'preferred',quote:'Docker 경험',assessment:'unanswered',detail:'',editable:false}]};
const render=(component,props)=>renderToStaticMarkup(React.createElement(component,props));

test('review uses a direct non-model request and corrections cannot change quotes',()=>{
 assert.deepEqual(helpers.savedAnswersRequest(10),{action:'review_answers',values:{offset:10}});
 const request=helpers.reviseSavedAnswer(data.items[0],'met','프로젝트 경험',data);
 assert.equal(request.action,'revise_answer');assert.equal(request.values.condition_id,'one');assert.equal(request.values.review_version,data.review_version);
 assert.equal('quote' in request.values,false);assert.equal('source_id' in request.values,false);
 assert.throws(()=>helpers.savedAnswersRequest(1));assert.throws(()=>helpers.reviseSavedAnswer(data.items[1],'met','',data));
 assert.throws(()=>helpers.reviseSavedAnswer(data.items[0],'unanswered','',data));assert.throws(()=>helpers.reviseSavedAnswer(data.items[0],'met','',{...data,review_version:'stale'}));
});
test('saved answers render original condition, explicit unknown, explanation and only editable answer control',()=>{
 const html=render(SavedAnswerItems,{data,busy:false});
 assert.match(html,/Python 또는 Java 경험/);assert.match(html,/모름·미확인/);assert.match(html,/아직 답하지 않음/);assert.match(html,/개인 실습만 했어요/);
 assert.equal((html.match(/이 답변만 수정/g)||[]).length,1);assert.doesNotMatch(html,/<script>/);assert.match(html,/&lt;script&gt;/);
});
test('review panel shows scope, saved version, original user statement and whole-reset warning',()=>{
 const html=render(SavedAnswersPanel,{data,busy:false,error:''});
 assert.match(html,/현재 선택 공고/);assert.match(html,/저장된 공고 버전 2/);assert.match(html,/Python 개인 프로젝트/);
 assert.match(html,/조건 답변을 초기화하고 다시 확인/);assert.match(html,/경험 전체 정정·조건 답변 재확인/);
 assert.match(html,/role="dialog"/);assert.match(html,/aria-modal="true"/);
});
test('busy review controls and expired-load errors do not show stale private data',()=>{
 const html=render(SavedAnswersPanel,{data:null,busy:true,error:'대화가 만료됐습니다.'});
 assert.match(html,/대화가 만료/);assert.doesNotMatch(html,/Python 개인 프로젝트/);assert.match(html,/disabled=""/);
});

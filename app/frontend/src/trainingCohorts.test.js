import assert from 'node:assert/strict';
import test from 'node:test';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { transformSync } from 'esbuild';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
const require=createRequire(import.meta.url);
function load(file){
 const code=transformSync(readFileSync(new URL(file,import.meta.url),'utf8'),{loader:file.endsWith('jsx')?'jsx':'js',format:'cjs'}).code;
 const module={exports:{}};
 new Function('require','module','exports',code)(name=>name.startsWith('./')?load(name):require(name),module,module.exports);
 return module.exports;
}
const {TrainingCohorts}=load('./TrainingCohorts.jsx');
test('each cohort retains its own schedule fee status and source link',()=>{
 const course={cohorts:[{source:'goyong24_training',source_id:'one',cohort_name:'43',dates:{starts_at:{raw:'2099-11-19'},ends_at:{raw:'2099-12-24'}},tuition:null,source_url:'https://example.com/43',schedule_label:'시작 예정',recruitment_label:'모집 여부 미확인'},
 {source:'goyong24_training',source_id:'two',cohort_name:'44',dates:{starts_at:{raw:'2099-11-24'}},tuition:400000,currency:'KRW',source_url:'https://example.com/44'}]};
 const html=renderToStaticMarkup(React.createElement(TrainingCohorts,{course}));
 for(const text of ['43회차','44회차','2099-11-19','2099-11-24','400,000','https://example.com/43','https://example.com/44','전체 개설 일정은 아닙니다'])assert.ok(html.includes(text));
 assert.doesNotMatch(html,/현재 신청 가능/);
});

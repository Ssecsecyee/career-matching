import assert from 'node:assert/strict';
import test from 'node:test';
import { trainingExplainRequest } from './trainingExplain.js';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { transformSync } from 'esbuild';
const module={exports:{}};
new Function('require','module','exports',transformSync(readFileSync(new URL('./TrainingExplainButton.jsx',import.meta.url),'utf8'),{loader:'jsx',format:'cjs'}).code)(createRequire(import.meta.url),module,module.exports);
const {TrainingExplainButton}=module.exports;
const course={source:'goyong24_training',source_id:'course:1',source_version:2,title:'포차 안주요리',provider_name:'교육기관',curriculum:'Not sent'};
test('explain button sends only the exact displayed identity and version',()=>{
 const request=trainingExplainRequest(course);
 assert.equal(request.action,'explain_training');
 assert.deepEqual(request.values,{source:course.source,source_id:course.source_id,source_version:'2'});
 assert.match(request.label,/포차 안주요리/);
 let clicked;const element=TrainingExplainButton({course,active:true,busy:false,onExplain:value=>clicked=value});
 element.props.onClick();assert.equal(clicked,course);
});
test('old cards and busy requests disable explanation and label is clear',()=>{
 for(const props of [{active:false,busy:false},{active:true,busy:true}]){
 const html=renderToStaticMarkup(React.createElement(TrainingExplainButton,{course,...props,onExplain:()=>{}}));
 assert.match(html,/disabled/);assert.match(html,/이 교육 설명해줘/);
 }
});

import assert from 'node:assert/strict';
import test from 'node:test';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { transformSync } from 'esbuild';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
const code=transformSync(readFileSync(new URL('./TrainingStatus.jsx',import.meta.url),'utf8'),{loader:'jsx',format:'cjs'}).code;
const module={exports:{}};
new Function('require','module','exports',code)(createRequire(import.meta.url),module,module.exports);
const render=course=>renderToStaticMarkup(React.createElement(module.exports.TrainingStatus,{course}));
test('upcoming course with unknown recruitment is not called historical',()=>{
 const html=render({schedule_label:'시작 예정',recruitment_label:'모집 여부 미확인',recommendation_eligible:false});
 assert.match(html,/시작 예정/);assert.match(html,/모집 여부 미확인/);assert.doesNotMatch(html,/과거|신청 가능/);
});
test('older responses do not assume ended or open recruitment',()=>{
 assert.match(render({}),/일정 미확인/);assert.match(render({}),/모집 여부 미확인/);
 assert.match(render({schedule_label:'종료',recruitment_label:'마감으로 기록'}),/종료/);
});

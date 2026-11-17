import assert from 'node:assert/strict';
import test from 'node:test';
import { createRequire } from 'node:module';
import {fileURLToPath} from 'node:url';
import { buildSync } from 'esbuild';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';

// Compile the real JSX component for isolated rendering; no browser/network dependency.
const code = buildSync({entryPoints:[fileURLToPath(new URL('./SearchReview.jsx',import.meta.url))],bundle:true,write:false,platform:'node',format:'cjs',external:['react']}).outputFiles[0].text;
const module = { exports: {} };
new Function('require', 'module', 'exports', code)(createRequire(import.meta.url), module, module.exports);
const { SearchReview } = module.exports;
const data = { stage: 'search_review', search_id: 'search-1', total: 2,
  search_summary: { verified_total: 2, filters: ['근무지역: 부산 또는 경남'], ranking: ['보유 기술: Python'], limitations: ['경력 요건은 미확인입니다.'] } };
const render = (props = {}) => renderToStaticMarkup(React.createElement(SearchReview, { data, active: true, busy: false, ...props }));

test('review renders actual count, applied filters and limitations before cards', () => {
  const html = render();
  assert.match(html, /부산 또는 경남/);
  assert.match(html, /2건/);
  assert.match(html, /경력 요건은 미확인/);
  assert.match(html, /이 기준으로 공고 보기/);
  assert.doesNotMatch(html, /공고 원문/);
});
test('old, zero-result or changed searches cannot offer a confirmation button', () => {
  assert.doesNotMatch(render({ active: false }), /<button/);
  assert.doesNotMatch(render({ data: { ...data, stage: 'no_results', search_changed: true } }), /<button/);
  const empty = render({ data: { ...data, stage: 'no_results' } });
  assert.doesNotMatch(empty, /이 기준으로 공고 보기/);
  assert.match(empty, /조건 수정/);
});
test('busy confirmation controls are disabled', () => {
  const html = render({ busy: true });
  assert.equal((html.match(/disabled=""/g) || []).length, 2);
});

const trainingData = {stage:'training_search_review',search_target:'training',search_id:'education-1',search_summary:{candidate_total:9000,preview_count:3,filters:['주제·기관 검색어: React'],ranking:[],limitations:['신청 가능 여부는 미확인입니다.']}};
test('training preview uses education consent and distinguishes candidate count',()=>{
 const html=render({data:trainingData});
 assert.match(html,/이 기준으로 교육 보기/);assert.match(html,/검색한 교육 후보/);
 assert.doesNotMatch(html,/공고 보기|학습 루트 참고 교육/);
 assert.match(html,/9000회차/);
});
test('unknown training total is not displayed as a global count',()=>{
 const html=render({data:{...trainingData,search_summary:{...trainingData.search_summary,candidate_total:null}}});
 assert.match(html,/우선 확인한 후보/);assert.match(html,/전체 건수 미집계/);
});
test('empty or expired training review cannot confirm but can modify',()=>{
 const html=render({data:{...trainingData,stage:'training_no_results',search_changed:true}});
 assert.doesNotMatch(html,/이 기준으로 교육 보기/);assert.match(html,/조건 수정/);
});
test('education button forwards the correct review reference and target',()=>{
 let selected;
 const element=SearchReview({data:trainingData,active:true,busy:false,onConfirm:(...args)=>{selected=args;}});
 function find(node){if(Array.isArray(node)){for(const child of node){const found=find(child);if(found)return found;}}else if(node?.props){if(node.type==='button'&&node.props.children==='이 기준으로 교육 보기')return node;return find(node.props.children);}return null;}
 find(element).props.onClick();assert.deepEqual(selected,['education-1','training']);
});


test('cached search explanations show actual terms without internal AND or repair details',()=>{
 const html=render({data:{...trainingData,search_summary:{candidate_total:10,filters:['주제·기관 검색어 (모두 포함 · AND): 마케팅 AND SCM'],ranking:['내부 점수'],limitations:['AI가 AND 보정하여 재검색했습니다.','신청 가능 여부는 원문에서 확인하세요.']}}});
 assert.match(html,/마케팅 · SCM/);assert.match(html,/10회차/);
 assert.doesNotMatch(html,/AND|보정|내부 점수/);assert.match(html,/신청 가능 여부/);
});


test('successful searches still show their terms and semantic candidates do not claim exact totals',()=>{
 const html=render({data:{...data,stage:'choose_job',retrieval_mode:'section_vector_fallback',total:4,search_summary:{verified_total:0,filters:['검색어: 백엔드'],ranking:[],limitations:[]}}});
 assert.match(html,/백엔드/);assert.match(html,/관련 공고 후보/);assert.match(html,/4건/);
 assert.doesNotMatch(html,/이 기준으로 공고 보기|0건|AND|벡터/);
});

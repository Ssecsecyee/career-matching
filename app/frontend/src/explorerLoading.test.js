import test from 'node:test';
import assert from 'node:assert/strict';
import React from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
import {build} from 'esbuild';
const built=await build({entryPoints:['src/ExplorationPreview.jsx'],bundle:true,write:false,format:'esm',platform:'node',packages:'external'});
// Inline modules resolve React against this package when imported through a temporary file.
import {writeFile,unlink} from 'node:fs/promises';
const path=new URL('./.explorer-loading-test.mjs',import.meta.url);
await writeFile(path,built.outputFiles[0].text);
let ExplorationPreview;try{({ExplorationPreview}=await import(path.href));}finally{await unlink(path);}
test('initial loading shows skeletons instead of empty result or zero total',()=>{
 const html=renderToStaticMarkup(React.createElement(ExplorationPreview,{target:'jobs',results:{items:[],total:0},loading:true}));
 assert.match(html,/목록 불러오는 중/);assert.match(html,/skeleton-card/);assert.doesNotMatch(html,/현재 조건에서 표시할 공고가 없습니다/);assert.doesNotMatch(html,/0건/);
 const empty=renderToStaticMarkup(React.createElement(ExplorationPreview,{target:'jobs',results:{items:[],total:0},loading:false}));
 assert.match(empty,/현재 조건에서 표시할 공고가 없습니다/);assert.doesNotMatch(empty,/skeleton-card/);
});

test('infinite lists omit numbered navigation and show retry after failure',()=>{
 const props={target:'jobs',results:{items:[{source_id:'1',title:'Job',source_url:'https://example.com'}],hasMore:true,total:10}};
 const normal=renderToStaticMarkup(React.createElement(ExplorationPreview,props));
 assert.doesNotMatch(normal,/목록 페이지|다음 →/);assert.match(normal,/아래로 스크롤/);assert.doesNotMatch(normal,/다시 불러오기/);
 const failed=renderToStaticMarkup(React.createElement(ExplorationPreview,{...props,loadError:'failed'}));
 assert.match(failed,/다시 불러오기/);assert.doesNotMatch(failed,/다음 공고 보기/);
});

test('personal lists omit browse controls and job search has no small skill input',()=>{
 const props={target:'jobs',results:{items:[{source_id:'1',title:'Job'}],hasMore:false,total:1}};
 const personal=renderToStaticMarkup(React.createElement(ExplorationPreview,{...props,personal:true}));
 assert.doesNotMatch(personal,/browse-toolbar|browse-heading|전체 공고로 초기화|현재 목록에서 검색/);
 const jobs=renderToStaticMarkup(React.createElement(ExplorationPreview,props));
 assert.doesNotMatch(jobs,/예: Python|현재 목록 기술/);assert.match(jobs,/현재 목록 지역/);
});

test('each catalog card has exactly one source shortcut',()=>{
 for(const target of ['jobs','training']){
 const html=renderToStaticMarkup(React.createElement(ExplorationPreview,{target,results:{items:[{source_id:'1',title:'Example',source_url:'https://example.com/one'}],total:1}}));
 const footer=html.match(/<div class="explore-card-footer">([\s\S]*?)<\/div>/)[1];
 assert.equal((footer.match(/<a /g)||[]).length,1);
 }
});

test('infinite catalog retains cards beyond the first twenty',()=>{
 const items=Array.from({length:43},(_,i)=>({source_id:String(i),title:'Job '+i}));
 const html=renderToStaticMarkup(React.createElement(ExplorationPreview,{target:'jobs',results:{items,total:100,hasMore:true}}));
 assert.equal((html.match(/class="explore-card"/g)||[]).length,43);
 assert.doesNotMatch(html,/numbered-pages|한 페이지 20개/);
});

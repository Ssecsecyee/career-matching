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

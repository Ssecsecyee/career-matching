import assert from 'node:assert/strict';
import test from 'node:test';
import {readFileSync} from 'node:fs';
import {transformSync} from 'esbuild';
import React from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
let code=transformSync(readFileSync(new URL('./MarkdownAnswer.jsx',import.meta.url),'utf8'),{loader:'jsx',format:'esm'}).code;
for(const name of ['react','react-markdown','remark-gfm'])code=code.replaceAll(`from "${name}"`,`from ${JSON.stringify(import.meta.resolve(name))}`);
const {MarkdownAnswer}=await import('data:text/javascript;base64,'+Buffer.from(code).toString('base64'));
const render=(text,pending=false)=>renderToStaticMarkup(React.createElement(MarkdownAnswer,{text,pending}));
test('headings emphasis lists rules and tables render as structured content',()=>{
 const html=render('## 기본 정보\n\n- **기관**: 교육원\n- 일정 확인\n\n---\n\n| 회차 | 시작일 |\n| --- | --- |\n| 97 | 2026-11-10 |');
 for(const tag of ['<h2>','<strong>','<ul>','<li>','<hr','<table>'])assert.ok(html.includes(tag));
 assert.doesNotMatch(html,/##|\*\*기관/);
});
test('named and bare source links hide long URLs and preserve destination',()=>{
 const url='https://www.work24.go.kr/hr/a/a/3100/selectTracseDetl.do?tracseId=TEST&tracseTme=97';
 const html=render(`[97회차 상세 보기](${url})`);
 assert.match(html,/97회차 상세 보기/);assert.match(html,/class="answer-link"/);
 assert.ok(html.includes('tracseTme=97'));assert.match(html,/rel="noopener noreferrer"/);
 assert.doesNotMatch(html,/>https:\/\//);
 const bare=render(url);assert.match(bare,/고용24 상세 보기/);assert.doesNotMatch(bare,/>https:\/\//);
});
test('HTML images and executable links are not active content',()=>{
 const html=render('<script>alert(1)</script>\n\n<img src="https://example.com/track.png" onerror="alert(1)">\n\n![tracking](https://example.com/track.png)\n\n[bad](javascript:alert) [data](data:text/html,test) [plain](http://example.com)');
 assert.doesNotMatch(html,/<script|<img|javascript:|data:text|href="http:/);
});
test('unfinished streaming link hides its incomplete URL',()=>{
 const html=render('원문: [97회차 상세 보기](https://www.work24.go.kr/hr/a/a/3100/',true);
 assert.match(html,/링크 작성 중/);assert.doesNotMatch(html,/work24.go.kr/);
 assert.doesNotThrow(()=>render('### 작성 중 **강조',true));
});

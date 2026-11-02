import assert from 'node:assert/strict';
import test from 'node:test';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { transformSync } from 'esbuild';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';

// Compile the real JSX component for isolated rendering; no browser/network dependency.
const code = transformSync(readFileSync(new URL('./SearchReview.jsx', import.meta.url), 'utf8'), { loader: 'jsx', format: 'cjs' }).code;
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

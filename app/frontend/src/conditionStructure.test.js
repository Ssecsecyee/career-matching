import assert from 'node:assert/strict';
import test from 'node:test';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import { buildSync } from 'esbuild';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';

const require = createRequire(import.meta.url);
function component(file, name) {
  const code = buildSync({ entryPoints: [fileURLToPath(new URL(file, import.meta.url))], bundle: true,
    write: false, platform: 'node', format: 'cjs', external: ['react'] }).outputFiles[0].text;
  const module = { exports: {} };
  new Function('require', 'module', 'exports', code)(require, module, module.exports);
  return module.exports[name];
}
const AssessmentStepper = component('./AssessmentStepper.jsx', 'AssessmentStepper');
const AssessmentSummary = component('./AssessmentSummary.jsx', 'AssessmentSummary');
const notice = '여러 기술이 나열된 원문 묶음입니다. 개별 기술을 모두 검증한 것으로 해석하지 않습니다.';
const question = { question_id: '42:1:preferred:new:0', quote: '* 추가 기술스택\nPython\nSQL', summary: '추가 기술스택 · Python · SQL', source_notice: notice };

test('grouped-source notice is visible before choosing an assessment', () => {
  const data = { questions: [question], requirement_type: 'preferred', progress: { answered: 0, total: 1 }, source_url: 'https://example.com/job' };
  const html = renderToStaticMarkup(React.createElement(AssessmentStepper, { data, active: true, busy: false }));
  assert.match(html, /개별 기술을 모두 검증한 것으로 해석하지 않습니다/);
  assert.match(html, /Python\nSQL/);
  assert.match(html, /아직 모르겠어요/);
});

test('saved summary retains the grouped-source limitation and original quote', () => {
  const counts = { met: 1, unmet: 0, unknown: 0, unanswered: 0, total: 1 };
  const summary = { source: { title: '합성 공고', company_name: '테스트', source_version: 1, source_url: 'https://example.com/job' },
    headline: '사용자 답변 정리', groups: { required: { label: '필수', counts }, preferred: { label: '우대', counts } },
    conflicts: [], items: [{ condition_id: question.question_id, type: 'preferred', assessment: 'met', summary: question.summary, source_notice: notice }], answered: 1, next_actions: [] };
  const checks = [{ condition_id: question.question_id, quote: question.quote, assessment: 'met', source_notice: notice }];
  const html = renderToStaticMarkup(React.createElement(AssessmentSummary, { summary, checks, active: false }));
  assert.match(html, /개별 기술을 모두 검증한 것으로 해석하지 않습니다/);
  assert.match(html, /Python\nSQL/);
});

const ConditionReferences = component('./ConditionReferences.jsx','ConditionReferences');
test('AI reference selection keeps original text and reason without a met answer',()=>{
 const html=renderToStaticMarkup(React.createElement(ConditionReferences,{data:{condition_source_url:'https://example.com',reference_conditions:[{condition_id:'one',type:'required',quote:'학력무관 <script>',reason:'학력 제한이 없습니다.'}]}}));
 assert.match(html,/충족한 것으로 계산하지 않습니다/);assert.match(html,/학력무관 &lt;script&gt;/);
 assert.match(html,/학력 제한이 없습니다/);assert.doesNotMatch(html,/<script>/);
 assert.equal(renderToStaticMarkup(React.createElement(ConditionReferences,{data:{}})),'');
});

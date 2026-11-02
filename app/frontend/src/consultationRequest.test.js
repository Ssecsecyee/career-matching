import assert from 'node:assert/strict';
import test from 'node:test';
import { summaryActionRequest } from './consultationRequest.js';
test('known summary counseling actions bypass the search classifier', () => {
  for (const id of ['prepare', 'interview', 'learning_plan', 'explain_unknown', 'defer']) {
    const result = summaryActionRequest({ id, message: '저장한 답변으로 안내해줘' }, 'a'.repeat(64));
    assert.equal(result.action, 'consult');
    assert.equal(result.values.task, id);
    assert.equal(result.values.summary_id, 'a'.repeat(64));
  }
});
test('similar jobs remains a search without a consultation summary reference', () => {
  assert.deepEqual(summaryActionRequest({ id: 'similar_jobs', message: '다른 공고 찾아줘' }),
    { action: 'search', values: { message: '다른 공고 찾아줘' } });
});
test('unknown tasks and stale malformed references cannot be sent', () => {
  assert.throws(() => summaryActionRequest({ id: 'prepare', message: '준비' }, 'old'));
  assert.throws(() => summaryActionRequest({ id: 'unknown', message: '준비' }, 'a'.repeat(64)));
});

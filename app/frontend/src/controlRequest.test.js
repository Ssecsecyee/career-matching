import assert from 'node:assert/strict';
import test from 'node:test';
import {controlRequest} from './controlRequest.js';
test('known UI controls dispatch explicit actions rather than free-text search', () => {
  assert.deepEqual(controlRequest('역량 확인 질문은 그만해줘'), {action:'assessment_control',values:{control:'stop'}});
  assert.equal(controlRequest('우대조건도 계속 확인해줘').values.control, 'preferred');
  assert.equal(controlRequest('다른 공고 추천해줘').action, 'next_results');
  assert.equal(controlRequest('다른 교육 추천해줘').values.target, 'training');
  assert.equal(controlRequest('현재 답변으로 보완 방향을 정리해줘.').action, 'consult');
  assert.throws(() => controlRequest('arbitrary user message'));
});

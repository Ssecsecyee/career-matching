import assert from 'node:assert/strict';
import test from 'node:test';
import {controlRequest} from './controlRequest.js';
test('stable button IDs dispatch direct actions independently of display text', () => {
  assert.equal(controlRequest('assessment_stop').values.control,'stop');
  assert.equal(controlRequest('assessment_preferred').values.control,'preferred');
  assert.equal(controlRequest('next_jobs').action,'next_results');
  assert.equal(controlRequest('next_training').values.target,'training');
  assert.equal(controlRequest('consult_gaps').action,'consult');
  assert.throws(()=>controlRequest('다른 공고 추천해줘'));
  assert.throws(()=>controlRequest('toString'));
  const value=controlRequest('next_jobs');value.values.target='training';
  assert.equal(controlRequest('next_jobs').values.target,'jobs');
});

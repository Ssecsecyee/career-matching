import test from 'node:test';import assert from 'node:assert/strict';import {needsStepRecovery,recoveryMessage} from './requestRecovery.js';
test('format recovery is distinct from service failures and preserves the original goal',()=>{
 assert.equal(needsStepRecovery({error_code:'ModelOutputFormatError'}),true);assert.equal(needsStepRecovery({error_code:'ThrottlingException'}),false);
 const message=recoveryMessage('데이터분석가가 되고 싶은데 내역량을 평가해서 교육까지 추천해줘','assessment');assert.match(message,/데이터분석가/);assert.match(message,/한 단계/);assert.match(message,/먼저 내 역량/);assert.ok(recoveryMessage('a'.repeat(4000),'training').length<4000);
});

test('repeated recovery retains the goal without nested instructions',()=>{
 const once=recoveryMessage('AI 직무를 추천해줘','assessment');
 const twice=recoveryMessage(once,'training');
 const third=recoveryMessage(twice,'assessment');
 assert.equal((third.match(/이전 요청:/g)||[]).length,1);
 assert.equal((third.match(/이번에는 한 단계만/g)||[]).length,1);
 assert.match(third,/AI 직무를 추천해줘/);
});

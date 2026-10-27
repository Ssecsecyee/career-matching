import test from 'node:test';
import assert from 'node:assert/strict';
import { postChat, requestPayload, safeSourceUrl } from './api.js';

test('source links reject javascript and non-HTTPS URLs', () => {
  assert.equal(safeSourceUrl('javascript:alert(1)'), undefined);
  assert.equal(safeSourceUrl('http://example.com'), undefined);
  assert.equal(safeSourceUrl('https://example.com/job/42'), 'https://example.com/job/42');
});

test('retries can retain request ID and owner token stays in headers', async () => {
  const payload = requestPayload('select', { source_id: '42' }, 'session', 'request-id');
  let captured;
  const result = await postChat({ payload, accessCode: 'test-secret', ownerToken: 'test-owner', fetcher: async (url, options) => {
    captured = { url, options }; return { ok: true, status: 200, json: async () => ({ stage: 'checking_required' }) };
  } });
  assert.equal(captured.url, '/api/chat');
  assert.equal(captured.options.headers.Authorization, 'Bearer test-secret');
  assert.equal(JSON.parse(captured.options.body).request_id, 'request-id');
  assert.ok(!captured.options.body.includes('test-secret'));
  assert.ok(!captured.options.body.includes('test-owner'));
  assert.equal(result.body.stage, 'checking_required');
});


test('queued response polls same-origin status with owner headers and no new POST', async () => {
  const id = 'a'.repeat(64), calls = [];
  const replies = [{status:202,body:{job_id:id}}, {status:429,body:{}}, {status:202,body:{job_id:id}}, {status:200,body:{stage:'choose_job'}}];
  const result = await postChat({payload:{request_id:'same-id'}, accessCode:'test-secret', ownerToken:'test-owner', pause:async()=>{}, fetcher: async (url,options) => {
    calls.push({url,options}); const next=replies.shift(); return {status:next.status,ok:next.status<400,json:async()=>next.body};
  }});
  assert.equal(result.body.stage,'choose_job');
  assert.equal(calls.filter(call=>call.options.method==='POST').length,1);
  assert.equal(calls[1].url,`/api/jobs/${id}`);
  assert.equal(calls[1].options.headers['X-Client-Token'],'test-owner');
  assert.equal(calls[1].options.cache,'no-store');
});

test('malformed async job reference cannot forward credentials to another URL', async () => {
  let calls=0;
  await assert.rejects(postChat({payload:{},accessCode:'fixture',ownerToken:'fixture',pause:async()=>{},fetcher:async()=>{
    calls++; return {status:202,ok:true,json:async()=>({job_id:'https://attacker.example'})};
  }}));
  assert.equal(calls,1);
});


test('finished model throttling response is returned rather than mistaken for API polling throttling', async () => {
  const replies=[{status:202,body:{job_id:'b'.repeat(64)}},{status:429,body:{status:'model_temporarily_unavailable',error_code:'ThrottlingException',retryable:true}}];
  const result=await postChat({payload:{},accessCode:'fixture',ownerToken:'fixture',pause:async()=>{},fetcher:async()=>{
    const next=replies.shift(); return {status:next.status,ok:next.status<400,json:async()=>next.body};
  }});
  assert.equal(result.status,429);
  assert.equal(result.body.error_code,'ThrottlingException');
});

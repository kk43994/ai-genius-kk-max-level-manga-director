import test from 'node:test';
import assert from 'node:assert/strict';
import { createApiClient, ApiError } from '../../frontend/api-client.js';

const ok = data => new Response(JSON.stringify({data, meta:{apiVersion:1}}), {status:200,headers:{'Content-Type':'application/json'}});
test('root and subpath deployment resolve without domain-root leakage', async () => {
  for (const [options, expected] of [[{},'/api/v1/session'],[{publicBasePath:'/asset-lab/'},'/asset-lab/api/v1/session'],[{publicBasePath:'/asset-lab/',apiBase:'/custom/v1'},'/custom/v1/session']]) {
    let captured;
    const api=createApiClient({...options,fetchImpl:async(url,init)=>{captured={url,init};return ok({selection:{revision:0}});}});
    assert.deepEqual(await api.request('/session'),{selection:{revision:0}});
    assert.equal(captured.url,expected);assert.equal(captured.init.credentials,'same-origin');assert.equal(captured.init.redirect,'error');
  }
});
test('session CSRF stays in memory and writes preserve caller idempotency', async () => {
  const requests=[];
  const api=createApiClient({fetchImpl:async(url,init)=>{requests.push({url,init});return ok(url.endsWith('/session')?{csrfToken:'synthetic-csrf'}:{id:'synthetic-task'});}});
  await api.request('/session');
  await api.request('/tasks/prepare',{method:'POST',body:{projectId:'example'},idempotencyKey:'synthetic-key'});
  const req=requests[1];assert.equal(req.init.headers.get('X-CSRF-Token'),'synthetic-csrf');assert.equal(req.init.headers.get('Idempotency-Key'),'synthetic-key');assert.deepEqual(JSON.parse(req.init.body),{projectId:'example'});
  assert.equal('csrfToken' in api,false);
});
test('unsafe destinations and missing CSRF are blocked before fetch', async () => {
  let calls=0;const api=createApiClient({fetchImpl:async()=>{calls++;return ok({});}});
  for (const path of ['//evil.invalid/path','https://evil.invalid','/../x','/%2e%2e/x','/a%2fb','/a\\b']) await assert.rejects(api.request(path),TypeError);
  assert.throws(()=>createApiClient({apiBase:'https://evil.invalid'}),TypeError);
  await assert.rejects(api.request('/projects',{method:'POST',body:{}}),e=>e.code==='CSRF_TOKEN_REQUIRED');assert.equal(calls,0);
});
test('unconfirmed POST failures are never automatically retried', async () => {
  let calls=0;const api=createApiClient({csrfToken:'synthetic',fetchImpl:async()=>{calls++;throw new Error('private upstream text');}});
  await assert.rejects(api.request('/tasks/example/submit',{method:'POST',body:{}}),e=>e instanceof ApiError && e.code==='NETWORK_ERROR' && e.retryable===false && !e.message.includes('private'));
  assert.equal(calls,1);
});
test('structured errors preserve contract code, status and request ID', async () => {
  const api=createApiClient({fetchImpl:async()=>new Response(JSON.stringify({error:{code:'SELECTION_CHANGED',message:'选择已变化',retryable:false,details:{expectedRevision:1}},meta:{requestId:'synthetic-request'}}),{status:409})});
  await assert.rejects(api.request('/tasks'),e=>e.code==='SELECTION_CHANGED' && e.status===409 && e.requestId==='synthetic-request' && e.message==='选择已变化');
});
test('malformed/legacy envelopes are explicit errors, not successful data', async () => {
  for(const response of [()=>new Response('<html>private error</html>',{status:502}),()=>ok(undefined)]) {
    const api=createApiClient({fetchImpl:async()=>response()});
    await assert.rejects(api.request('/tasks'),e=>e.code==='INVALID_RESPONSE' && !e.message.includes('private'));
  }
});
test('binary downloads and AbortError are handled without JSON fallback/retry', async () => {
  const binary=createApiClient({fetchImpl:async()=>new Response('synthetic-zip',{status:200})});
  assert.equal(await (await binary.request('/projects/example/export',{responseType:'blob'})).text(),'synthetic-zip');
  const abort=new DOMException('aborted','AbortError');const api=createApiClient({fetchImpl:async()=>{throw abort;}});
  await assert.rejects(api.request('/tasks'),e=>e===abort);
});

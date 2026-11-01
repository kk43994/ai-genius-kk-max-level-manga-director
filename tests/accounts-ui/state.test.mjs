import test from 'node:test';
import assert from 'node:assert/strict';
import { accountState, attemptState, activeAttempt, selectable, validSelection, sameSelection,
  officialAuthorizationUrl, publicReturnPath, publicAttemptError, quotaPresentation, retainQuotaOnFailure, errorText } from '../../frontend/accounts/state.js';

const now = Date.parse('2026-10-27T10:00:00Z');
const account = { id: 'test_a', identity: { verified: true }, authorization: { state: 'connected' } };

test('connected requires verified identity; removal and actual expiry take precedence', () => {
  assert.equal(accountState(account, now), 'connected');
  assert.equal(accountState({ ...account, identity: { verified: false } }, now), 'error');
  assert.equal(accountState({ ...account, removedAt: '2026-10-27T00:00:00Z' }, now), 'removed');
  assert.equal(accountState({ ...account, authorization: { state: 'connected', expiresAt: '2026-10-27T09:00:00Z' } }, now), 'expired');
  assert.equal(accountState({ authorization: { state: 'invented' } }, now), 'error');
});

test('only available spaces of a connected account can be selected', () => {
  assert.equal(selectable(account, { kind: 'team', access: 'available' }), true);
  assert.equal(selectable(account, { kind: 'personal', access: 'revoked' }), false);
  assert.equal(selectable(account, { kind: 'other', access: 'available' }), false);
  assert.equal(selectable({ ...account, capabilities: { spaces: false } }, { kind: 'team', access: 'available' }), false);
});

test('selection CAS shape and account-space pairing', () => {
  assert.equal(validSelection({ providerAccountId: null, spaceId: 'x', revision: 1 }), false);
  assert.equal(validSelection({ providerAccountId: 'a', spaceId: 'x', revision: -1 }), false);
  assert.equal(validSelection({ providerAccountId: 'a', spaceId: null, revision: 2 }), true);
  assert.equal(sameSelection({ providerAccountId: 'a', spaceId: 'x', revision: 1 }, { providerAccountId: 'a', spaceId: 'x', revision: 2 }), true);
});

test('official authorization destination is exact HTTPS endpoint', () => {
  assert.equal(officialAuthorizationUrl('https://mcp.liblib.tv/authorize?state=synthetic'), 'https://mcp.liblib.tv/authorize?state=synthetic');
  for (const url of ['http://mcp.liblib.tv/authorize', 'https://mcp.liblib.tv.evil.example/authorize',
    'javascript:alert(1)', 'https://user:pass@mcp.liblib.tv/authorize', 'https://mcp.liblib.tv:444/authorize',
    'https://mcp.liblib.tv/redirect', 'https://mcp.liblib.tv/authorize#token', '//mcp.liblib.tv/authorize']) {
    assert.throws(() => officialAuthorizationUrl(url), /INVALID_AUTHORIZATION_URL/);
  }
});

test('root and subpath callback paths are explicit and safe', () => {
  assert.equal(publicReturnPath(), '/');
  assert.equal(publicReturnPath('/asset-lab'), '/asset-lab/');
  assert.equal(publicReturnPath('/asset-lab/'), '/asset-lab/');
  for (const path of ['//evil.example', '/..', '/asset-lab/?next=evil', 'https://example.test', '/a//b', '/a\\b']) assert.throws(() => publicReturnPath(path));
});

test('local pause is distinct from official cancellation; expiry releases pending guard', () => {
  const attempt = { status: 'pending', expiresAt: '2026-10-27T10:01:00Z' };
  assert.equal(attemptState(attempt, now), 'pending');
  assert.equal(attemptState({ ...attempt, paused: true }, now), 'paused');
  assert.equal(activeAttempt({ ...attempt, paused: true }, now), true);
  assert.equal(attemptState(attempt, now + 61000), 'expired');
  assert.equal(activeAttempt(attempt, now + 61000), false);
  assert.equal(attemptState({ ...attempt, status: 'failed', error: { code: 'access_denied' } }, now), 'cancelled');
  assert.equal(attemptState({ ...attempt, status: 'failed', error: { code: 'OTHER' } }, now), 'failed');
});

test('unknown balance, plan credits and invalid number never become zero', () => {
  for (const quota of [null, { state: 'unknown', planName: '3000-credit-plan', remaining: 3000 },
    { state: 'known', remaining: null }, { state: 'known', remaining: -1 }, { state: 'known', remaining: Infinity },
    { state: 'known', remaining: '0' }]) assert.equal(quotaPresentation(quota, now).value, '余额未知');
});

test('confirmed zero remains zero, expired known value is labelled stale', () => {
  assert.equal(quotaPresentation({ state: 'known', remaining: 0, unit: 'credits' }, now).value, '0 积分');
  const old = quotaPresentation({ state: 'known', remaining: 123.45, unit: 'credits', expiresAt: '2026-10-27T09:00:00Z' }, now);
  assert.equal(old.state, 'stale'); assert.equal(old.label, '上次已知余额'); assert.match(old.note, /数据已过期/);
});

test('quota buckets keep separate units and never become an invented total', () => {
  const q=quotaPresentation({state:'known',remaining:null,buckets:[
    {name:'个人积分',remaining:0,unit:'credits'}, {name:'现金',remaining:12.5,unit:'CNY'}]},now);
  assert.equal(q.value,'分项余额'); assert.equal(q.state,'known');
  assert.deepEqual(q.buckets,[{name:'个人积分',value:'0 积分'},{name:'现金',value:'12.5 CNY'}]);
});

test('unsupported quota explains the missing official capability', () => {
  const q=quotaPresentation({state:'unknown',reason:'provider_capability_unavailable'},now);
  assert.equal(q.value,'余额未知');assert.match(q.note,/未提供余额数值/);
});

test('failed check keeps only a clearly stale balance in the same account and space', () => {
  const previous={providerAccountId:'a',spaceId:'personal',state:'known',remaining:9,unit:'credits',observedAt:'2026-10-27T09:00:00Z'};
  const failure={providerAccountId:'a',spaceId:'personal',state:'unavailable',checkedAt:'2026-10-27T10:00:00Z'};
  const saved=retainQuotaOnFailure(previous,failure);
  assert.equal(saved.state,'stale');assert.equal(saved.remaining,9);assert.equal(saved.observedAt,previous.observedAt);
  assert.equal(saved.checkedAt,failure.checkedAt);
  for (const next of [{...failure,providerAccountId:'b'},{...failure,spaceId:'team'},{...failure,state:'unknown'}])
    assert.equal(retainQuotaOnFailure(previous,next),next);
});

test('never show raw transport messages or URLs in errors', () => {
  const result = errorText({ message: 'token=DO_NOT_RENDER https://bad.example/private' });
  assert.doesNotMatch(result, /DO_NOT_RENDER|https/);
  assert.match(errorText({ code: 'SELECTION_CHANGED' }), /别处更改/);
});

test('persist only recognized public authorization error codes', () => {
  assert.equal(publicAttemptError(null), null);
  assert.deepEqual(publicAttemptError({ code: 'ACCESS_DENIED', message: 'secret' }), { code: 'ACCESS_DENIED' });
  assert.match(errorText(publicAttemptError({ code:'PROVIDER_ACCOUNT_READ_UNAVAILABLE',message:'secret'})),/暂时无法读取原账号资料/);
  assert.deepEqual(publicAttemptError({ code: 'token=DO_NOT_STORE' }), { code: 'AUTHORIZATION_FAILED' });
});

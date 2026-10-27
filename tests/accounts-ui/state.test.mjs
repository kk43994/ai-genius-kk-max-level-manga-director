import test from 'node:test';
import assert from 'node:assert/strict';
import { accountState, attemptState, activeAttempt, selectable, validSelection, sameSelection,
  officialAuthorizationUrl, publicReturnPath, publicAttemptError, quotaPresentation, errorText } from '../../frontend/accounts/state.js';

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

test('never show raw transport messages or URLs in errors', () => {
  const result = errorText({ message: 'token=DO_NOT_RENDER https://bad.example/private' });
  assert.doesNotMatch(result, /DO_NOT_RENDER|https/);
  assert.match(errorText({ code: 'SELECTION_CHANGED' }), /别处更改/);
});

test('persist only recognized public authorization error codes', () => {
  assert.equal(publicAttemptError(null), null);
  assert.deepEqual(publicAttemptError({ code: 'ACCESS_DENIED', message: 'secret' }), { code: 'ACCESS_DENIED' });
  assert.deepEqual(publicAttemptError({ code: 'token=DO_NOT_STORE' }), { code: 'AUTHORIZATION_FAILED' });
});

import test from 'node:test';
import assert from 'node:assert/strict';
import { ownerStartBody, ownerConfirmBody, ownerAuthorizationUrl, draftSummary,
  publicOwnerMarker, savedDraftReferences, ownerErrorText } from '../../frontend/accounts/owner-state.js';

const future = () => new Date(Date.now() + 60000).toISOString();
const intent = () => ({ id: 'wi_test', purpose: 'recover_workspace', status: 'awaiting_confirmation', version: 2,
  proofExpiresAt: future(), sourceWorkspace: { id: 'source', content: { revision: 8 } }, candidates: [{ id: 'old', label: '原工作区' }] });

test('owner start sends only documented purpose fields and forces confirmation for a clean editor', () => {
  assert.deepEqual(ownerStartBody({ purpose: 'recover_workspace', label: ' 当前工作区 ', drafts: { hasUnsavedChanges: false }, publicBasePath: '/asset-lab/' }),
    { purpose: 'recover_workspace', workspaceLabel: '当前工作区', hasUnsavedChanges: null, returnPath: '/asset-lab/' });
  assert.equal(ownerStartBody({ purpose: 'bind_owner', label: '新工作区', drafts: { hasUnsavedChanges: true } }).hasUnsavedChanges, true);
  assert.throws(() => ownerStartBody({ purpose: 'provider_account', label: 'x' }));
  assert.throws(() => ownerStartBody({ purpose: 'bind_owner', label: ' ' }));
});

test('owner URL accepts only the official read-only identity scope', () => {
  assert.match(ownerAuthorizationUrl('https://mcp.liblib.tv/authorize?scope=libtv%3Aaccount%3Aread'), /^https:/);
  for (const url of ['https://mcp.liblib.tv/authorize', 'https://mcp.liblib.tv/authorize?scope=libtv%3Aaccount%3Aread+libtv%3Atask%3Awrite',
    'https://mcp.liblib.tv/authorize?scope=libtv%3Aaccount%3Aread&scope=libtv%3Atask%3Awrite', 'https://evil.example/authorize?scope=libtv%3Aaccount%3Aread']) assert.throws(() => ownerAuthorizationUrl(url));
});

test('recovery requires explicit candidate, acknowledgment and known-clean draft state', () => {
  const input = { intent: intent(), workspaceId: 'old', drafts: { hasUnsavedChanges: false }, savedDrafts: [], initiallyDirty: false, acknowledged: true };
  assert.deepEqual(ownerConfirmBody(input), { action: 'recover_preserve_current', workspaceId: 'old', expectedVersion: 2,
    expectedContentRevision: 8, draftDisposition: 'none', savedDrafts: [] });
  for (const change of [{ acknowledged: false }, { workspaceId: 'forged' }, { drafts: { hasUnsavedChanges: null } }, { drafts: { hasUnsavedChanges: true } }]) assert.throws(() => ownerConfirmBody({ ...input, ...change }));
});

test('initial dirty flag cannot be downgraded; persistent references are required', () => {
  const input = { intent: intent(), workspaceId: 'old', drafts: { hasUnsavedChanges: false }, initiallyDirty: true, acknowledged: true };
  assert.throws(() => ownerConfirmBody(input), /DRAFT_SAVE_REQUIRED/);
  assert.equal(ownerConfirmBody({ ...input, savedDrafts: [{ collection: 'drafts', id: 'draft_real', version: 3 }] }).draftDisposition, 'saved');
  assert.throws(() => savedDraftReferences([{ collection: 'drafts', id: 'draft_real', version: 0 }]));
  assert.throws(() => savedDraftReferences([{ collection: 'drafts', id: 'same', version: 1 }, { collection: 'drafts', id: 'same', version: 2 }]));
});

test('binding can only bind current workspace and never sends candidate workspaceId', () => {
  const body = ownerConfirmBody({ intent: { ...intent(), purpose: 'bind_owner' }, workspaceId: 'old', drafts: { hasUnsavedChanges: false }, acknowledged: true });
  assert.equal(body.action, 'bind_current'); assert.equal('workspaceId' in body, false);
});

test('expired or malformed confirmation cannot proceed', () => {
  for (const patch of [{ proofExpiresAt: '2020-01-01T00:00:00Z' }, { status: 'pending' }, { version: null }, { sourceWorkspace: {} }]) {
    assert.throws(() => ownerConfirmBody({ intent: { ...intent(), ...patch }, workspaceId: 'old', drafts: { hasUnsavedChanges: false }, acknowledged: true }));
  }
});

test('resume marker drops nonce, proof, subject, authorization URL and candidate contents', () => {
  const marker = publicOwnerMarker({ purpose: 'bind_owner', attemptId: 'oa_1', intentId: 'wi_1', sourceSessionId: 'ss_1',
    sourceWorkspaceId: 'source', expiresAt: future(), nonce: 'DO_NOT_KEEP', proof: { token: 'DO_NOT_KEEP' },
    authorizationUrl: 'DO_NOT_KEEP', subject: 'DO_NOT_KEEP', candidates: ['DO_NOT_KEEP'] });
  assert.doesNotMatch(JSON.stringify(marker), /DO_NOT_KEEP|nonce|proof|subject|authorizationUrl|candidates/);
  assert.equal(publicOwnerMarker({ purpose: 'provider_account' }), null);
});

test('draft inspector and errors never infer ownership or show raw secrets', () => {
  assert.equal(draftSummary(null).hasUnsavedChanges, null);
  assert.deepEqual(draftSummary({ hasUnsavedChanges: true, items: [{ label: '剧本输入', content: 'PRIVATE' }] }).items, [{ label: '剧本输入' }]);
  assert.match(ownerErrorText({ code: 'OWNER_WORKSPACE_NOT_FOUND' }), /生成账号不能/);
  assert.doesNotMatch(ownerErrorText({ code: 'UNKNOWN', message: 'nonce=PRIVATE' }), /PRIVATE|nonce/);
});

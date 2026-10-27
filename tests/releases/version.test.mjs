import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { compareVersions, validateManifest, trustedEntry } from '../../frontend/updates/version-contract.mjs';
import { VersionChecker } from '../../frontend/updates/version-checker.mjs';
const template = JSON.parse(readFileSync(new URL('./fixtures/manifest.json', import.meta.url)));
const trust = { origin: 'https://kk666.best', basePath: '/asset-lab/' };
const make = patch => ({ ...structuredClone(template), ...patch });
const build = m => Object.fromEntries(['schemaVersion','product','channel','version','buildId','apiVersion','dataSchemaVersion'].map(k => [k, m[k]]));
function fixture(options = {}) {
  let server = make(), latest = make({ version: '1.1.0', buildId: 'synthetic-b' }), calls = [], navigations = [];
  let state = { hasUnsavedChanges: false, activeTasks: 0 }, offline = false;
  const checker = new VersionChecker({ current: build(make()), ...trust,
    api: { request: async (path, opts) => { calls.push([path, opts]); if (offline) throw new Error('offline'); return structuredClone(path === '/version' ? server : latest); } },
    getSafetyState: async () => state, navigate: url => navigations.push(url), environment: {}, ...options });
  return { checker, calls, navigations, setServer(v) { server = v; }, setLatest(v) { latest = v; }, setSafety(v) { state = v; }, setOffline(v) { offline = v; } };
}

test('SemVer numeric ordering and full official prerelease precedence', () => {
  assert.equal(compareVersions('1.10.0', '1.9.0'), 1);
  const versions = ['1.0.0-alpha','1.0.0-alpha.1','1.0.0-alpha.beta','1.0.0-beta','1.0.0-beta.2','1.0.0-beta.11','1.0.0-rc.1','1.0.0'];
  for (let i = 1; i < versions.length; i++) assert.equal(compareVersions(versions[i-1], versions[i]), -1);
  assert.equal(compareVersions('1.0.0+one', '1.0.0+two'), 0);
  assert.equal(compareVersions('9007199254740993.0.0', '9007199254740992.0.0'), 1);
});
test('invalid versions, fields, dates, checksum and credentials fields are rejected', () => {
  for (const v of ['01.0.0','1.2','v1.2.3','1.0.0-01','1.0.0+','1.2.3\n']) assert.throws(() => compareVersions(v,'1.0.0'));
  for (const patch of [{ token: 'not-a-secret-test' }, { publishedAt: '2026-02-30T08:00:00Z' }, { apiVersion: '1' }, { integrity: { algorithm:'sha256',value:null } }, { version:'1.0.0-beta' }, { minCompatibleClient:'2.0.0' }]) assert.throws(() => validateManifest(make(patch), trust));
});
test('same-origin HTTPS and base path allowlist rejects redirect/exfil paths', () => {
  for (const entry of ['https://other.test/asset-lab/','//other.test/asset-lab/','javascript:alert(1)','/outside/','/asset-lab/../outside','/asset-lab/%2e%2e/outside','/asset-lab/?token=x','/asset-lab/#x','https://a@kk666.best/asset-lab/']) assert.throws(() => trustedEntry(entry, trust));
  assert.equal(trustedEntry('/asset-lab/', trust), 'https://kk666.best/asset-lab/');
});
test('startup coalesces, interval is six hours, manual checks use shared API', async () => {
  const f = fixture(); f.checker.start(); f.checker.start(); await f.checker.check();
  assert.equal(f.calls.length, 2); assert.equal(f.checker.intervalMs, 21600000);
  assert.equal(f.checker.state.status, 'update_available'); assert.equal(f.navigations.length, 0);
  assert.equal(f.calls[0][1].cache, 'no-store'); await f.checker.check(); assert.equal(f.calls.length, 4); f.checker.destroy();
});
test('offline keeps last good timestamp but never reports latest or navigates', async () => {
  const f = fixture({ environment: { navigator: { onLine: false } } }); await f.checker.check();
  const stamp = f.checker.state.checkedAt; f.setOffline(true); await f.checker.check();
  assert.equal(f.checker.state.status, 'offline'); assert.equal(f.checker.state.checkedAt, stamp);
  assert.equal(await f.checker.applyUpdate(), false); assert.equal(f.navigations.length, 0);
});
test('malformed, untrusted and wrong-channel manifests fail safely', async () => {
  for (const latest of [null, {}, make({ entryUrl:'https://other.test/' }), make({ channel:'preview' })]) {
    const f = fixture(); f.setLatest(latest); await f.checker.check(); assert.equal(f.checker.state.status, 'error'); assert.equal(f.checker.state.canUpdate, false);
  }
});
test('timeout works even when a shared API adapter ignores AbortSignal', async () => {
  const f = fixture({ api: { request: () => new Promise(() => {}) }, timeoutMs: 10 });
  await f.checker.check(); assert.equal(f.checker.state.status, 'error');
});
test('new runtime requiring a newer client is detected, but safe update is possible', async () => {
  const f = fixture(); f.setServer(make({ version:'1.1.0', buildId:'synthetic-b', minCompatibleClient:'1.1.0' }));
  await f.checker.check(); assert.equal(f.checker.state.status,'incompatible'); assert.equal(f.checker.state.compatibleNow, false); assert.equal(f.checker.state.canUpdate,true);
});
test('new frontend requiring an unstarted API or schema cannot refresh', async () => {
  for (const patch of [{apiVersion:2},{dataSchemaVersion:2}]) {
    const f = fixture(); f.setLatest(make({version:'1.1.0',buildId:'b',...patch}));
    await f.checker.check(); assert.equal(f.checker.state.status,'incompatible'); assert.equal(await f.checker.applyUpdate(),false);
  }
});
test('same version different build and server rollback both offer explicit refresh', async () => {
  const f = fixture(); f.setLatest(make({buildId:'hotfix-b'})); await f.checker.check(); assert.equal(f.checker.state.status,'update_available');
  f.setLatest(make({version:'0.9.0',buildId:'older',minCompatibleClient:'0.9.0'})); f.setServer(make({version:'0.9.0',buildId:'older',minCompatibleClient:'0.9.0'}));
  await f.checker.check(); assert.equal(f.checker.state.changeKind,'rollback'); assert.equal(f.navigations.length,0);
});
test('same identity reports up to date', async () => { const f=fixture(); f.setLatest(make()); await f.checker.check(); assert.equal(f.checker.state.status,'up_to_date'); });
test('dirty state, active tasks/downloads and unknown safety all block navigation', async () => {
  for (const state of [{hasUnsavedChanges:true,activeTasks:0},{hasUnsavedChanges:false,activeTasks:2},{hasUnsavedChanges:false,activeTasks:0,activeDownloads:1},null,{hasUnsavedChanges:false}]) {
    const f=fixture(); f.setSafety(state); assert.equal(await f.checker.applyUpdate(),false); assert.equal(f.navigations.length,0);
  }
});
test('draft save must be acknowledged; conflict retains content and stops refresh', async () => {
  const f=fixture({saveDraft:async()=>{throw new Error('VERSION_CONFLICT');}}); f.setSafety({hasUnsavedChanges:true,activeTasks:0});
  assert.equal(await f.checker.applyUpdate(),false); assert.match(f.checker.state.reason,/冲突/); assert.equal(f.navigations.length,0);
});
test('confirmed draft save is awaited then safety is re-read before navigation', async () => {
  let dirty=true, saved=false;
  const f=fixture({getSafetyState:async()=>({hasUnsavedChanges:dirty,activeTasks:0}),saveDraft:async()=>{await new Promise(r=>setTimeout(r,5));dirty=false;saved=true;return {saved:true};}});
  assert.equal(await f.checker.applyUpdate(),true); assert.equal(saved,true); assert.equal(f.navigations.length,1); assert.equal(f.navigations[0],'https://kk666.best/asset-lab/?_release=synthetic-b');
});
test('click rechecks latest and refuses reload after a network failure', async () => { const f=fixture();await f.checker.check();f.setOffline(true);assert.equal(await f.checker.applyUpdate(),false); });
test('double click only navigates once; unmount disables further requests', async () => {
  const f=fixture(); const results=await Promise.all([f.checker.applyUpdate(),f.checker.applyUpdate()]);assert.deepEqual(results,[true,false]);assert.equal(f.navigations.length,1);
  f.checker.destroy(); const count=f.calls.length;await f.checker.check();assert.equal(f.calls.length,count);
});
test('root mount and subpath mount both retain relative API calls', async()=>{
  const f=fixture({basePath:'/'}); f.setLatest(make({version:'1.1.0',buildId:'b',entryUrl:'/'})); f.setServer(make({entryUrl:'/'}));
  await f.checker.check(); assert.equal(await f.checker.applyUpdate(),true);assert.equal(f.navigations[0],'https://kk666.best/?_release=b');
  assert.ok(f.calls.every(([p])=>!p.startsWith('/api/')));
});
test('hidden pages pause polling and visibility only checks when expired', async()=>{
  const document=new EventTarget();document.visibilityState='hidden';const f=fixture({document});
  await f.checker.check();let count=f.calls.length;f.checker.onVisible();assert.equal(f.calls.length,count);
  document.visibilityState='visible';f.checker.onVisible();assert.equal(f.calls.length,count);
  f.checker.lastAttempt=Date.now()-21600001;f.checker.onVisible();await f.checker.check();assert.equal(f.calls.length,count+2);f.checker.destroy();
});

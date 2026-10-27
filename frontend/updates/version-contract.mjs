// No runtime dependencies; shared by the browser and the Node HTTP adapter.
const CORE = '(0|[1-9][0-9]*)';
const SEMVER = new RegExp(`^${CORE}\\.${CORE}\\.${CORE}(?:-([0-9A-Za-z-]+(?:\\.[0-9A-Za-z-]+)*))?(?:\\+([0-9A-Za-z-]+(?:\\.[0-9A-Za-z-]+)*))?$`);
export const PRODUCT = 'asset-lab-customer';
export const NO_CACHE_HEADERS = Object.freeze({
  'Cache-Control': 'no-store, no-cache, must-revalidate, max-age=0',
  'Pragma': 'no-cache', 'Expires': '0',
  'Content-Type': 'application/json; charset=utf-8',
  'X-Content-Type-Options': 'nosniff',
});
export function parseVersion(value) {
  if (typeof value !== 'string' || value.length > 128) throw new Error('Invalid semantic version');
  const match = value.match(SEMVER);
  if (!match || (match[4] || '').split('.').some(x => /^0[0-9]+$/.test(x))) throw new Error('Invalid semantic version');
  return { core: match.slice(1, 4).map(BigInt), pre: match[4]?.split('.') || [] };
}
export function compareVersions(a, b) {
  const x = parseVersion(a), y = parseVersion(b);
  for (let i = 0; i < 3; i++) if (x.core[i] !== y.core[i]) return x.core[i] > y.core[i] ? 1 : -1;
  if (!x.pre.length || !y.pre.length) return x.pre.length === y.pre.length ? 0 : x.pre.length ? -1 : 1;
  for (let i = 0; i < Math.max(x.pre.length, y.pre.length); i++) {
    if (x.pre[i] === undefined) return -1;
    if (y.pre[i] === undefined) return 1;
    if (x.pre[i] === y.pre[i]) continue;
    const xn = /^[0-9]+$/.test(x.pre[i]), yn = /^[0-9]+$/.test(y.pre[i]);
    if (xn !== yn) return xn ? -1 : 1;
    return (xn ? BigInt(x.pre[i]) > BigInt(y.pre[i]) : x.pre[i] > y.pre[i]) ? 1 : -1;
  }
  return 0;
}
export function inRange(v, min, maxExclusive) {
  return compareVersions(v, min) >= 0 && compareVersions(v, maxExclusive) < 0;
}
function shape(value, keys, name) {
  if (!value || typeof value !== 'object' || Array.isArray(value) || Object.keys(value).some(k => !keys.includes(k)) || keys.some(k => !(k in value))) throw new Error(`Invalid ${name} fields`);
}
function range(min, max) {
  if (compareVersions(min, max) >= 0) throw new Error('Empty compatibility range');
}
function identity(x) {
  parseVersion(x.version);
  if (typeof x.buildId !== 'string' || !/^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$/.test(x.buildId)) throw new Error('Invalid build identifier');
}
export function trustedEntry(value, { origin, basePath = '/' }) {
  if (typeof value !== 'string' || value.length > 2048 || /[\\\s]/.test(value) || !/^\/(?:[A-Za-z0-9_-]+\/)*$/.test(basePath)) throw new Error('Invalid entry URL');
  const url = new URL(value, origin);
  const loopback = ['localhost', '127.0.0.1', '[::1]'].includes(url.hostname);
  if (url.origin !== new URL(origin).origin || (url.protocol !== 'https:' && !(loopback && url.protocol === 'http:')) || url.username || url.password || url.search || url.hash || !url.pathname.startsWith(basePath) || /%2f|%5c|%2e/i.test(url.pathname)) throw new Error('Untrusted entry URL');
  return url.href;
}
export function validateManifest(x, trust) {
  shape(x, ['schemaVersion', 'product', 'version', 'buildId', 'channel', 'publishedAt', 'apiVersion', 'dataSchemaVersion', 'minCompatibleClient', 'releaseNotes', 'reloadRequired', 'entryUrl', 'integrity'], 'manifest');
  if (x.schemaVersion !== 1 || x.product !== PRODUCT || !['stable', 'preview'].includes(x.channel)) throw new Error('Unsupported manifest');
  identity(x);
  if (x.channel === 'stable' && parseVersion(x.version).pre.length) throw new Error('Stable cannot contain a prerelease');
  if (typeof x.publishedAt !== 'string' || !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$/.test(x.publishedAt) || !Number.isFinite(Date.parse(x.publishedAt)) || new Date(x.publishedAt).toISOString().replace('.000Z', 'Z') !== x.publishedAt) throw new Error('Invalid release date');
  if (!Array.isArray(x.releaseNotes) || x.releaseNotes.length > 30 || x.releaseNotes.some(n => typeof n !== 'string' || !n.length || n.length > 2000)) throw new Error('Invalid release notes');
  if (!Number.isSafeInteger(x.apiVersion) || x.apiVersion < 1 || !Number.isSafeInteger(x.dataSchemaVersion) || x.dataSchemaVersion < 1 || typeof x.reloadRequired !== 'boolean') throw new Error('Invalid compatibility fields');
  parseVersion(x.minCompatibleClient);
  if (compareVersions(x.minCompatibleClient, x.version) > 0) throw new Error('Release does not support its own client');
  shape(x.integrity, ['algorithm', 'value'], 'integrity');
  if (x.integrity.algorithm !== 'sha256' || typeof x.integrity.value !== 'string' || !/^[a-f0-9]{64}$/.test(x.integrity.value)) throw new Error('Invalid payload checksum');
  trustedEntry(x.entryUrl, trust);
  return structuredClone(x);
}
export function validateClientBuild(x) {
  shape(x, ['schemaVersion', 'product', 'version', 'buildId', 'channel', 'apiVersion', 'dataSchemaVersion'], 'client build');
  if (x.schemaVersion !== 1 || x.product !== PRODUCT || !['stable', 'preview'].includes(x.channel)) throw new Error('Invalid client build');
  identity(x);
  if (!Number.isSafeInteger(x.apiVersion) || x.apiVersion < 1 || !Number.isSafeInteger(x.dataSchemaVersion) || x.dataSchemaVersion < 1) throw new Error('Invalid client compatibility');
  return structuredClone(x);
}
export function compatibility(client, running) {
  return client.apiVersion === running.apiVersion && compareVersions(client.version, running.minCompatibleClient) >= 0;
}

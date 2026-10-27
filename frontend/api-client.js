/** Contract-v1 transport. No provider credentials, hidden globals or automatic retries. */
export class ApiError extends Error {
  constructor(message, { code = 'REQUEST_FAILED', status = 0, retryable = false, requestId = null, details = {} } = {}) {
    super(message);
    this.name = 'ApiError';
    Object.assign(this, { code, status, retryable, requestId, details });
  }
}

function basePath(value, name) {
  if (typeof value !== 'string' || !/^\/[A-Za-z0-9._~/-]*$/.test(value) || value.startsWith('//') || value.split('/').some(p => p === '.' || p === '..')) {
    throw new TypeError(`${name} must be a same-origin absolute pathname`);
  }
  return value.replace(/\/+$/, '') || '';
}

export function createApiClient({ publicBasePath = '/', apiBase, csrfToken = null, fetchImpl = globalThis.fetch } = {}) {
  const publicBase = basePath(publicBasePath, 'publicBasePath');
  const endpoint = basePath(apiBase ?? `${publicBase}/api/v1`, 'apiBase');
  if (!endpoint) throw new TypeError('apiBase must identify the API path');
  if (typeof fetchImpl !== 'function') throw new TypeError('fetchImpl is required');
  let csrf = null;
  function setCsrfToken(value) {
    if (value !== null && (typeof value !== 'string' || /[\r\n]/.test(value))) throw new TypeError('Invalid CSRF token');
    csrf = value || null;
  }
  setCsrfToken(csrfToken);
  function requestUrl(path) {
    if (typeof path !== 'string' || !path.startsWith('/') || path.startsWith('//') || /[\\\s#]/.test(path)) throw new TypeError('Request path must start with one slash');
    const pathname = path.split('?')[0];
    const segments = pathname.split('/');
    for (const segment of segments) {
      let decoded;
      try { decoded = decodeURIComponent(segment); } catch { throw new TypeError('Invalid request path'); }
      if (decoded === '.' || decoded === '..' || /[/\\\u0000-\u001f]/.test(decoded)) throw new TypeError('Invalid request path');
    }
    return `${endpoint}${path}`;
  }
  async function request(path, { method = 'GET', body, idempotencyKey, signal, responseType = 'json' } = {}) {
    const url = requestUrl(path);
    method = method.toUpperCase();
    if (!['GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'HEAD'].includes(method)) throw new TypeError('Unsupported request method');
    if (!['json', 'blob'].includes(responseType)) throw new TypeError('Unsupported responseType');
    const writing = !['GET', 'HEAD'].includes(method);
    if (!writing && body !== undefined) throw new TypeError('Read requests cannot carry a body');
    if (writing && !csrf) throw new ApiError('会话尚未准备好，请重新载入后再试。', { code: 'CSRF_TOKEN_REQUIRED' });
    const headers = new Headers({ Accept: responseType === 'blob' ? 'application/octet-stream, application/json' : 'application/json' });
    if (writing) headers.set('X-CSRF-Token', csrf);
    if (idempotencyKey !== undefined) headers.set('Idempotency-Key', idempotencyKey);
    if (body !== undefined) headers.set('Content-Type', 'application/json');
    let response;
    try {
      response = await fetchImpl(url, { method, headers, body: body === undefined ? undefined : JSON.stringify(body), credentials: 'same-origin', cache: 'no-store', redirect: 'error', signal });
    } catch (error) {
      if (error?.name === 'AbortError') throw error;
      throw new ApiError('暂时无法连接服务，请检查网络后重试。', { code: 'NETWORK_ERROR', retryable: !writing });
    }
    if (response.ok && responseType === 'blob') return response.blob();
    if (response.ok && (response.status === 204 || method === 'HEAD')) return null;
    let envelope;
    try { envelope = await response.json(); } catch (error) {
      if (error?.name === 'AbortError') throw error;
      throw new ApiError('服务返回了无法读取的结果，请稍后重试。', { code: 'INVALID_RESPONSE', status: response.status });
    }
    if (!response.ok) {
      const error = envelope?.error;
      const data = error && typeof error === 'object' ? error : {};
      throw new ApiError(typeof data.message === 'string' ? data.message : '请求未能完成，请稍后重试。', {
        code: typeof data.code === 'string' ? data.code : 'REQUEST_FAILED', status: response.status,
        retryable: data.retryable === true, requestId: envelope?.meta?.requestId ?? null,
        details: data.details && typeof data.details === 'object' ? data.details : {},
      });
    }
    if (!envelope || !Object.hasOwn(envelope, 'data')) throw new ApiError('服务响应与当前版本不兼容。', { code: 'INVALID_RESPONSE', status: response.status });
    if (path.split('?')[0] === '/session' && typeof envelope.data?.csrfToken === 'string') setCsrfToken(envelope.data.csrfToken);
    return envelope.data;
  }
  return Object.freeze({ request, setCsrfToken, publicBasePath: `${publicBase}/`, apiBase: endpoint });
}

export default createApiClient;

/** Merge simultaneous reads only. Never cache an authorization or replay writes. */
export function coalesceStatusReads(request, context) {
  const pending = new Map();
  return (path, options) => {
    if (options?.method && options.method !== 'GET') return request(path, options);
    const key = `${context()}\n${path}`;
    if (pending.has(key)) return pending.get(key);
    const promise = Promise.resolve().then(() => request(path, options));
    pending.set(key, promise);
    const clear = () => { if (pending.get(key) === promise) pending.delete(key); };
    promise.then(clear, clear);
    return promise;
  };
}

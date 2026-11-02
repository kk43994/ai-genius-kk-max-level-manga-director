/** Coalesce interaction events into one paint, without delaying state updates. */
export function frameRenderer(window, paint) {
  let frame = null, disposed = false;
  function cancel() {
    if (frame !== null) window.cancelAnimationFrame(frame);
    frame = null;
  }
  return {
    request() {
      if (disposed || frame !== null) return;
      frame = window.requestAnimationFrame(() => {
        frame = null;
        if (!disposed) paint();
      });
    },
    flush() { cancel(); if (!disposed) paint(); },
    cancel,
    dispose() { cancel(); disposed = true; },
  };
}

// Rig Relay — Frontend Event Trace Emission
// Unified trace point for frontend lifecycle observability

import { getSafeTimestamp } from './correlation.js';

let sharedHandshakeId = null;

export function setFrontendHandshakeId(id) {
  sharedHandshakeId = id;
}

export function recordFrontendEvent(type, detail = {}) {
  const payload = {
    type,
    handshake_id: sharedHandshakeId,
    timestamp: getSafeTimestamp(),
    ...detail
  };

  // 1. Pywebview native injection (primary)
  if (window.pywebview && window.pywebview.api && window.pywebview.api.record_frontend_event) {
    try {
      window.pywebview.api.record_frontend_event(payload).catch(err => {
        console.warn('Pywebview event emission failed:', err);
      });
      return;
    } catch (e) {
      console.warn('Pywebview API access error:', e);
    }
  }

  // 2. Fetch fallback (for browser debug)
  try {
    fetch('/frontend-event', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    }).catch(() => { /* silent fallback */ });
  } catch (e) {
    // silent
  }
}

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

  // 2. HTTP GET fallback (for browser debug) — uses query params, never hits /ws
  const detailParam = encodeURIComponent(JSON.stringify(detail || {}));
  const url = `/frontend-event?type=${encodeURIComponent(type)}&handshake_id=${encodeURIComponent(sharedHandshakeId || '')}&detail=${detailParam}`;
  try {
    fetch(url, {
      method: 'GET',
      credentials: 'same-origin',
      cache: 'no-store',
      keepalive: true,
    }).catch(() => { /* silent fallback */ });
  } catch (e) {
    // silent
  }
}

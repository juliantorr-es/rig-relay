// Rig Relay — Utilities
// Small pure helpers, no dependencies

export function escapeHtml(str) {
  if (typeof str !== 'string') return String(str);
  return str.replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
}

export function setText(el, text) {
  if (el) el.textContent = String(text ?? '');
}

export function row(label, value, cls) {
  return '<tr><td class="key">' + escapeHtml(label) +
         '</td><td class="val' + (cls ? ' ' + cls : '') + '">' +
         escapeHtml(value) + '</td></tr>';
}

export function monoRow(label, value) {
  return '<tr><td class="key">' + escapeHtml(label) +
         '</td><td class="val mono">' + escapeHtml(value) + '</td></tr>';
}

export function el(id) {
  return document.getElementById(id);
}

export function recordFrontendEvent(type, detail = {}) {
  if (window.pywebview && window.pywebview.api && window.pywebview.api.record_frontend_event) {
    window.pywebview.api.record_frontend_event({
      type,
      detail,
      token_present: !!detail.token_present,
    }).catch(function() {});
    return;
  }
  const runtimeConfig = window.__RIG_RELAY_RUNTIME_CONFIG__ || {};
  const handshakeId = runtimeConfig.handshake_id || runtimeConfig.handshakeId || '';
  const detailParam = encodeURIComponent(JSON.stringify(detail || {}));
  const url = `/frontend-event?type=${encodeURIComponent(type)}&handshake_id=${encodeURIComponent(handshakeId)}&detail=${detailParam}`;
  if (typeof fetch === 'function') {
    fetch(url, {
      method: 'GET',
      credentials: 'same-origin',
      cache: 'no-store',
      keepalive: true,
    }).catch(function() {});
  }
}

export function truncate(s, max) {
  if (!s || s.length <= max) return s;
  return s.substring(0, max) + '\u2026';
}

export function formatBytes(bytes) {
  if (bytes == null) return '\u2014';
  const mb = bytes / (1024 * 1024);
  return mb.toFixed(1) + ' MB';
}

export function formatTimestamp(iso) {
  if (!iso) return '\u2014';
  return iso.substring(0, 19).replace('T', ' ');
}

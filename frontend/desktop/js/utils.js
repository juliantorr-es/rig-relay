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

export function setHTML(el, html) {
  if (el) el.innerHTML = html;
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

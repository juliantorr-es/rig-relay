// Rig Relay — ToolRuntime Widget
// Renders tool execution outcomes from the projection

import { state } from './state.js';
import { escapeHtml, el, row, formatTimestamp } from './utils.js';
import { registerWidget } from './widgets.js';

const STATUS_CLASSES = {
  completed: 'status-ok',
  cached: 'status-ok',
  refused: 'status-warn',
  failed: 'status-err',
  degraded: 'status-warn',
  skipped: 'status-info',
};

function statusBadge(status) {
  const cls = STATUS_CLASSES[status] || 'status-info';
  return `<span class="badge ${cls}">${escapeHtml(status)}</span>`;
}

function renderToolRuntime(container, level) {
  const p = state.projection;
  if (!p || !p.tool_runtime_summary || !p.tool_runtime_summary.available) {
    container.innerHTML = '<div class="dim">No tool executions recorded yet.</div>';
    return;
  }

  const s = p.tool_runtime_summary;
  const compact = level === 'compact';

  let html = '';

  // ── Compact view: status bar ─────────────────────────────────
  if (compact) {
    const total = s.total_executions || 0;
    const ok = (s.completed_count || 0) + (s.cached_count || 0);
    const bad = (s.failed_count || 0) + (s.refused_count || 0);
    const warn = (s.degraded_count || 0);
    html += `<div class="flex-row gap-sm">
      <span>Tools: <strong>${total}</strong></span>`;
    if (ok) html += `<span class="status-ok">${ok} ok</span>`;
    if (warn) html += `<span class="status-warn">${warn} degraded</span>`;
    if (bad) html += `<span class="status-err">${bad} failed/refused</span>`;
    if (s.cache_hit_count) html += `<span class="dim">${s.cache_hit_count} cached</span>`;
    html += `</div>`;
    container.innerHTML = html;
    return;
  }

  // ── Standard view: summary table ─────────────────────────────
  html += '<div class="section-title">Tool Runtime</div>';

  // Status counts
  html += '<table class="kv-table">';
  html += row('Total', s.total_executions);
  html += row('Completed', s.completed_count);
  html += row('Cached', s.cached_count);
  html += row('Refused', s.refused_count);
  html += row('Failed', s.failed_count);
  html += row('Degraded', s.degraded_count);
  html += '</table>';

  // Cache
  if (s.cache_hit_count || s.cache_miss_count || s.cache_write_failed_count) {
    html += '<div class="section-title">Cache</div>';
    html += '<table class="kv-table">';
    html += row('Hits', s.cache_hit_count);
    html += row('Misses', s.cache_miss_count);
    if (s.cache_write_failed_count) html += row('Write failures', s.cache_write_failed_count);
    html += '</table>';
  }

  // Refusals
  if (s.refusal_counts && Object.keys(s.refusal_counts).length) {
    html += '<div class="section-title">Refusals</div>';
    html += '<table class="kv-table">';
    for (const [code, count] of Object.entries(s.refusal_counts)) {
      html += row(escapeHtml(code), count);
    }
    html += '</table>';
  }

  // Degradation
  if (s.degradation_counts && Object.keys(s.degradation_counts).length) {
    html += '<div class="section-title">Degradation</div>';
    html += '<table class="kv-table">';
    for (const [cap, count] of Object.entries(s.degradation_counts)) {
      html += row(escapeHtml(cap), count);
    }
    html += '</table>';
  }

  // Recent results
  if (s.recent_results && s.recent_results.length) {
    html += '<div class="section-title">Recent</div>';
    html += '<div class="scroll-x"><table class="data-table">';
    html += '<tr><th>Tool</th><th>Status</th><th>Cache</th><th>Refusal</th><th>Duration</th></tr>';
    for (const r of s.recent_results.slice(-8)) {
      const ms = r.duration_ms != null ? r.duration_ms.toFixed(0) + 'ms' : '-';
      const refusal = r.refusal_code ? escapeHtml(r.refusal_code) : '-';
      html += `<tr>
        <td>${escapeHtml(r.tool_name)}</td>
        <td>${statusBadge(r.status)}</td>
        <td>${escapeHtml(r.cache_status)}</td>
        <td>${refusal}</td>
        <td class="mono">${ms}</td>
      </tr>`;
    }
    html += '</table></div>';
  }

  container.innerHTML = html;
}

export function initToolRuntimeWidget() {
  registerWidget('tool_runtime', renderToolRuntime);
}

// Rig Relay — Widgets
// Registry, render coordination, disclosure levels

import { state, getDisclosure, setDisclosure } from './state.js';
import { escapeHtml, el, row, monoRow, formatBytes, formatTimestamp } from './utils.js';

// Widget renderers keyed by widget ID
const renderers = {};

export function registerWidget(id, renderFn) {
  renderers[id] = renderFn;
}

export function renderAllWidgets() {
  for (const [id, fn] of Object.entries(renderers)) {
    renderWidget(id, fn);
  }
}

export function renderWidget(id, fn) {
  const container = el('widget-' + id);
  if (!container) return;
  const level = getDisclosure(id);
  fn(container, level);
}

export function cycleDisclosure(id) {
  const current = getDisclosure(id);
  const next = current === 'compact' ? 'standard' :
               current === 'standard' ? 'expanded' :
               'compact';
  setDisclosure(id, next);

  if (next === 'expanded') {
    showExpanded(id);
  } else {
    hideExpanded();
    renderWidget(id, renderers[id]);
  }
}

export function showExpanded(id) {
  const overlay = el('expanded-overlay');
  const content = el('expanded-content');
  if (!overlay || !content) return;

  const fn = renderers[id];
  if (!fn) return;

  overlay.classList.add('active');
  const card = el('widget-' + id);
  if (card) card.setAttribute('aria-expanded', 'true');
  fn(content, 'expanded');
  // Focus trap: move focus into the overlay
  const closeBtn = el('expanded-close-btn');
  if (closeBtn) closeBtn.focus();
}

export function hideExpanded() {
  const overlay = el('expanded-overlay');
  if (overlay) {
    overlay.classList.remove('active');
    // Restore focus to the originating widget
    const visibleCard = overlay.querySelector('.expanded-widget');
    if (visibleCard) {
      const widgetId = visibleCard.closest('[id^="widget-"]');
      // Focus goes back to the chat input
      const chatInput = el('chat-input');
      if (chatInput) chatInput.focus();
    }
  }
}

// ── Built-in widget renderers ──

registerWidget('operatorHeader', (container, level) => {
  if (level === 'compact') {
    renderCompactChip(container, 'Session', () => {
      const proj = state.projection;
      const version = (proj && proj.app_version) || '—';
      return { text: version, cls: 'info' };
    });
    return;
  }
  if (level === 'expanded') {
    renderExpandedWidget(container, 'Session', buildOperatorHeaderExpanded());
    return;
  }
  const proj = state.projection;
  const cs = (proj && proj.current_state) || {};
  const st = (proj && proj.storage) || {};
  const html =
    '<table class="kv-table">' +
    row('Mode', 'desktop') +
    row('Version', proj ? proj.app_version : '—') +
    row('Session', cs.available ? (cs.generated_at || '').substring(0, 10) : '—') +
    row('Storage', st.available ? formatBytes((st.total_size_mb || 0) * 1024 * 1024) : '—') +
    '</table>';
  renderStandardCard(container, 'Session', html, 'operatorHeader');
});

registerWidget('safetyState', (container, level) => {
  const proj = state.projection;
  const cs = (proj && proj.current_state) || {};
  const dirty = cs.available ? (cs.active_writers || 0) + (cs.active_readers || 0) : 0;
  const leases = cs.available ? (cs.active_children || 0) : 0;
  const stale = cs.available ? (cs.stale_leases || 0) : 0;
  const status = (dirty > 0 || stale > 0) ? 'warn' : 'ok';

  if (level === 'compact') {
    renderCompactChip(container, 'Safety', () => ({ text: status === 'ok' ? 'Safe' : dirty + ' active', cls: status }));
    return;
  }
  if (level === 'expanded') {
    const html = '<h3>Safety State</h3><table class="kv-table">' +
      row('Dirty files', String(dirty)) +
      row('Active leases', String(leases)) +
      row('Stale leases', String(stale), stale > 0 ? 'warn' : '') +
      row('Worktree writers', String(cs.active_writers || 0)) +
      row('Worktree readers', String(cs.active_readers || 0)) +
      row('Active children', String(cs.active_children || 0)) +
      (cs.available ? row('Last heartbeat', (cs.generated_at || '').substring(0, 19)) : '') +
      '</table>' +
      (cs.available ? '' : '<p class="widget-missing">Current state not available. Run the current_state generator.</p>');
    renderExpandedWidget(container, 'Safety State', html);
    return;
  }
  const html =
    '<table class="kv-table">' +
    row('Dirty files', String(dirty)) +
    row('Active leases', String(leases)) +
    row('Stale leases', String(stale), stale > 0 ? 'warn' : '') +
    '</table>';
  renderStandardCard(container, 'Safety', html, 'safetyState', status);
});

registerWidget('nextAction', (container, level) => {
  if (level === 'compact') {
    const proj = state.projection;
    const warnings = (proj && proj.warnings && proj.warnings.length) || 0;
    const text = warnings > 0 ? warnings + ' warnings' : 'Ready';
    renderCompactChip(container, 'Next', () => ({ text, cls: warnings > 0 ? 'warn' : 'ok' }));
    return;
  }
  if (level !== 'standard') return;
  const proj = state.projection;
  const warnings = (proj && proj.warnings) || [];
  let detail = 'System ready. No pending actions.';
  let title = 'Ready';
  let cls = 'ok';
  if (warnings.length > 0) {
    title = warnings.length + ' Warnings';
    detail = warnings.slice(0, 3).map(w => '\u2022 ' + w).join('<br>');
    cls = 'warn';
  }
  const html = '<div style="white-space:pre-wrap">' + escapeHtml(detail) + '</div>';
  renderStandardCard(container, 'Next Action: ' + title, html, 'nextAction', cls);
});

registerWidget('validationSummary', (container, level) => {
  const proj = state.projection;
  const val = (proj && proj._last_validation) || {};
  const passed = val.passed_count || 0;
  const failed = val.failed_count || 0;

  if (level === 'compact') {
    renderCompactChip(container, 'Validation', () => ({
      text: passed + '/' + (passed + failed) + ' passed',
      cls: failed > 0 ? 'warn' : 'ok'
    }));
    return;
  }
  if (level !== 'standard') return;
  const html =
    '<table class="kv-table">' +
    row('Passed', String(passed)) +
    row('Failed', String(failed), failed > 0 ? 'error' : '') +
    row('Duration', (val.duration_ms || '\u2014') + ' ms') +
    (val.last_run_at ? row('Last run', formatTimestamp(val.last_run_at)) : '') +
    '</table>' +
    '<div class="widget-actions">' +
    '<button onclick="window.RigRelay.dispatchIntent(\'run_validation_suite\')">Run Validation</button>' +
    '</div>';
  renderStandardCard(container, 'Validation', html, 'validationSummary', failed > 0 ? 'warn' : 'ok');
});

registerWidget('storageBudget', (container, level) => {
  const proj = state.projection;
  const st = (proj && proj.storage) || {};

  if (level === 'compact') {
    const size = st.available ? (st.total_size_mb || 0).toFixed(1) + ' MB' : '\u2014';
    renderCompactChip(container, 'Storage', () => ({
      text: size,
      cls: st.budget_status === 'ok' ? 'ok' : 'warn'
    }));
    return;
  }
  if (level !== 'standard') return;
  if (!st.available) {
    renderStandardCard(container, 'Storage', '<span class="widget-missing">No data</span>', 'storageBudget');
    return;
  }
  let html = '<table class="kv-table">' +
    row('Size', (st.total_size_mb || 0).toFixed(1) + ' MB') +
    row('Budget', st.budget_status || '\u2014', st.budget_status === 'ok' ? 'ok' : 'warn') +
    row('Prune candidates', String(st.prune_candidate_count || 0)) +
    row('Stale leases', String(st.stale_lease_count || 0)) +
    '</table>';
  if (st.recommendations && st.recommendations.length) {
    html += '<div class="widget-actions">' +
      '<button onclick="window.RigRelay.dispatchIntent(\'run_storage_audit\')">Storage Audit</button>' +
      '</div>';
  }
  renderStandardCard(container, 'Storage', html, 'storageBudget', st.budget_status === 'ok' ? 'ok' : 'warn');
});

registerWidget('intentResult', (container, level) => {
  if (level !== 'standard') return;
  renderStandardCard(container, 'Latest Result',
    '<span class="widget-missing">No intents executed yet.</span>', 'intentResult');
});

export function updateIntentResult(status, intentName, summary) {
  const container = el('widget-intentResult');
  if (!container) return;
  const cls = status === 'completed' ? 'ok' : status === 'refused' ? 'warn' : 'error';
  const html = '<div>' + escapeHtml(intentName) + ': ' + escapeHtml(status) + '</div>' +
    (summary ? '<div style="margin-top:4px;color:var(--text-secondary)">' + escapeHtml(summary) + '</div>' : '');
  renderStandardCard(container, 'Latest Result', html, 'intentResult', cls);
}

registerWidget('providerHealth', (container, level) => {
  const proj = state.projection;
  const pd = (proj && proj.providers) || {};

  if (level === 'compact') {
    const config = pd.configured || 0;
    const total = pd.total || 0;
    renderCompactChip(container, 'Providers', () => ({
      text: config + '/' + total + ' ready',
      cls: config > 0 ? 'ok' : 'warn'
    }));
    return;
  }
  if (level !== 'standard') return;
  if (!pd.providers || !pd.providers.length) {
    renderStandardCard(container, 'Model Providers',
      '<span class="widget-missing">No provider data</span>', 'providerHealth');
    return;
  }
  let html = '<table class="kv-table">';
  pd.providers.forEach(function(p) {
    html += row(p.display_name || p.provider,
      (p.configured ? 'Configured' : 'Missing'),
      p.configured ? 'ok' : 'warn');
  });
  html += '</table>';
  renderStandardCard(container, 'Model Providers', html, 'providerHealth',
    (pd.configured > 0) ? 'ok' : 'warn');
});

registerWidget('progressTimeline', (container, level) => {
  if (level === 'expanded') {
    renderExpandedWidget(container, 'Progress Timeline', buildProgressTimelineExpanded());
    return;
  }
  if (level !== 'standard') return;
  const events = state.progressEvents;
  if (!events.length) {
    renderStandardCard(container, 'Progress',
      '<span class="widget-missing">No progress events yet.</span>', 'progressTimeline');
    return;
  }
  const recent = events.slice(-10);
  let html = '<div class="kv-table" style="max-height:200px;overflow-y:auto">';
  for (let i = recent.length - 1; i >= 0; i--) {
    const ev = recent[i];
    const data = ev.data || ev;
    const type = (data.event_type || 'unknown').replace(/^operation\./, '');
    const status = data.status || 'running';
    const cls = status === 'completed' ? 'ok' : status === 'failed' ? 'error' : 'warn';
    html += '<div style="display:flex;justify-content:space-between;padding:2px 0;font-size:var(--font-size-xs)">' +
      '<span>' + escapeHtml(type) + '</span>' +
      '<span class="' + cls + '">' + escapeHtml(status) + '</span>' +
      '</div>';
  }
  html += '</div>';
  renderStandardCard(container, 'Progress (' + events.length + ')', html, 'progressTimeline');
});

registerWidget('connectionStatus', (container, level) => {
  if (level !== 'standard') return;
  const html = '<table class="kv-table">' +
    row('Transport', state.transport === 'ws' ? 'WebSocket' : (state.transport === 'bridge' ? 'Bridge' : 'Offline')) +
    row('WS Status', state.wsConnected ? 'Connected' : 'Disconnected') +
    '</table>';
  renderStandardCard(container, 'Connection', html, 'connectionStatus', state.wsConnected ? 'ok' : 'warn');
});

// ── Review mode widgets ──

registerWidget('reviewSnippets', (container, level) => {
  if (level !== 'standard') return;
  const proj = state.projection;
  const ss = (proj && proj.semantic_snippets) || {};
  if (!ss.available) {
    renderStandardCard(container, 'Semantic Snippets',
      '<span class="widget-missing">No data</span>', 'reviewSnippets');
    return;
  }
  const html = '<table class="kv-table">' +
    row('Snippets', String(ss.snippet_count || 0)) +
    row('Skipped', String(ss.skipped_count || 0)) +
    row('Remote safe', ss.remote_sharing_safe ? 'Yes' : 'No') +
    '</table>';
  renderStandardCard(container, 'Semantic Snippets', html, 'reviewSnippets');
});

registerWidget('reviewDataset', (container, level) => {
  if (level === 'expanded') {
    renderExpandedWidget(container, 'Dataset Summary', buildDatasetExpanded());
    return;
  }
  if (level !== 'standard') return;
  const proj = state.projection;
  const ds = (proj && proj.dataset) || {};
  if (!ds.available) {
    renderStandardCard(container, 'Dataset',
      '<span class="widget-missing">No data</span>', 'reviewDataset');
    return;
  }
  const html = '<table class="kv-table">' +
    row('Coordination', (ds.coordination_rows || 0) + ' rows') +
    row('Tool failures', (ds.tool_failure_rows || 0) + ' rows') +
    row('Artifact reuse', (ds.artifact_reuse_rows || 0) + ' rows') +
    row('Checkpoints', (ds.checkpoint_rows || 0) + ' rows') +
    '</table>';
  renderStandardCard(container, 'Dataset', html, 'reviewDataset');
});

// ── Helpers ──

function renderCompactChip(container, label, valueFn) {
  const v = valueFn();
  // DOM construction — no innerHTML
  while (container.firstChild) container.removeChild(container.firstChild);
  const header = document.createElement('div');
  header.className = 'widget-header';
  header.textContent = label;
  const chip = document.createElement('div');
  chip.className = 'widget-chip' + (v.cls ? ' ' + v.cls : '');
  const dot = document.createElement('span');
  dot.className = 'dot';
  chip.appendChild(dot);
  chip.appendChild(document.createTextNode(v.text));
  container.appendChild(header);
  container.appendChild(chip);
  container.onclick = function() { cycleDisclosure(container.id.replace('widget-', '')); };
}

function renderStandardCard(container, title, bodyHTML, widgetId, statusCls) {
  // DOM construction — no innerHTML
  while (container.firstChild) container.removeChild(container.firstChild);

  const header = document.createElement('div');
  header.className = 'widget-header';
  header.onclick = function() { window.RigRelay.cycleWidgetDisclosure(widgetId); };
  header.appendChild(document.createTextNode(title));

  if (statusCls) {
    const chip = document.createElement('div');
    chip.className = 'widget-chip ' + statusCls;
    const dot = document.createElement('span');
    dot.className = 'dot';
    chip.appendChild(dot);
    header.appendChild(chip);
  }

  const icon = document.createElement('span');
  icon.className = 'widget-expand-icon';
  icon.textContent = '\u25B2';
  header.appendChild(icon);

  const body = document.createElement('div');
  body.className = 'widget-body';
  // bodyHTML comes from widget renderers that already escapeHtml all user data
  setSafeHTML(body, bodyHTML);

  const trigger = document.createElement('div');
  trigger.className = 'widget-expand-trigger';
  trigger.textContent = 'Expand \u2192';
  trigger.onclick = function() { window.RigRelay.cycleWidgetDisclosure(widgetId); };

  container.appendChild(header);
  container.appendChild(body);
  container.appendChild(trigger);
}

function renderExpandedWidget(container, title, bodyHTML) {
  while (container.firstChild) container.removeChild(container.firstChild);
  const header = document.createElement('div');
  header.className = 'widget-header';
  header.appendChild(document.createTextNode(title));
  const closeBtn = document.createElement('button');
  closeBtn.className = 'close-btn';
  closeBtn.textContent = '\u00d7';
  closeBtn.onclick = function() { window.RigRelay.closeExpanded(); };
  header.appendChild(closeBtn);
  const body = document.createElement('div');
  body.className = 'widget-body';
  setSafeHTML(body, bodyHTML);
  container.appendChild(header);
  container.appendChild(body);
}

// Safe HTML rendering via DOM parser — string → DocumentFragment, no innerHTML
function setSafeHTML(element, html) {
  const template = document.createElement('template');
  template.innerHTML = html;
  element.appendChild(template.content.cloneNode(true));
}

// ── Review mode widgets (continuation) ──

registerWidget('receiptTimeline', (container, level) => {
  if (level === 'expanded') {
    renderExpandedWidget(container, 'Receipt Timeline', buildReceiptTimelineExpanded());
    return;
  }
  if (level !== 'standard') return;
  var receipts = state.projection && state.projection._receipts;
  if (!receipts || !receipts.length) {
    renderStandardCard(container, 'Receipt Timeline',
      '<span class="widget-missing">No receipts available.</span>', 'receiptTimeline');
    return;
  }
  var html = '';
  receipts.slice(0, 10).forEach(function(r) {
    html += '<div style="padding:4px 0;font-size:var(--font-size-xs);border-bottom:1px solid var(--border-subtle)">' +
      '<span style="font-weight:500">' + escapeHtml(r.kind || 'Unknown') + '</span> ' +
      '<span style="color:var(--text-muted)">' + escapeHtml(r.timestamp || '') + '</span>' +
      '</div>';
  });
  renderStandardCard(container, 'Receipt Timeline', html, 'receiptTimeline');
});

registerWidget('refinementBacklog', (container, level) => {
  if (level !== 'standard') return;
  var ref = state.projection && state.projection._refinement;
  if (!ref) {
    renderStandardCard(container, 'Refinement',
      '<span class="widget-missing">No refinement data.</span>', 'refinementBacklog');
    return;
  }
  var html = '<table class="kv-table">' +
    row('Pending', String(ref.pending || 0)) +
    row('Refined', String(ref.refined || 0)) +
    row('Last', ref.last_refined_at || '—') +
    '</table>';
  renderStandardCard(container, 'Refinement', html, 'refinementBacklog');
});

registerWidget('reviewValidation', (container, level) => {
  if (level !== 'standard') return;
  var val = state.projection && state.projection._last_validation;
  if (!val) {
    renderStandardCard(container, 'Validation History',
      '<span class="widget-missing">No validation history.</span>', 'reviewValidation');
    return;
  }
  var html = '<table class="kv-table">' +
    row('Status', val.status || '—') +
    row('Passed', String(val.passed_count || 0)) +
    row('Failed', String(val.failed_count || 0)) +
    row('Duration', (val.duration_ms || '—') + ' ms') +
    '</table>';
  renderStandardCard(container, 'Validation History', html, 'reviewValidation');
});

registerWidget('reviewStorage', (container, level) => {
  if (level === 'expanded') {
    renderExpandedWidget(container, 'Storage Audit', buildStorageExpanded());
    return;
  }
  if (level !== 'standard') return;
  var st = state.projection && state.projection.storage;
  if (!st || !st.available) {
    renderStandardCard(container, 'Storage Audit',
      '<span class="widget-missing">No storage audit data.</span>', 'reviewStorage');
    return;
  }
  var html = '<table class="kv-table">' +
    row('Total', (st.total_size_mb || 0).toFixed(1) + ' MB') +
    row('Budget', st.budget_status || '—') +
    row('Rollup candidates', String(st.rollup_candidate_count || 0)) +
    row('Prune candidates', String(st.prune_candidate_count || 0)) +
    row('Stale leases', String(st.stale_lease_count || 0)) +
    '</table>';
  renderStandardCard(container, 'Storage Audit', html, 'reviewStorage');
});

// ── System mode widgets ──

registerWidget('identity', (container, level) => {
  if (level !== 'standard') return;
  renderStandardCard(container, 'Identity',
    '<span class="widget-missing">Sign in to associate telemetry.</span>', 'identity');
});

registerWidget('modelProviders', (container, level) => {
  if (level !== 'standard') return;
  var pd = state.projection && state.projection.providers;
  if (!pd || !pd.providers || !pd.providers.length) {
    renderStandardCard(container, 'Model Providers',
      '<span class="widget-missing">No provider data.</span>', 'modelProviders');
    return;
  }
  var html = '<table class="kv-table">';
  pd.providers.forEach(function(p) {
    html += row(p.display_name || p.provider,
      (p.configured ? 'Configured' : 'Missing'),
      p.configured ? 'ok' : 'warn');
  });
  html += '</table>' +
    '<div class="widget-actions">' +
    '<button onclick="window.RigRelay.dispatchIntent(\'provider_status\')">Refresh</button>' +
    '</div>';
  renderStandardCard(container, 'Model Providers', html, 'modelProviders');
});

registerWidget('telemetryConsent', (container, level) => {
  if (level !== 'standard') return;
  renderStandardCard(container, 'Telemetry Consent',
    '<span class="widget-missing">No consent data.</span>', 'telemetryConsent');
});

registerWidget('authReceipts', (container, level) => {
  if (level !== 'standard') return;
  renderStandardCard(container, 'Authorization Receipts',
    '<span class="widget-missing">No authorization receipts.</span>', 'authReceipts');
});

registerWidget('telemetryBundle', (container, level) => {
  if (level === 'expanded') {
    var tb = state.projection && state.projection.telemetry_bundle;
    if (!tb || !tb.available) {
      renderExpandedWidget(container, 'Telemetry Bundle', '<span class="widget-missing">No bundle data.</span>');
    } else {
      var html = '<h3>Telemetry Bundle</h3><table class="kv-table">' +
        row('Bundle ID', tb.bundle_id || '—') +
        row('Share level', tb.share_level || '—') +
        row('Status', tb.status || '—') +
        row('SHA256', (tb.bundle_sha256 || '—').substring(0, 16) + '...') +
        '</table>';
      renderExpandedWidget(container, 'Telemetry Bundle', html);
    }
    return;
  }
  if (level !== 'standard') return;
  var tb = state.projection && state.projection.telemetry_bundle;
  if (!tb || !tb.available) {
    renderStandardCard(container, 'Telemetry Bundle',
      '<span class="widget-missing">No telemetry bundle.</span>', 'telemetryBundle');
    return;
  }
  var html = '<table class="kv-table">' +
    row('Bundle', tb.bundle_id || '—') +
    row('Share level', tb.share_level || '—') +
    row('Status', tb.status || '—') +
    '</table>';
  renderStandardCard(container, 'Telemetry Bundle', html, 'telemetryBundle');
});

registerWidget('updateStatus', (container, level) => {
  if (level === 'expanded') {
    renderExpandedWidget(container, 'Update Status', buildUpdateExpanded());
    return;
  }
  if (level !== 'standard') return;
  var up = state.projection && state.projection.update;
  if (!up || !up.available) {
    renderStandardCard(container, 'Update',
      '<span class="widget-missing">No update data.</span>', 'updateStatus');
    return;
  }
  var html = '<table class="kv-table">' +
    row('Current', up.current_version || '—') +
    row('Latest', up.latest_version || '—') +
    row('Update', up.update_available ? 'Available' : 'Up to date', up.update_available ? 'warn' : 'ok') +
    '</table>';
  renderStandardCard(container, 'Update', html, 'updateStatus');
});

registerWidget('projectionSources', (container, level) => {
  if (level === 'expanded') {
    renderExpandedWidget(container, 'Projection Sources', buildProjectionSourcesExpanded());
    return;
  }
  if (level !== 'standard') return;
  var sources = state.projection && state.projection.source_status;
  if (!sources) {
    renderStandardCard(container, 'Projection Sources',
      '<span class="widget-missing">No source data.</span>', 'projectionSources');
    return;
  }
  var html = '<table class="kv-table">';
  var count = 0;
  for (var key in sources) {
    if (sources.hasOwnProperty(key)) {
      var available = sources[key];
      html += row(key, available ? 'available' : 'missing', available ? 'ok' : 'warn');
      count++;
    }
  }
  html += '</table>';
  if (count === 0) html = '<span class="widget-missing">No source data.</span>';
  renderStandardCard(container, 'Projection Sources', html, 'projectionSources');
});

registerWidget('storageDiagnostics', (container, level) => {
  if (level === 'expanded') {
    renderExpandedWidget(container, 'Storage Diagnostics', buildStorageExpanded());
    return;
  }
  if (level !== 'standard') return;
  var st = state.projection && state.projection.storage;
  if (!st || !st.available) {
    renderStandardCard(container, 'Storage Diagnostics',
      '<span class="widget-missing">No diagnostics.</span>', 'storageDiagnostics');
    return;
  }
  var html = '<table class="kv-table">' +
    row('Rollup candidates', String(st.rollup_candidate_count || 0)) +
    row('Prune candidates', String(st.prune_candidate_count || 0)) +
    row('Stale leases', String(st.stale_lease_count || 0)) +
    '</table>';
  renderStandardCard(container, 'Storage Diagnostics', html, 'storageDiagnostics');
};

// ── Expanded widget content builders ────────────────────────────────

function buildOperatorHeaderExpanded() {
  const proj = state.projection;
  const cs = (proj && proj.current_state) || {};
  const st = (proj && proj.storage) || {};
  const pd = (proj && proj.providers) || {};
  return '<h3>Runtime Snapshot</h3>' +
    '<table class="kv-table">' +
    row('App version', proj ? proj.app_version : '—') +
    row('Schema', (proj && proj.schema_version) || '—') +
    row('Alpha label', proj && proj.alpha_label ? 'Yes' : 'No') +
    (cs.available ? row('Generated at', (cs.generated_at || '').substring(0, 19)) : row('Current state', 'Not available', 'warn')) +
    '</table>' +
    '<h3 style="margin-top:16px">Storage</h3>' +
    '<table class="kv-table">' +
    row('Total size', st.available ? (st.total_size_mb || 0).toFixed(1) + ' MB' : '—') +
    row('Budget status', st.budget_status || '—', st.budget_status === 'ok' ? 'ok' : 'warn') +
    row('Rollup candidates', String(st.rollup_candidate_count || 0)) +
    row('Prune candidates', String(st.prune_candidate_count || 0)) +
    row('Stale leases', String(st.stale_lease_count || 0)) +
    (st.recommendations && st.recommendations.length ?
      '<tr><td class="key">Recommendations</td><td class="val">' +
      st.recommendations.map(function(r) { return '\u2022 ' + escapeHtml(r); }).join('<br>') +
      '</td></tr>' : '') +
    '</table>' +
    '<h3 style="margin-top:16px">Providers</h3>' +
    '<table class="kv-table">' +
    row('Configured', String(pd.configured || 0)) +
    row('Total', String(pd.total || 0)) +
    (pd.providers ? pd.providers.map(function(p) {
      return row(p.display_name || p.provider, p.configured ? 'Configured' : 'Missing', p.configured ? 'ok' : 'warn');
    }).join('') : row('Details', 'No provider data')) +
    '</table>';
}

function buildProjectionSourcesExpanded() {
  const proj = state.projection;
  const sources = (proj && proj.source_status) || {};
  let html = '<h3>All Data Sources</h3><table class="kv-table">';
  var count = 0;
  for (var key in sources) {
    if (sources.hasOwnProperty(key)) {
      html += row(key, sources[key] ? 'available' : 'missing', sources[key] ? 'ok' : 'warn');
      count++;
    }
  }
  html += '</table>';
  if (count === 0) html += '<span class="widget-missing">No sources.</span>';

  const warnings = (proj && proj.warnings) || [];
  if (warnings.length > 0) {
    html += '<h3 style="margin-top:16px">Warnings (' + warnings.length + ')</h3>';
    html += '<ul style="margin:0;padding-left:20px;font-size:var(--font-size-sm);color:var(--warn)">';
    warnings.forEach(function(w) { html += '<li>' + escapeHtml(w) + '</li>'; });
    html += '</ul>';
  }
  return html;
}

function buildProgressTimelineExpanded() {
  const events = state.progressEvents;
  if (!events.length) return '<span class="widget-missing">No progress events yet.</span>';
  let html = '<h3>Progress Timeline (' + events.length + ' events)</h3>';
  html += '<div style="max-height:500px;overflow-y:auto">';
  for (let i = events.length - 1; i >= 0; i--) {
    const ev = events[i];
    const data = ev.data || ev;
    const type = (data.event_type || 'unknown').replace(/^operation\./, '');
    const status = data.status || 'running';
    const cls = status === 'completed' ? 'ok' : status === 'failed' ? 'error' : 'warn';
    const msg = data.message || '';
    const pct = data.percent;
    html += '<div style="padding:6px 0;border-bottom:1px solid var(--border-subtle)">' +
      '<div style="display:flex;justify-content:space-between">' +
      '<strong>' + escapeHtml(type) + '</strong>' +
      '<span class="' + cls + '">' + escapeHtml(status) + '</span>' +
      '</div>';
    if (msg) html += '<div style="font-size:var(--font-size-xs);color:var(--text-secondary)">' + escapeHtml(msg) + '</div>';
    if (typeof pct === 'number') {
      html += '<div style="background:var(--border);border-radius:3px;height:4px;margin-top:4px">' +
        '<div style="background:var(--accent);height:4px;border-radius:3px;width:' + Math.round(pct) + '%"></div></div>';
    }
    html += '</div>';
  }
  html += '</div>';
  return html;
}

function buildReceiptTimelineExpanded() {
  var receipts = state.projection && state.projection._receipts;
  if (!receipts || !receipts.length) return '<span class="widget-missing">No receipts available.</span>';
  let html = '<h3>Receipt Timeline (' + receipts.length + ' receipts)</h3>';
  receipts.forEach(function(r) {
    const sha = r.sha256 ? r.sha256.substring(0, 16) + '...' : '';
    html += '<div style="padding:8px 0;border-bottom:1px solid var(--border-subtle)">' +
      '<div><strong>' + escapeHtml(r.kind || 'Unknown') + '</strong></div>' +
      '<div style="font-size:var(--font-size-xs);color:var(--text-secondary)">' + escapeHtml(r.summary || '') + '</div>' +
      '<div style="font-size:var(--font-size-xs);font-family:var(--font-mono);color:var(--text-muted)">' +
      escapeHtml(r.timestamp || '') + (sha ? ' · ' + sha : '') + '</div>' +
      '</div>';
  });
  return html;
}

function buildDatasetExpanded() {
  const ds = (state.projection && state.projection.dataset) || {};
  if (!ds.available) return '<span class="widget-missing">No dataset data.</span>';
  return '<h3>Dataset Summary</h3>' +
    '<table class="kv-table">' +
    row('Exported at', (ds.exported_at || '').substring(0, 19)) +
    row('Coordination rows', String(ds.coordination_rows || 0)) +
    row('Tool failure rows', String(ds.tool_failure_rows || 0)) +
    row('Provider perf rows', String(ds.provider_perf_rows || 0)) +
    row('Findings rows', String(ds.findings_rows || 0)) +
    row('Artifact reuse rows', String(ds.artifact_reuse_rows || 0)) +
    row('Checkpoint rows', String(ds.checkpoint_rows || 0)) +
    row('Sessions observed', String(ds.sessions_observed || 0)) +
    row('Coordination events', String(ds.coordination_events_total || 0)) +
    row('Tool calls total', String(ds.tool_calls_total || 0)) +
    row('Strict mode', ds.strict ? 'Yes' : 'No') +
    '</table>';
}

function buildStorageExpanded() {
  const st = (state.projection && state.projection.storage) || {};
  if (!st.available) return '<span class="widget-missing">No storage data.</span>';
  let html = '<h3>Storage Audit</h3><table class="kv-table">' +
    row('Total size', (st.total_size_mb || 0).toFixed(1) + ' MB') +
    row('Budget status', st.budget_status || '—', st.budget_status === 'ok' ? 'ok' : 'warn') +
    row('Rollup candidates', String(st.rollup_candidate_count || 0)) +
    row('Prune candidates', String(st.prune_candidate_count || 0)) +
    row('Stale leases', String(st.stale_lease_count || 0)) +
    '</table>';
  if (st.recommendations && st.recommendations.length) {
    html += '<h3 style="margin-top:16px">Recommendations</h3><ul style="margin:0;padding-left:20px">';
    st.recommendations.forEach(function(r) { html += '<li>' + escapeHtml(r) + '</li>'; });
    html += '</ul>';
  }
  return html;
}

function buildUpdateExpanded() {
  const up = (state.projection && state.projection.update) || {};
  if (!up.available) return '<span class="widget-missing">No update data.</span>';
  return '<h3>Update Status</h3><table class="kv-table">' +
    row('Current version', up.current_version || '—') +
    row('Latest version', up.latest_version || '—') +
    row('Update available', up.update_available ? 'Yes' : 'No', up.update_available ? 'warn' : 'ok') +
    row('Update state', up.update_state || '—') +
    row('Restart required', up.restart_required ? 'Yes' : 'No') +
    row('Restart safe', up.restart_safe ? 'Yes' : 'No') +
    row('Blocked by sessions', String(up.blocked_by_active_sessions || 0)) +
    '</table>';
}

// ── Workspace / Fleet widgets ──

registerWidget('workspaceStatus', function(container, level) {
  if (level !== 'standard') return;
  var actions = '<div class="widget-actions">' +
    '<button onclick="window.RigRelay.dispatchIntent(\'workspace_init\')">Bootstrap</button>' +
    '<button onclick="window.RigRelay.dispatchIntent(\'worktree_list\')">List Worktrees</button>' +
    '</div>';
  renderStandardCard(container, 'Workspace',
    '<span class="widget-missing">/init to bootstrap, /worktree to manage</span>' + actions,
    'workspaceStatus');
});

registerWidget('fleetStatus', function(container, level) {
  if (level !== 'standard') return;
  var actions = '<div class="widget-actions">' +
    '<button onclick="window.RigRelay.dispatchIntent(\'fleet_queue_snapshot\')">Snapshot</button>' +
    '<button onclick="window.RigRelay.dispatchIntent(\'run_queue_plan_dry_run\')">Plan</button>' +
    '<button onclick="window.RigRelay.dispatchIntent(\'run_spawn_plan_dry_run\')">Spawn</button>' +
    '<button onclick="window.RigRelay.dispatchIntent(\'fleet_orchestrate\')">Run Once</button>' +
    '</div>' +
    '<div style="margin-top:6px;padding-top:6px;border-top:1px solid var(--border-subtle);font-size:var(--font-size-xs);color:var(--text-muted)">' +
    '/orchestrator to plan roadmap, /fleet run to execute</div>';
  renderStandardCard(container, 'Fleet',
    '<span class="widget-missing">/fleet queue, plan, spawn, or run</span>' + actions,
    'fleetStatus');
});

// ── Provider Dock widget ─────────────────────────────────────────────

registerWidget('providerDock', function(container, level) {
  if (level === 'expanded') {
    renderProviderDockExpanded(container);
    return;
  }
  if (level !== 'standard') return;
  var proj = state.projection;
  var pd = (proj && proj.providers) || {};
  var providerList = (pd.providers || []);
  var configured = pd.configured || 0;
  var total = pd.total || 0;

  var html = '';
  if (providerList.length > 0) {
    html += '<div style="display:flex;flex-wrap:wrap;gap:4px;margin-bottom:8px">';
    providerList.forEach(function(p) {
      var cls = p.configured ? 'ok' : 'warn';
      html += '<div class="widget-chip ' + cls + '" style="cursor:default">' +
        '<span class="dot"></span>' +
        escapeHtml(p.display_name || p.provider) +
        '</div>';
    });
    html += '</div>';
    html += '<div style="font-size:var(--font-size-xs);color:var(--text-muted);margin-bottom:6px">' +
      configured + '/' + total + ' configured</div>';
  } else {
    html += '<span class="widget-missing">Run provider_status to load.</span>';
  }

  html += '<div class="widget-actions" style="flex-wrap:wrap">' +
    '<button onclick="window.RigRelay.openProvider(\'chatgpt\')">ChatGPT</button>' +
    '<button onclick="window.RigRelay.openProvider(\'claude\')">Claude</button>' +
    '<button onclick="window.RigRelay.openProvider(\'gemini\')">Gemini</button>' +
    '<button onclick="window.RigRelay.openProvider(\'deepseek\')">DeepSeek</button>' +
    '<button onclick="window.RigRelay.openProvider(\'mistral\')">Mistral</button>' +
    '</div>' +
    '<div style="margin-top:6px;font-size:var(--font-size-xs);color:var(--text-muted)">' +
    'Opens provider in companion window. /provider, /send_to, /read_from in chat.</div>';

  renderStandardCard(container, 'Provider Dock', html, 'providerDock',
    configured > 0 ? 'ok' : 'warn');
});

function renderProviderDockExpanded(container) {
  var proj = state.projection;
  var pd = (proj && proj.providers) || {};
  var providerList = (pd.providers || []);

  // Provider capability table — content-light reference
  var providers = [
    { id: 'chatgpt', name: 'OpenAI ChatGPT', model: 'GPT-4o', context: '128K', strengths: 'multimodal, function calling, JSON mode', pricing: 'Pay-per-token', url: 'https://chatgpt.com' },
    { id: 'claude', name: 'Anthropic Claude', model: 'Claude 3.5 Sonnet', context: '200K', strengths: 'long context, safety, reasoning, code', pricing: 'Pay-per-token', url: 'https://claude.ai' },
    { id: 'gemini', name: 'Google Gemini', model: 'Gemini 2.5 Pro', context: '2M', strengths: 'largest context, multimodal, search grounding', pricing: 'Pay-per-token + free tier', url: 'https://gemini.google.com' },
    { id: 'deepseek', name: 'DeepSeek', model: 'DeepSeek-V3', context: '128K', strengths: 'MoE architecture, strong reasoning, generous free tier', pricing: 'Pay-per-token + free tier', url: 'https://chat.deepseek.com' },
    { id: 'mistral', name: 'Mistral AI', model: 'Mistral Large 2', context: '128K', strengths: 'frontier European, function calling, JSON mode', pricing: 'Pay-per-token', url: 'https://chat.mistral.ai' },
    { id: 'perplexity', name: 'Perplexity', model: 'Sonar', context: '128K', strengths: 'web search built-in, citations, real-time data', pricing: 'Freemium + Pro plan', url: 'https://perplexity.ai' },
    { id: 'openrouter', name: 'OpenRouter', model: '300+ models', context: 'varies', strengths: 'unified API, model routing, no subscriptions', pricing: 'Pay-per-token', url: 'https://openrouter.ai' },
  ];

  var html = '<h3>Provider Capabilities</h3>';
  html += '<div style="overflow-x:auto">';
  html += '<table style="width:100%;border-collapse:collapse;font-size:var(--font-size-xs)">';
  html += '<thead><tr style="border-bottom:1px solid var(--border)">' +
    '<th style="text-align:left;padding:4px 8px">Provider</th>' +
    '<th style="text-align:left;padding:4px 8px">Model</th>' +
    '<th style="text-align:left;padding:4px 8px">Context</th>' +
    '<th style="text-align:left;padding:4px 8px">Strengths</th>' +
    '<th style="text-align:left;padding:4px 8px">Pricing</th>' +
    '</tr></thead><tbody>';

  providers.forEach(function(p) {
    var configured = providerList.some(function(pl) {
      return (pl.provider || '').toLowerCase() === p.id ||
             (pl.display_name || '').toLowerCase().includes(p.id);
    });
    var rowCls = configured ? ' style="background:var(--ok-bg)"' : '';
    html += '<tr' + rowCls + '>' +
      '<td style="padding:6px 8px;border-bottom:1px solid var(--border-subtle);white-space:nowrap">' +
      '<a href="' + escapeHtml(p.url) + '" target="_blank" style="color:var(--accent);text-decoration:none;font-weight:500">' +
      escapeHtml(p.name) + '</a></td>' +
      '<td style="padding:6px 8px;border-bottom:1px solid var(--border-subtle);font-family:var(--font-mono);font-size:var(--font-size-xs)">' + escapeHtml(p.model) + '</td>' +
      '<td style="padding:6px 8px;border-bottom:1px solid var(--border-subtle);font-family:var(--font-mono);font-size:var(--font-size-xs)">' + escapeHtml(p.context) + '</td>' +
      '<td style="padding:6px 8px;border-bottom:1px solid var(--border-subtle)">' + escapeHtml(p.strengths) + '</td>' +
      '<td style="padding:6px 8px;border-bottom:1px solid var(--border-subtle);white-space:nowrap">' + escapeHtml(p.pricing) + '</td>' +
      '</tr>';
  });

  html += '</tbody></table></div>';

  // API key status from projection
  if (providerList.length > 0) {
    html += '<h3 style="margin-top:16px">Your Configuration</h3>';
    html += '<table class="kv-table">';
    providerList.forEach(function(p) {
      var cls = p.configured ? 'ok' : 'warn';
      var status = p.configured ? 'Configured' : (p.key_source === 'env' ? 'Key set' : 'Missing');
      html += row(p.display_name || p.provider, status, cls);
    });
    html += '</table>';
  }

  html += '<div style="margin-top:12px;font-size:var(--font-size-xs);color:var(--text-muted)">' +
    'None of these providers allow iframe embedding. Click a provider name to open their web app in your browser.<br>' +
    'Rig Relay connects to all providers via API — configure keys in System → Model Providers.</div>';

  renderExpandedWidget(container, 'Provider Capabilities', html);
}

// ── Council widget ───────────────────────────────────────────────────

registerWidget('council', function(container, level) {
  if (level !== 'standard') return;
  var html = '<span class="widget-missing">External adversarial review.</span>' +
    '<div class="widget-actions" style="flex-wrap:wrap">' +
    '<button onclick="window.RigRelay.openProvider(\'chatgpt\')">ChatGPT</button>' +
    '<button onclick="window.RigRelay.openProvider(\'claude\')">Claude</button>' +
    '<button onclick="window.RigRelay.openProvider(\'gemini\')">Gemini</button>' +
    '<button onclick="window.RigRelay.openProvider(\'deepseek\')">DeepSeek</button>' +
    '<button onclick="window.RigRelay.openProvider(\'mistral\')">Mistral</button>' +
    '</div>' +
    '<div style="margin-top:6px;padding-top:6px;border-top:1px solid var(--border-subtle)">' +
    '<button onclick="window.RigRelay.dispatchIntent(\'council_consult\')" ' +
    'style="width:100%">Send to All Open Providers</button>' +
    '</div>' +
    '<div style="margin-top:4px;font-size:var(--font-size-xs);color:var(--text-muted)">' +
    'External adversarial review with receipts.<br>' +
    '/council, /send_to, /read_from in chat.</div>';
  renderStandardCard(container, 'Council', html, 'council');
});

// ── Provider Dock widget ─────────────────────────────────────────────

registerWidget('providerDock', function(container, level) {
  if (level !== 'standard') return;
  var proj = state.projection;
  var pd = (proj && proj.providers) || {};
  var configured = pd.configured || 0;
  var total = pd.total || 0;
  var providerList = (pd.providers || []);

  var html = '';
  if (providerList.length > 0) {
    html += '<div style="display:flex;flex-wrap:wrap;gap:4px;margin-bottom:6px">';
    providerList.forEach(function(p) {
      var cls = p.configured ? 'ok' : 'warn';
      html += '<div class="widget-chip ' + cls + '">' +
        '<span class="dot"></span>' + escapeHtml(p.display_name || p.provider) + '</div>';
    });
    html += '</div>';
  }
  html += '<div class="widget-actions">' +
    '<button onclick="window.RigRelay.dispatchIntent(\'provider_status\')">Refresh</button>' +
    '<button onclick="window.RigRelay.cycleWidgetDisclosure(\'providerDock\')">Capabilities →</button>' +
    '</div>';
  html += '<div style="margin-top:4px;font-size:var(--font-size-xs);color:var(--text-muted)">' +
    '/provider &lt;name&gt; to open companion windows</div>';
  renderStandardCard(container, 'Providers', html, 'providerDock',
    configured > 0 ? 'ok' : 'warn');
});

// ── Ralph Scout widget ───────────────────────────────────────────────

registerWidget('ralphScout', function(container, level) {
  const ralph = state.ralph;
  const panel = ralph.panel;

  if (!panel) {
    if (level === 'compact') return;
    const html = '<div style="padding:8px">' +
      '<p style="color:var(--text-muted);margin:0 0 8px 0">No scan results yet.</p>' +
      '<button onclick="window.RigRelay.dispatchIntent(\'ralph_scan\')">Scan</button>' +
      '</div>';
    renderStandardCard(container, 'Ralph Scout', html, 'ralphScout', '');
    return;
  }

  const lastIntent = ralph.lastIntent;
  const summary = panel.summary || {};
  const top = panel.top_candidate;
  const mission = panel.mission_candidate;
  const approval = panel.approval_state || 'not_requested';

  if (level === 'compact') {
    let statusCls = approval === 'approved' ? 'ok' : approval === 'declined' ? 'error' : 'warn';
    let label = approval === 'approved' ? 'Approved' : approval === 'declined' ? 'Declined' : (top ? top.score.toFixed(0) + 'pts' : 'idle');
    renderCompactChip(container, 'Ralph', function() {
      return { text: label, cls: statusCls };
    });
    return;
  }

  if (level === 'expanded') {
    renderRalphExpanded(container, panel, ralph);
    return;
  }

  var html = '';

  // Status bar
  var statusCls = approval === 'approved' ? 'ok' : approval === 'declined' ? 'error' : approval === 'pending' ? 'warn' : '';
  var decisionTag = panel.decision_required
    ? '<span class="widget-chip ' + statusCls + '"><span class="dot"></span>' + escapeHtml(approval) + '</span>'
    : '<span class="widget-chip">idle</span>';

  html += '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px">' +
    '<span style="font-weight:600">' + escapeHtml(panel.status || 'idle') + '</span>' +
    decisionTag +
    '</div>';

  // Top candidate summary
  if (top) {
    html += '<div style="margin-bottom:6px">' +
      '<div style="font-size:var(--font-size-sm);font-weight:600;margin-bottom:2px">' + escapeHtml(top.title.substring(0, 80)) + '</div>';
    if (top.score_components) {
      var sc = top.score_components;
      html += '<div style="font-size:var(--font-size-xs);color:var(--text-muted)">' +
        'Score: ' + sc.total_score.toFixed(0) +
        ' (sev=' + sc.severity_weight.toFixed(0) +
        ' kind=' + sc.kind_weight.toFixed(0) +
        ' ev=' + sc.evidence_bonus.toFixed(0) + ')' +
        '</div>';
    }
    html += '<div style="font-size:var(--font-size-xs);color:var(--text-muted)">' +
      'Source: ' + escapeHtml(top.source_kind) +
      ' | Policy: ' + escapeHtml(top.ranking_policy_version) +
      '</div>';
  }

  // Mission candidate summary
  if (mission) {
    html += '<div style="margin-top:6px;font-size:var(--font-size-xs)">' +
      '<span style="color:var(--text-muted)">Mission:</span> ' + escapeHtml(mission.mission_kind) +
      ' | <span style="color:var(--text-muted)">Approval:</span> ' + (mission.requires_approval ? 'required' : 'not required') +
      '</div>';
  }

  // Last intent result
  if (lastIntent) {
    var resultCls = lastIntent.status === 'completed' ? 'ok' : lastIntent.status === 'failed' ? 'error' : '';
    html += '<div class="widget-chip ' + resultCls + '" style="margin-top:4px;font-size:var(--font-size-xs)">' +
      escapeHtml(lastIntent.name + ': ' + (lastIntent.summary || lastIntent.status).substring(0, 60)) +
      '</div>';
  }

  // Actions
  html += '<div class="widget-actions" style="margin-top:6px">' +
    '<button onclick="window.RigRelay.dispatchIntent(\'ralph_scan\')">Scan</button>';

  if (panel.decision_required && panel.panel_sha256 && panel.mission_candidate_sha256) {
    html +=
      '<button onclick="window.RigRelay.dispatchIntent(\'ralph_approve\', {' +
      '\'run_id\':\'' + (panel.run_id || '') + '\',' +
      '\'scan_id\':\'' + (panel.scan_id || '') + '\',' +
      '\'panel_sha256\':\'' + panel.panel_sha256 + '\',' +
      '\'mission_candidate_sha256\':\'' + panel.mission_candidate_sha256 + '\'' +
      '})">Approve</button>' +
      '<button onclick="window.RigRelay.dispatchIntent(\'ralph_decline\', {' +
      '\'run_id\':\'' + (panel.run_id || '') + '\',' +
      '\'scan_id\':\'' + (panel.scan_id || '') + '\',' +
      '\'panel_sha256\':\'' + panel.panel_sha256 + '\',' +
      '\'mission_candidate_sha256\':\'' + panel.mission_candidate_sha256 + '\'' +
      '})">Decline</button>';
  }

  html += '<button onclick="window.RigRelay.dispatchIntent(\'ralph_rescan\')">Rescan</button>' +
    '</div>';

  // Hashes (compact)
  if (panel.panel_sha256) {
    html += '<div style="margin-top:4px;font-size:var(--font-size-xs);color:var(--text-muted);font-family:monospace">' +
      'SHA: ' + panel.panel_sha256.substring(0, 12) + '...</div>';
  }

  var cardStatus = approval === 'approved' ? 'ok' : approval === 'declined' ? 'error' :
    (panel.decision_required ? 'warn' : '');
  renderStandardCard(container, 'Ralph Scout', html, 'ralphScout', cardStatus);
});

function renderRalphExpanded(container, panel, ralph) {
  const top = panel.top_candidate;
  const mission = panel.mission_candidate;
  const summary = panel.summary || {};

  var html = '<div style="max-width:700px;margin:0 auto">';

  html += '<h3 style="margin:0 0 12px 0">Ralph Scout — Full Report</h3>';
  html += '<table class="kv-table">' +
    row('Status', escapeHtml(panel.status)) +
    row('Candidates', String(summary.candidate_count || 0)) +
    row('Top Score', String(summary.top_score || 0)) +
    row('Input Source', escapeHtml(summary.input_source || 'unknown')) +
    row('Approval', escapeHtml(panel.approval_state || 'not_requested')) +
    row('Decision Req.', panel.decision_required ? 'Yes' : 'No') +
    row('Policy', escapeHtml(summary.ranking_policy_version || '')) +
    '</table>';

  if (top) {
    html += '<h4 style="margin:16px 0 8px 0">Top Candidate</h4>';
    html += '<table class="kv-table">' +
      row('ID', escapeHtml(top.candidate_id)) +
      row('Title', escapeHtml(top.title)) +
      row('Kind', escapeHtml(top.source_kind)) +
      row('Severity', escapeHtml(top.severity)) +
      row('Score', top.score_components
        ? 'sev=' + top.score_components.severity_weight.toFixed(0) +
          ' kind=' + top.score_components.kind_weight.toFixed(0) +
          ' ev=' + top.score_components.evidence_bonus.toFixed(0) +
          ' total=' + top.score_components.total_score.toFixed(0)
        : String(top.score)) +
      row('Source ID', escapeHtml(top.source_finding_id || '')) +
      row('Reason', escapeHtml((top.reason || '').substring(0, 120))) +
      '</table>';
  }

  if (mission) {
    html += '<h4 style="margin:16px 0 8px 0">Mission Candidate</h4>';
    html += '<table class="kv-table">' +
      row('Mission', escapeHtml(mission.mission_kind)) +
      row('Allowed', (mission.allowed_actions || []).join(', ')) +
      row('Forbidden', (mission.forbidden_actions || []).slice(0, 3).join(', ')) +
      row('Approval', mission.requires_approval ? 'Required' : 'Not required') +
      row('Tier', 'Tier ' + String(mission.required_autonomy_tier || 0)) +
      '</table>';
  }

  if (panel.ranked_candidates && panel.ranked_candidates.length > 1) {
    html += '<h4 style="margin:16px 0 8px 0">All Candidates (' + panel.ranked_candidates.length + ')</h4>';
    panel.ranked_candidates.forEach(function(c, i) {
      html += '<div style="font-size:var(--font-size-sm);margin-bottom:4px">' +
        (i + 1) + '. [' + escapeHtml(c.severity) + '] ' + escapeHtml(c.title.substring(0, 60)) +
        ' (' + c.score.toFixed(0) + ')</div>';
    });
  }

  html += '<h4 style="margin:16px 0 8px 0">Hashes</h4>';
  html += '<div style="font-family:monospace;font-size:var(--font-size-xs);color:var(--text-muted);word-break:break-all">' +
    'panel: ' + (panel.panel_sha256 || '—') + '<br>' +
    'mission: ' + (panel.mission_candidate_sha256 || '—') + '<br>' +
    'input: ' + (panel.input_snapshot_sha256 || '—') +
    '</div>';

  html += '</div>';

  renderExpandedWidget(container, 'Ralph Scout — Full Report', html);
}

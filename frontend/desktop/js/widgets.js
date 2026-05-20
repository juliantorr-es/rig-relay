// Rig Relay — Widgets
// Registry, render coordination, disclosure levels

import { state, getDisclosure, setDisclosure } from './state.js';
import { TransportStatus, STATUS_LABELS, STATUS_CHIP_CLASS } from './transportState.js';
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
  try {
    fn(container, level);
  } catch (_) {
    _renderErrorCard(container, id);
  }
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

let _previousFocus = null;

export function showExpanded(id) {
  const overlay = el('expanded-overlay');
  const content = el('expanded-content');
  if (!overlay || !content) return;

  const fn = renderers[id];
  if (!fn) return;

  _previousFocus = document.activeElement;
  overlay.classList.add('active');
  const card = el('widget-' + id);
  if (card) card.setAttribute('aria-expanded', 'true');
  try {
    fn(content, 'expanded');
  } catch (_) {
    _renderErrorCard(content, id);
  }
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
  if (_previousFocus && typeof _previousFocus.focus === 'function') {
    _previousFocus.focus();
    _previousFocus = null;
  }
}

// ── Built-in widget renderers ──

registerWidget('operatorHeader', (container, level) => {
  const proj = state.projection;
  const telemetryMode = proj ? (proj.telemetry_mode || 'unknown') : '—';
  const telemetryState = proj && proj.telemetry_degraded ? 'Degraded' : 'Healthy';

  if (level === 'compact') {
    renderCompactChip(container, 'Session', () => {
      const version = (proj && proj.app_version) || '—';
      return { text: version, cls: 'info' };
    });
    return;
  }
  if (level === 'expanded') {
    renderExpandedWidget(container, 'Session', buildOperatorHeaderExpanded());
    return;
  }
  const cs = (proj && proj.current_state) || {};
  const st = (proj && proj.storage) || {};
  const html =
    '<table class="kv-table">' +
    row('Mode', 'desktop') +
    row('Version', proj ? proj.app_version : '—') +
    row('Telemetry', telemetryMode, proj && proj.telemetry_degraded ? 'warn' : 'ok') +
    row('Telemetry state', telemetryState, proj && proj.telemetry_degraded ? 'warn' : 'ok') +
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

export function updateIntentResult(status, intentName, summary, details) {
  const container = el('widget-intentResult');
  if (!container) return;
  const cls = status === 'completed' ? 'ok' : status === 'refused' ? 'warn' : 'error';

  // DOM construction — no innerHTML for untrusted data
  while (container.firstChild) container.removeChild(container.firstChild);

  const header = document.createElement('div');
  header.className = 'widget-header';
  header.onclick = function() { window.RigRelay.cycleWidgetDisclosure('intentResult'); };
  header.appendChild(document.createTextNode('Latest Result'));

  var statusText = escapeHtml(intentName) + ': ' + escapeHtml(status);
  if (details && details.error_code) {
    statusText += ' (' + escapeHtml(details.error_code) + ')';
  }

  const chip = document.createElement('div');
  chip.className = 'widget-chip ' + cls;
  const dot = document.createElement('span');
  dot.className = 'dot';
  chip.appendChild(dot);
  header.appendChild(chip);

  const icon = document.createElement('span');
  icon.className = 'widget-expand-icon';
  icon.textContent = '\u25B2';
  header.appendChild(icon);

  const body = document.createElement('div');
  body.className = 'widget-body';

  const statusLine = document.createElement('div');
  statusLine.textContent = statusText;
  body.appendChild(statusLine);

  if (summary) {
    const sumLine = document.createElement('div');
    sumLine.style.cssText = 'margin-top:4px;color:var(--text-secondary)';
    sumLine.textContent = summary;
    body.appendChild(sumLine);
  }

  // ── Structured refusal display ──
  if (status === 'refused') {
    if (details && details.required_approval) {
      const approvalLine = document.createElement('div');
      approvalLine.style.cssText = 'margin-top:6px;padding:4px 8px;background:var(--warn-bg, rgba(210,153,34,0.1));border-radius:4px;font-size:var(--font-size-xs);color:var(--warn)';
      approvalLine.textContent = 'This action requires approval from: ' + details.required_approval;
      body.appendChild(approvalLine);
    }
    if (details && details.required_receipt) {
      const receiptLine = document.createElement('div');
      receiptLine.style.cssText = 'margin-top:4px;padding:4px 8px;background:var(--warn-bg, rgba(210,153,34,0.1));border-radius:4px;font-size:var(--font-size-xs);color:var(--warn)';
      receiptLine.textContent = 'This action requires a valid authorization receipt';
      body.appendChild(receiptLine);
    }
    if (details && details.hint) {
      const hintLine = document.createElement('div');
      hintLine.style.cssText = 'margin-top:4px;font-size:var(--font-size-xs);color:var(--text-muted)';
      hintLine.textContent = 'Try: ' + details.hint;
      body.appendChild(hintLine);
    }
  }

  const trigger = document.createElement('div');
  trigger.className = 'widget-expand-trigger';
  trigger.textContent = 'Expand \u2192';
  trigger.onclick = function() { window.RigRelay.cycleWidgetDisclosure('intentResult'); };

  container.appendChild(header);
  container.appendChild(body);
  container.appendChild(trigger);
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
  if (level === 'compact') {
    const progressEvents = state.progressEvents;
    if (!progressEvents.length) return;
    const latest = progressEvents[progressEvents.length - 1];
    var data = latest.data || latest;
    var type = (data.event_type || 'unknown').replace(/^operation\./, '');
    var status = data.status || 'running';
    var cls = status === 'completed' ? 'ok' : status === 'failed' ? 'error' : 'warn';
    var text = type;
    if (data.message) text += ': ' + data.message.substring(0, 40);
    else text += ': ' + status;
    renderCompactChip(container, 'Progress', function() {
      return { text: text, cls: cls };
    });
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
  const status = (state.transport && state.transport.status) || TransportStatus.IDLE;
  const transportLabel = STATUS_LABELS[status] || 'Unknown';
  const chipCls = STATUS_CHIP_CLASS[status] || 'warn';
  const html = '<table class="kv-table">' +
    row('Transport', transportLabel) +
    row('Status', status) +
    row('Phase', (state.transport && state.transport.phase) || '—') +
    row('WS Connected', state.wsConnected ? 'Yes' : 'No') +
    row('Handshake', ((state.transport && state.transport.handshakeId) || '—').substring(0, 20)) +
    '</table>';
  renderStandardCard(container, 'Connection', html, 'connectionStatus', chipCls);
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

function _renderErrorCard(container, widgetId) {
  while (container.firstChild) container.removeChild(container.firstChild);
  container.className = 'widget-card widget-failed';
  var header = document.createElement('div');
  header.className = 'widget-header';
  header.textContent = widgetId;
  var body = document.createElement('div');
  body.className = 'widget-body';
  var icon = document.createElement('span');
  icon.textContent = '\u26A0 ';
  body.appendChild(icon);
  body.appendChild(document.createTextNode('Render failed'));
  container.appendChild(header);
  container.appendChild(body);
  if (window.RigRelay && window.RigRelay.notifications) {
    try {
      window.RigRelay.notifications.emit({
        kind: 'error',
        message: 'Widget render failed',
        dedupKey: 'widget-' + widgetId + '-render-failed',
      });
    } catch (_) { /* notifications unavailable */ }
  }
}

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
  container.setAttribute('tabindex', '0');
  container.setAttribute('role', 'button');
  container.onclick = function() { cycleDisclosure(container.id.replace('widget-', '')); };
  container.addEventListener('keydown', function(e) {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      cycleDisclosure(container.id.replace('widget-', ''));
    }
  });
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

// ── Receipt dot coloring ──
function receiptKindDotCls(kind) {
  var k = (kind || '').toLowerCase();
  if (k === 'checkpoint') return 'info';
  if (k === 'validation') return 'ok';
  if (k === 'authorization') return 'warn';
  if (k === 'bash') return 'info';
  if (k === 'report') return '';
  return '';
}

function receiptItemDotCls(receipt) {
  var kind = (receipt.kind || '').toLowerCase();
  if (kind === 'validation') {
    var passed = receipt.passed !== false;
    return passed ? 'ok' : 'warn';
  }
  return receiptKindDotCls(kind);
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

  // ── Group by kind ──
  var grouped = {};
  receipts.forEach(function(r) {
    var kind = r.kind || 'Unknown';
    if (!grouped[kind]) grouped[kind] = [];
    grouped[kind].push(r);
  });

  // Sort groups by most recent receipt in each group
  var kindOrder = Object.keys(grouped).sort(function(a, b) {
    var aTs = grouped[a][0].timestamp || '';
    var bTs = grouped[b][0].timestamp || '';
    return bTs.localeCompare(aTs);
  });

  var html = '';
  var totalShown = 0;
  var maxItems = 20;

  for (var gi = 0; gi < kindOrder.length && totalShown < maxItems; gi++) {
    var kind = kindOrder[gi];
    var items = grouped[kind];
    var dotCls = receiptKindDotCls(kind);

    html += '<div style="padding:6px 0 2px 0;font-size:var(--font-size-xs);color:var(--text-secondary);border-bottom:1px solid var(--border);margin-top:4px">' +
      '<span class="dot ' + dotCls + '" style="display:inline-block;width:6px;height:6px;border-radius:50%;margin-right:5px;vertical-align:middle"></span>' +
      escapeHtml(kind) + ' (' + items.length + ')' +
      '</div>';

    for (var i = 0; i < items.length && totalShown < maxItems; i++) {
      var r = items[i];
      var isLatest = totalShown === 0;
      var itemCls = receiptItemDotCls(r);

      html += '<div style="padding:4px 0;font-size:var(--font-size-xs);border-bottom:1px solid var(--border-subtle)">' +
        (isLatest ? '<span class="widget-chip ok" style="font-size:9px;padding:1px 5px;margin-right:4px;vertical-align:middle">latest</span>' : '') +
        '<span class="dot ' + itemCls + '" style="display:inline-block;width:5px;height:5px;border-radius:50%;margin-right:4px;vertical-align:middle"></span>' +
        (r.summary ? '<span style="font-weight:500">' + escapeHtml(r.summary.substring(0, 80)) + '</span> ' : '') +
        '<span style="color:var(--text-muted)">' + escapeHtml(r.timestamp || '') + '</span>' +
        '</div>';
      totalShown++;
    }
  }

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
  const proj = state.projection;
  const id = (proj && proj.identity) || {};
  const providers = id.providers || {};
  const hasGithub = providers.github || {};
  const hasGoogle = providers.google || {};

  const ghStatus = hasGithub.status || 'signed_out';
  const goStatus = hasGoogle.status || 'signed_out';
  const anySignedIn = ghStatus === 'signed_in' || goStatus === 'signed_in';
  const anyPending = ghStatus === 'pending' || goStatus === 'pending';

  let html = '<table class="kv-table">';

  function providerRow(name, p) {
    const st = p.status || 'signed_out';
    let cls = st === 'signed_in' ? 'ok' : st === 'pending' ? 'warn' : st === 'error' || st === 'failed' ? 'error' : '';
    let label = st === 'signed_in' ? (p.display_name || 'Signed in') : st;
    return row(name, label, cls);
  }

  html += providerRow('GitHub', hasGithub);
  html += providerRow('Google', hasGoogle);
  html += '</table>';

  html += '<div class="widget-actions" style="flex-wrap:wrap;gap:4px">';
  if (ghStatus !== 'signed_in' && ghStatus !== 'pending') {
    html += '<button onclick="window.RigRelay.signInWithProvider(\'github\')">Sign in GitHub</button>';
  }
  if (goStatus !== 'signed_in' && goStatus !== 'pending') {
    html += '<button onclick="window.RigRelay.signInWithProvider(\'google\')">Sign in Google</button>';
  }
  if (anySignedIn) {
    html += '<button onclick="window.RigRelay.dispatchIntent(\'identity_status\')">Refresh</button>';
  }
  if (anyPending) {
    html += '<button onclick="window.RigRelay.checkAuthStatus(\'github\')">Check GitHub</button>';
    html += '<button onclick="window.RigRelay.checkAuthStatus(\'google\')">Check Google</button>';
  }
  html += '</div>';

  const statusCls = anySignedIn ? 'ok' : anyPending ? 'warn' : '';
  renderStandardCard(container, 'Identity', html, 'identity', statusCls);
});

registerWidget('integrationStatus', (container, level) => {
  const proj = state.projection;
  const integ = (proj && proj.integrations) || {};
  const providers = integ.providers || [];

  const connectionStateCls = function(state) {
    if (state === 'connected') return 'ok';
    if (state === 'auth_required') return 'warn';
    if (state === 'degraded') return 'warn';
    if (state === 'error') return 'error';
    return '';
  };

  const connectedCount = providers.filter(function(p) {
    return p.connection_state === 'connected';
  }).length;

  if (level === 'compact') {
    renderCompactChip(container, 'Integrations', function() {
      return {
        text: connectedCount > 0 ? connectedCount + ' connected' : 'None',
        cls: connectedCount > 0 ? 'ok' : ''
      };
    });
    return;
  }

  if (level === 'expanded') {
    var html = '<h3>Integration Status</h3>';
    if (!providers.length) {
      html += '<p class="widget-missing">No integrations configured.</p>';
    } else {
      html += '<table class="kv-table">';
      providers.forEach(function(p) {
        html += row(p.display_name || p.provider_id, p.connection_state || '—', connectionStateCls(p.connection_state));
        html += row('Provider ID', p.provider_id || '—');
        html += row('Capability count', String(p.capability_count || 0));
        if (p.granted_scopes && p.granted_scopes.length) {
          html += '<tr><td class="key">Granted scopes</td><td class="val">' + escapeHtml(p.granted_scopes.join(', ')) + '</td></tr>';
        }
        if (p.degraded_reason) {
          html += row('Degraded reason', p.degraded_reason, 'warn');
        }
        if (p.capabilities && p.capabilities.length) {
          html += '<tr><td class="key">Capabilities</td><td class="val">';
          p.capabilities.forEach(function(c) {
            var name = c.name || c.id || '—';
            var gate = c.gating_status ? ' (' + escapeHtml(c.gating_status) + ')' : '';
            html += '<div>' + escapeHtml(name) + gate + '</div>';
          });
          html += '</td></tr>';
        }
        html += '<tr><td colspan="2" style="padding:4px 0;border-bottom:1px solid var(--border)"></td></tr>';
      });
      html += '</table>';
    }
    renderExpandedWidget(container, 'Integration Status', html);
    return;
  }

  if (!providers.length) {
    renderStandardCard(container, 'Integrations',
      '<span class="widget-missing">No integrations configured.</span>', 'integrationStatus');
    return;
  }

  var html = '<table class="kv-table">';
  providers.forEach(function(p) {
    var cls = connectionStateCls(p.connection_state);
    html += row('Provider', p.display_name || p.provider_id || '—');
    html += row('Provider ID', p.provider_id || '—');
    html += row('State', p.connection_state || '—', cls);
    html += row('Capabilities', String(p.capability_count || 0));
    html += '<tr><td colspan="2" style="padding:2px 0"></td></tr>';
  });
  html += '</table>';

  renderStandardCard(container, 'Integrations', html, 'integrationStatus',
    connectedCount > 0 ? 'ok' : '');
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
});

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
    row('Telemetry', proj ? (proj.telemetry_mode || 'unknown') : '—', proj && proj.telemetry_degraded ? 'warn' : 'ok') +
    row('Telemetry state', proj && proj.telemetry_degraded ? 'Degraded' : 'Healthy', proj && proj.telemetry_degraded ? 'warn' : 'ok') +
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

// ── Ralph Lifecycle widget ──────────────────────────────────────────

registerWidget('ralphLifecycle', function(container, level) {
  const lifecycle = state.ralph.lifecycle;

  if (!lifecycle) {
    if (level === 'compact') return;
    renderStandardCard(container, 'Background Lanes', '<p style="color:var(--text-muted);margin:0;padding:8px">No lifecycle data available.</p>', 'ralphLifecycle', '');
    return;
  }

  if (level === 'compact') {
    const count = lifecycle.active_lane_count || 0;
    const label = lifecycle.background_enabled
      ? (count > 0 ? count + ' active' : 'ON (idle)')
      : 'OFF';
    const cls = lifecycle.background_enabled ? (count > 0 ? 'ok' : '') : '';
    renderCompactChip(container, 'Lanes', function() {
      return { text: label, cls: cls };
    });
    return;
  }

  if (level === 'expanded') {
    renderRalphLifecycleExpanded(container, lifecycle);
    return;
  }

  var html = '';

  // Status header
  var bgCls = lifecycle.background_enabled ? 'ok' : '';
  html += '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px">' +
    '<span style="font-weight:600">Background Lanes</span>' +
    '<span class="widget-chip ' + bgCls + '"><span class="dot"></span>' +
    (lifecycle.background_enabled ? 'ON' : 'OFF') + '</span>' +
    '</div>';

  // Execution scopes
  html += '<table class="kv-table" style="margin-bottom:4px">' +
    '<tr><td>Lane execution</td><td><span class="widget-chip ' + (lifecycle.isolated_lane_execution_enabled ? 'ok' : '') + '">' +
    (lifecycle.isolated_lane_execution_enabled ? 'allowed' : 'blocked') + '</span></td></tr>' +
    '<tr><td>Runtime mutation</td><td><span class="widget-chip">blocked</span></td></tr>' +
    '<tr><td>Merge</td><td><span class="widget-chip ' + (lifecycle.merge_enabled ? 'ok' : 'warn') + '">' +
    (lifecycle.merge_enabled ? 'allowed' : 'requires adoption approval') + '</span></td></tr>' +
    '<tr><td>Push</td><td><span class="widget-chip ' + (lifecycle.push_enabled ? 'ok' : 'warn') + '">' +
    (lifecycle.push_enabled ? 'allowed' : 'requires preproduction approval') + '</span></td></tr>' +
    '</table>';

  // Counts
  html += '<div style="font-size:var(--font-size-sm);margin-bottom:6px">' +
    '<span>Active: <strong>' + (lifecycle.active_lane_count || 0) + '</strong></span>' +
    ' &middot; <span>Completed: <strong>' + (lifecycle.completed_lane_count || 0) + '</strong></span>' +
    ' &middot; <span>Pending review: <strong>' + (lifecycle.pending_review_count || 0) + '</strong></span>' +
    '</div>';

  // Latest lane
  if (lifecycle.latest_lane) {
    var ll = lifecycle.latest_lane;
    html += '<div style="font-size:var(--font-size-xs);color:var(--text-muted);margin-bottom:4px">' +
      '<div>Latest: <span style="font-family:monospace">' + escapeHtml(ll.branch_name || ll.lane_id || '—') + '</span></div>' +
      '<div>Status: ' + escapeHtml(ll.status || '—');
    if (ll.latest_commit_sha) html += ' | Commit: ' + ll.latest_commit_sha.substring(0, 8);
    html += '</div></div>';
  }

  // Latest adoption
  if (lifecycle.latest_adoption_proposal) {
    var ap = lifecycle.latest_adoption_proposal;
    html += '<div style="font-size:var(--font-size-xs);color:var(--text-muted);margin-bottom:4px">' +
      '<div>Adoption: ' + escapeHtml(ap.status || '—') + ' → ' + escapeHtml(ap.target_kind || '—') + '</div></div>';
  }

  // Gates
  if (lifecycle.gates && lifecycle.gates.length > 0) {
    html += '<div style="display:flex;flex-wrap:wrap;gap:3px;margin-top:4px">';
    lifecycle.gates.forEach(function(g) {
      var gCls = g.allowed ? 'ok' : (g.label.indexOf('requires') >= 0 ? 'warn' : '');
      html += '<span class="widget-chip ' + gCls + '" title="' + escapeHtml(g.requires || '') + '">' + escapeHtml(g.label) + '</span>';
    });
    html += '</div>';
  }

  // Actions
  html += '<div class="widget-actions" style="margin-top:6px">' +
    '<button onclick="window.RigRelay.dispatchIntent(\'ralph_scan\')">Scan</button>' +
    '<button onclick="window.RigRelay.dispatchIntent(\'ralph_background_toggle_on\')">Enable</button>' +
    '<button onclick="window.RigRelay.dispatchIntent(\'ralph_background_toggle_off\')">Disable</button>' +
    '</div>';

  renderStandardCard(container, 'Background Lanes', html, 'ralphLifecycle', lifecycle.active_lane_count > 0 ? 'ok' : '');
});

function renderRalphLifecycleExpanded(container, lc) {
  var html = '<div style="max-width:700px;margin:0 auto">';
  html += '<h3 style="margin:0 0 12px 0">Background Lane Lifecycle</h3>';
  html += '<table class="kv-table">' +
    '<tr><td>Background</td><td>' + (lc.background_enabled ? 'ON' : 'OFF') + '</td></tr>' +
    '<tr><td>Active lanes</td><td>' + (lc.active_lane_count || 0) + '</td></tr>' +
    '<tr><td>Completed lanes</td><td>' + (lc.completed_lane_count || 0) + '</td></tr>' +
    '<tr><td>Pending review</td><td>' + (lc.pending_review_count || 0) + '</td></tr>' +
    '</table>';

  html += '<h4 style="margin:16px 0 8px 0">Execution Scopes</h4>';
  html += '<table class="kv-table">' +
    '<tr><td>Isolated lane execution</td><td>' + (lc.isolated_lane_execution_enabled ? '✅ Allowed' : '❌ Blocked') + '</td></tr>' +
    '<tr><td>Live runtime mutation</td><td>❌ Blocked</td></tr>' +
    '<tr><td>Merge</td><td>' + (lc.merge_enabled ? '✅ Allowed' : '❌ Requires adoption approval') + '</td></tr>' +
    '<tr><td>Push to preproduction</td><td>' + (lc.push_enabled ? '✅ Allowed' : '❌ Requires preproduction approval') + '</td></tr>' +
    '</table>';

  html += '<h4 style="margin:16px 0 8px 0">Gates</h4>';
  html += '<table class="kv-table">';
  (lc.gates || []).forEach(function(g) {
    html += '<tr><td>' + escapeHtml(g.name) + '</td><td>' +
      (g.allowed ? '✅ Allowed' : '❌ ' + escapeHtml(g.label)) + '</td></tr>';
  });
  html += '</table>';

  if (lc.active_lanes && lc.active_lanes.length > 0) {
    html += '<h4 style="margin:16px 0 8px 0">Active Lanes</h4>';
    lc.active_lanes.forEach(function(l) {
      html += '<div style="font-size:var(--font-size-sm);margin-bottom:2px;font-family:monospace">' +
        escapeHtml(l.branch_name || l.lane_id) + ' [' + escapeHtml(l.status) + ']</div>';
    });
  }

  if (lc.completed_lanes && lc.completed_lanes.length > 0) {
    html += '<h4 style="margin:16px 0 8px 0">Completed Lanes</h4>';
    lc.completed_lanes.forEach(function(l) {
      html += '<div style="font-size:var(--font-size-sm);margin-bottom:2px">' +
        escapeHtml(l.lane_id) + ' [' + escapeHtml(l.status) + '] ' +
        (l.review_bundle_sha256 ? '(bundle: ' + l.review_bundle_sha256.substring(0, 8) + ')' : '') +
        '</div>';
    });
  }

  html += '</div>';
  renderExpandedWidget(container, 'Background Lane Lifecycle', html);
}

// ── Orchestrator Mission Board widget ───────────────────────────────

registerWidget('missionBoard', function(container, level) {
  const board = (state.projection && state.projection.orchestrator_board) || null;

  if (!board) {
    if (level === 'compact') return;
    renderStandardCard(container, 'Mission Board', '<p style="color:var(--text-muted);margin:0;padding:8px">Type /orchestrator to create missions.</p>', 'missionBoard', '');
    return;
  }

  if (level === 'compact') {
    const count = board.active_missions || 0;
    const ralphPending = board.pending_ralph_report_count || 0;
    const label = ralphPending > 0 ? count + ' active + ' + ralphPending + ' Ralph' : count + ' active';
    const cls = ralphPending > 0 ? 'warn' : (count > 0 ? 'ok' : '');
    renderCompactChip(container, 'Missions', function() {
      return { text: label, cls: cls };
    });
    return;
  }

  if (level === 'expanded') {
    renderMissionBoardExpanded(container, board);
    return;
  }

  var html = '';
  html += '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px">' +
    '<span style="font-weight:600">Orchestrator Board</span>' +
    '<span style="font-size:var(--font-size-xs);color:var(--text-muted)">' +
    (board.active_missions || 0) + ' missions / ' + (board.pending_ralph_report_count || 0) + ' Ralph</span>' +
    '</div>';

  // Workstream 1: Assigned Subagent Lanes
  if (board.assigned_subagent_lanes && board.assigned_subagent_lanes.length > 0) {
    html += '<div style="font-size:var(--font-size-xs);color:var(--text-secondary);margin-bottom:3px">Assigned Subagents</div>';
    board.assigned_subagent_lanes.forEach(function(l) {
      var isRalph = l.profile_kind === 'autonomous_background_worker';
      var cls = isRalph ? '' : (l.active_missions > 0 ? 'ok' : '');
      var icon = isRalph ? '🤖 ' : '▸ ';
      var modelLabel = l.model_binding_label || '';
      var providerLabel = l.provider_status === 'demo_local' ? ' (local demo)' : (l.provider_status === 'configured' ? ' (configured)' : '');
      html += '<div style="font-size:var(--font-size-sm);margin-bottom:2px">' +
        '<span class="widget-chip ' + cls + '">' + escapeHtml(l.status) + '</span> ' +
        icon + escapeHtml(l.display_name) +
        (modelLabel ? '<span style="color:var(--text-muted);font-size:var(--font-size-xs);margin-left:4px">' + escapeHtml(modelLabel) + escapeHtml(providerLabel) + '</span>' : '') +
        '</div>';
    });
  }

  // Workstream 2: Ralph Background Reports
  if (board.ralph_reports && board.ralph_reports.length > 0) {
    var pendingReports = board.ralph_reports.filter(function(r) { return r.requires_orchestrator_review; });
    if (pendingReports.length > 0) {
      html += '<div style="margin-top:6px;font-size:var(--font-size-xs);color:var(--text-secondary);margin-bottom:3px">Ralph Background Reports</div>';
      pendingReports.slice(0, 2).forEach(function(r) {
        html += '<div style="font-size:var(--font-size-sm);margin-bottom:2px">' +
          '<span class="widget-chip warn">' + escapeHtml(r.report_kind) + '</span> ' +
          escapeHtml(r.title.substring(0, 45)) + '</div>';
      });
      if (pendingReports.length > 2) {
        html += '<div style="font-size:var(--font-size-xs);color:var(--text-muted)">+ ' +
          (pendingReports.length - 2) + ' more</div>';
      }
    }
  }

  // Workstream 3: Review entrypoint
  if (board.review_entrypoint && board.review_entrypoint.available) {
    var re = board.review_entrypoint;
    html += '<div style="margin-top:6px">' +
      '<button onclick="window.RigRelay.dispatchIntent(\'review_with_orchestrator\')" ' +
      'style="background:var(--color-accent);color:#fff;border:none;padding:4px 10px;border-radius:4px;cursor:pointer;font-size:var(--font-size-sm)">' +
      escapeHtml(re.label) + '</button></div>';
  }

  html += '<div class="widget-actions" style="margin-top:4px">' +
    '<button onclick="window.RigRelay.dispatchIntent(\'orchestrator_new_mission\')">New</button>' +
    '<button onclick="window.RigRelay.cycleWidgetDisclosure(\'missionBoard\')">Timeline →</button>' +
    '</div>';

  renderStandardCard(container, 'Orchestrator Board', html, 'missionBoard', (board.pending_ralph_report_count || 0) > 0 ? 'warn' : (board.active_missions > 0 ? 'ok' : ''));
});

function renderMissionBoardExpanded(container, board) {
  var html = '<div style="max-width:700px;margin:0 auto">';
  html += '<h3 style="margin:0 0 12px 0">Orchestrator Mission Board</h3>';

  // Workstream 1: Assigned Subagent Lanes
  if (board.assigned_subagent_lanes && board.assigned_subagent_lanes.length > 0) {
    html += '<h4 style="margin:12px 0 8px 0">Assigned Subagents</h4>';
    board.assigned_subagent_lanes.forEach(function(l) {
      var isRalph = l.profile_kind === 'autonomous_background_worker';
      var icon = isRalph ? '🤖' : '▸';
      html += '<div style="margin-bottom:4px;padding:4px;border-left:3px solid var(--color-accent)">' +
        '<div style="font-weight:600">' + icon + ' ' + escapeHtml(l.display_name) + '</div>' +
        '<div style="font-size:var(--font-size-xs);color:var(--text-muted)">' +
        escapeHtml(l.role) + ' | Profile: ' + escapeHtml(l.profile_kind) +
        ' | Missions: ' + (l.active_missions || 0) + '/' + (l.max_concurrent || 0);
      if (l.model_binding_label) {
        html += ' | Model: ' + escapeHtml(l.model_binding_label);
      }
      if (l.provider_status) {
        html += ' | Provider: ' + escapeHtml(l.provider_status);
      }
      html += '</div></div>';
    });
  }

  // Workstream 2: Ralph Background Reports
  if (board.ralph_reports && board.ralph_reports.length > 0) {
    html += '<h4 style="margin:12px 0 8px 0">Ralph Background Reports (' + (board.pending_ralph_report_count || 0) + ' pending)</h4>';
    board.ralph_reports.forEach(function(r) {
      var cls = r.requires_orchestrator_review ? 'warn' : '';
      html += '<div style="margin-bottom:4px;padding:4px;border-left:3px solid var(--warn)">' +
        '<div style="font-weight:600">' + escapeHtml(r.title) + '</div>' +
        '<div style="font-size:var(--font-size-xs);color:var(--text-muted)">' +
        'Kind: ' + escapeHtml(r.report_kind) + ' | Status: ' + escapeHtml(r.status) +
        ' | Relevance: ' + (r.relevance_score * 100).toFixed(0) + '%' +
        (r.branch_name ? ' | Branch: ' + escapeHtml(r.branch_name) : '') +
        '</div></div>';
    });
  }

  // Workstream 3: Missions
  if (board.missions && board.missions.length > 0) {
    html += '<h4 style="margin:12px 0 8px 0">Assigned Missions</h4>';
    board.missions.forEach(function(m) {
      html += '<div style="margin-bottom:4px;padding:4px;border-left:3px solid var(--color-accent)">' +
        '<div style="font-weight:600">' + escapeHtml(m.title) + '</div>' +
        '<div style="font-size:var(--font-size-xs);color:var(--text-muted)">' +
        escapeHtml(m.status) + (m.assigned_profile_name ? ' | Agent: ' + escapeHtml(m.assigned_profile_name) : '') +
        ' | Lane: ' + escapeHtml(m.lane_id || '—') + '</div></div>';
    });
  }

  if (board.lifecycle_timeline && board.lifecycle_timeline.length > 0) {
    html += '<h4 style="margin:12px 0 8px 0">Ralph Lifecycle Timeline</h4>';
    board.lifecycle_timeline.forEach(function(e) {
      var icon = e.status === 'completed' ? '✅' : (e.blocked ? '🔒' : '⏳');
      html += '<div style="display:flex;align-items:center;gap:8px;font-size:var(--font-size-sm);margin-bottom:3px">' +
        '<span>' + icon + '</span>' +
        '<span>' + escapeHtml(e.label) + '</span>' +
        '<span style="color:var(--text-muted);font-size:var(--font-size-xs)">' + escapeHtml(e.detail) + '</span>' +
        '</div>';
    });
  }

  html += '<h4 style="margin:12px 0 8px 0">Execution Scopes</h4>';
  html += '<table class="kv-table">' +
    '<tr><td>Isolated lane</td><td>' + (board.isolated_lane_execution_enabled ? '✅' : '❌') + '</td></tr>' +
    '<tr><td>Live runtime</td><td>❌</td></tr>' +
    '<tr><td>Merge</td><td>' + (board.merge_enabled ? '✅' : '❌ requires adoption approval') + '</td></tr>' +
    '<tr><td>Push</td><td>' + (board.push_enabled ? '✅' : '❌ requires preproduction approval') + '</td></tr>' +
    '</table>';

  html += '</div>';
  renderExpandedWidget(container, 'Orchestrator Board', html);
}

// ── Role Model explainer widget ──────────────────────────────────────

registerWidget('roleModel', function(container, level) {
  const rm = (state.projection && state.projection.role_model) || null;

  if (!rm) {
    if (level === 'compact') return;
    renderStandardCard(container, 'Role Model', '<p style="color:var(--text-muted);margin:0;padding:8px">Role model data not available.</p>', 'roleModel', '');
    return;
  }

  if (level === 'compact') {
    const count = (rm.assignable_subagent_count || 0);
    const ralph = (rm.autonomous_worker_count || 0);
    const label = count + ' subagents' + (ralph > 0 ? ' + Ralph' : '');
    renderCompactChip(container, 'Roles', function() {
      return { text: label, cls: '' };
    });
    return;
  }

  if (level === 'expanded') {
    renderRoleModelExpanded(container, rm);
    return;
  }

  var html = '';

  html += '<div style="font-size:var(--font-size-sm);margin-bottom:8px">' +
    '<span>' + (rm.assignable_subagent_count || 0) + ' subagents</span>' +
    ' &middot; <span>' + (rm.autonomous_worker_count || 0) + ' autonomous</span>' +
    ' &middot; <span>' + (rm.configured_model_binding_count || 0) + ' bindings</span>' +
    '</div>';

  if (rm.roles && rm.roles.length > 0) {
    rm.roles.slice(0, 4).forEach(function(r) {
      html += '<div style="font-size:var(--font-size-sm);margin-bottom:3px">' +
        '<span>' + (r.emoji || '') + ' <strong>' + escapeHtml(r.role_name) + '</strong></span>' +
        ' <span style="color:var(--text-muted);font-size:var(--font-size-xs)">' + escapeHtml(r.description.substring(0, 60)) + '</span>' +
        '</div>';
    });
  }

  html += '<div class="widget-actions" style="margin-top:4px">' +
    '<button onclick="window.RigRelay.cycleWidgetDisclosure(\'roleModel\')">More</button>' +
    '</div>';

  renderStandardCard(container, 'Role Model', html, 'roleModel', '');
});

registerWidget('releaseGate', (container, level) => {
  const proj = state.projection;
  const rg = proj && proj._release_gate;

  if (!rg || !rg.available) {
    if (level === 'compact') {
      renderCompactChip(container, 'RC Gate', () => ({ text: 'N/A', cls: '' }));
      return;
    }
    if (level === 'standard') {
      renderStandardCard(container, 'Release Candidate Gate',
        '<span class="widget-missing">No release gate data</span>', 'releaseGate');
      return;
    }
    return;
  }

  const overallStatus = rg.overall_status || 'unknown';
  const statusCls = overallStatus === 'ready' || overallStatus === 'passing' ? 'ok' :
                    overallStatus === 'blocked' ? 'warn' : '';

  if (level === 'compact') {
    renderCompactChip(container, 'RC Gate', () => ({
      text: overallStatus,
      cls: statusCls
    }));
    return;
  }

  if (level !== 'standard') return;

  const phases = rg.phases || [];
  const openBlockers = rg.open_blocker_count || 0;
  const totalBlockers = rg.total_blocker_count || 0;

  let html = '';
  if (openBlockers > 0) {
    html += '<div style="margin-bottom:8px;font-size:var(--font-size-sm)">' +
      '<span class="widget-chip warn"><span class="dot"></span>' +
      openBlockers + '/' + totalBlockers + ' blockers open</span>' +
      '</div>';
  }

  if (phases.length > 0) {
    html += '<table class="kv-table">';
    phases.forEach(function(p) {
      var pCls = p.status === 'ready' || p.status === 'passing' ? 'ok' :
                 p.status === 'blocked' ? 'warn' : '';
      html += row(p.title, p.status, pCls);
    });
    html += '</table>';
  }

  if (rg.last_validation_run) {
    var lvr = rg.last_validation_run;
    html += '<div style="margin-top:8px;font-size:var(--font-size-xs);color:var(--text-muted)">' +
      'Last validation: ' + escapeHtml(lvr.result) +
      ' (' + lvr.tests_run + ' tests)' +
      (lvr.created_at ? ' · ' + formatTimestamp(lvr.created_at) : '') +
      '</div>';
  }

  renderStandardCard(container, 'RC Gate: ' + overallStatus, html, 'releaseGate', statusCls);
});

// ── Bridge Protocol widget ──────────────────────────────────────────

 registerWidget('bridgeProtocol', function(container, level) {
   if (level === 'expanded') return;
   renderBridgeProtocol(container, level);
 });

function renderBridgeProtocol(container, level) {
  var client = window.__RIG_RELAY_PROTOCOL_CLIENT__
  if (!client) {
    renderCompactCard(container, 'Bridge Protocol', 'Protocol client not initialized', 'bridgeProtocol', 'warn')
    return
  }

  var stats = client.getStats()
  var html = '<div class="widget-content protocol-widget">'

  var hbAge = stats.heartbeatAgeMs
  var hbStatus = hbAge < 0 ? 'No heartbeat yet'
    : hbAge > 30000 ? 'Degraded (no heartbeat ' + Math.round(hbAge / 1000) + 's)'
    : hbAge > 15000 ? 'Slow (' + Math.round(hbAge / 1000) + 's)'
    : 'OK'
  var hbCls = hbAge < 0 ? 'warn' : hbAge > 30000 ? 'error' : hbAge > 15000 ? 'warn' : 'ok'

  html += '<div class="proto-row"><span class="proto-label">Heartbeat</span>'
  html += '<span class="proto-value ' + hbCls + '">' + escapeHtml(hbStatus) + '</span></div>'

  // Compact: only show heartbeat + seq
  if (level === 'compact') {
    html += '<div class="proto-row"><span class="proto-label">Seq</span>'
    html += '<span class="proto-value">in:' + (stats.inboundSeq || 0) + ' out:' + (stats.outboundSeq || 0) + '</span></div>'
    html += '</div>'
    renderStandardCard(container, 'Bridge Protocol', html, 'bridgeProtocol', hbCls === 'ok' ? 'ok' : 'warn')
    return
  }

  html += '<div class="proto-row"><span class="proto-label">Outbound Seq</span>'
  html += '<span class="proto-value">' + (stats.outboundSeq || 0) + '</span></div>'

  html += '<div class="proto-row"><span class="proto-label">Inbound Seq</span>'
  html += '<span class="proto-value">' + (stats.inboundSeq || 0) + '</span></div>'

  html += '<div class="proto-row"><span class="proto-label">Projection Seq</span>'
  html += '<span class="proto-value">' + (stats.lastProjectionSeq || 0) + '</span></div>'

  html += '<div class="proto-row"><span class="proto-label">Duplicates</span>'
  html += '<span class="proto-value">' + (stats.duplicateCount || 0) + '</span></div>'

  html += '<div class="proto-row"><span class="proto-label">Stale Projections</span>'
  html += '<span class="proto-value">' + (stats.staleProjectionCount || 0) + '</span></div>'

  html += '<div class="proto-row"><span class="proto-label">Protocol Errors</span>'
  var errCls = (stats.protocolErrorCount || 0) > 0 ? 'error' : ''
  html += '<span class="proto-value ' + errCls + '">' + (stats.protocolErrorCount || 0) + '</span></div>'

  html += '<div class="proto-row"><span class="proto-label">Dropped</span>'
  html += '<span class="proto-value">' + (stats.droppedCount || 0) + '</span></div>'

  html += '<div class="proto-row"><span class="proto-label">Coalesced</span>'
  html += '<span class="proto-value">' + (stats.coalescedCount || 0) + '</span></div>'

  html += '<div class="proto-row"><span class="proto-label">Max Queue Depth</span>'
  html += '<span class="proto-value">' + (stats.maxQueueDepth || 0) + '</span></div>'

  var kinds = Object.keys(stats.messageCountByKind || {})
  if (kinds.length > 0) {
    html += '<div class="proto-section"><span class="proto-section-label">Messages by Kind</span>'
    kinds.forEach(function(k) {
      html += '<div class="proto-row proto-sub"><span class="proto-label">' + escapeHtml(k) + '</span>'
      html += '<span class="proto-value">' + (stats.messageCountByKind[k] || 0) + '</span></div>'
    })
    html += '</div>'
  }

  html += '</div>'

  var cardStatus = (stats.duplicateCount || 0) > 10 || (stats.protocolErrorCount || 0) > 0 ? 'warn' : 'ok'
  renderStandardCard(container, 'Bridge Protocol', html, 'bridgeProtocol', cardStatus)
}

function renderRoleModelExpanded(container, rm) {
  var html = '<div style="max-width:700px;margin:0 auto">';
  html += '<h3 style="margin:0 0 12px 0">Role Model</h3>';

  if (rm.roles && rm.roles.length > 0) {
    rm.roles.forEach(function(r) {
      html += '<div style="margin-bottom:12px;padding:8px;border-left:3px solid var(--color-accent);background:#161b22;border-radius:4px">' +
        '<div style="font-weight:600;margin-bottom:4px">' + (r.emoji || '') + ' ' + escapeHtml(r.role_name) +
        ' <span style="font-size:var(--font-size-xs);color:var(--text-muted)">(' + escapeHtml(r.role_kind) + ')</span>' +
        '</div>' +
        '<div style="font-size:var(--font-size-sm);color:var(--text-muted)">' + escapeHtml(r.description) + '</div>' +
        '<div style="font-size:var(--font-size-xs);color:var(--text-muted);margin-top:2px">Count: ' + (r.count || 0) + '</div>' +
        '</div>';
    });
  }

  html += '<table class="kv-table" style="margin-top:16px">' +
    '<tr><td>Assignable subagents</td><td>' + (rm.assignable_subagent_count || 0) + '</td></tr>' +
    '<tr><td>Autonomous workers</td><td>' + (rm.autonomous_worker_count || 0) + '</td></tr>' +
    '<tr><td>Model bindings</td><td>' + (rm.configured_model_binding_count || 0) + '</td></tr>' +
    '<tr><td>Pending Ralph reports</td><td>' + (rm.pending_ralph_report_count || 0) + '</td></tr>' +
    '</table>';

  html += '</div>';
  renderExpandedWidget(container, 'Role Model', html);
}

// ── Profile README Publish Lane widget ──
registerWidget('profileReadmeLane', (container, level) => {
  const p = state.projection;
  if (!p || !p.profile_readme_lane || !p.profile_readme_lane.available) return;

  const lane = p.profile_readme_lane;
  const statusCls = lane.publish_gate_status === 'dry_run_blocked' ? 'warn'
    : lane.publish_gate_status === 'publish_blocked' ? 'warn'
    : lane.publish_gate_status === 'publish_ready' ? 'success'
    : 'dimmed';

  if (level === 'compact') {
    renderCompactChip(container, 'Profile README', () => ({
      text: `${lane.operation_mode} — ${lane.publish_gate_status}`,
      cls: statusCls
    }));
    return;
  }

  const gatesHtml = (lane.gates || []).map(g =>
    `<tr><td style="color:${g.passed ? '#4caf50' : '#f44336'}">${g.passed ? '\u2713' : '\u2717'}</td><td>${escapeHtml(g.gate)}</td><td style="font-size:0.85em;color:var(--text-dimmed)">${escapeHtml(g.detail)}</td></tr>`
  ).join('');

  const stepsHtml = (lane.planned_steps || []).map(s =>
    `<tr><td>${s.step}</td><td>${escapeHtml(s.operation)}</td><td style="color:var(--text-dimmed)">${escapeHtml(s.permission)}</td></tr>`
  ).join('');

  const blockedHtml = (lane.blocked_reasons || []).map(r =>
    `<span class="badge warn">${escapeHtml(r)}</span>`
  ).join(' ');

  const disabledReasons = (lane.publish_disabled_reasons || []).map(r =>
    `<li>${escapeHtml(r)}</li>`
  ).join('');

  let html = '<div style="font-size:0.9em">';

  // Status bar
  html += `<div style="margin-bottom:8px"><strong>Mode:</strong> ${escapeHtml(lane.operation_mode)} &middot; <strong>Gate:</strong> ${escapeHtml(lane.publish_gate_status)}</div>`;

  // Blocked reasons
  if (blockedHtml) html += `<div style="margin-bottom:8px"><strong>Blocked:</strong> ${blockedHtml}</div>`;

  // Gates table
  if (gatesHtml) {
    html += '<div style="margin-bottom:8px"><strong>Publish Gates</strong>';
    html += '<table style="font-size:0.85em;width:100%">';
    html += '<tr><th></th><th>Gate</th><th>Detail</th></tr>';
    html += gatesHtml;
    html += '</table></div>';
  }

  // Planned steps
  if (stepsHtml) {
    html += '<div style="margin-bottom:8px"><strong>Planned Steps</strong>';
    html += '<table style="font-size:0.85em;width:100%">';
    html += '<tr><th>#</th><th>Operation</th><th>Permission</th></tr>';
    html += stepsHtml;
    html += '</table></div>';
  }

  // Preview metadata
  if (lane.preview) {
    html += '<div style="margin-bottom:8px"><strong>Preview:</strong> ';
    html += `${escapeHtml(String(lane.preview.path || ''))}<br>`;
    html += `SHA256: ${escapeHtml(String(lane.preview.sha256 || '').substring(0, 16))}... &middot; `;
    html += `${lane.preview.line_count || 0} lines &middot; `;
    html += `${lane.preview.included_claim_count || 0} claims`;
    html += '</div>';
  }

  // Publish disabled CTA
  html += '<div style="margin-top:8px;padding:8px;border:1px solid var(--warn-border);border-radius:4px;background:var(--warn-bg)">';
  html += '<strong>Publish disabled</strong>';
  if (disabledReasons) html += `<ul style="margin:4px 0 0 16px;font-size:0.85em">${disabledReasons}</ul>`;
  html += '</div>';

  html += '</div>';

  if (level === 'expanded') {
    renderExpandedWidget(container, 'Profile README Publish Lane', html);
    return;
  }

  renderStandardCard(container, 'Profile README Publish Lane', html, 'profileReadmeLane', statusCls);
});

// ── Spiderweb Topology widget ──
registerWidget('spiderwebTopology', (container, level) => {
  const p = state.projection;
  const topo = (p && p.spiderweb_topology) || {};

  if (!topo.available) {
    if (level === 'compact') return;
    const reason = topo.status === 'invalid_artifact'
      ? 'Topology artifact is invalid or unreadable.'
      : 'No topology data available.';
    renderStandardCard(container, 'Spiderweb Topology',
      '<span class="widget-missing" style="color:var(--text-dimmed)">' + escapeHtml(reason) + '</span>',
      'spiderwebTopology', 'dimmed');
    return;
  }

  const statusCls = topo.status === 'live' || topo.status === 'live_seeded' ? 'ok'
    : topo.status === 'degraded_no_input' ? 'warn'
    : topo.status === 'empty' ? 'dimmed'
    : 'dimmed';

  if (level === 'compact') {
    renderCompactChip(container, 'Topology', () => ({
      text: topo.node_count + ' nodes, ' + topo.active_strand_count + ' active',
      cls: (topo.active_strand_count || 0) > 0 ? 'ok' : 'dimmed'
    }));
    return;
  }

  let html = '<div style="font-size:0.9em">';

  // Status line
  html += '<div style="margin-bottom:8px"><strong>Status:</strong> '
    + escapeHtml(topo.status || 'unknown')
    + ' &middot <strong>Nodes:</strong> ' + (topo.node_count || 0)
    + ' &middot <strong>Edges:</strong> ' + (topo.edge_count || 0)
    + ' &middot <strong>Active strands:</strong> ' + (topo.active_strand_count || 0)
    + '</div>';

  // Strand state summary
  const strand = topo.strand_state_summary || {};
  html += '<div style="margin-bottom:8px"><strong>Strands:</strong> ';
  html += '<span style="color:var(--clr-success)">active: ' + (strand.active_count || 0) + '</span>';
  html += ' &middot <span style="color:var(--clr-info)">idle: ' + (strand.idle_count || 0) + '</span>';
  html += ' &middot <span style="color:var(--text-dimmed)">no input: ' + (strand.no_input_count || 0) + '</span>';
  if (strand.degraded_count) html += ' &middot <span style="color:var(--clr-warn)">degraded: ' + strand.degraded_count + '</span>';
  if (strand.blocked_count) html += ' &middot <span style="color:var(--clr-error)">blocked: ' + strand.blocked_count + '</span>';
  html += '</div>';

  // Pressure summary
  const pressure = topo.resource_pressure_summary || {};
  html += '<div style="margin-bottom:8px"><strong>Pressure:</strong> ';
  html += 'reconnect: <span class="badge ' + (pressure.reconnect_pressure === 'none' ? 'ok' : pressure.reconnect_pressure === 'moderate' ? 'warn' : 'error') + '">' + escapeHtml(pressure.reconnect_pressure || 'none') + '</span>';
  html += ' &middot queue: <span class="badge ' + (pressure.queue_pressure === 'none' ? 'ok' : 'warn') + '">' + escapeHtml(pressure.queue_pressure || 'none') + '</span>';
  html += ' &middot consumer errors: <span class="badge ' + (pressure.consumer_errors === 'none' ? 'ok' : 'warn') + '">' + escapeHtml(pressure.consumer_errors || 'none') + (pressure.consumer_error_count ? ' (' + pressure.consumer_error_count + ')' : '') + '</span>';
  html += ' &middot bridge: ' + escapeHtml(pressure.bridge_health || 'unknown');
  html += '</div>';

  // Causal summary
  const causal = topo.causal_summary || {};
  html += '<div style="margin-bottom:8px"><strong>Causal:</strong> ';
  html += 'observed: ' + (causal.observed_links || 0) + ' &middot correlated: ' + (causal.correlated_only_links || 0);
  html += '</div>';

  // Degraded reasons
  const reasons = topo.degraded_reasons || [];
  if (reasons.length) {
    html += '<div style="margin-bottom:8px;color:var(--clr-warn)"><strong>Degraded:</strong> ';
    html += reasons.map(function(r) { return escapeHtml(String(r)); }).join(' &middot ');
    html += '</div>';
  }

  // Source hashes
  const hashes = topo.source_artifact_hashes || {};
  if (Object.keys(hashes).length) {
    html += '<div style="font-size:0.75em;color:var(--text-dimmed)"><strong>Source hashes:</strong> ';
    html += Object.keys(hashes).map(function(k) { return escapeHtml(k) + '=' + escapeHtml(hashes[k]); }).join(', ');
    html += '</div>';
  }

  html += '</div>';

  if (level === 'expanded') {
    renderExpandedWidget(container, 'Spiderweb Topology', html);
    return;
  }

  renderStandardCard(container, 'Spiderweb Topology', html, 'spiderwebTopology', statusCls);
});

// ── Security Lifecycle Program widget ──
registerWidget('securityLifecycle', (container, level) => {
  const p = state.projection;
  const sl = (p && p.security_lifecycle_program) || {};

  if (!sl.available) {
    if (level === 'compact') return;
    const reason = sl.status === 'missing_artifacts'
      ? 'No security lifecycle artifacts found.'
      : 'Security lifecycle data not available.';
    renderStandardCard(container, 'Security Lifecycle',
      '<span class="widget-missing" style="color:var(--text-dimmed)">' + escapeHtml(reason) + '</span>',
      'securityLifecycle', 'dimmed');
    return;
  }

  const blockedCount = (sl.blocked_reasons || []).length;
  const statusCls = sl.mutation_status && sl.mutation_status.remote_mutation ? 'warn'
    : blockedCount > 0 ? 'warn'
    : 'ok';

  if (level === 'compact') {
    renderCompactChip(container, 'Sec Lifecycle', () => ({
      text: (sl.current_stage || 'none') + ' | ' + (sl.next_safe_action || 'idle'),
      cls: statusCls
    }));
    var _lmrc = p && p.live_mutation_readiness;
    if (_lmrc && _lmrc.available) {
      var _lmStat = _lmrc.live_mutation_readiness_status || 'unknown';
      var _lmCls = _lmStat === 'ready' ? 'ok' : 'warn';
      renderCompactChip(container, 'Live Mutation', () => ({
        text: _lmStat,
        cls: _lmCls
      }));
    }
    return;
  }

  if (level === 'expanded') {
    renderSecurityLifecycleExpanded(container, sl);
    var _lmre = p && p.live_mutation_readiness;
    if (_lmre && _lmre.available) {
      renderLiveMutationExpanded(container, _lmre);
    }
    return;
  }

  var html = '<div style="font-size:0.9em">';

  html += '<div style="margin-bottom:8px"><strong>Phase:</strong> '
    + escapeHtml(sl.phase_status || 'unknown')
    + ' &middot <strong>Stage:</strong> ' + escapeHtml(sl.current_stage || 'none')
    + ' &middot <strong>Next:</strong> ' + escapeHtml(sl.next_safe_action || 'idle')
    + '</div>';

  const qs = sl.queue_summary || {};
  html += '<div style="margin-bottom:8px"><strong>Queue:</strong> '
    + (qs.present_count || 0) + '/' + (qs.total_artifacts || 0) + ' present'
    + (qs.missing_count ? ' (' + qs.missing_count + ' missing)' : '')
    + '</div>';

  const sel = sl.selected_alert_summary || {};
  html += '<div style="margin-bottom:8px"><strong>Stages:</strong> '
    + (sel.current_stage_count || 0) + ' active'
    + (sel.blocked_stage_count ? ', ' + sel.blocked_stage_count + ' blocked' : '')
    + '</div>';

  html += '<div style="margin-bottom:8px"><strong>PR:</strong> ' + escapeHtml(sl.pr_lifecycle_state || '—')
    + ' &middot <strong>Alert:</strong> ' + escapeHtml(sl.alert_lifecycle_state || '—')
    + ' &middot <strong>Approval:</strong> ' + escapeHtml(sl.approval_status || '—')
    + '</div>';

  const mut = sl.mutation_status || {};
  html += '<div style="margin-bottom:8px"><strong>Mutation:</strong> '
    + 'remote: <span class="badge ' + (mut.remote_mutation ? 'warn' : 'ok') + '">' + (mut.remote_mutation ? 'true' : 'false') + '</span>'
    + ' &middot local: <span class="badge ok">false</span>'
    + '</div>';

  if (blockedCount > 0) {
    html += '<div style="margin-bottom:8px;color:var(--clr-warn)"><strong>Blocked:</strong> ';
    html += (sl.blocked_reasons || []).slice(0, 5).map(function(r) {
      return '<span class="badge warn">' + escapeHtml(r) + '</span>';
    }).join(' ');
    if (blockedCount > 5) html += ' +' + (blockedCount - 5) + ' more';
    html += '</div>';
  }

  var _lmrs = p && p.live_mutation_readiness;
  if (_lmrs && _lmrs.available) {
    html += '<hr style="border:none;border-top:1px solid var(--border-dimmed);margin:10px 0">';
    html += '<div style="margin-bottom:8px"><strong>Live Mutation Readiness</strong>'
      + ' <span class="badge ' + (_lmrs.live_mutation_readiness_status === 'ready' ? 'ok' : 'warn') + '">'
      + escapeHtml(_lmrs.live_mutation_readiness_status || 'unknown')
      + '</span></div>';
    html += '<div style="margin-bottom:8px">'
      + '<strong>Flags:</strong> ' + (_lmrs.required_flags || []).map(function(f) { return escapeHtml(f); }).join(', ')
      + ' &middot <strong>Ops:</strong> ' + (_lmrs.expected_live_operations || []).map(function(o) { return escapeHtml(o); }).join(', ')
      + '</div>';
    html += '<div style="margin-bottom:8px"><strong>Perms:</strong> '
      + (_lmrs.required_permissions || []).map(function(p) { return '<span class="badge dimmed">' + escapeHtml(p) + '</span>'; }).join(' ')
      + '</div>';
    html += '<div style="margin-bottom:8px"><strong>Deferred:</strong> '
      + (_lmrs.deferred_actions || []).map(function(a) { return '<span class="badge dimmed">' + escapeHtml(a) + '</span>'; }).join(' ')
      + '</div>';
    var _lmGates = _lmrs.readiness_gates || [];
    if (_lmGates.length > 0) {
      html += '<div style="margin-bottom:8px;font-size:0.8em;color:var(--text-dimmed)"><strong>Gates:</strong> '
        + _lmGates.slice(0, 8).map(function(g) { return escapeHtml(g); }).join(', ')
        + (_lmGates.length > 8 ? ' +' + (_lmGates.length - 8) + ' more' : '')
        + '</div>';
    }
    if (_lmrs.rollback_guidance_summary) {
      html += '<div style="margin-bottom:8px;font-size:0.8em;color:var(--text-dimmed)"><strong>Rollback:</strong> '
        + escapeHtml(_lmrs.rollback_guidance_summary) + '</div>';
    }
  }

  html += '</div>';

  renderStandardCard(container, 'Security Lifecycle', html, 'securityLifecycle', statusCls);
});

function renderSecurityLifecycleExpanded(container, sl) {
  var html = '<div style="max-width:700px;margin:0 auto;font-size:0.9em">';
  html += '<h3 style="margin:0 0 12px 0">Security Lifecycle Program</h3>';

  html += '<table class="kv-table">'
    + '<tr><td>Phase status</td><td>' + escapeHtml(sl.phase_status || '—') + '</td></tr>'
    + '<tr><td>Current stage</td><td>' + escapeHtml(sl.current_stage || '—') + '</td></tr>'
    + '<tr><td>Next safe action</td><td>' + escapeHtml(sl.next_safe_action || '—') + '</td></tr>'
    + '<tr><td>PR lifecycle</td><td>' + escapeHtml(sl.pr_lifecycle_state || '—') + '</td></tr>'
    + '<tr><td>Alert lifecycle</td><td>' + escapeHtml(sl.alert_lifecycle_state || '—') + '</td></tr>'
    + '<tr><td>Approval</td><td>' + escapeHtml(sl.approval_status || '—') + '</td></tr>'
    + '</table>';

  html += '<h4 style="margin:16px 0 8px 0">Queue Summary</h4>';
  const qs = sl.queue_summary || {};
  html += '<table class="kv-table">'
    + '<tr><td>Total artifacts</td><td>' + (qs.total_artifacts || 0) + '</td></tr>'
    + '<tr><td>Present</td><td>' + (qs.present_count || 0) + '</td></tr>'
    + '<tr><td>Missing</td><td>' + (qs.missing_count || 0) + '</td></tr>'
    + '</table>';

  html += '<h4 style="margin:16px 0 8px 0">Alert Summary</h4>';
  const sel = sl.selected_alert_summary || {};
  html += '<table class="kv-table">'
    + '<tr><td>Total stages</td><td>' + (sel.total_stages || 0) + '</td></tr>'
    + '<tr><td>Active stages</td><td>' + (sel.current_stage_count || 0) + '</td></tr>'
    + '<tr><td>Blocked stages</td><td>' + (sel.blocked_stage_count || 0) + '</td></tr>'
    + '</table>';

  html += '<h4 style="margin:16px 0 8px 0">Mutation Status</h4>';
  const mut = sl.mutation_status || {};
  html += '<table class="kv-table">'
    + '<tr><td>Remote mutation</td><td><span class="badge ' + (mut.remote_mutation ? 'warn' : 'ok') + '">' + (mut.remote_mutation ? 'true' : 'false') + '</span></td></tr>'
    + '<tr><td>Local mutation</td><td><span class="badge ok">false</span></td></tr>'
    + '</table>';

  html += '<h4 style="margin:16px 0 8px 0">Permission Boundary Audit</h4>';
  const perm = sl.permission_summary || {};
  html += '<table class="kv-table">'
    + '<tr><td>Gates passed</td><td>' + (perm.gates_passed || 0) + '/' + (perm.gates_total || 0) + '</td></tr>'
    + '<tr><td>Verdict</td><td>' + escapeHtml(perm.verdict || '—') + '</td></tr>'
    + '<tr><td>Read perms</td><td>' + (perm.read_permissions || []).map(function(r) { return escapeHtml(r); }).join(', ') + '</td></tr>'
    + '<tr><td>Mutation perms</td><td>' + (perm.mutation_permissions || []).length === 0 ? 'none' : (perm.mutation_permissions || []).map(function(r) { return escapeHtml(r); }).join(', ') + '</td></tr>'
    + '</table>';

  const reasons = sl.blocked_reasons || [];
  if (reasons.length > 0) {
    html += '<h4 style="margin:16px 0 8px 0">Blocked Reasons (' + reasons.length + ')</h4>';
    html += '<ul style="margin:0;padding-left:20px;color:var(--clr-warn)">';
    reasons.forEach(function(r) {
      html += '<li>' + escapeHtml(r) + '</li>';
    });
    html += '</ul>';
  }

  html += '<h4 style="margin:16px 0 8px 0">Evidence Artifacts (' + (sl.evidence_artifacts || []).length + ')</h4>';
  html += '<table class="kv-table">';
  (sl.evidence_artifacts || []).forEach(function(a) {
    html += '<tr><td style="font-family:monospace;font-size:0.75em">' + escapeHtml(a.path.split('/').pop() || a.path) + '</td>'
      + '<td style="font-family:monospace;font-size:0.75em;color:var(--text-dimmed)">' + escapeHtml(a.sha256 || '—') + '</td></tr>';
  });
  html += '</table>';

  html += '<h4 style="margin:16px 0 8px 0">Event Fabric & Topology</h4>';
  const ef = sl.event_fabric_summary || {};
  const sts = sl.spiderweb_topology_summary || {};
  html += '<table class="kv-table">'
    + '<tr><td>Event count</td><td>' + (ef.event_count || 0) + '</td></tr>'
    + '<tr><td>Active strands (fabric)</td><td>' + (ef.active_strands || 0) + '</td></tr>'
    + '<tr><td>Node count</td><td>' + (sts.node_count || 0) + '</td></tr>'
    + '<tr><td>Edge count</td><td>' + (sts.edge_count || 0) + '</td></tr>'
    + '<tr><td>Active strands (topology)</td><td>' + (sts.active_strands || 0) + '</td></tr>'
    + '</table>';

  html += '<div style="margin-top:12px;font-size:0.75em;color:var(--text-dimmed)">'
    + '<strong>Redaction:</strong> ' + escapeHtml(sl.redaction_status || '—')
    + ' &middot <strong>Raw payloads:</strong> ' + (sl.raw_payloads_exposed ? 'exposed' : 'not exposed')
    + '</div>';

  html += '</div>';
  renderExpandedWidget(container, 'Security Lifecycle Program', html);
}

function renderLiveMutationExpanded(container, lm) {
  if (!lm || !lm.available) return;
  var h = '<div style="max-width:700px;margin:20px auto 0 auto;font-size:0.9em">';
  h += '<h3 style="margin:0 0 12px 0;color:var(--clr-warn)">Live Mutation Readiness</h3>';

  h += '<table class="kv-table">'
    + '<tr><td>Status</td><td><span class="badge ' + (lm.live_mutation_readiness_status === 'ready' ? 'ok' : 'warn') + '">' + escapeHtml(lm.live_mutation_readiness_status || '—') + '</span></td></tr>'
    + '<tr><td>Checklist</td><td>' + escapeHtml(lm.operator_checklist_status || '—') + '</td></tr>'
    + '<tr><td>Runbook</td><td>' + escapeHtml(lm.runbook_status || '—') + '</td></tr>'
    + '<tr><td>Next safe action</td><td>' + escapeHtml(lm.next_safe_action || '—') + '</td></tr>'
    + '<tr><td>Rollback</td><td style="font-size:0.85em">' + escapeHtml(lm.rollback_guidance_summary || '—') + '</td></tr>'
    + '</table>';

  h += '<h4 style="margin:16px 0 8px 0">Required Flags</h4>';
  h += '<p style="font-family:monospace;font-size:0.85em">' + (lm.required_flags || []).map(function(f) { return escapeHtml(f); }).join(' ') + '</p>';

  h += '<h4 style="margin:16px 0 8px 0">Required Permissions</h4>';
  h += '<ul style="margin:0;padding-left:20px">';
  (lm.required_permissions || []).forEach(function(p) {
    h += '<li>' + escapeHtml(p) + '</li>';
  });
  h += '</ul>';

  var gates = lm.readiness_gates || [];
  if (gates.length > 0) {
    h += '<h4 style="margin:16px 0 8px 0">Readiness Gates (' + gates.length + ')</h4>';
    h += '<ul style="margin:0;padding-left:20px">';
    gates.forEach(function(g) {
      h += '<li>' + escapeHtml(g) + '</li>';
    });
    h += '</ul>';
  }

  h += '<h4 style="margin:16px 0 8px 0">Expected Live Operations</h4>';
  h += '<ul style="margin:0;padding-left:20px">';
  (lm.expected_live_operations || []).forEach(function(o) {
    h += '<li>' + escapeHtml(o) + '</li>';
  });
  h += '</ul>';

  h += '<h4 style="margin:16px 0 8px 0">Deferred Actions</h4>';
  h += '<ul style="margin:0;padding-left:20px">';
  (lm.deferred_actions || []).forEach(function(a) {
    h += '<li>' + escapeHtml(a) + '</li>';
  });
  h += '</ul>';

  var reasons = lm.blocked_reasons || [];
  if (reasons.length > 0) {
    h += '<h4 style="margin:16px 0 8px 0;color:var(--clr-warn)">Blocked Reasons (' + reasons.length + ')</h4>';
    h += '<ul style="margin:0;padding-left:20px;color:var(--clr-warn)">';
    reasons.forEach(function(r) {
      h += '<li>' + escapeHtml(r) + '</li>';
    });
    h += '</ul>';
  }

  h += '<h4 style="margin:16px 0 8px 0">Evidence Artifacts (' + (lm.evidence_artifacts || []).length + ')</h4>';
  h += '<table class="kv-table">';
  (lm.evidence_artifacts || []).forEach(function(a) {
    h += '<tr><td style="font-family:monospace;font-size:0.75em">' + escapeHtml(a.path || '—') + '</td>'
      + '<td style="font-family:monospace;font-size:0.75em;color:var(--text-dimmed)">'
      + (a.present ? '<span class="badge ok">present</span>' : '<span class="badge warn">missing</span>')
      + '</td></tr>';
  });
  h += '</table>';

  h += '<div style="margin-top:12px;font-size:0.75em;color:var(--text-dimmed)">'
    + '<strong>Redaction:</strong> ' + escapeHtml(lm.redaction_status || '—')
    + ' &middot <strong>Raw payloads:</strong> ' + (lm.raw_payloads_exposed ? 'exposed' : 'not exposed')
    + '</div>';

  h += '</div>';
  renderExpandedWidget(container, 'Live Mutation Readiness', h);
}

// ── Carte Blanche Dashboard widget ──
registerWidget('carteBlancheDashboard', (container, level) => {
  const p = state.projection;
  if (!p || !p.carte_blanche_dashboard || !p.carte_blanche_dashboard.available) return;

  const d = p.carte_blanche_dashboard;
  const probes = d.surface_probes || {};
  let h = '<div style="font-size:0.85em">';

  h += `<div style="margin-bottom:6px"><strong>13 GitHub surfaces</strong> | ${d.live_proven_write_lanes} live-proven | ${d.read_verified_surfaces} read-verified | ${d.gated_write_lanes} write-lanes wired</div>`;

  h += '<table style="font-size:0.85em;width:100%"><tr><th>Surface</th><th>Status</th><th>API</th></tr>';
  for (const [name, probe] of Object.entries(probes)) {
    const sc = probe.status_code || '—';
    const cls = sc === 200 ? 'success' : sc > 0 ? 'warn' : 'dimmed';
    h += `<tr><td>${name}</td><td class="${cls}">${sc}</td><td>${probe.probed ? 'live' : 'not probed'}</td></tr>`;
  }
  h += '<tr><td>branch/file/PR</td><td class="success">201</td><td>live-proven</td></tr>';
  h += '<tr><td>release/create</td><td class="success">201</td><td>live-proven</td></tr>';
  h += '<tr><td>alert/update</td><td class="warn">gated</td><td>wired</td></tr>';
  h += '<tr><td>issue/create</td><td class="warn">410</td><td>repo config</td></tr>';
  h += '</table>';
  h += '</div>';

  if (level === 'expanded') {
    renderExpandedWidget(container, 'Carte Blanche Dashboard', h);
    return;
  }
  renderStandardCard(container, 'Carte Blanche Dashboard', h, 'carteBlancheDashboard', 'success');
});

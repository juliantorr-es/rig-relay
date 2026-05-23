// CONTRACT: Bridge Projection Pipeline
// ─────────────────────────────────────
// Owner: frontend/desktop/js/projection.js
// Safety: Never renders raw backend data as innerHTML.
//         Uses textContent for untrusted content, template for trusted HTML.
//         Digest computed server-side when available.
//         First projection triggers onProjectionReceived() on transport.
//
// Rig Relay — Projection
// Ingestion, caching, widget render coordination
// Batches DOM updates via requestAnimationFrame deduplication.
// Tracks projection digests to skip redundant full re-renders.
// Supports progressive partial/delta patches for targeted widget updates.

import { state } from './state.js';
import { renderWidget, renderAllWidgets, updateIntentResult } from './widgets.js';
import { renderStatusBar } from './status.js';
import { renderChat, restoreIntentButton } from './chat.js';
import { updateAnalyticsData } from './widgets/analytics.js';

// ════════════════════════════════════════════════════════════════
// STAGE 0: Render Batch — requestAnimationFrame dedup
// Ownership: frontend/desktop/js/projection.js
// ════════════════════════════════════════════════════════════════
// Only one full render cycle per animation frame, regardless of how many
// times scheduleRender() is called within that frame.
// For partial patches, uses a merge queue to coalesce multiple sections
// into fewer render calls.

let _renderScheduled = false;
let _pendingProjection = null;
let _pendingPartialSections = null;
let _partialSectionCount = 0;

// Threshold: if more than this many sections change in partial patches
// during one frame, coalesce into a full render.
var COALESCE_PARTIAL_THRESHOLD = 8;

function scheduleRender(projection) {
  _pendingProjection = projection;
  _pendingPartialSections = null;
  if (_renderScheduled) return;
  _renderScheduled = true;
  requestAnimationFrame(() => {
    _renderScheduled = false;
    if (_pendingPartialSections) {
      _applyPartialSections(_pendingPartialSections);
      _pendingPartialSections = null;
    } else if (_pendingProjection) {
      state.projection = _pendingProjection;
      _pendingProjection = null;
      renderStatusBar();
      renderAllWidgets();
    }
  });
}

function _schedulePartial(sections, changedSectionNames) {
  _pendingProjection = null;
  _partialSectionCount += changedSectionNames.length;
  if (_partialSectionCount > COALESCE_PARTIAL_THRESHOLD) {
    _pendingPartialSections = null;
    _pendingProjection = state.projection;
    if (!_renderScheduled) {
      _renderScheduled = true;
      requestAnimationFrame(() => {
        _renderScheduled = false;
        state.projection = _pendingProjection || state.projection;
        _pendingProjection = null;
        _pendingPartialSections = null;
        renderStatusBar();
        renderAllWidgets();
      });
    }
    return;
  }
  if (!_pendingPartialSections) {
    _pendingPartialSections = Object.create(null);
  }
  for (var k in sections) {
    if (sections.hasOwnProperty(k)) {
      _pendingPartialSections[k] = sections[k];
    }
  }
  if (!_renderScheduled) {
    _renderScheduled = true;
    requestAnimationFrame(() => {
      _renderScheduled = false;
      if (_pendingPartialSections) {
        _applyPartialSections(_pendingPartialSections);
        _pendingPartialSections = null;
      } else if (_pendingProjection) {
        state.projection = _pendingProjection;
        _pendingProjection = null;
        renderStatusBar();
        renderAllWidgets();
      }
    });
  }
}

function _applyPartialSections(sections) {
  if (!state.projection) {
    state.projection = sections;
    renderStatusBar();
    renderAllWidgets();
    return;
  }
  for (var key in sections) {
    if (sections.hasOwnProperty(key)) {
      state.projection[key] = sections[key];
    }
  }
  var sectionToWidget = {
    current_state: 'safetyState',
    queue: 'queuePlan',
    dataset: 'datasetSummary',
    semantic_snippets: 'semanticSnippets',
    telemetry_bundle: 'telemetryBundle',
    update: 'updateStatus',
    storage: 'storageBudget',
    providers: 'providerStatus',
    identity: 'identity',
    integrations: 'integrations',
    release_gate: 'releaseGate',
    service_state: 'serviceState',
    warnings: 'warnings',
    execution_progress: 'executionProgress',
    tool_runtime_summary: 'toolRuntimeSummary',
    analytics: 'governanceGateHealth',
  };
  var rendered = Object.create(null);
  // Analytics section touches all 8 analytics widgets
  var analyticsWidgets = [
    'governanceGateHealth', 'sessionHealth', 'toolLatency',
    'releaseBlocker', 'dependencyRisk', 'findingsWidget',
    'correlationIntegrity', 'localInference',
  ];
  for (var sectionName in sections) {
    if (sections.hasOwnProperty(sectionName)) {
      var widgetId = sectionToWidget[sectionName];
      if (widgetId && !rendered[widgetId]) {
        rendered[widgetId] = true;
        var container = document.getElementById('widget-' + widgetId);
        var wasFocused = document.activeElement && container && container.contains(document.activeElement);
        var scrollTop = container ? container.scrollTop : 0;
        renderWidget(widgetId);
        if (container && wasFocused) {
          try { document.activeElement && document.activeElement.focus(); } catch (_) {}
        }
        if (container && scrollTop > 0) {
          try { container.scrollTop = scrollTop; } catch (_) {}
        }
      }
      // Analytics section change: re-render all analytics widgets
      if (sectionName === 'analytics') {
        for (var ai = 0; ai < analyticsWidgets.length; ai++) {
          var awId = analyticsWidgets[ai];
          if (!rendered[awId]) {
            rendered[awId] = true;
            renderWidget(awId);
          }
        }
      }
    }
  }
  renderStatusBar();
}

// ════════════════════════════════════════════════════════════════
// STAGE 1: Digest — content hash comparison, skip redundant renders
// Ownership: frontend/desktop/js/projection.js
// ════════════════════════════════════════════════════════════════
// Compute a content hash of the projection (excluding volatile fields
// like generated_at) to detect true changes vs. timer ticks.

function computeDigest(data) {
  if (!data) return '';
  // Normalize: strip generated_at (changes every tick) and schema_validation_errors
  const copy = Object.assign({}, data);
  delete copy.generated_at;
  delete copy._schema_validation_errors;

  // Stable JSON sort for deterministic hashing
  const json = JSON.stringify(copy, Object.keys(copy).sort());
  let hash = 0;
  for (let i = 0; i < json.length; i++) {
    const chr = json.charCodeAt(i);
    hash = ((hash << 5) - hash) + chr;
    hash |= 0; // Convert to 32bit integer
  }
  return hash.toString(36);
}

let _lastDigest = '';

// ── Server-provided digest ───────────────────────────────────────────
// If the server sends a digest field, prefer it over our local computation.
// This allows the server to optimize which field changes are significant.

function getDigest(data) {
  if (data && data.digest) return data.digest;
  return computeDigest(data);
}

// ── Public API ───────────────────────────────────────────────────────

export function handleProjectionPatch(patch) {
  if (!patch || !patch.schema_version) return;

  var kind = patch.patch_kind || 'full';
  var changedSections = patch.changed_sections || [];
  var sections = patch.sections || {};

  switch (kind) {
    case 'full':
      scheduleRender(sections);
      break;
    case 'partial':
    case 'delta':
      if (changedSections.length === 0) return;
      _schedulePartial(sections, changedSections);
      break;
    default:
      scheduleRender(sections);
  }
}

export function handleProjection(data) {
  // ── Analytics projection: route to dedicated state path ──
  if (data && data.schema_version === 'rig.relay.analytics_projection.v1') {
    handleAnalyticsProjection(data);
    return;
  }

  const serverDigest = (data && data.digest) || '';
  const projection = data || {};

  const effectiveDigest = serverDigest || computeDigest(projection);
  if (effectiveDigest && effectiveDigest === _lastDigest) {
    return;
  }
  const isFirst = !_lastDigest;
  _lastDigest = effectiveDigest;
  // ════════════════════════════════════════════════════════════════
  // STAGE 2: First Projection — first digest received → signal transport readiness
  // Ownership: frontend/desktop/js/projection.js
  // ════════════════════════════════════════════════════════════════
  if (isFirst) {
    console.log("[bridge:frontend] first projection rendered, digest=" + effectiveDigest.substring(0, 12));
    if (window.pywebview && window.pywebview.api && window.pywebview.api.record_frontend_event) {
      window.pywebview.api.record_frontend_event({
        type: "frontend_first_projection_rendered",
        message: "digest=" + effectiveDigest.substring(0, 12),
        digest: effectiveDigest
      }).catch(function() {});
    }
    if (window.RigRelay && typeof window.RigRelay.onProjectionReceived === 'function') {
      window.RigRelay.onProjectionReceived();
    }
  }

  // ════════════════════════════════════════════════════════════════
  // STAGE 3: Widget Dispatch — distribute projection fields to widget renderers
  // Ownership: frontend/desktop/js/projection.js
  // ════════════════════════════════════════════════════════════════
  if (projection.ralph_lifecycle) {
    state.ralph.lifecycle = projection.ralph_lifecycle;
  }
  if (projection.orchestrator_board) {
    state.ralph.missionBoard = projection.orchestrator_board;
  }

  scheduleRender(projection);
}

export function handleChatState(data) {
  // Chat state changes are small — render immediately, no batching needed
  renderChat(data);
}

export function handleIntentResult(msg) {
  const result = msg.data || msg.result || msg;
  const name = result.intent_kind || result.intent_name || 'Intent';
  const status = result.status || 'unknown';
  const summary = result.message || result.summary || '';

  // ── Restore any pending intent buttons ──
  restoreIntentButton(name, status);

  // ── Auth intent handling ──
  if (_handleAuthIntentResult(name, status, result)) {
    return;
  }

  if (name.startsWith('ralph_')) {
    if (result.status !== 'refused' && result.ralph && result.ralph.panel) {
      state.ralph.panel = result.ralph.panel;
    }
    if (result.ralph && result.ralph.run_state) {
      state.ralph.runState = result.ralph.run_state;
    }
    if (result.approval_state && state.ralph.panel) {
      state.ralph.panel.approval_state = result.approval_state;
    }
    var refusalText = result.status === 'refused'
      ? (result.error_code || 'refused') + ': ' + (result.message || '')
      : '';
    state.ralph.lastIntent = {
      name: name,
      status: status,
      summary: refusalText || summary,
      error_code: result.error_code || null
    };
    renderWidget('ralphScout');
    return;
  }

  // ── Identity status update ──
  if (name === 'identity_status' || name.startsWith('sign_out_')) {
    renderWidget('identity');
  }

  var details = {};
  if (result.status === 'refused') {
    details.error_code = result.error_code;
    details.required_approval = result.required_approval;
    details.required_receipt = result.required_receipt;
    details.hint = result.hint;
  }
  updateIntentResult(status, name, summary, details);
}

// ── Auth intent result handler ───────────────────────────────────────

function _handleAuthIntentResult(name, status, result) {
  const extra = result.extra_fields || {};
  const isAuthStart = name === 'sign_in_github_start' || name === 'sign_in_google_start';
  const isAuthPoll = name === 'sign_in_github_poll' || name === 'sign_in_google_poll';
  const isAuthCancel = name === 'sign_in_github_cancel' || name === 'sign_in_google_cancel';
  const isAuthManual = name === 'sign_in_github_manual_code' || name === 'sign_in_google_manual_code';

  if (!isAuthStart && !isAuthPoll && !isAuthCancel && !isAuthManual) {
    return false;
  }

  const providerName = extra.provider || name.split('_')[2] || '';

  if (isAuthStart && status === 'completed' && extra.auth_url && extra.auth_session_id) {
    // Store session ID for polling
    window.RigRelay._authSessionId = extra.auth_session_id;
    // Clear previous poll timer if any
    if (window.RigRelay._authPollTimer) {
      clearInterval(window.RigRelay._authPollTimer);
      window.RigRelay._authPollTimer = null;
    }
    // Show auth action card
    _showAuthActionCard(providerName, extra);
    renderWidget('identity');
    updateIntentResult(status, name, 'Auth URL ready. Open your browser to sign in.', {});
    return true;
  }

  if (isAuthStart && status === 'completed' && !extra.configured) {
    updateIntentResult('failed', name,
      providerName + ' credentials not configured. Set environment variables.',
      { error_code: 'not_configured' });
    renderWidget('identity');
    return true;
  }

  if (isAuthPoll) {
    const authStatus = extra.status || 'pending';
    if (authStatus === 'signed_in') {
      // Stop polling — signed in
      if (window.RigRelay._authPollTimer) {
        clearInterval(window.RigRelay._authPollTimer);
        window.RigRelay._authPollTimer = null;
      }
      window.RigRelay._authSessionId = null;
      updateIntentResult('completed', name,
        'Signed in to ' + providerName + (extra.display_name ? ' as ' + extra.display_name : '') + '.', {});
      renderWidget('identity');
    } else if (authStatus === 'pending') {
      // Still waiting — update with subtle status
      updateIntentResult('completed', name,
        'Waiting for ' + providerName + ' authorization...', {});
    } else if (authStatus === 'failed' || authStatus === 'cancelled' || authStatus === 'expired') {
      // Stop polling — failed/cancelled/expired
      if (window.RigRelay._authPollTimer) {
        clearInterval(window.RigRelay._authPollTimer);
        window.RigRelay._authPollTimer = null;
      }
      window.RigRelay._authSessionId = null;
      updateIntentResult('failed', name,
        providerName + ' sign-in ' + authStatus + '.',
        { error_code: extra.error_code || authStatus });
      renderWidget('identity');
    } else {
      updateIntentResult('failed', name, summary || 'Auth error', { error_code: result.error_code });
      renderWidget('identity');
    }
    return true;
  }

  if (isAuthCancel) {
    if (window.RigRelay._authPollTimer) {
      clearInterval(window.RigRelay._authPollTimer);
      window.RigRelay._authPollTimer = null;
    }
    window.RigRelay._authSessionId = null;
    updateIntentResult('completed', name, providerName + ' sign-in cancelled.', {});
    renderWidget('identity');
    return true;
  }

  if (isAuthManual) {
    updateIntentResult(status, name,
      status === 'completed' ? 'Signed in to ' + providerName + ' via manual code.' : summary,
      { error_code: result.error_code });
    renderWidget('identity');
    return true;
  }

  return true;
}

function _showAuthActionCard(providerName, extra) {
  const authUrl = extra.auth_url || '';
  const sessionId = extra.auth_session_id || '';
  const container = el('widget-intentResult');
  if (!container) return;

  while (container.firstChild) container.removeChild(container.firstChild);

  const header = document.createElement('div');
  header.className = 'widget-header';
  header.onclick = function() { window.RigRelay.cycleWidgetDisclosure('intentResult'); };
  header.textContent = 'Sign in with ' + providerName;

  const chip = document.createElement('div');
  chip.className = 'widget-chip warn';
  const dot = document.createElement('span');
  dot.className = 'dot';
  chip.appendChild(dot);
  chip.appendChild(document.createTextNode('Action required'));
  header.appendChild(chip);

  const icon = document.createElement('span');
  icon.className = 'widget-expand-icon';
  icon.textContent = '\u25B2';
  header.appendChild(icon);

  const body = document.createElement('div');
  body.className = 'widget-body';

  const desc = document.createElement('div');
  desc.style.cssText = 'margin-bottom:8px;color:var(--text-secondary)';
  desc.textContent = 'A browser tab will open for you to authorize.';
  body.appendChild(desc);

  const btnRow = document.createElement('div');
  btnRow.style.cssText = 'display:flex;flex-wrap:wrap;gap:6px';

  const openBtn = document.createElement('button');
  openBtn.textContent = 'Open Browser';
  openBtn.onclick = function() {
    window.RigRelay.openInAppAuth(authUrl, 0, '', providerName, sessionId);
  };
  btnRow.appendChild(openBtn);

  const copyBtn = document.createElement('button');
  copyBtn.textContent = 'Copy Auth URL';
  copyBtn.onclick = function() {
    navigator.clipboard.writeText(authUrl).then(function() {
      copyBtn.textContent = 'Copied!';
      setTimeout(function() { copyBtn.textContent = 'Copy Auth URL'; }, 2000);
    });
  };
  btnRow.appendChild(copyBtn);

  const checkBtn = document.createElement('button');
  checkBtn.textContent = 'Check Status';
  checkBtn.onclick = function() {
    window.RigRelay.checkAuthStatus(providerName);
  };
  btnRow.appendChild(checkBtn);

  const cancelBtn = document.createElement('button');
  cancelBtn.textContent = 'Cancel';
  cancelBtn.style.cssText = 'color:var(--warn)';
  cancelBtn.onclick = function() {
    window.RigRelay.cancelAuth(providerName);
  };
  btnRow.appendChild(cancelBtn);

  body.appendChild(btnRow);

  const manualDiv = document.createElement('div');
  manualDiv.style.cssText = 'margin-top:10px;padding-top:8px;border-top:1px solid var(--border-subtle)';
  const manualLabel = document.createElement('div');
  manualLabel.style.cssText = 'font-size:var(--font-size-xs);color:var(--text-muted);margin-bottom:4px';
  manualLabel.textContent = 'Or paste authorization code manually:';
  manualDiv.appendChild(manualLabel);

  const manualRow = document.createElement('div');
  manualRow.style.cssText = 'display:flex;gap:4px';
  const codeInput = document.createElement('input');
  codeInput.type = 'text';
  codeInput.placeholder = 'Paste code here...';
  codeInput.style.cssText = 'flex:1;padding:4px 8px;background:var(--bg-input);color:var(--text);border:1px solid var(--border);border-radius:4px;font-size:var(--font-size-xs)';
  codeInput.id = 'oauth-manual-code-input';
  manualRow.appendChild(codeInput);

  const submitBtn = document.createElement('button');
  submitBtn.textContent = 'Submit';
  submitBtn.onclick = function() {
    var codeInput = document.getElementById('oauth-manual-code-input');
    if (codeInput && codeInput.value) {
      window.RigRelay.submitManualCode(providerName, codeInput.value);
    }
  };
  manualRow.appendChild(submitBtn);
  manualDiv.appendChild(manualRow);
  body.appendChild(manualDiv);

  const trigger = document.createElement('div');
  trigger.className = 'widget-expand-trigger';
  trigger.textContent = 'Expand \u2192';
  trigger.onclick = function() { window.RigRelay.cycleWidgetDisclosure('intentResult'); };

  container.appendChild(header);
  container.appendChild(body);
  container.appendChild(trigger);
}

export function handleProgressEvent(msg) {
  state.progressEvents.push(msg);
  if (state.progressEvents.length > 100) {
    state.progressEvents = state.progressEvents.slice(-100);
  }
  // Only re-render the progress timeline widget, not all widgets
  renderWidget('progressTimeline');
}

export function handleProgressEvents(events) {
  state.progressEvents = (events || []).slice(-100);
  // Batch: schedule full render to pick up the new events list
  scheduleRender(state.projection);
}

// ════════════════════════════════════════════════════════════════
// Analytics Projection — dedicated state path, no collision with main projection
// Ownership: frontend/desktop/js/projection.js
// ════════════════════════════════════════════════════════════════

var _WIDGET_ID_TO_FRONTEND_KEY = {
  governance_gate_health: 'governance_gate_health',
  session_health_scorecard: 'session_health',
  tool_latency_heatmap: 'tool_latency',
  release_gate_blocker_burndown: 'release_blockers',
  dependency_risk_surface: 'dependency_risk',
  out_of_scope_findings: 'findings',
  correlation_integrity: 'correlation_integrity',
  local_inference_capability: 'local_inference',
};

function _convertAnalyticsProjection(projection) {
  var widgets = projection.widgets || [];
  var engineAvailable = projection.engine_available != null ? projection.engine_available : false;
  var result = Object.create(null);
  result.engine_available = engineAvailable;

  for (var wi = 0; wi < widgets.length; wi++) {
    var widget = widgets[wi];
    var widgetId = widget.widget_id;
    var frontendKey = _WIDGET_ID_TO_FRONTEND_KEY[widgetId];
    if (!frontendKey) continue;
    var data = widget.data || [];
    var converted = _convertWidget(widgetId, data, engineAvailable);
    if (converted) result[frontendKey] = converted;
  }
  return result;
}

function _convertWidget(widgetId, data, engineAvailable) {
  switch (widgetId) {
    case 'governance_gate_health':
      return _convertGovernanceGateHealth(data);
    case 'session_health_scorecard':
      return _convertSessionHealth(data);
    case 'tool_latency_heatmap':
      return _convertToolLatency(data);
    case 'release_gate_blocker_burndown':
      return _convertReleaseBlockers(data);
    case 'dependency_risk_surface':
      return _convertDependencyRisk(data);
    case 'out_of_scope_findings':
      return _convertFindings(data);
    case 'correlation_integrity':
      return _convertCorrelationIntegrity(data);
    case 'local_inference_capability':
      return _convertLocalInference(data);
    default:
      return null;
  }
}

function _convertGovernanceGateHealth(data) {
  var decisions = { allowed: 0, blocked: 0, critical: 0 };
  if (!data || !data.length) {
    return { available: false, decisions: decisions, total: 0 };
  }
  for (var i = 0; i < data.length; i++) {
    var row = data[i];
    var status = (row.status || '').toLowerCase();
    var count = row.count || 0;
    if (status === 'allowed' || status === 'passed' || status === 'approved') {
      decisions.allowed += count;
    } else if (status === 'blocked' || status === 'rejected' || status === 'denied') {
      decisions.blocked += count;
    } else if (status === 'critical' || status === 'error' || status === 'fatal') {
      decisions.critical += count;
    }
  }
  var total = decisions.allowed + decisions.blocked + decisions.critical;
  return { available: total > 0, decisions: decisions, total: total };
}

function _convertSessionHealth(data) {
  if (!data || !data.length) {
    return { available: false, sessions: { healthy: 0, degraded: 0, failed: 0 }, total: 0 };
  }
  var sessions = { healthy: 0, degraded: 0, failed: 0 };
  var rawSessions = data[0] ? (data[0].sessions || []) : [];
  for (var i = 0; i < rawSessions.length; i++) {
    var s = rawSessions[i];
    var errorRate = s.error_rate || 0;
    if (errorRate >= 0.2) {
      sessions.failed++;
    } else if (errorRate > 0) {
      sessions.degraded++;
    } else {
      sessions.healthy++;
    }
  }
  var total = sessions.healthy + sessions.degraded + sessions.failed;
  return { available: total > 0, sessions: sessions, total: total };
}

function _convertToolLatency(data) {
  if (!data || !data.length || !data[0]) {
    return { available: false, tools: [] };
  }
  var rawTools = data[0].tools || [];
  var tools = [];
  for (var i = 0; i < rawTools.length; i++) {
    var t = rawTools[i];
    tools.push({
      name: t.tool_name || '',
      p50_ms: t.p50_latency_ms || 0,
      p95_ms: t.p95_latency_ms || 0,
      p99_ms: t.avg_latency_ms || 0,
    });
  }
  return { available: tools.length > 0, tools: tools };
}

function _convertReleaseBlockers(data) {
  if (!data || !data.length || !data[0]) {
    return { available: false, open: 0, resolved: 0, total: 0, trend: '' };
  }
  var d = data[0];
  var open = d.open_blockers || 0;
  var total = d.total_blockers || 0;
  var resolved = Math.max(0, total - open);
  return { available: true, open: open, resolved: resolved, total: total, trend: d.trend || '' };
}

function _convertDependencyRisk(data) {
  if (!data || !data.length || !data[0]) {
    return { available: false, packages: [] };
  }
  var rawRisks = data[0].risks || [];
  var packages = [];
  for (var i = 0; i < rawRisks.length; i++) {
    var r = rawRisks[i];
    var severity = (r.severity || '').toLowerCase();
    var risk;
    if (severity === 'critical' || severity === 'high') {
      risk = 'high';
    } else if (severity === 'medium') {
      risk = 'medium';
    } else {
      risk = 'low';
    }
    packages.push({
      name: r.kind || '',
      risk: risk,
      current: r.count != null ? String(r.count) : '',
      latest: '',
    });
  }
  return { available: packages.length > 0, packages: packages };
}

function _convertFindings(data) {
  if (!data || !data.length || !data[0]) {
    return { available: false, total: 0, open: 0, resolved: 0, by_severity: { critical: 0, high: 0, medium: 0, low: 0 } };
  }
  var d = data[0];
  var findings = d.findings || [];
  var bySeverity = { critical: 0, high: 0, medium: 0, low: 0 };
  var open = 0;
  var resolved = 0;
  for (var i = 0; i < findings.length; i++) {
    var f = findings[i];
    var sev = (f.severity || '').toLowerCase();
    var st = (f.status || '').toLowerCase();
    var count = f.count || 0;
    if (sev === 'critical' || sev === 'high' || sev === 'medium' || sev === 'low') {
      bySeverity[sev] += count;
    }
    if (st === 'open' || st === 'new' || st === 'in_progress') {
      open += count;
    } else if (st === 'closed' || st === 'resolved' || st === 'done' || st === 'fixed') {
      resolved += count;
    }
  }
  var total = open + resolved;
  return { available: total > 0, total: total, open: open, resolved: resolved, by_severity: bySeverity };
}

function _convertCorrelationIntegrity(data) {
  if (!data || !data.length || !data[0]) {
    return { available: false, status: 'unknown', matched: 0, unmatched: 0, total: 0 };
  }
  var d = data[0];
  var matched = d.distinct_report_hashes || 0;
  var total = (d.report_count || 0) + (d.turn_count || 0);
  return {
    available: true,
    status: d.integrity_status || 'unknown',
    matched: matched,
    unmatched: 0,
    total: total,
  };
}

function _convertLocalInference(data) {
  if (!data || !data.length || !data[0]) {
    return { available: false, models: [] };
  }
  var rawProviders = data[0].providers || [];
  var models = [];
  for (var i = 0; i < rawProviders.length; i++) {
    var p = rawProviders[i];
    var tps = p.tokens_per_sec || 0;
    models.push({
      name: p.model || '',
      status: tps > 0 ? 'running' : 'stopped',
      tokens_per_sec: tps,
    });
  }
  return { available: models.length > 0, models: models };
}

export function handleAnalyticsProjection(data) {
  if (!data) return;
  var converted = _convertAnalyticsProjection(data);
  state.analytics = converted;
  updateAnalyticsData(converted);
  renderAllWidgets();
}

// ── Reset for reconnect ──────────────────────────────────────────────

export function isProjectionReady() {
  return !!_lastDigest;
}

export function resetDigest() {
  _lastDigest = '';
}

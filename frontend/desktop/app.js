// Rig Relay Cockpit Frontend Logic
let wsClient = null;
let wsConnected = false;
let wsAuthFailed = false;
let currentMode = 'operate';

let chatState = {
  messages: [],
  backend_wired: false,
  pending_response: false
};

// ── Mode Switching ──

function switchMode(mode) {
  currentMode = mode;
  document.querySelectorAll('.mode-btn').forEach(b => b.classList.remove('active'));
  document.getElementById('mode-' + mode).classList.add('active');
  document.querySelectorAll('.mode-view').forEach(v => v.classList.remove('active'));
  document.getElementById(mode + '-view').classList.add('active');
}

// ── Sanitize: textContent only for untrusted content ──

function setText(el, text) {
  if (el) el.textContent = String(text);
}

function escapeHtml(str) {
  if (typeof str !== 'string') return String(str);
  return str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

// Helper: builder-safe innerHTML for trusted backend widget HTML
function setWidgetHTML(el, html) {
  if (el) el.innerHTML = html;
}

function row(label, value, cls) {
  return '<tr><td class="k">' + escapeHtml(label) + '</td><td class="' + (cls || '') + '">' + escapeHtml(value) + '</td></tr>';
}

// ── Projection Rendering ──

function renderProjection(data) {
  if (!data) return;

  // Header
  setText(document.getElementById('version-badge'), (data.app_version || ''));

  // OperatorHeader
  setText(document.getElementById('op-version'), data.app_version || '—');
  setText(document.getElementById('op-mode'), 'desktop');

  // SafetyState
  const cs = data.current_state || {};
  var dirtyCount = 0;
  var leaseCount = 0;
  var staleCount = 0;
  if (cs.available) {
    setText(document.getElementById('op-session'), (cs.generated_at || '').substring(0, 10) || '—');
    dirtyCount = (cs.active_writers || 0) + (cs.active_readers || 0);
    leaseCount = cs.active_children || 0;
    staleCount = cs.stale_leases || 0;
  }
  setText(document.getElementById('safety-dirty'), String(dirtyCount));
  setText(document.getElementById('safety-leases'), String(leaseCount));
  setText(document.getElementById('safety-stale'), String(staleCount));

  // ValidationSummary from projection update field (or fallback)
  var valPassed = 0;
  var valFailed = 0;
  if (data._last_validation) {
    valPassed = data._last_validation.passed_count || 0;
    valFailed = data._last_validation.failed_count || 0;
  }
  setText(document.getElementById('validation-passed'), String(valPassed));
  setText(document.getElementById('validation-failed'), String(valFailed));

  // StorageBudget
  const storage = data.storage || {};
  if (storage.available) {
    setText(document.getElementById('storage-size'), (storage.total_size_mb || 0).toFixed(1) + ' MB');
    setText(document.getElementById('storage-budget'), storage.budget_status || '—');
    setText(document.getElementById('storage-prune'), String(storage.prune_candidate_count || 0));
    var budgetPill = document.getElementById('storage-status-pill');
    if (budgetPill) {
      budgetPill.className = 'safety-indicator ' + (storage.budget_status === 'ok' ? 'ok' : 'warn');
      setText(budgetPill.querySelector('.dot + *'), storage.budget_status === 'ok' ? 'OK' : 'Warn');
    }
  }

  // NextAction (from projection or default)
  renderNextAction(data);

  // Review mode data
  renderReceiptTimeline(data);
  renderRefinementBacklog(data);
  renderReviewValidation(data);
  renderReviewStorage(data);
  renderSemanticSnippetsInReview(data.semantic_snippets);
  renderDatasetInReview(data.dataset);

  // System mode data
  renderTelemetryBundleInSystem(data.telemetry_bundle);
  renderUpdateStatus(data.update);
  renderProjectionSources(data);
  renderStorageDiagnostics(data);
  renderConnectionStatus(data);

  // Provider data
  renderProviderHealthPill(data);
  renderModelProvidersInSystem(data.providers);
}

function renderNextAction(data) {
  var actionEl = document.getElementById('next-action-name');
  var detailEl = document.getElementById('next-action-detail');
  var readyEl = document.getElementById('next-action-ready');
  var blockedEl = document.getElementById('next-action-blocked');

  var warnings = data.warnings && data.warnings.length;
  if (warnings) {
    setText(actionEl, 'Review Warnings');
    setText(detailEl, data.warnings.length + ' data sources need attention.');
    if (readyEl) readyEl.style.display = 'none';
    if (blockedEl) { blockedEl.style.display = 'block'; setText(blockedEl, data.warnings.length + ' warnings'); }
    return;
  }

  var hasReceipts = data._receipts && data._receipts.length;
  if (hasReceipts) {
    setText(actionEl, 'Review Receipt Timeline');
    setText(detailEl, data._receipts.length + ' receipts to review.');
    if (readyEl) { readyEl.style.display = 'block'; setText(readyEl, 'Ready'); }
    if (blockedEl) blockedEl.style.display = 'none';
    return;
  }

  setText(actionEl, 'Refresh Projection');
  setText(detailEl, 'System ready. No pending actions.');
  if (readyEl) readyEl.style.display = 'none';
  if (blockedEl) blockedEl.style.display = 'none';
}

// ── Review Mode Renderers ──

function renderReceiptTimeline(data) {
  var body = document.getElementById('receipt-timeline-body');
  if (!body) return;
  var receipts = data._receipts;
  if (!receipts || !receipts.length) {
    body.innerHTML = '<span class="missing">No receipts available.</span>';
    return;
  }
  var html = '';
  receipts.forEach(function(r) {
    var kind = (r.kind || 'unknown').toLowerCase();
    html += '<div class="receipt-entry">' +
      '<div class="receipt-dot ' + kind + '"></div>' +
      '<div class="receipt-body">' +
      '<div class="receipt-kind">' + escapeHtml(r.kind || 'Unknown') + '</div>' +
      '<div class="receipt-summary">' + escapeHtml(r.summary || '') + '</div>' +
      '<div class="receipt-meta">' + escapeHtml(r.timestamp || '') + (r.sha256 ? ' &middot; ' + r.sha256.substring(0, 12) : '') + '</div>' +
      '</div></div>';
  });
  body.innerHTML = html;
}

function renderRefinementBacklog(data) {
  var body = document.getElementById('refinement-backlog-body');
  if (!body) return;
  var ref = data._refinement;
  if (!ref) {
    body.innerHTML = '<span class="missing">No refinement data available.</span>';
    return;
  }
  body.innerHTML = '<table class="kv">' +
    '<tr><td class="k">Pending</td><td>' + (ref.pending || 0) + '</td></tr>' +
    '<tr><td class="k">Refined</td><td>' + (ref.refined || 0) + '</td></tr>' +
    '<tr><td class="k">Last</td><td>' + escapeHtml(ref.last_refined_at || '—') + '</td></tr>' +
    '</table>';
}

function renderReviewValidation(data) {
  var body = document.getElementById('review-validation-body');
  if (!body) return;
  var val = data._last_validation;
  if (!val) {
    body.innerHTML = '<span class="missing">No validation history available.</span>';
    return;
  }
  body.innerHTML = '<table class="kv">' +
    '<tr><td class="k">Status</td><td>' + escapeHtml(val.status || 'unknown') + '</td></tr>' +
    '<tr><td class="k">Passed</td><td>' + (val.passed_count || 0) + '</td></tr>' +
    '<tr><td class="k">Failed</td><td>' + (val.failed_count || 0) + '</td></tr>' +
    '<tr><td class="k">Duration</td><td>' + (val.duration_ms || '—') + ' ms</td></tr>' +
    (val.last_run_at ? '<tr><td class="k">Last run</td><td>' + escapeHtml(val.last_run_at) + '</td></tr>' : '') +
    '</table>';
}

function renderReviewStorage(data) {
  var body = document.getElementById('review-storage-body');
  if (!body) return;
  var st = data.storage;
  if (!st || !st.available) {
    body.innerHTML = '<span class="missing">No storage audit data available.</span>';
    return;
  }
  var html = '<table class="kv">' +
    '<tr><td class="k">Total</td><td>' + (st.total_size_mb || 0).toFixed(1) + ' MB</td></tr>' +
    '<tr><td class="k">Budget</td><td>' + escapeHtml(st.budget_status || '—') + '</td></tr>' +
    '<tr><td class="k">Rollup candidates</td><td>' + (st.rollup_candidate_count || 0) + '</td></tr>' +
    '<tr><td class="k">Prune candidates</td><td>' + (st.prune_candidate_count || 0) + '</td></tr>' +
    '<tr><td class="k">Stale leases</td><td>' + (st.stale_lease_count || 0) + '</td></tr>';
  if (st.recommendations && st.recommendations.length) {
    html += '<tr><td class="k">Actions</td><td><ul style="margin:0;padding-left:16px">';
    st.recommendations.forEach(function(r) {
      html += '<li>' + escapeHtml(r) + '</li>';
    });
    html += '</ul></td></tr>';
  }
  html += '</table>';
  body.innerHTML = html;
}

function renderSemanticSnippetsInReview(data) {
  var body = document.getElementById('review-snippets-body');
  var status = document.getElementById('snippet-status');
  if (!body) return;
  if (!data || !data.available) {
    body.innerHTML = '<span class="missing">No snippet data available.</span>';
    if (status) { status.className = 'source-status warning'; status.textContent = '—'; }
    return;
  }
  if (status) { status.className = 'source-status ok'; status.textContent = data.snippet_count + ' snippets'; }
  body.innerHTML = '<table class="kv">' +
    '<tr><td class="k">Snippets</td><td>' + (data.snippet_count || 0) + '</td></tr>' +
    '<tr><td class="k">Skipped</td><td>' + (data.skipped_count || 0) + '</td></tr>' +
    '<tr><td class="k">Remote safe</td><td>' + (data.remote_sharing_safe ? 'Yes' : 'No') + '</td></tr>' +
    '</table>';
}

function renderDatasetInReview(data) {
  var body = document.getElementById('review-dataset-body');
  var status = document.getElementById('dataset-status');
  if (!body) return;
  if (!data || !data.available) {
    body.innerHTML = '<span class="missing">No dataset data available.</span>';
    if (status) { status.className = 'source-status warning'; status.textContent = '—'; }
    return;
  }
  if (status) { status.className = 'source-status ok'; status.textContent = 'OK'; }
  body.innerHTML = '<table class="kv">' +
    '<tr><td class="k">Coordination</td><td>' + (data.coordination_rows || 0) + ' rows</td></tr>' +
    '<tr><td class="k">Tool failures</td><td>' + (data.tool_failure_rows || 0) + ' rows</td></tr>' +
    '<tr><td class="k">Artifact reuse</td><td>' + (data.artifact_reuse_rows || 0) + ' rows</td></tr>' +
    '<tr><td class="k">Checkpoints</td><td>' + (data.checkpoint_rows || 0) + ' rows</td></tr>' +
    '</table>';
}

// ── System Mode Renderers ──

function renderTelemetryBundleInSystem(data) {
  var body = document.getElementById('sys-telemetry-body');
  var status = document.getElementById('telemetry-bundle-status');
  if (!body) return;
  if (!data || !data.available) {
    body.innerHTML = '<span class="missing">No telemetry bundle available.</span>';
    if (status) { status.className = 'source-status warning'; status.textContent = '—'; }
    return;
  }
  if (status) { status.className = 'source-status ok'; status.textContent = data.share_level || 'OK'; }
  body.innerHTML = '<table class="kv">' +
    '<tr><td class="k">Bundle</td><td>' + escapeHtml(data.bundle_id || '—') + '</td></tr>' +
    '<tr><td class="k">Share level</td><td>' + escapeHtml(data.share_level || '—') + '</td></tr>' +
    '<tr><td class="k">Status</td><td>' + escapeHtml(data.status || '—') + '</td></tr>' +
    '<tr><td class="k">SHA256</td><td style="font-family:var(--font-mono);font-size:0.7rem">' + escapeHtml((data.bundle_sha256 || '').substring(0, 16) + '...') + '</td></tr>' +
    '</table>';
}

function renderUpdateStatus(data) {
  var body = document.getElementById('sys-update-body');
  var status = document.getElementById('update-status-pill');
  if (!body) return;
  if (!data || !data.available) {
    body.innerHTML = '<span class="missing">No update data available.</span>';
    if (status) { status.className = 'source-status warning'; status.textContent = '—'; }
    return;
  }
  if (status) { status.className = 'source-status ' + (data.update_available ? 'warning' : 'ok'); status.textContent = data.update_available ? 'Update available' : 'Up to date'; }
  body.innerHTML = '<table class="kv">' +
    '<tr><td class="k">Current</td><td>' + escapeHtml(data.current_version || '—') + '</td></tr>' +
    '<tr><td class="k">Latest</td><td>' + escapeHtml(data.latest_version || '—') + '</td></tr>' +
    '<tr><td class="k">Restart required</td><td>' + (data.restart_required ? 'Yes' : 'No') + '</td></tr>' +
    '</table>';
}

function renderProjectionSources(data) {
  var body = document.getElementById('sys-projection-sources-body');
  if (!body) return;
  var sources = data.source_status;
  if (!sources) {
    body.innerHTML = '<span class="missing">No projection source data.</span>';
    return;
  }
  var html = '<table class="kv">';
  var count = 0;
  for (var key in sources) {
    if (sources.hasOwnProperty(key)) {
      var available = sources[key];
      html += '<tr><td class="k">' + escapeHtml(key) + '</td><td class="' + (available ? 'ok' : 'warning') + '">' + (available ? 'available' : 'missing') + '</td></tr>';
      count++;
    }
  }
  html += '</table>';
  if (count === 0) html = '<span class="missing">No projection source data.</span>';
  body.innerHTML = html;
}

function renderStorageDiagnostics(data) {
  var body = document.getElementById('sys-storage-diag-body');
  if (!body) return;
  var st = data.storage;
  if (!st || !st.available) {
    body.innerHTML = '<span class="missing">No diagnostics available.</span>';
    return;
  }
  body.innerHTML = '<table class="kv">' +
    '<tr><td class="k">Rollup candidates</td><td>' + (st.rollup_candidate_count || 0) + '</td></tr>' +
    '<tr><td class="k">Prune candidates</td><td>' + (st.prune_candidate_count || 0) + '</td></tr>' +
    '<tr><td class="k">Stale leases</td><td>' + (st.stale_lease_count || 0) + '</td></tr>' +
    '</table>' +
    '<div class="action-buttons compact" style="margin-top:8px">' +
    '<button onclick="runIntent(\'gc_artifacts\')" class="secondary-btn">Run GC</button>' +
    '</div>';
}

function renderConnectionStatus(data) {
  var transport = document.getElementById('sys-transport');
  var wsStatus = document.getElementById('sys-ws-status');
  var bridgeStatus = document.getElementById('sys-bridge-status');
  var wsPill = document.getElementById('ws-status-pill');
  if (!transport) return;

  var hasWs = typeof wsClient !== 'undefined' && wsClient !== null;
  setText(transport, hasWs ? 'WebSocket / Bridge' : 'Bridge only');
  setText(wsStatus, wsConnected ? 'Connected' : 'Disconnected');
  setText(bridgeStatus, window.pywebview && window.pywebview.api ? 'Available' : 'Unavailable');

  if (wsPill) {
    if (wsConnected) {
      wsPill.className = 'safety-indicator ok';
      var textNode = wsPill.querySelector('.dot + *') || wsPill.lastChild;
      setText(wsPill.querySelector('.dot').nextSibling ? wsPill.querySelector('.dot').nextSibling : wsPill.lastChild, 'Connected');
    } else {
      wsPill.className = 'safety-indicator warn';
    }
  }
}

// ── Provider Rendering ──

function renderProviderHealthPill(data) {
  var pill = document.getElementById('provider-health-pill');
  var detail = document.getElementById('provider-health-detail');
  if (!pill) return;

  // Try to get provider status from the projection
  var providerData = data.providers;
  if (!providerData || !providerData.total) {
    setText(pill.querySelector('.dot + *') || pill.lastChild, 'No data');
    pill.className = 'safety-indicator warn';
    if (detail) setText(detail, 'No provider data in projection.');
    return;
  }

  var configured = providerData.configured || 0;
  var total = providerData.total || 0;
  setText(pill.querySelector('.dot + *') || pill.lastChild, configured + '/' + total + ' configured');
  pill.className = 'safety-indicator ' + (configured > 0 ? 'ok' : 'warn');
  if (detail) setText(detail, configured + ' of ' + total + ' model providers configured.');
}

function renderModelProvidersInSystem(providerData) {
  var body = document.getElementById('providers-table');
  var pill = document.getElementById('sys-providers-pill');
  if (!body) return;

  if (!providerData || !providerData.providers || !providerData.providers.length) {
    body.innerHTML = '<tr><td class="k">No data</td><td>Run provider_status to load.</td></tr>';
    if (pill) { pill.className = 'safety-indicator warn'; setText(pill.querySelector('.dot + *') || pill.lastChild, '—'); }
    return;
  }

  var html = '';
  var configuredCount = 0;
  providerData.providers.forEach(function(p) {
    var configured = p.configured || false;
    var keySource = p.key_source || 'missing';
    var fingerprint = p.key_fingerprint || '';
    var status = p.status || 'unknown';
    if (configured) configuredCount++;

    html += '<tr>' +
      '<td class="k">' + escapeHtml(p.display_name || p.provider) + '</td>' +
      '<td class="' + (configured ? 'ok' : 'warning') + '">' + (configured ? 'Configured' : 'Missing') + '</td>' +
      '<td style="font-size:0.7rem;color:var(--text-muted)">' + escapeHtml(keySource) + '</td>' +
      '<td style="font-size:0.65rem;font-family:var(--font-mono);color:var(--text-muted)">' + escapeHtml(fingerprint.substring(0, 20)) + '</td>' +
      '<td class="' + (status === 'valid' ? 'ok' : 'warning') + '" style="font-size:0.7rem">' + escapeHtml(status) + '</td>' +
      '</tr>';
  });

  body.innerHTML = html;
  if (pill) {
    pill.className = 'safety-indicator ' + (configuredCount > 0 ? 'ok' : 'warn');
    setText(pill.querySelector('.dot + *') || pill.lastChild, configuredCount + '/' + providerData.providers.length + ' configured');
  }
}

// ── Provider Actions ──

function saveProviderKey() {
  var select = document.getElementById('provider-select');
  var input = document.getElementById('provider-key-input');
  var provider = select ? select.value : '';
  var apiKey = input ? input.value : '';

  if (!provider) { alert('Please select a provider.'); return; }
  if (!apiKey) { alert('Please paste an API key.'); return; }

  runIntentWithCallback('provider_onboarding_save_key', { provider: provider, api_key: apiKey }, function(result) {
    displayIntentResult('provider-intent-result', result);
    // Clear the input field after save — no raw key remains visible
    if (input) input.value = '';
    // Refresh provider status
    loadProviderStatus();
  });
}

function removeProviderKey() {
  var select = document.getElementById('provider-select');
  var provider = select ? select.value : '';
  if (!provider) { alert('Please select a provider.'); return; }

  runIntentWithCallback('provider_onboarding_remove_key', { provider: provider }, function(result) {
    displayIntentResult('provider-intent-result', result);
    loadProviderStatus();
  });
}

function checkProviderHealth() {
  var select = document.getElementById('provider-select');
  var provider = select ? select.value : '';

  runIntentWithCallback('provider_health_check', { provider: provider, network_allowed: false }, function(result) {
    displayIntentResult('provider-intent-result', result);
  });
}

function loadProviderStatus() {
  runIntentWithCallback('provider_status', {}, function(result) {
    if (result && result.status === 'completed' && result.extra_fields) {
      renderModelProvidersInSystem(result.extra_fields);
    }
  });
}

// ── Intent Result Display ──

function displayIntentResult(elementId, result) {
  var el = document.getElementById(elementId);
  if (!el) return;
  if (!result) { el.style.display = 'none'; return; }

  el.style.display = 'block';
  el.className = 'intent-result-card ' + (result.status === 'completed' ? 'ok' : result.status === 'refused' ? 'warn' : 'error');

  var html = '<div class="status-line">' + escapeHtml(result.intent_name || 'Intent') + ': ' + escapeHtml(result.status || 'unknown') + '</div>';
  if (result.summary) {
    html += '<div class="detail-line">' + escapeHtml(result.summary) + '</div>';
  }
  if (result.kind) {
    var structured = renderStructuredCard(result.kind, result.summary || '', result);
    html += structured;
  }
  el.innerHTML = html;

  // Also update LatestIntentResult in Operate
  var latestBody = document.getElementById('latest-intent-body');
  if (latestBody) {
    latestBody.innerHTML = html;
    latestBody.className = 'widget-card-body ' + (result.status === 'completed' ? 'ok' : 'warn');
  }
}

function displayOperateIntentResult(result) {
  displayIntentResult('operate-intent-result', result);
}

function renderStructuredCard(kind, summary, result) {
  switch (kind) {
    case 'validation_suite':
      return renderValidationSuiteCard(summary);
    case 'storage_audit':
      return renderStorageAuditCard(summary);
    case 'report':
      return renderReportCard(summary);
    case 'packets':
      return renderPacketsCard(summary);
    case 'projection':
      return renderProjectionCard(summary);
    case 'checkpoint':
      return renderCheckpointCard(summary);
    case 'lease_cleanup':
      return renderLeaseCleanupCard(summary);
    case 'bundle_dry_run':
    case 'plan_dry_run':
    case 'validation':
    case 'chat_state':
    case 'authorization_receipt':
    case 'identity_status':
    case 'provider_status':
    case 'provider_onboarding':
    case 'summary':
    default:
      return '<div class="detail-line">' + escapeHtml(summary) + '</div>';
  }
}

function renderValidationSuiteCard(summary) {
  var m = summary.match(/Validation suite '(.+?)':\s*(\w+)\.\s*(\d+)\s+executed,\s*(\d+)\s+skipped\.\s*Steps:\s*\[(.+?)\]\s*\.\s*sha256:\s*(\S+)/);
  if (!m) return '<div class="detail-line">' + escapeHtml(summary) + '</div>';
  return '<table class="kv">' +
    row('Suite', m[1]) +
    row('Status', m[2]) +
    row('Executed', m[3]) +
    row('Skipped', m[4]) +
    row('Steps', m[5]) +
    row('SHA256', m[6]) +
    '</table>';
}

function renderStorageAuditCard(summary) {
  var m = summary.match(/Storage audit:\s*([\d.]+)\s*MB,\s*budget=(\w+),\s*stale_leases=(\d+),\s*rollup_candidates=(\d+),\s*prune_candidates=(\d+),\s*(\d+)\s*recommendations/);
  if (!m) return '<div class="detail-line">' + escapeHtml(summary) + '</div>';
  var budgetCls = m[2] === 'ok' ? 'ok' : 'warning';
  return '<table class="kv">' +
    row('Total', m[1] + ' MB') +
    row('Budget', m[2], budgetCls) +
    row('Stale Leases', m[3]) +
    row('Rollup Candidates', m[4]) +
    row('Prune Candidates', m[5]) +
    row('Recommendations', m[6]) +
    '</table>';
}

function renderReportCard(summary) {
  var m = summary.match(/(\d+)\s+backlog items/);
  if (!m) return '<div class="detail-line">' + escapeHtml(summary) + '</div>';
  return '<table class="kv">' +
    row('Backlog Items', m[1]) +
    row('Summary', summary) +
    '</table>';
}

function renderPacketsCard(summary) {
  var m = summary.match(/(\d+)\s+packets/);
  if (!m) return '<div class="detail-line">' + escapeHtml(summary) + '</div>';
  return '<table class="kv">' +
    row('Packets Created', m[1]) +
    row('Mode', 'dry-run') +
    '</table>';
}

function renderProjectionCard(summary) {
  var m = summary.match(/(\d+)\/(\d+)\s+sources/);
  if (!m) return '<div class="detail-line">' + escapeHtml(summary) + '</div>';
  return '<table class="kv">' +
    row('Sources', m[1] + ' / ' + m[2] + ' available') +
    '</table>';
}

function renderCheckpointCard(summary) {
  var m = summary.match(/committed:\s*(\S+)\.\s*(\d+)\s+files/);
  if (!m) return '<div class="detail-line">' + escapeHtml(summary) + '</div>';
  var shaM = summary.match(/sha256:\s*(\S+)/);
  return '<table class="kv">' +
    row('Commit', m[1]) +
    row('Files', m[2]) +
    row('SHA256', shaM ? shaM[1] : '\u2014') +
    '</table>';
}

function renderLeaseCleanupCard(summary) {
  var m = summary.match(/archive:\s*(\w+)\.\s*(\d+)\s+entries/);
  if (!m) return '<div class="detail-line">' + escapeHtml(summary) + '</div>';
  return '<table class="kv">' +
    row('Action', m[1]) +
    row('Entries', m[2]) +
    '</table>';
}

// ── Chat ──

function renderChat(data) {
  if (!data || !data.messages) return;

  var transcript = document.getElementById('chat-transcript');
  var statusBadge = document.getElementById('chat-status-badge');

  chatState.messages = data.messages;
  chatState.backend_wired = data.backend_wired || false;

  if (statusBadge) {
    statusBadge.className = 'source-status ' + (chatState.backend_wired ? 'ok' : 'warning');
    statusBadge.textContent = chatState.backend_wired ? 'Backend Online' : 'Backend Offline';
  }

  var sendBtn = document.getElementById('send-btn');
  if (sendBtn) sendBtn.disabled = !chatState.backend_wired;

  if (!transcript) return;
  transcript.innerHTML = '';
  data.messages.forEach(function(msg) {
    var div = document.createElement('div');
    div.className = 'message ' + (msg.role || 'system');
    div.textContent = msg.content || '';
    transcript.appendChild(div);
  });
  transcript.scrollTop = transcript.scrollHeight;
}

function updateCharCount() {
  var input = document.getElementById('chat-input');
  var count = document.getElementById('char-count');
  if (input && count) count.textContent = input.value.length + '/4000';
}

function sendMessage() {
  var input = document.getElementById('chat-input');
  if (!input || !input.value.trim()) return;
  if (!chatState.backend_wired) return;

  var text = input.value.trim();
  input.value = '';
  updateCharCount();

  if (wsClient && wsConnected) {
    wsClient.sendMessage({ type: 'chat_message', content: text });
  } else if (window.pywebview && window.pywebview.api) {
    window.pywebview.api.send_chat_message(text);
  }

  // Optimistic append
  var transcript = document.getElementById('chat-transcript');
  if (transcript) {
    var div = document.createElement('div');
    div.className = 'message user';
    div.textContent = text;
    transcript.appendChild(div);
    transcript.scrollTop = transcript.scrollHeight;
  }
}

function clearChat() {
  if (wsClient && wsConnected) {
    wsClient.sendMessage({ type: 'clear_chat' });
  } else if (window.pywebview && window.pywebview.api) {
    window.pywebview.api.clear_chat();
  }
  var transcript = document.getElementById('chat-transcript');
  if (transcript) {
    transcript.innerHTML = '';
  }
}

// ── Intent Execution ──

function runIntent(name) {
  var resultEl = document.getElementById('operate-intent-result');

  if (wsClient && wsConnected) {
    wsClient.sendMessage({
      type: 'desktop_intent_request',
      intent_name: name,
      dry_run: true
    });
    if (resultEl) {
      resultEl.style.display = 'block';
      resultEl.className = 'intent-result-card pending';
      resultEl.innerHTML = '<div class="status-line">' + escapeHtml(name) + ': running...</div>';
    }
    // Response comes via message handler
    return;
  }

  if (window.pywebview && window.pywebview.api) {
    window.pywebview.api.execute_intent(JSON.stringify({
      intent_name: name,
      dry_run: true
    })).then(function(result) {
      displayOperateIntentResult(result);
    }).catch(function(e) {
      if (resultEl) {
        resultEl.style.display = 'block';
        resultEl.className = 'intent-result-card error';
        resultEl.innerHTML = '<div class="status-line">Error: ' + escapeHtml(e.message || e) + '</div>';
      }
    });
    return;
  }

  if (resultEl) {
    resultEl.style.display = 'block';
    resultEl.className = 'intent-result-card warn';
    resultEl.innerHTML = '<div class="status-line">No backend connection</div>';
  }
}

// ── Authorization Receipts (System mode only) ──

function mintLocalAuthReceipt() {
  var action = document.getElementById('receipt-action');
  var ttl = document.getElementById('receipt-ttl');
  if (!action || !ttl) return;
  runAuthReceipt('mint_authorization_receipt_local', {
    action: action.value,
    ttl_seconds: parseInt(ttl.value) || 300
  });
}

function mintDevReceipt() {
  var action = document.getElementById('receipt-action');
  runAuthReceipt('mint_authorization_receipt_dev', {
    action: action ? action.value : 'checkpoint.commit'
  });
}

function runAuthReceipt(intentName, params) {
  var resultEl = document.getElementById('receipt-result');
  if (!resultEl) return;

  if (wsClient && wsConnected) {
    wsClient.sendMessage({
      type: 'desktop_intent_request',
      intent_name: intentName,
      parameters: params,
      dry_run: false
    });
    resultEl.style.display = 'block';
    resultEl.className = 'intent-result-card pending';
    resultEl.innerHTML = '<div class="status-line">' + escapeHtml(intentName) + ': running...</div>';
    return;
  }

  if (window.pywebview && window.pywebview.api) {
    window.pywebview.api.execute_intent(JSON.stringify({
      intent_name: intentName,
      parameters: params,
      dry_run: false
    })).then(function(result) {
      resultEl.style.display = 'block';
      resultEl.className = 'intent-result-card ' + (result.status === 'completed' ? 'ok' : 'warn');
      resultEl.innerHTML = '<div class="status-line">' + escapeHtml(intentName) + ': ' + escapeHtml(result.status || 'unknown') + '</div>' +
        (result.summary ? '<div class="detail-line">' + escapeHtml(result.summary) + '</div>' : '');
    }).catch(function(e) {
      resultEl.style.display = 'block';
      resultEl.className = 'intent-result-card error';
      resultEl.innerHTML = '<div class="status-line">Error: ' + escapeHtml(e.message || e) + '</div>';
    });
  }
}

function inspectDevReceipt() {
  var jsonText = document.getElementById('receipt-json');
  var resultEl = document.getElementById('receipt-result');
  if (!jsonText || !resultEl) return;
  var receipt;
  try {
    receipt = JSON.parse(jsonText.value);
  } catch (e) {
    resultEl.style.display = 'block';
    resultEl.className = 'intent-result-card error';
    resultEl.innerHTML = '<div class="status-line">Invalid JSON</div>';
    return;
  }

  if (window.pywebview && window.pywebview.api) {
    window.pywebview.api.execute_intent(JSON.stringify({
      intent_name: 'inspect_authorization_receipt',
      parameters: { receipt: receipt },
      dry_run: true
    })).then(function(result) {
      resultEl.style.display = 'block';
      resultEl.className = 'intent-result-card ok';
      resultEl.innerHTML = '<div class="status-line">Inspected Receipt</div>' +
        (result.summary ? '<div class="detail-line">' + escapeHtml(result.summary) + '</div>' : '');
    }).catch(function(e) {
      resultEl.style.display = 'block';
      resultEl.className = 'intent-result-card error';
      resultEl.innerHTML = '<div class="status-line">Error: ' + escapeHtml(e.message || e) + '</div>';
    });
  }
}

// ── WS Message Handler ──

// ── Identity Controls (System mode only) ──

function renderIdentityStatus(result) {
  var body = document.getElementById('identity-body');
  var pill = document.getElementById('identity-status-pill');
  var signOutBtn = document.getElementById('sign-out-btn');
  if (!body) return;

  var extra = result.extra_fields || {};
  var providers = extra.providers || {};
  var anySignedIn = extra.any_signed_in || false;
  var github = providers.github || { status: 'signed_out' };
  var google = providers.google || { status: 'signed_out' };
  var githubStatus = github.status || 'signed_out';
  var googleStatus = google.status || 'signed_out';

  if (anySignedIn) {
    setText(pill, 'Signed In');
    pill.className = 'safety-indicator ok';
    if (signOutBtn) signOutBtn.style.display = 'inline-block';
  } else {
    setText(pill, 'Signed Out');
    pill.className = 'safety-indicator warn';
    if (signOutBtn) signOutBtn.style.display = 'none';
  }

  var html = '<table class="kv">' +
    row('GitHub', githubStatus === 'signed_in' ? (github.display_name || 'Signed In') : 'Not signed in', githubStatus === 'signed_in' ? 'ok' : '') +
    row('Google', googleStatus === 'signed_in' ? (google.display_name || 'Signed In') : 'Not signed in', googleStatus === 'signed_in' ? 'ok' : '') +
    (github.display_name ? row('GitHub User', escapeHtml(github.display_name)) : '') +
    (google.display_name ? row('Google User', escapeHtml(google.display_name)) : '') +
    '</table>';
  if (github.warnings && github.warnings.length) {
    html += '<div class="detail-line warning">' + escapeHtml(github.warnings.join('; ')) + '</div>';
  }
  if (google.warnings && google.warnings.length) {
    html += '<div class="detail-line warning">' + escapeHtml(google.warnings.join('; ')) + '</div>';
  }
  body.innerHTML = html;
}

function handleIdentityIntentResult(result, resultElementId) {
  var el = document.getElementById(resultElementId || 'identity-intent-result');
  if (!el) return;

  el.style.display = 'block';
  el.className = 'intent-result-card ' + (result.status === 'completed' ? 'ok' : 'warn');

  var html = '<div class="status-line">' + escapeHtml(result.intent_name || 'Identity') + ': ' + escapeHtml(result.status || 'unknown') + '</div>';
  if (result.summary) {
    html += '<div class="detail-line">' + escapeHtml(result.summary) + '</div>';
  }

  // Show auth URL if present
  var extra = result.extra_fields || {};
  if (extra.auth_url) {
    html += '<div class="detail-line"><a href="' + escapeHtml(extra.auth_url) + '" target="_blank" class="auth-link">Open browser to sign in</a></div>';
    html += '<div class="detail-line small-note">Redirects to localhost:' + escapeHtml(String(extra.loopback_port || '')) + '</div>';
  }
  if (extra.configured === false) {
    html += '<div class="detail-line warning">Provider not configured. Set credentials and retry.</div>';
  }
  if (extra.scopes && extra.scopes.length) {
    html += '<div class="detail-line">Scopes: ' + escapeHtml(extra.scopes.join(', ')) + '</div>';
  }

  el.innerHTML = html;

  // Refresh identity status display
  if (result.intent_name === 'identity_status') {
    renderIdentityStatus(result);
  }
}

function signOutProvider() {
  var provider = 'github';
  // Check which provider is signed in
  runIntentWithCallback('identity_status', {}, function(result) {
    if (!result) return;
    var extra = result.extra_fields || {};
    var providers = extra.providers || {};
    if ((providers.github || {}).status === 'signed_in') {
      provider = 'github';
    } else if ((providers.google || {}).status === 'signed_in') {
      provider = 'google';
    }
    runIntentWithCallback('sign_out_provider', { provider: provider }, function(signOutResult) {
      handleIdentityIntentResult(signOutResult, 'identity-intent-result');
      // Refresh identity status after sign-out
      runIntentWithCallback('identity_status', {}, function(statusResult) {
        renderIdentityStatus(statusResult);
      });
    });
  });
}

function runIntentWithCallback(name, params, callback) {
  if (window.pywebview && window.pywebview.api) {
    window.pywebview.api.execute_intent(JSON.stringify({
      intent_name: name,
      parameters: params || {},
      dry_run: true
    })).then(callback).catch(function(e) {
      console.warn('Intent failed:', e);
    });
  }
}

// ── Telemetry Consent (System mode) ──

function renderConsentStatus(result) {
  var pill = document.getElementById('consent-status-pill');
  var statusEl = document.getElementById('consent-status');
  var scopesEl = document.getElementById('consent-scopes');
  var grantedEl = document.getElementById('consent-granted-at');
  var revokedEl = document.getElementById('consent-revoked-at');
  var localEl = document.getElementById('consent-local-only');

  var extra = result.extra_fields || {};
  var status = extra.status || 'not_requested';
  var scopes = extra.scopes || [];
  var grantedAt = extra.granted_at || '';
  var revokedAt = extra.revoked_at || '';

  if (pill) {
    if (status === 'granted') {
      setText(pill, 'Granted');
      pill.className = 'safety-indicator ok';
    } else if (status === 'revoked') {
      setText(pill, 'Revoked');
      pill.className = 'safety-indicator warn';
    } else if (status === 'denied') {
      setText(pill, 'Denied');
      pill.className = 'safety-indicator error';
    } else {
      setText(pill, 'Not Requested');
      pill.className = 'safety-indicator warn';
    }
  }
  if (statusEl) setText(statusEl, status);
  if (scopesEl) setText(scopesEl, scopes.length > 0 ? scopes.join(', ') : '—');
  if (grantedEl) setText(grantedEl, grantedAt || '—');
  if (revokedEl) setText(revokedEl, revokedAt || '—');
  if (localEl) setText(localEl, 'true');

  // Sync checkbox states to match current consent scopes
  syncConsentCheckboxes(scopes);
}

function syncConsentCheckboxes(scopes) {
  var allScopes = [
    'usage_metrics', 'content_light_bundles', 'crash_reports',
    'coordination_metrics', 'tool_refinement_metrics',
    'provider_model_benchmarking', 'local_model_benchmarking',
    'commercial_dataset_license', 'aggregate_public_reporting'
  ];
  allScopes.forEach(function(s) {
    var cb = document.getElementById('scope-' + s);
    if (cb) {
      cb.checked = scopes.indexOf(s) >= 0;
    }
  });
}

function updateConsentButton() {
  var btn = document.getElementById('btn-grant-consent');
  if (!btn) return;
  // Disable button if no scopes are checked
  var anyChecked = document.querySelectorAll('.scope-check input:checked').length > 0;
  btn.disabled = !anyChecked;
}

function handleConsentIntentResult(result) {
  var el = document.getElementById('consent-intent-result');
  if (!el) return;

  el.style.display = 'block';
  el.className = 'intent-result-card ' + (result.status === 'completed' ? 'ok' : 'warn');

  var html = '<div class="status-line">' + escapeHtml(result.intent_name || 'Consent') + ': ' + escapeHtml(result.status || 'unknown') + '</div>';
  if (result.summary) {
    html += '<div class="detail-line">' + escapeHtml(result.summary) + '</div>';
  }
  el.innerHTML = html;

  // Refresh consent status
  runIntentWithCallback('telemetry_consent_status', {}, function(statusResult) {
    renderConsentStatus(statusResult);
  });
}

function grantTelemetryConsent() {
  // Collect checked scopes from checkboxes
  var checkedScopes = [];
  document.querySelectorAll('.scope-check input:checked').forEach(function(cb) {
    // Extract scope name from id="scope-{name}"
    var scopeId = cb.id;
    if (scopeId && scopeId.indexOf('scope-') === 0) {
      checkedScopes.push(scopeId.substring(6));
    }
  });
  if (checkedScopes.length === 0) return;
  runIntentWithCallback('telemetry_consent_grant', { scopes: checkedScopes }, function(result) {
    handleConsentIntentResult(result);
  });
}

function revokeTelemetryConsent() {
  runIntentWithCallback('telemetry_consent_revoke', {}, function(result) {
    handleConsentIntentResult(result);
  });
}

// ── Progress Timeline (Review mode) ──

var progressEvents = [];

function renderProgressTimeline() {
  var list = document.getElementById('progress-timeline-list');
  var count = document.getElementById('progress-timeline-count');
  if (!list) return;

  if (progressEvents.length === 0) {
    list.innerHTML = '<span class="missing">No progress events yet. Execute an intent to see progress.</span>';
    if (count) setText(count, '0');
    return;
  }

  if (count) setText(count, String(progressEvents.length));

  var html = '';
  var maxShow = Math.min(progressEvents.length, 30);
  var events = progressEvents.slice(-maxShow);

  for (var i = events.length - 1; i >= 0; i--) {
    var ev = events[i];
    var data = ev.data || ev;
    var eventType = data.event_type || 'unknown';
    var phase = data.phase || '';
    var status = data.status || 'running';
    var message = data.message || '';
    var pct = data.percent;
    var progressCur = data.progress_current;
    var progressTotal = data.progress_total;

    var statusCls = status === 'completed' ? 'ok' : status === 'failed' || status === 'refused' ? 'error' : 'warn';
    var eventLabel = eventType.replace(/^operation\./, '').replace(/^validation\./, 'val.').replace(/\./g, ' ');

    html += '<div class="progress-event-row ' + statusCls + '">';
    html += '<span class="progress-event-type">' + escapeHtml(eventLabel) + '</span>';
    if (phase && phase !== eventLabel) {
      html += '<span class="progress-event-phase">' + escapeHtml(phase) + '</span>';
    }
    html += '<span class="progress-event-status ' + statusCls + '">' + escapeHtml(status) + '</span>';
    if (message) {
      html += '<div class="progress-event-message">' + escapeHtml(message) + '</div>';
    }
    if (typeof pct === 'number') {
      html += '<div class="progress-bar-container"><div class="progress-bar" style="width:' + Math.round(pct) + '%"></div></div>';
    } else if (typeof progressCur === 'number' && typeof progressTotal === 'number' && progressTotal > 0) {
      var barPct = Math.round((progressCur / progressTotal) * 100);
      html += '<div class="progress-bar-container"><div class="progress-bar" style="width:' + barPct + '%"></div></div>';
    }
    html += '</div>';
  }

  list.innerHTML = html;
}

function handleWSMessage(message) {
  switch (message.type) {
    case 'desktop_intent_result':
      displayOperateIntentResult(message.result || message);
      break;
    case 'chat_state':
    case 'chat_state_updated':
      renderChat(message.data || message);
      break;
    case 'projection':
      renderProjection(message.data || message);
      break;
    case 'progress_event':
      progressEvents.push(message);
      if (progressEvents.length > 100) {
        progressEvents = progressEvents.slice(-100);
      }
      renderProgressTimeline();
      break;
    case 'progress_events':
      progressEvents = (message.events || []).slice(-100);
      renderProgressTimeline();
      break;
  }
}

// ── Init ──

function initWebSocket() {
  if (typeof ProjectionWebSocketClient === 'undefined') return;

  wsClient = new ProjectionWebSocketClient({
    onProjection: function(data) {
      renderProjection(data);
    },
    onMessage: function(msg) {
      handleWSMessage(msg);
    },
    onStatusChange: function(status, detail, attempt) {
      var connEl = document.getElementById('connection-status');
      connEl.className = 'source-status ' + (status === 'connected' ? 'ok' : 'warning');
      connEl.textContent = status === 'connected' ? 'WS' : 'WS ' + status;

      if (status === 'connected') {
        wsConnected = true;
        wsClient.sendMessage({ type: 'get_chat_state' });
      } else if (status === 'offline' || status === 'auth_failed') {
        wsConnected = false;
        loadFromBridge();
      }
    }
  });
}

async function loadFromBridge() {
  if (!window.pywebview || !window.pywebview.api) return;
  var connEl = document.getElementById('connection-status');
  connEl.textContent = 'Bridge';
  connEl.className = 'source-status ok';

  try {
    var projection = await window.pywebview.api.get_projection();
    renderProjection(projection);
    var chat = await window.pywebview.api.get_chat_state();
    renderChat(chat);
  } catch (e) {
    console.warn('Bridge fallback failed:', e);
  }
}

document.addEventListener('DOMContentLoaded', function() {
  // Chat UI listeners
  document.getElementById('chat-input').addEventListener('input', updateCharCount);
  document.getElementById('send-btn').addEventListener('click', sendMessage);
  document.getElementById('clear-chat-btn').addEventListener('click', clearChat);
  document.getElementById('chat-input').addEventListener('keydown', function(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  });

  // Init
  if (typeof ProjectionWebSocketClient !== 'undefined') {
    initWebSocket();
  } else {
    loadFromBridge();
  }

  // Periodic refresh
  setInterval(function() {
    if (!wsConnected && window.pywebview && window.pywebview.api) {
      loadFromBridge();
    }
  }, 10000);
});

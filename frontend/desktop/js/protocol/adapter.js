// GridlineFrontendProtocolConsumer — Lane S1
// ──────────────────────────────────────────────
// Owner: frontend/desktop/js/protocol/adapter.js
// Safety: textContent for all untrusted content, never innerHTML with projection data.
//         Fixture data only accessible through explicit opt-in mode.
//         Production boot never substitutes fixture projections.
//
// Accepts typed developer_studio_projection.v1 and backend_projection_patch.v1
// envelopes. Renders truthful unavailable/deferred/refused/loading/empty states.
// Emits typed intents without implementing domain authority in JavaScript.

// ── Mode detection ──────────────────────────────────────────────────
// Production mode (default): no fixture access. Live bridge required.
// Fixture mode (explicit opt-in): allows fixture-backed rendering.
// Detection priority: URL param > window flag > default (production).

function _detectMode() {
  var params = new URLSearchParams(window.location.search);
  if (params.get('fixture_mode') === '1') return 'fixture';
  if (params.get('fixture_mode') === '0') return 'production';
  if (window.__RIG_RELAY_FIXTURE_MODE__ === true) return 'fixture';
  if (window.__RIG_RELAY_FIXTURE_MODE__ === false) return 'production';
  return 'production';
}

var _mode = _detectMode();

// ── State ───────────────────────────────────────────────────────────

var _studioProjection = null;          // Latest full developer_studio_projection.v1
var _projectionPatch = null;           // Latest backend_projection_patch.v1 (partial)
var _lastProjectionSeq = -1;
var _surfaceStates = {
  'connect': { status: 'unavailable' },
  'repository-estate': { status: 'unavailable' },
  'project-studio': { status: 'unavailable' },
  'inference-studio': { status: 'unavailable' },
  'publish-preview': { status: 'unavailable' },
};
var _intentCallbacks = {};             // intentName -> callback(result)
var _projectionCallbacks = [];         // Called when projection state changes

// ── Canonical utility ───────────────────────────────────────────────

function _setText(el, str) {
  if (el) el.textContent = String(str);
}

function _escapeHtml(str) {
  if (typeof str !== 'string') return String(str);
  return str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

function _getEl(id) {
  return document.getElementById(id);
}

// ── Public mode API ─────────────────────────────────────────────────

function getMode() { return _mode; }

function isProduction() { return _mode === 'production'; }

function isFixture() { return _mode === 'fixture'; }

function setFixtureMode(enable) {
  _mode = enable ? 'fixture' : 'production';
}

// ── Projection ingestion ────────────────────────────────────────────

// Accept a full developer_studio_projection.v1 payload.
// Schema: schema_version === "rig.relay.developer_studio_projection.v1"
function acceptDeveloperStudioProjection(payload) {
  if (!payload || payload.schema_version !== 'rig.relay.developer_studio_projection.v1') {
    return { accepted: false, reason: 'invalid_schema' };
  }
  _studioProjection = payload;
  _computeSurfaceStates();
  _renderAllSurfaces();
  _notifyProjectionCallbacks();
  return { accepted: true, projection_id: payload.projection_id };
}

// Accept a backend_projection_patch.v1 payload (partial or delta).
// Schema: schema_version === "rig.relay.backend_projection_patch.v1"
function acceptProjectionPatch(payload) {
  if (!payload || payload.schema_version !== 'rig.relay.backend_projection_patch.v1') {
    return { accepted: false, reason: 'invalid_schema' };
  }
  // Sequence check: reject stale patches
  if (payload.projection_sequence != null && payload.projection_sequence <= _lastProjectionSeq) {
    return { accepted: false, reason: 'stale_sequence', received: payload.projection_sequence, last: _lastProjectionSeq };
  }
  _lastProjectionSeq = payload.projection_sequence != null ? payload.projection_sequence : _lastProjectionSeq;
  _projectionPatch = payload;

  if (payload.patch_kind === 'full' && payload.sections) {
    _studioProjection = payload.sections;
  } else if (payload.sections) {
    // Partial: merge sections into existing projection
    _studioProjection = _studioProjection || {};
    var keys = Object.keys(payload.sections);
    for (var i = 0; i < keys.length; i++) {
      _studioProjection[keys[i]] = payload.sections[keys[i]];
    }
  }
  _computeSurfaceStates();
  _renderAllSurfaces();
  _notifyProjectionCallbacks();
  return { accepted: true, projection_sequence: _lastProjectionSeq };
}

// Accept a raw projection from the existing bridge (legacy path)
// Only routes to surfaces if the projection contains developer_studio section
function acceptBridgeProjection(data) {
  if (!data) return { accepted: false, reason: 'empty' };
  // Legacy projection: extract developer_studio if present
  if (data.developer_studio) {
    return acceptDeveloperStudioProjection(data.developer_studio);
  }
  return { accepted: false, reason: 'no_developer_studio_section' };
}

// ── Surface state computation ───────────────────────────────────────

function _computeSurfaceStates() {
  var proj = _studioProjection;
  if (!proj) {
    _setAllSurfacesUnavailable();
    return;
  }
  _setSurfaceFromWorkspace(proj.workspace);
  _setSurfaceFromOperator(proj.operator);
  _setSurfaceFromContext(proj.context);
  _setSurfaceFromInference(proj.inference);
  _setPublishPreviewState(proj);
}

function _setAllSurfacesUnavailable() {
  var surfaces = ['connect', 'repository-estate', 'project-studio', 'inference-studio', 'publish-preview'];
  for (var i = 0; i < surfaces.length; i++) {
    _surfaceStates[surfaces[i]] = { status: 'unavailable', reason: 'No projection received' };
  }
}

function _setSurfaceFromWorkspace(ws) {
  if (!ws) {
    _surfaceStates['connect'] = { status: 'unavailable', reason: 'Workspace service unavailable' };
    _surfaceStates['repository-estate'] = { status: 'unavailable', reason: 'Workspace service unavailable' };
    return;
  }
  if (!ws.available) {
    _surfaceStates['connect'] = { status: 'deferred', reason: 'Workspace service not available', trust: ws.provenance || 'derived_projection' };
    _surfaceStates['repository-estate'] = { status: 'deferred', reason: 'Workspace service not available', trust: ws.provenance || 'derived_projection' };
    return;
  }
  // Connection surface state
  var conn = ws.connection || {};
  var connTrust = conn.trust_state || 'deferred';
  var connState = conn.connection_state || 'disconnected';
  _surfaceStates['connect'] = {
    status: _mapTrustToStatus(connTrust, connState),
    reason: connTrust === 'trusted_live' ? 'Live workspace connected' : 'Connection state: ' + connTrust,
    trust: connTrust,
    provenance: conn.provenance || 'canonical_fact',
    connection_state: connState,
    token_available: conn.token_available || false,
    installation_id_hash: conn.installation_id_hash || '',
    accessible_repository_count: conn.accessible_repository_count || 0,
  };
  // Repository estate surface state
  _surfaceStates['repository-estate'] = {
    status: 'available',
    trust: ws.provenance || 'derived_projection',
    repositories: ws.repositories || [],
    selected_count: ws.selected_count || 0,
    imported_count: ws.imported_count || 0,
    publishable_count: ws.publishable_count || 0,
    total_discovered: ws.total_discovered || 0,
  };
}

function _setSurfaceFromOperator(op) {
  if (!op) {
    _surfaceStates['project-studio'] = { status: 'unavailable', reason: 'Operator service unavailable' };
    return;
  }
  if (!op.available) {
    _surfaceStates['project-studio'] = { status: 'deferred', reason: 'Operator service not available', trust: op.provenance || 'derived_projection' };
    return;
  }
  _surfaceStates['project-studio'] = {
    status: 'available',
    trust: op.provenance || 'derived_projection',
    active_sessions: op.active_sessions || [],
    total_sessions: op.total_sessions || 0,
    active_session_count: op.active_session_count || 0,
    refused_session_count: op.refused_session_count || 0,
    proposal_pending_count: op.proposal_pending_count || 0,
    deferred_integrations: op.deferred_integrations || [],
    recovery_available: op.recovery_materialization_available || false,
  };
}

function _setSurfaceFromContext(ctx) {
  if (!ctx) return;
  // Context enriches project studio
  var ps = _surfaceStates['project-studio'];
  if (!ps) ps = _surfaceStates['project-studio'] = { status: 'unavailable' };
  ps.studies = ctx.studies || [];
  ps.intake_dependency = ctx.intake_dependency_status || {};
  ps.redaction_available = ctx.redaction_engine_available || false;
}

function _setSurfaceFromInference(inf) {
  if (!inf) {
    _surfaceStates['inference-studio'] = { status: 'unavailable', reason: 'Inference service unavailable' };
    return;
  }
  if (!inf.available) {
    _surfaceStates['inference-studio'] = { status: 'deferred', reason: 'Inference service not available', trust: inf.provenance || 'derived_projection' };
    return;
  }
  _surfaceStates['inference-studio'] = {
    status: 'available',
    trust: inf.provenance || 'derived_projection',
    runtime_available: inf.runtime_available || false,
    runtime_configured: inf.runtime_configured || false,
    runtime_kind: inf.runtime_kind || 'unknown',
    platform_class: inf.platform_class || 'unknown',
    task_suitability: inf.task_suitability || [],
    total_results: inf.total_results || 0,
    total_executed: inf.total_executed || 0,
    total_refused: inf.total_refused || 0,
    drafts_awaiting_review: inf.drafts_awaiting_review || 0,
    drafts: inf.drafts || [],
    refusals: inf.refusals || [],
  };
}

function _setPublishPreviewState(proj) {
  var ws = proj.workspace;
  var ctx = proj.context;
  if (!ws || !ctx) {
    _surfaceStates['publish-preview'] = { status: 'unavailable', reason: 'Required services unavailable' };
    return;
  }
  // Publish preview depends on workspace repositories and context studies
  var repos = ws.repositories || [];
  var publishable = repos.filter(function(r) { return r.publication_readiness_state === 'ready' || r.publication_readiness_state === 'review_required'; });
  _surfaceStates['publish-preview'] = {
    status: (publishable.length > 0 || (ctx.available && ctx.studies && ctx.studies.length > 0)) ? 'available' : 'empty',
    trust: ws.provenance || 'derived_projection',
    publishable_repositories: publishable,
    studies: ctx.studies || [],
  };
}

// ── Trust state mapping ─────────────────────────────────────────────

function _mapTrustToStatus(trustState, connectionState) {
  switch (trustState) {
    case 'trusted_live': return 'connected';
    case 'controlled_boundary': return connectionState || 'available';
    case 'fixture': return 'fixture';
    case 'deferred': return 'deferred';
    case 'refused': return 'refused';
    case 'corrupt': return 'error';
    default: return 'unknown';
  }
}

// ── Surface rendering ───────────────────────────────────────────────

function _renderAllSurfaces() {
  _renderConnectSurface();
  _renderRepositoryEstateSurface();
  _renderProjectStudioSurface();
  _renderInferenceStudioSurface();
  _renderPublishPreviewSurface();
}

function _renderConnectSurface() {
  var state = _surfaceStates['connect'];
  _setConnectFixtureBanner(state);
  _renderConnectStatus(state);
  _renderConnectRepoAccess(state);
  _renderConnectPublicationApproval(state);
}

function _renderConnectStatus(state) {
  var chip = _getEl('cb-status-chip');
  var detail = _getEl('cb-detail');
  if (!chip) return;

  var status = state.status || 'unavailable';
  _setStatusChip(chip, status, _connectStatusLabel(status, state));
  if (detail) {
    var detailText = '';
    if (status === 'unavailable') detailText = 'No connection available. Backend bridge not yet established.';
    else if (status === 'deferred') detailText = 'Connection deferred to live bridge aggregation milestone.';
    else if (status === 'refused') detailText = 'Connection refused by backend authority.';
    else if (status === 'connected') detailText = 'Live connection established.';
    else if (status === 'fixture') detailText = 'Fixture-backed projection — not live service data.';
    else detailText = 'Connection state: ' + _escapeHtml(state.connection_state || 'unknown');
    if (state.trust) detailText += ' \u00B7 Trust: ' + _escapeHtml(state.trust);
    _setText(detail, detailText);
  }
}

function _renderConnectRepoAccess(state) {
  var el = _getEl('repo-access-status');
  if (!el) return;
  if (state.status === 'unavailable' || state.status === 'deferred') {
    el.innerHTML = _renderEvidenceTag('planned') + ' Repository access: <strong>unavailable</strong>';
    return;
  }
  if (state.status === 'connected') {
    el.innerHTML = _renderEvidenceTag('proven') + ' Repository access: <strong>granted</strong>' +
      (state.token_available ? ' \u00B7 Token present' : ' \u00B7 No token') +
      ' \u00B7 ' + _escapeHtml(String(state.accessible_repository_count || 0)) + ' repositories accessible';
    return;
  }
  el.innerHTML = _renderEvidenceTag('claimed') + ' Repository access: <strong>' + _escapeHtml(state.status) + '</strong>';
}

function _renderConnectPublicationApproval(state) {
  var el = _getEl('publication-approval-status');
  if (!el) return;
  if (state.status === 'unavailable') {
    el.innerHTML = _renderEvidenceTag('planned') + ' Publication approval: <strong>unavailable</strong>';
    return;
  }
  if (state.status === 'connected') {
    el.innerHTML = _renderEvidenceTag('proven') + ' Publication approval: <strong>granted</strong>';
    return;
  }
  el.innerHTML = _renderEvidenceTag('planned') + ' Publication approval: <strong>deferred</strong><br><span class="status-detail">Live integration deferred to O0 bridge aggregation milestone</span>';
}

function _renderConnectFixtureBanner(state) {
  // Remove old fixture banners
  var banners = document.querySelectorAll('#surface-connect .fixture-banner, #surface-connect .production-banner');
  for (var i = 0; i < banners.length; i++) banners[i].remove();

  var card = document.querySelector('#surface-connect .connect-card');
  if (!card) return;

  var banner = document.createElement('div');
  if (_mode === 'production' && (state.status === 'unavailable' || state.status === 'deferred')) {
    banner.className = 'production-banner';
    banner.style.cssText = 'margin-top:16px;padding:8px 14px;background:rgba(83,155,245,0.08);border:1px solid rgba(83,155,245,0.15);border-radius:var(--radius-sm);font-size:0.75rem;color:var(--info-color);text-align:center';
    _setText(banner, '\u2139\uFE0F Production mode \u2014 live bridge projection not yet received');
  } else if (_mode === 'fixture' && state.status !== 'connected') {
    banner.className = 'fixture-banner';
    banner.style.cssText = 'margin-top:16px;padding:8px 14px;background:rgba(198,144,38,0.1);border:1px solid rgba(198,144,38,0.2);border-radius:var(--radius-sm);font-size:0.75rem;color:var(--warning-color);text-align:center';
    _setText(banner, '\u26A0 Fixture-backed projection \u2014 not live service data');
  }
  card.appendChild(banner);
}

function _renderRepositoryEstateSurface() {
  var state = _surfaceStates['repository-estate'];
  _setRepoFixtureBanner(state);
  _renderRepoList(state);
  _renderRepoIntake(state);
}

function _setRepoFixtureBanner(state) {
  var banners = document.querySelectorAll('#surface-repository-estate .fixture-banner, #surface-repository-estate .production-banner');
  for (var i = 0; i < banners.length; i++) banners[i].remove();

  var content = document.querySelector('#surface-repository-estate .surface-content');
  if (!content) return;

  var banner = document.createElement('div');
  if (_mode === 'production' && state.status === 'unavailable') {
    banner.className = 'production-banner';
    banner.style.cssText = 'margin-top:16px;padding:8px 14px;background:rgba(83,155,245,0.08);border:1px solid rgba(83,155,245,0.15);border-radius:var(--radius-sm);font-size:0.75rem;color:var(--info-color);text-align:center';
    _setText(banner, '\u2139\uFE0F Production mode \u2014 live bridge projection not yet received');
    content.appendChild(banner);
  } else if (_mode === 'fixture') {
    banner.className = 'fixture-banner';
    banner.style.cssText = 'margin-top:16px;padding:8px 14px;background:rgba(198,144,38,0.1);border:1px solid rgba(198,144,38,0.2);border-radius:var(--radius-sm);font-size:0.75rem;color:var(--warning-color);text-align:center';
    _setText(banner, '\u26A0 Fixture-backed projection \u2014 not live service data');
    content.appendChild(banner);
  }
}

function _renderRepoList(state) {
  var repoList = _getEl('repo-list-container');
  if (!repoList) return;

  var repos = state.repositories || [];
  if (repos.length === 0) {
    if (state.status === 'unavailable') {
      repoList.innerHTML = '<div class="status-detail">Repository service unavailable. No live bridge projection received.</div>';
    } else if (state.status === 'deferred') {
      repoList.innerHTML = '<div class="status-detail">Repository discovery deferred. Awaiting live workspace integration.</div>';
    } else {
      repoList.innerHTML = '<div class="status-detail">No repositories discovered.</div>';
    }
    return;
  }

  var html = '';
  for (var i = 0; i < repos.length; i++) {
    var r = repos[i];
    var statusTag = '';
    var importState = r.import_state || r.intake_state || 'unknown';
    if (importState === 'imported' || importState === 'cloned') statusTag = _renderEvidenceTag('proven');
    else if (importState === 'failed') statusTag = _renderEvidenceTag('claimed');
    else statusTag = _renderEvidenceTag('planned');

    var pubState = r.publication_readiness_state || 'unknown';
    var pubTag = '';
    if (pubState === 'ready') pubTag = ' <span class="evidence-tag proven">public-ready</span>';
    else if (pubState === 'review_required') pubTag = ' <span class="evidence-tag claimed">review-required</span>';
    else pubTag = ' <span class="evidence-tag planned">private</span>';

    html += '<div class="repo-card">' +
      '<div class="repo-name">' + _escapeHtml(r.name || r.display_name || '') + '</div>' +
      '<div class="repo-meta">' + statusTag +
      ' ' + _escapeHtml(r.full_name || '') + ' \u00B7 ' + _escapeHtml(r.default_branch || r.branch || '') + ' \u00B7 ' + _escapeHtml(importState) +
      pubTag +
      '</div></div>';
  }
  repoList.innerHTML = html;
}

function _renderRepoIntake(state) {
  var el = _getEl('repo-intake-status');
  if (!el) return;
  if (state.status === 'unavailable') {
    el.innerHTML = '<span class="status-chip deferred">Intake: unavailable</span><br><div class="status-detail">No intake data available.</div>';
    return;
  }
  el.innerHTML = '<span class="status-chip">Intake: ' + _escapeHtml(String(state.selected_count || 0)) + ' selected, ' +
    _escapeHtml(String(state.imported_count || 0)) + ' imported, ' +
    _escapeHtml(String(state.total_discovered || 0)) + ' discovered</span>';
}

function _renderProjectStudioSurface() {
  var state = _surfaceStates['project-studio'];
  _setStudioFixtureBanner(state);
  _renderStudioOperator(state);
  _renderStudioUnderstanding(state);
}

function _setStudioFixtureBanner(state) {
  var banners = document.querySelectorAll('#surface-project-studio .fixture-banner, #surface-project-studio .production-banner');
  for (var i = 0; i < banners.length; i++) banners[i].remove();

  var content = document.querySelector('#surface-project-studio .surface-content');
  if (!content) return;

  var banner = document.createElement('div');
  if (_mode === 'production' && (state.status === 'unavailable' || state.status === 'deferred')) {
    banner.className = 'production-banner';
    banner.style.cssText = 'margin-top:16px;padding:8px 14px;background:rgba(83,155,245,0.08);border:1px solid rgba(83,155,245,0.15);border-radius:var(--radius-sm);font-size:0.75rem;color:var(--info-color);text-align:center';
    _setText(banner, '\u2139\uFE0F Production mode \u2014 live bridge projection not yet received');
    content.appendChild(banner);
  } else if (_mode === 'fixture') {
    banner.className = 'fixture-banner';
    banner.style.cssText = 'margin-top:16px;padding:8px 14px;background:rgba(198,144,38,0.1);border:1px solid rgba(198,144,38,0.2);border-radius:var(--radius-sm);font-size:0.75rem;color:var(--warning-color);text-align:center';
    _setText(banner, '\u26A0 Fixture-backed projection \u2014 not live service data');
    content.appendChild(banner);
  }
}

function _renderStudioOperator(state) {
  var osEl = _getEl('operator-session-status');
  if (!osEl) return;

  if (state.status === 'unavailable') {
    osEl.innerHTML = '<span class="status-line">Operator service: <strong>unavailable</strong></span><br><span class="status-detail">No live bridge projection received.</span>';
    return;
  }
  if (state.status === 'deferred') {
    osEl.innerHTML = '<span class="status-line">Operator service: <strong>deferred</strong></span><br><span class="status-detail">Awaiting live bridge aggregation.</span>';
    return;
  }

  var sessions = state.active_sessions || [];
  if (sessions.length === 0) {
    osEl.innerHTML = '<span class="status-line">No active operator sessions</span><br><span class="status-detail">Start an investigation to begin.</span>';
    return;
  }

  var html = '';
  for (var i = 0; i < sessions.length; i++) {
    var s = sessions[i];
    html += '<span class="status-line">Session: <strong>' + _escapeHtml(s.status || 'idle') + '</strong> \u00B7 Phase: ' + _escapeHtml(s.phase || 'idle') + '</span>' +
      '<br><span class="status-detail">' + _escapeHtml(s.purpose || '') + ' on ' + _escapeHtml(s.repository_label || '') + '</span>';
    if (s.pending_decisions && s.pending_decisions.length) {
      html += '<br><span class="status-detail" style="color:var(--warning-color)">\u26A0 Pending: ' + _escapeHtml(s.pending_decisions.join(', ')) + '</span>';
    }
    if (s.blocked_capabilities && s.blocked_capabilities.length) {
      html += '<br><span class="status-detail" style="color:var(--error-color)">Blocked: ' + _escapeHtml(s.blocked_capabilities.join(', ')) + '</span>';
    }
    html += '<br>';
  }
  osEl.innerHTML = html;

  var tsEl = _getEl('operator-tool-summary');
  if (tsEl) {
    var totalCalls = 0, totalSuccess = 0;
    for (var j = 0; j < sessions.length; j++) {
      totalCalls += sessions[j].tool_call_count || 0;
      totalSuccess += sessions[j].tool_success_count || 0;
    }
    if (totalCalls > 0) {
      tsEl.innerHTML = '<table class="kv"><tr><td class="k">Total Calls</td><td>' + totalCalls + '</td></tr><tr><td class="k">Successes</td><td class="ok">' + totalSuccess + '</td></tr></table>';
    } else {
      _setText(tsEl, 'No tool activity yet.');
    }
  }

  var propEl = _getEl('operator-proposals');
  if (propEl) {
    var totalProposals = 0, totalPending = 0, totalRefused = 0;
    for (var k = 0; k < sessions.length; k++) {
      totalProposals += sessions[k].proposal_count || 0;
      totalPending += sessions[k].proposal_pending_count || 0;
      totalRefused += sessions[k].refusal_count || 0;
    }
    if (totalProposals > 0) {
      propEl.innerHTML = '<div class="status-line">Proposals: ' + totalProposals + ' (\u00B7 ' +
        totalPending + ' pending, ' + totalRefused + ' refused)</div>';
    } else {
      _setText(propEl, 'No proposals yet.');
    }
  }
}

function _renderStudioUnderstanding(state) {
  var usEl = _getEl('understanding-status');
  if (!usEl) return;

  var studies = state.studies || [];
  if (studies.length === 0) {
    usEl.innerHTML = '<span class="status-line">Study status: <strong>not_started</strong></span><br><span class="status-detail">No project studies available.</span>';
    _setText(_getEl('understanding-details'), '');
    return;
  }

  var study = studies[0];
  usEl.innerHTML = '<span class="status-line">Study status: <strong>' + _escapeHtml(study.study_status || 'unknown') + '</strong></span>' +
    '<br><span class="status-detail">' + (study.facts_discovered || 0) + ' facts (' + (study.facts_with_provenance || 0) + ' with provenance) \u00B7 ' +
    (study.draft_narrative_count || 0) + ' drafts (' + (study.draft_narrative_awaiting_approval || 0) + ' awaiting approval)</span>';

  var udEl = _getEl('understanding-details');
  if (udEl) {
    var detailsHtml = '<table class="kv">';
    if (study.languages_detected) detailsHtml += '<tr><td class="k">Languages</td><td>' + _escapeHtml(study.languages_detected.join(', ')) + '</td></tr>';
    if (study.frameworks_detected) detailsHtml += '<tr><td class="k">Frameworks</td><td>' + _escapeHtml(study.frameworks_detected.join(', ')) + '</td></tr>';
    if (study.withheld_reasons && study.withheld_reasons.length) {
      detailsHtml += '<tr><td class="k warning">Withheld</td><td>' + _escapeHtml(study.withheld_material_count + ' items: ' + study.withheld_reasons.join(', ')) + '</td></tr>';
    }
    detailsHtml += '<tr><td class="k">Portfolio</td><td>' + _escapeHtml(study.portfolio_eligibility || 'unknown') + '</td></tr>';
    detailsHtml += '<tr><td class="k">Approval</td><td>' + _escapeHtml(study.approval_status || 'unknown') + '</td></tr>';
    detailsHtml += '</table>';
    udEl.innerHTML = detailsHtml;
  }
}

function _renderInferenceStudioSurface() {
  var state = _surfaceStates['inference-studio'];
  _setInferenceFixtureBanner(state);
  _renderInferenceRuntime(state);
  _renderInferenceTasks(state);
  _renderInferenceDrafts(state);
  _renderInferenceRefusals(state);
}

function _setInferenceFixtureBanner(state) {
  var banners = document.querySelectorAll('#surface-inference-studio .fixture-banner, #surface-inference-studio .production-banner');
  for (var i = 0; i < banners.length; i++) banners[i].remove();

  var content = document.querySelector('#surface-inference-studio .surface-content');
  if (!content) return;

  var banner = document.createElement('div');
  if (_mode === 'production' && (state.status === 'unavailable' || state.status === 'deferred')) {
    banner.className = 'production-banner';
    banner.style.cssText = 'margin-top:16px;padding:8px 14px;background:rgba(83,155,245,0.08);border:1px solid rgba(83,155,245,0.15);border-radius:var(--radius-sm);font-size:0.75rem;color:var(--info-color);text-align:center';
    _setText(banner, '\u2139\uFE0F Production mode \u2014 live bridge projection not yet received');
    content.appendChild(banner);
  } else if (_mode === 'fixture') {
    banner.className = 'fixture-banner';
    banner.style.cssText = 'margin-top:16px;padding:8px 14px;background:rgba(198,144,38,0.1);border:1px solid rgba(198,144,38,0.2);border-radius:var(--radius-sm);font-size:0.75rem;color:var(--warning-color);text-align:center';
    _setText(banner, '\u26A0 Fixture-backed projection \u2014 not live service data');
    content.appendChild(banner);
  }
}

function _renderInferenceRuntime(state) {
  var irEl = _getEl('inference-runtime-status');
  if (!irEl) return;

  if (state.status === 'unavailable' || state.status === 'deferred') {
    irEl.innerHTML = '<span class="status-chip disconnected">Inference Unavailable</span>';
    return;
  }

  var available = state.runtime_available;
  _setStatusChip(irEl.querySelector('.status-chip') || irEl, available ? 'available' : 'offline',
    available ? 'Runtime Available' : 'Runtime Offline');
  var detail = irEl.querySelector('.status-detail');
  if (detail) _setText(detail, (available ? 'Local inference ready (' + _escapeHtml(state.runtime_kind || 'unknown') + ')' : 'No local runtime configured'));
}

function _renderInferenceTasks(state) {
  var tasksGrid = _getEl('inference-tasks');
  if (!tasksGrid) return;

  var ts = state.task_suitability || [];
  if (ts.length === 0) {
    if (state.status === 'unavailable') {
      tasksGrid.innerHTML = '<div class="task-card"><div class="task-name">No tasks</div><div class="task-status">Inference service unavailable.</div></div>';
    } else {
      tasksGrid.innerHTML = '<div class="task-card"><div class="task-name">No tasks</div><div class="task-status">No task suitability data.</div></div>';
    }
    return;
  }

  var html = '';
  for (var i = 0; i < ts.length; i++) {
    var t = ts[i];
    var suitable = t.suitable;
    html += '<div class="task-card ' + (suitable ? 'suitable' : 'unsuitable') + '">' +
      '<div class="task-name">' + _escapeHtml(t.task_kind) + '</div>' +
      '<div class="task-status">' + _renderEvidenceTag(suitable ? 'proven' : 'refused') + ' ' +
      (suitable ? _escapeHtml(t.enforcement_class_required || '') + ' admitted' : _escapeHtml(t.refusal_reason || 'Refused')) +
      '</div></div>';
  }
  tasksGrid.innerHTML = html;
}

function _renderInferenceDrafts(state) {
  var draftList = _getEl('inference-drafts');
  if (!draftList) return;

  var drafts = state.drafts || [];
  var html = '<h3>Drafts (' + drafts.length + ')</h3>';
  if (drafts.length === 0) {
    html += '<div class="draft-item">No drafts awaiting review.</div>';
  } else {
    for (var i = 0; i < drafts.length; i++) {
      var d = drafts[i];
      var needsApproval = d.requires_approval !== false;
      html += '<div class="draft-item">' +
        '<strong>' + _escapeHtml(d.task_kind) + '</strong>: ' + _escapeHtml(d.draft_sha256 ? d.draft_sha256.substring(0, 16) + '...' : 'unknown') +
        ' <span class="evidence-tag ' + (needsApproval ? 'claimed' : 'proven') + '">' + (needsApproval ? 'review-required' : 'approved') + '</span>' +
        ' (' + (d.draft_byte_count || 0) + ' bytes)' +
        '</div>';
    }
  }
  draftList.innerHTML = html;
}

function _renderInferenceRefusals(state) {
  var refusalList = _getEl('inference-refusals');
  if (!refusalList) return;

  var refusals = state.refusals || [];
  var html = '<h3>Refusals (' + refusals.length + ')</h3>';
  if (refusals.length === 0) {
    html += '<div class="refusal-item" style="color:var(--text-secondary)">No refusals.</div>';
  } else {
    for (var i = 0; i < refusals.length; i++) {
      var r = refusals[i];
      html += '<div class="refusal-item">' +
        '<strong>' + _escapeHtml(r.task_kind) + '</strong>: ' + _escapeHtml(r.refusal_reason || r.refusal_code || 'Refused') +
        ' (code: ' + _escapeHtml(r.refusal_code || 'UNKNOWN') + ')' +
        '</div>';
    }
  }
  refusalList.innerHTML = html;
}

function _renderPublishPreviewSurface() {
  var state = _surfaceStates['publish-preview'];
  _setPublishFixtureBanner(state);
  _renderPublishReadiness(state);
  _renderPublishSections(state);
  _renderPublishWithheld(state);
}

function _setPublishFixtureBanner(state) {
  var banners = document.querySelectorAll('#surface-publish-preview .fixture-banner, #surface-publish-preview .production-banner');
  for (var i = 0; i < banners.length; i++) banners[i].remove();

  var content = document.querySelector('#surface-publish-preview .surface-content');
  if (!content) return;

  var banner = document.createElement('div');
  if (_mode === 'production' && state.status === 'unavailable') {
    banner.className = 'production-banner';
    banner.style.cssText = 'margin-top:16px;padding:8px 14px;background:rgba(83,155,245,0.08);border:1px solid rgba(83,155,245,0.15);border-radius:var(--radius-sm);font-size:0.75rem;color:var(--info-color);text-align:center';
    _setText(banner, '\u2139\uFE0F Production mode \u2014 live bridge projection not yet received');
    content.appendChild(banner);
  } else if (_mode === 'fixture') {
    banner.className = 'fixture-banner';
    banner.style.cssText = 'margin-top:16px;padding:8px 14px;background:rgba(198,144,38,0.1);border:1px solid rgba(198,144,38,0.2);border-radius:var(--radius-sm);font-size:0.75rem;color:var(--warning-color);text-align:center';
    _setText(banner, '\u26A0 Fixture-backed projection \u2014 not live service data');
    content.appendChild(banner);
  }
}

function _renderPublishReadiness(state) {
  var readinessEl = _getEl('publish-readiness');
  if (!readinessEl) return;

  if (state.status === 'unavailable') {
    readinessEl.innerHTML = '<span class="status-chip deferred">Not Available</span><div class="status-detail">Publish service unavailable. No live projection received.</div>';
    return;
  }

  var repos = state.publishable_repositories || [];
  var studies = state.studies || [];
  var canPublish = repos.length > 0;
  _setStatusChip(readinessEl.querySelector('.status-chip') || readinessEl, canPublish ? 'available' : 'deferred',
    canPublish ? repos.length + ' repositories publishable' : 'Not Ready');
  var detail = readinessEl.querySelector('.status-detail');
  if (detail) _setText(detail, repos.length + ' repositories ready, ' + studies.length + ' studies available.');
}

function _renderPublishSections(state) {
  var sectionsGrid = _getEl('publish-sections');
  if (!sectionsGrid) return;

  if (state.status === 'unavailable') {
    sectionsGrid.innerHTML = '<div class="section-card not-ready"><strong>No sections</strong> <span class="evidence-tag planned">planned</span></div>';
    return;
  }

  // Derive sections from repositories
  var repos = state.publishable_repositories || [];
  var html = '';
  for (var i = 0; i < repos.length; i++) {
    var r = repos[i];
    var ready = r.publication_readiness_state === 'ready';
    html += '<div class="section-card ' + (ready ? 'ready' : 'not-ready') + '">' +
      '<strong>' + _escapeHtml(r.name || r.full_name || '') + '</strong> ' +
      _renderEvidenceTag(ready ? 'proven' : 'claimed') +
      '</div>';
  }
  if (html === '') html = '<div class="section-card not-ready"><strong>No publishable sections</strong></div>';
  sectionsGrid.innerHTML = html;
}

function _renderPublishWithheld(state) {
  var withheldEl = _getEl('publish-withheld');
  if (!withheldEl) return;

  var studies = state.studies || [];
  var html = '<h3>Withheld from Public Preview</h3>';
  if (studies.length > 0) {
    var study = studies[0];
    var reasons = study.withheld_reasons || [];
    if (reasons.length > 0) {
      for (var i = 0; i < reasons.length; i++) {
        html += '<div class="withheld-item">' + _escapeHtml(reasons[i]) + ' (internal_only)</div>';
      }
    } else {
      html += '<div class="withheld-item">No explicitly withheld sections.</div>';
    }
  } else {
    html += '<div class="withheld-item">No withheld data recorded.</div>';
  }
  html += '<div class="withheld-item" style="margin-top:8px;color:var(--text-muted)">Any section not listed above is withheld by default. Private/internal-only material is never rendered.</div>';
  withheldEl.innerHTML = html;
}

// ── Intent emission ──────────────────────────────────────────────────

function emitConnectIntent(intentName, params) {
  var payload = _buildIntentPayload(intentName, params, 'connect');
  _dispatchViaProtocol(intentName, params, payload);
  return payload;
}

function emitRepositoryEstateIntent(intentName, params) {
  var payload = _buildIntentPayload(intentName, params, 'repository-estate');
  _dispatchViaProtocol(intentName, params, payload);
  return payload;
}

function emitProjectStudioIntent(intentName, params) {
  var payload = _buildIntentPayload(intentName, params, 'project-studio');
  _dispatchViaProtocol(intentName, params, payload);
  return payload;
}

function _buildIntentPayload(intentName, params, sourceSurface) {
  return {
    intent_name: intentName,
    parameters: params || {},
    source: sourceSurface,
    fixture_backed: _mode === 'fixture',
    authority: 'none_local',
    schema_version: 'rig.relay.desktop_intent_request.v1',
    created_at: new Date().toISOString(),
  };
}

function _dispatchViaProtocol(intentName, params, payload) {
  // Route through protocol client if available
  var pc = window.__RIG_RELAY_PROTOCOL_CLIENT__;
  if (pc && typeof pc.sendIntentRequest === 'function') {
    var intentId = 'intent_' + (Date.now().toString(36)) + '_' + (Math.random().toString(36).slice(2, 8));
    pc.sendIntentRequest(intentId, intentName, params, 'idem_' + intentId);
  }
  // Also fire legacy bridge path if applicable
  if (window.pywebview && window.pywebview.api && window.pywebview.api.execute_intent) {
    window.pywebview.api.execute_intent(JSON.stringify({
      intent_name: intentName,
      parameters: params,
      dry_run: true,
      source_surface: payload.source,
    })).catch(function() {});
  }
  // Notify callbacks
  var cb = _intentCallbacks[intentName];
  if (typeof cb === 'function') {
    try { cb(payload); } catch (e) {}
  }
}

// ── Evidence tag ─────────────────────────────────────────────────────

function _renderEvidenceTag(status) {
  var cls = 'evidence-tag';
  if (status === 'proven') cls += ' proven';
  else if (status === 'claimed') cls += ' claimed';
  else if (status === 'planned') cls += ' planned';
  else if (status === 'narrative') cls += ' narrative';
  else if (status === 'refused') cls += ' narrative';
  else cls += ' narrative';
  return '<span class="' + cls + '">' + _escapeHtml(status) + '</span>';
}

// ── Status chip helper ──────────────────────────────────────────────

function _setStatusChip(el, status, label) {
  if (!el) return;
  var cls = 'status-chip';
  if (status === 'connected' || status === 'granted' || status === 'synced' || status === 'cloned' || status === 'ok' || status === 'available') cls += ' connected';
  else if (status === 'disconnected' || status === 'refused' || status === 'failed' || status === 'error') cls += ' disconnected';
  else if (status === 'deferred' || status === 'blocked' || status === 'warning') cls += ' deferred';
  else cls += ' pending';
  el.className = cls;
  _setText(el, label || status);
}

function _connectStatusLabel(status, state) {
  switch (status) {
    case 'connected': return 'Carte Blanche Connected';
    case 'deferred': return 'Carte Blanche Deferred';
    case 'refused': return 'Carte Blanche Refused';
    case 'fixture': return 'Carte Blanche (Fixture)';
    case 'error': return 'Carte Blanche Error';
    default: return 'Carte Blanche ' + _escapeHtml(status);
  }
}

// ── Callback registration ───────────────────────────────────────────

function onIntent(intentName, callback) {
  _intentCallbacks[intentName] = callback;
}

function onProjectionChange(callback) {
  _projectionCallbacks.push(callback);
}

function _notifyProjectionCallbacks() {
  for (var i = 0; i < _projectionCallbacks.length; i++) {
    try { _projectionCallbacks[i](_studioProjection); } catch (e) {}
  }
}

// ── Surface state access ────────────────────────────────────────────

function getSurfaceState(surfaceId) {
  return _surfaceStates[surfaceId] || { status: 'unavailable' };
}

// ── Fixture rendering (explicit mode only) ──────────────────────────

function renderFixtureSurface(surfaceId) {
  if (_mode !== 'fixture') return { rendered: false, reason: 'not_in_fixture_mode' };
  var fix = _getFixture(surfaceId);
  if (!fix) return { rendered: false, reason: 'fixture_not_found' };
  // Map the fixture into the surface state and render
  _applyFixtureToState(surfaceId, fix);
  _renderAllSurfaces();
  return { rendered: true };
}

function _getFixture(surfaceId) {
  if (!window.__P0_FIXTURES__) return null;
  switch (surfaceId) {
    case 'connect': return window.__P0_FIXTURES__.connect;
    case 'repository-estate': return window.__P0_FIXTURES__.repository_estate;
    case 'project-studio': return window.__P0_FIXTURES__.project_studio;
    case 'inference-studio': return window.__P0_FIXTURES__.inference_studio;
    case 'publish-preview': return window.__P0_FIXTURES__.publish_preview;
    default: return null;
  }
}

function _applyFixtureToState(surfaceId, fix) {
  var state = _surfaceStates[surfaceId];
  if (!state) state = _surfaceStates[surfaceId] = { status: 'fixture' };
  state.status = 'fixture';
  state.trust = 'fixture';
  switch (surfaceId) {
    case 'connect':
      state.connection_state = (fix.carte_blanche && fix.carte_blanche.status) || 'connected';
      state.token_available = fix.repository_access && fix.repository_access.token_present;
      break;
    case 'repository-estate':
      state.repositories = (fix.repositories || []).map(function(r) {
        return {
          name: r.display_name,
          full_name: r.full_name,
          default_branch: r.branch,
          import_state: r.clone_status,
          publication_readiness_state: r.publication_ready ? 'ready' : 'not_ready',
        };
      });
      break;
    case 'project-studio':
      var os = fix.operator_session || {};
      state.active_sessions = [{
        status: os.status,
        phase: os.phase,
        purpose: os.purpose,
        repository_label: os.repository_label,
        tool_call_count: (os.tool_summary || []).reduce(function(a, t) { return a + (t.calls || 0); }, 0),
        tool_success_count: (os.tool_summary || []).reduce(function(a, t) { return a + (t.successes || 0); }, 0),
        proposal_count: os.proposal_count || 0,
        refusal_count: os.refusal_count || 0,
        pending_decisions: os.pending_decisions || [],
        blocked_capabilities: os.blocked_capabilities || [],
      }];
      var pu = fix.project_understanding || {};
      state.studies = [{
        study_status: pu.study_status,
        facts_discovered: pu.facts_discovered,
        facts_with_provenance: pu.facts_with_provenance,
        languages_detected: pu.languages_detected,
        frameworks_detected: pu.frameworks_detected,
        withheld_reasons: pu.withheld_reasons,
        withheld_material_count: pu.withheld_material_count,
        draft_narrative_count: pu.draft_narrative_count,
        draft_narrative_awaiting_approval: pu.draft_narrative_awaiting_approval,
        portfolio_eligibility: pu.portfolio_eligibility,
        approval_status: pu.approval_status,
      }];
      break;
    case 'inference-studio':
      state.runtime_available = fix.local_runtime && fix.local_runtime.available;
      state.runtime_kind = fix.local_runtime && fix.local_runtime.runtime_kind;
      state.task_suitability = fix.task_suitability || [];
      state.drafts = (fix.drafts || []).map(function(d) {
        return {
          task_kind: d.task_kind,
          draft_sha256: d.draft_sha256,
          draft_byte_count: d.draft_byte_count,
          requires_approval: d.requires_approval,
          provenance: 'review_required_draft',
        };
      });
      state.refusals = (fix.refusal_explanations || []).map(function(r) {
        return {
          task_kind: r.task_kind,
          refusal_code: r.refusal_code,
          refusal_reason: r.refusal_reason,
          provenance: 'refused',
        };
      });
      break;
    case 'publish-preview':
      state.publishable_repositories = [];
      var pc = fix.profile_candidate || {};
      state.studies = [{
        withheld_reasons: (pc.withheld_sections || []).map(function(w) { return w.section_id + ': ' + w.reason; }),
      }];
      break;
  }
}

// ── Public API ──────────────────────────────────────────────────────

// Public alias for _renderAllSurfaces
function renderAllSurfaces() { _renderAllSurfaces(); }

export {
  // Mode
  getMode,
  isProduction,
  isFixture,
  setFixtureMode,

  // Projection ingestion
  acceptDeveloperStudioProjection,
  acceptProjectionPatch,
  acceptBridgeProjection,

  // Surface state queries
  getSurfaceState,

  // Intent emission
  emitConnectIntent,
  emitRepositoryEstateIntent,
  emitProjectStudioIntent,

  // Callbacks
  onIntent,
  onProjectionChange,

  // Fixture rendering (explicit mode only)
  renderFixtureSurface,

  // Direct surface rendering for external callers
  _renderAllSurfaces,
  renderAllSurfaces,
};

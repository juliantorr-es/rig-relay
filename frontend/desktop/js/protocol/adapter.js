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
  'timeline': { status: 'unavailable' },
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

function _clearEl(el) {
  if (!el) return;
  while (el.firstChild) el.firstChild.remove();
}

function _buildEvidenceTagDom(status) {
  var span = document.createElement('span');
  span.className = 'evidence-tag';
  switch (status) {
    case 'proven': span.classList.add('proven'); break;
    case 'claimed': span.classList.add('claimed'); break;
    case 'planned': span.classList.add('planned'); break;
    case 'narrative': span.classList.add('narrative'); break;
    case 'refused': span.classList.add('narrative'); break;
    default: span.classList.add('narrative');
  }
  span.textContent = status;
  return span;
}

function _makeEl(tag, cls, text) {
  var el = document.createElement(tag);
  if (cls) el.className = cls;
  if (text !== undefined && text !== null) el.textContent = String(text);
  return el;
}

function _tn(text) {
  return document.createTextNode(String(text));
}

function _strong(text) {
  var s = document.createElement('strong');
  s.textContent = String(text);
  return s;
}

function _row(label, value, cls) {
  var tr = document.createElement('tr');
  tr.appendChild(_makeEl('td', 'k', label));
  tr.appendChild(_makeEl('td', cls || '', value));
  return tr;
}

// ── Public mode API

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
  // New surface projection sections (Lane X0 Phase 2)
  _setConnectSurfaceState(proj);
  _setRepositoryEstateSurfaceState(proj);
  _setPublishPreviewSurfaceState(proj);
  _setTimelineSurfaceState(proj);
  _setInferenceStudioSurfaceState(proj);
}

function _setAllSurfacesUnavailable() {
  var surfaces = ['connect', 'repository-estate', 'project-studio', 'inference-studio', 'publish-preview', 'timeline'];
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

function _setConnectSurfaceState(proj) {
  var cs = proj.connect_surface;
  if (!cs) return; // Fall through to existing workspace-based logic

  var trust = cs.trust_state || 'deferred';
  _surfaceStates['connect'] = {
    status: cs.available ? _mapTrustToStatus(trust) : 'unavailable',
    trust: trust,
    provenance: cs.provenance || 'derived_projection',
    reason: cs.degraded_reason || '',
    // Provider data
    providers: cs.providers || [],
    providers_configured: cs.providers_configured || 0,
    providers_total: cs.providers_total || 0,
    // Workspace connection
    connection_state: cs.workspace_connection_state || 'disconnected',
    token_available: cs.workspace_token_available || false,
    installation_id_hash: cs.workspace_installation_id_hash || '',
    accessible_repository_count: cs.workspace_accessible_repository_count || 0,
  };
}

function _setRepositoryEstateSurfaceState(proj) {
  var re = proj.repository_estate_surface;
  if (!re) return;

  var trust = re.trust_state || 'deferred';
  _surfaceStates['repository-estate'] = {
    status: re.available ? _mapTrustToStatus(trust) : 'unavailable',
    trust: trust,
    provenance: re.provenance || 'derived_projection',
    reason: re.degraded_reason || '',
    repositories: re.registered_repositories || [],
    total_registered: re.total_registered || 0,
    local_only_count: re.local_only_count || 0,
    github_backed_count: re.github_backed_count || 0,
    dirty_count: re.dirty_count || 0,
    inaccessible_count: re.inaccessible_count || 0,
    recent_changes: re.recent_changes || [],
    total_observations: re.total_observations || 0,
    corrupt_registration_count: re.corrupt_registration_count || 0,
    corrupt_observation_count: re.corrupt_observation_count || 0,
    corrupt_chain_links: re.corrupt_chain_links || 0,
    corruption_events: re.corruption_events || [],
  };
}

function _setPublishPreviewSurfaceState(proj) {
  var pp = proj.publish_preview_surface;
  if (!pp) return;

  var trust = pp.trust_state || 'deferred';
  _surfaceStates['publish-preview'] = {
    status: pp.available ? _mapTrustToStatus(trust) : 'unavailable',
    trust: trust,
    provenance: pp.provenance || 'derived_projection',
    reason: pp.degraded_reason || '',
    operation_id: pp.operation_id || '',
    last_result_status: pp.last_result_status || 'none',
    preview_result: pp.preview_result || null,
    refusal: pp.refusal || null,
    ledger_total_events: pp.ledger_total_events || 0,
    ledger_valid_rows: pp.ledger_valid_rows || 0,
    ledger_corrupt_rows: pp.ledger_corrupt_rows || 0,
    ledger_corruption_detected: pp.ledger_corruption_detected || false,
    publishable_repository_count: pp.publishable_repository_count || 0,
    deployment_available: pp.deployment_available || false,
    deployment_deferred_reason: pp.deployment_deferred_reason || 'Deployment not available in this release',
  };
}

function _setTimelineSurfaceState(proj) {
  var tl = proj.timeline_surface;
  if (!tl) {
    _surfaceStates['timeline'] = { status: 'unavailable', reason: 'Timeline service not available' };
    return;
  }

  var trust = tl.trust_state || 'deferred';
  _surfaceStates['timeline'] = {
    status: tl.available ? _mapTrustToStatus(trust) : 'unavailable',
    trust: trust,
    provenance: tl.provenance || 'derived_projection',
    reason: tl.degraded_reason || '',
    timeline_id: tl.timeline_id || '',
    assembled_at: tl.assembled_at || '',
    events: tl.events || [],
    event_count: tl.event_count || 0,
    domain_coverage: tl.domain_coverage || {},
    unsupported_domains: tl.unsupported_domains || [],
    verified_canonical_count: tl.verified_canonical_count || 0,
    parsed_unverified_count: tl.parsed_unverified_count || 0,
    canonical_degraded_count: tl.canonical_degraded_count || 0,
    corrupt_count: tl.corrupt_count || 0,
    unsupported_count: tl.unsupported_count || 0,
    missing_count: tl.missing_count || 0,
    contradictory_count: tl.contradictory_count || 0,
    stale_count: tl.stale_count || 0,
    assembly_warnings: tl.assembly_warnings || [],
    assembly_errors: tl.assembly_errors || [],
  };
}

function _setInferenceStudioSurfaceState(proj) {
  var is_ = proj.inference_studio_surface;
  if (!is_) return;

  var trust = is_.trust_state || 'deferred';
  _surfaceStates['inference-studio'] = {
    status: is_.available ? _mapTrustToStatus(trust) : 'unavailable',
    trust: trust,
    provenance: is_.provenance || 'derived_projection',
    reason: is_.degraded_reason || '',
    runtime_available: is_.runtime_available || false,
    runtime_configured: is_.runtime_configured || false,
    runtime_kind: is_.runtime_kind || 'unknown',
    omlx_strategy: is_.omlx_strategy || 'pending_infrastructure_handoff',
    omlx_available: is_.omlx_available || false,
    omlx_disclosure: is_.omlx_disclosure || 'Hardware-accelerated local inference is pending infrastructure integration and verification.',
    task_suitability_count: is_.task_suitability_count || 0,
    total_results: is_.total_results || 0,
    total_executed: is_.total_executed || 0,
    total_refused: is_.total_refused || 0,
    drafts_awaiting_review: is_.drafts_awaiting_review || 0,
    native_schema_capability_claimed: is_.native_schema_capability_claimed || false,
    native_schema_capability_proven: is_.native_schema_capability_proven || false,
    grammar_capability_claimed: is_.grammar_capability_claimed || false,
    grammar_capability_proven: is_.grammar_capability_proven || false,
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
  _renderTimelineSurface();
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
  _setConsumerStatusChip(chip, status, _connectStatusLabel(status, state));
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
  _clearEl(el);
  if (state.status === 'unavailable' || state.status === 'deferred') {
    el.appendChild(_buildEvidenceTagDom('planned'));
    el.appendChild(_tn(' Repository access: '));
    el.appendChild(_strong('unavailable'));
    return;
  }
  if (state.status === 'connected') {
    el.appendChild(_buildEvidenceTagDom('proven'));
    el.appendChild(_tn(' Repository access: '));
    el.appendChild(_strong('granted'));
    el.appendChild(_tn(state.token_available ? ' \u00B7 Token present' : ' \u00B7 No token'));
    el.appendChild(_tn(' \u00B7 ' + String(state.accessible_repository_count || 0) + ' repositories accessible'));
    return;
  }
  el.appendChild(_buildEvidenceTagDom('claimed'));
  el.appendChild(_tn(' Repository access: '));
  el.appendChild(_strong(_escapeHtml(state.status)));
}

function _renderConnectPublicationApproval(state) {
  var el = _getEl('publication-approval-status');
  if (!el) return;
  _clearEl(el);
  if (state.status === 'unavailable') {
    el.appendChild(_buildEvidenceTagDom('planned'));
    el.appendChild(_tn(' Publication approval: '));
    el.appendChild(_strong('unavailable'));
    return;
  }
  if (state.status === 'connected') {
    el.appendChild(_buildEvidenceTagDom('proven'));
    el.appendChild(_tn(' Publication approval: '));
    el.appendChild(_strong('granted'));
    return;
  }
  el.appendChild(_buildEvidenceTagDom('planned'));
  el.appendChild(_tn(' Publication approval: '));
  el.appendChild(_strong('deferred'));
  el.appendChild(_makeEl('br'));
  var deferredDetail = _makeEl('span', 'status-detail', 'Live integration deferred to O0 bridge aggregation milestone');
  el.appendChild(deferredDetail);
}

function _renderConnectFixtureBanner(state) {
  // Status rendering handled by _setConsumerStatusChip
}

function _renderRepositoryEstateSurface() {
  var state = _surfaceStates['repository-estate'];
  _setRepoFixtureBanner(state);
  _renderRepoList(state);
  _renderRepoIntake(state);
}

function _setRepoFixtureBanner(state) {
  // Status rendering handled by _setConsumerStatusChip
}

function _renderRepoList(state) {
  var repoList = _getEl('repo-list-container');
  if (!repoList) return;

  var repos = state.repositories || [];
  _clearEl(repoList);

  if (repos.length === 0) {
    if (state.status === 'unavailable') {
      repoList.appendChild(_makeEl('div', 'status-detail', 'Repository service unavailable. No live bridge projection received.'));
    } else if (state.status === 'deferred') {
      repoList.appendChild(_makeEl('div', 'status-detail', 'Repository discovery deferred. Awaiting live workspace integration.'));
    } else {
      repoList.appendChild(_makeEl('div', 'status-detail', 'No repositories discovered.'));
    }
    return;
  }

  for (var i = 0; i < repos.length; i++) {
    var r = repos[i];
    var importState = r.import_state || r.intake_state || 'unknown';
    var importEvidence = 'planned';
    if (importState === 'imported' || importState === 'cloned') importEvidence = 'proven';
    else if (importState === 'failed') importEvidence = 'claimed';

    var pubState = r.publication_readiness_state || 'unknown';
    var pubEvidence = 'planned';
    var pubLabel = 'private';
    if (pubState === 'ready') { pubEvidence = 'proven'; pubLabel = 'public-ready'; }
    else if (pubState === 'review_required') { pubEvidence = 'claimed'; pubLabel = 'review-required'; }

    var card = _makeEl('div', 'repo-card');

    var nameDiv = _makeEl('div', 'repo-name', r.name || r.display_name || '');
    card.appendChild(nameDiv);

    var metaDiv = _makeEl('div', 'repo-meta');
    metaDiv.appendChild(_buildEvidenceTagDom(importEvidence));
    metaDiv.appendChild(_tn(' ' + _escapeHtml(r.full_name || '') + ' \u00B7 ' + _escapeHtml(r.default_branch || r.branch || '') + ' \u00B7 ' + _escapeHtml(importState)));
    metaDiv.appendChild(_tn(' '));
    metaDiv.appendChild(_buildEvidenceTagDom(pubEvidence));
    metaDiv.lastChild.textContent = pubLabel;
    card.appendChild(metaDiv);
    repoList.appendChild(card);
  }
}

function _renderRepoIntake(state) {
  var el = _getEl('repo-intake-status');
  if (!el) return;
  _clearEl(el);
  if (state.status === 'unavailable') {
    var chip = _makeEl('span', 'status-chip deferred', 'Intake: unavailable');
    el.appendChild(chip);
    el.appendChild(_makeEl('br'));
    el.appendChild(_makeEl('div', 'status-detail', 'No intake data available.'));
    return;
  }
  el.appendChild(_makeEl('span', 'status-chip', 'Intake: ' + String(state.selected_count || 0) + ' selected, ' +
    String(state.imported_count || 0) + ' imported, ' +
    String(state.total_discovered || 0) + ' discovered'));
}

function _renderProjectStudioSurface() {
  var state = _surfaceStates['project-studio'];
  _setStudioFixtureBanner(state);
  _renderStudioOperator(state);
  _renderStudioUnderstanding(state);
}

function _setStudioFixtureBanner(state) {
  // Status rendering handled by _setConsumerStatusChip
}

function _renderStudioOperator(state) {
  var osEl = _getEl('operator-session-status');
  if (!osEl) return;

  _clearEl(osEl);

  if (state.status === 'unavailable') {
    var unavLine = _makeEl('span', 'status-line');
    unavLine.appendChild(_tn('Operator service: '));
    unavLine.appendChild(_strong('unavailable'));
    osEl.appendChild(unavLine);
    osEl.appendChild(_makeEl('br'));
    osEl.appendChild(_makeEl('span', 'status-detail', 'No live bridge projection received.'));
    return;
  }
  if (state.status === 'deferred') {
    var defLine = _makeEl('span', 'status-line');
    defLine.appendChild(_tn('Operator service: '));
    defLine.appendChild(_strong('deferred'));
    osEl.appendChild(defLine);
    osEl.appendChild(_makeEl('br'));
    osEl.appendChild(_makeEl('span', 'status-detail', 'Awaiting live bridge aggregation.'));
    return;
  }

  var sessions = state.active_sessions || [];
  if (sessions.length === 0) {
    osEl.appendChild(_makeEl('span', 'status-line', 'No active operator sessions'));
    osEl.appendChild(_makeEl('br'));
    osEl.appendChild(_makeEl('span', 'status-detail', 'Start an investigation to begin.'));
    return;
  }

  for (var i = 0; i < sessions.length; i++) {
    var s = sessions[i];
    var sLine = _makeEl('span', 'status-line');
    sLine.appendChild(_tn('Session: '));
    sLine.appendChild(_strong(_escapeHtml(s.status || 'idle')));
    sLine.appendChild(_tn(' \u00B7 Phase: ' + _escapeHtml(s.phase || 'idle')));
    osEl.appendChild(sLine);
    osEl.appendChild(_makeEl('br'));
    osEl.appendChild(_makeEl('span', 'status-detail', _escapeHtml(s.purpose || '') + ' on ' + _escapeHtml(s.repository_label || '')));
    if (s.pending_decisions && s.pending_decisions.length) {
      osEl.appendChild(_makeEl('br'));
      var pendSpan = _makeEl('span', 'status-detail', '\u26A0 Pending: ' + _escapeHtml(s.pending_decisions.join(', ')));
      pendSpan.style.color = 'var(--warning-color)';
      osEl.appendChild(pendSpan);
    }
    if (s.blocked_capabilities && s.blocked_capabilities.length) {
      osEl.appendChild(_makeEl('br'));
      var blockSpan = _makeEl('span', 'status-detail', 'Blocked: ' + _escapeHtml(s.blocked_capabilities.join(', ')));
      blockSpan.style.color = 'var(--error-color)';
      osEl.appendChild(blockSpan);
    }
    osEl.appendChild(_makeEl('br'));
  }

  var tsEl = _getEl('operator-tool-summary');
  if (tsEl) {
    _clearEl(tsEl);
    var totalCalls = 0, totalSuccess = 0;
    for (var j = 0; j < sessions.length; j++) {
      totalCalls += sessions[j].tool_call_count || 0;
      totalSuccess += sessions[j].tool_success_count || 0;
    }
    if (totalCalls > 0) {
      var tsTable = _makeEl('table', 'kv');
      tsTable.appendChild(_row('Total Calls', String(totalCalls)));
      tsTable.appendChild(_row('Successes', String(totalSuccess), 'ok'));
      tsEl.appendChild(tsTable);
    } else {
      _setText(tsEl, 'No tool activity yet.');
    }
  }

  var propEl = _getEl('operator-proposals');
  if (propEl) {
    _clearEl(propEl);
    var totalProposals = 0, totalPending = 0, totalRefused = 0;
    for (var k = 0; k < sessions.length; k++) {
      totalProposals += sessions[k].proposal_count || 0;
      totalPending += sessions[k].proposal_pending_count || 0;
      totalRefused += sessions[k].refusal_count || 0;
    }
    if (totalProposals > 0) {
      propEl.appendChild(_makeEl('div', 'status-line', 'Proposals: ' + totalProposals + ' (\u00B7 ' +
        totalPending + ' pending, ' + totalRefused + ' refused)'));
    } else {
      _setText(propEl, 'No proposals yet.');
    }
  }
}

function _renderStudioUnderstanding(state) {
  var usEl = _getEl('understanding-status');
  if (!usEl) return;

  var studies = state.studies || [];
  _clearEl(usEl);

  if (studies.length === 0) {
    var line = _makeEl('span', 'status-line');
    line.appendChild(_tn('Study status: '));
    line.appendChild(_strong('not_started'));
    usEl.appendChild(line);
    usEl.appendChild(_makeEl('br'));
    usEl.appendChild(_makeEl('span', 'status-detail', 'No project studies available.'));
    _setText(_getEl('understanding-details'), '');
    return;
  }

  var study = studies[0];
  var sLine = _makeEl('span', 'status-line');
  sLine.appendChild(_tn('Study status: '));
  sLine.appendChild(_strong(_escapeHtml(study.study_status || 'unknown')));
  usEl.appendChild(sLine);
  usEl.appendChild(_makeEl('br'));
  usEl.appendChild(_makeEl('span', 'status-detail', (study.facts_discovered || 0) + ' facts (' + (study.facts_with_provenance || 0) + ' with provenance) \u00B7 ' +
    (study.draft_narrative_count || 0) + ' drafts (' + (study.draft_narrative_awaiting_approval || 0) + ' awaiting approval)'));

  var udEl = _getEl('understanding-details');
  if (udEl) {
    _clearEl(udEl);
    var detailsTable = _makeEl('table', 'kv');
    if (study.languages_detected) detailsTable.appendChild(_row('Languages', _escapeHtml(study.languages_detected.join(', '))));
    if (study.frameworks_detected) detailsTable.appendChild(_row('Frameworks', _escapeHtml(study.frameworks_detected.join(', '))));
    if (study.withheld_reasons && study.withheld_reasons.length) {
      detailsTable.appendChild(_row('Withheld', _escapeHtml((study.withheld_material_count || 0) + ' items: ' + study.withheld_reasons.join(', ')), 'warning'));
    }
    detailsTable.appendChild(_row('Portfolio', _escapeHtml(study.portfolio_eligibility || 'unknown')));
    detailsTable.appendChild(_row('Approval', _escapeHtml(study.approval_status || 'unknown')));
    udEl.appendChild(detailsTable);
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
  // Status rendering handled by _setConsumerStatusChip
}

function _renderInferenceRuntime(state) {
  var irEl = _getEl('inference-runtime-status');
  if (!irEl) return;

  if (state.status === 'unavailable' || state.status === 'deferred') {
    _clearEl(irEl);
    irEl.appendChild(_makeEl('span', 'status-chip disconnected', 'Inference Unavailable'));
    // Show OMLX disclosure even when surface is deferred
    if (state.omlx_strategy && state.omlx_disclosure) {
      irEl.appendChild(_buildOMLXDisclosure(state));
    }
    return;
  }

  var available = state.runtime_available;
  _setConsumerStatusChip(irEl.querySelector('.status-chip') || irEl, available ? 'available' : 'offline',
    available ? 'Runtime Available' : 'Runtime Offline');
  var detail = irEl.querySelector('.status-detail');
  if (detail) _setText(detail, (available ? 'Local inference ready (' + _escapeHtml(state.runtime_kind || 'unknown') + ')' : 'No local runtime configured'));

  // OMLX disclosure — truthful blocked/deferred state from backend projection
  if (state.omlx_strategy && state.omlx_disclosure) {
    irEl.appendChild(_buildOMLXDisclosure(state));
  }
}

function _renderInferenceTasks(state) {
  var tasksGrid = _getEl('inference-tasks');
  if (!tasksGrid) return;

  var ts = state.task_suitability || [];
  _clearEl(tasksGrid);

  if (ts.length === 0) {
    var card = _makeEl('div', 'task-card');
    card.appendChild(_makeEl('div', 'task-name', 'No tasks'));
    card.appendChild(_makeEl('div', 'task-status', state.status === 'unavailable' ? 'Inference service unavailable.' : 'No task suitability data.'));
    tasksGrid.appendChild(card);
    return;
  }

  for (var i = 0; i < ts.length; i++) {
    var t = ts[i];
    var suitable = t.suitable;
    var card = _makeEl('div', 'task-card ' + (suitable ? 'suitable' : 'unsuitable'));
    card.appendChild(_makeEl('div', 'task-name', _escapeHtml(t.task_kind)));
    var statusDiv = _makeEl('div', 'task-status');
    statusDiv.appendChild(_buildEvidenceTagDom(suitable ? 'proven' : 'refused'));
    statusDiv.appendChild(_tn(' '));
    statusDiv.appendChild(_tn(suitable ? _escapeHtml(t.enforcement_class_required || '') + ' admitted' : _escapeHtml(t.refusal_reason || 'Refused')));
    card.appendChild(statusDiv);
    tasksGrid.appendChild(card);
  }
}

function _renderInferenceDrafts(state) {
  var draftList = _getEl('inference-drafts');
  if (!draftList) return;

  var drafts = state.drafts || [];
  _clearEl(draftList);
  draftList.appendChild(_makeEl('h3', '', 'Drafts (' + drafts.length + ')'));

  if (drafts.length === 0) {
    draftList.appendChild(_makeEl('div', 'draft-item', 'No drafts awaiting review.'));
  } else {
    for (var i = 0; i < drafts.length; i++) {
      var d = drafts[i];
      var needsApproval = d.requires_approval !== false;
      var item = _makeEl('div', 'draft-item');
      item.appendChild(_strong(_escapeHtml(d.task_kind)));
      item.appendChild(_tn(': ' + _escapeHtml(d.draft_sha256 ? d.draft_sha256.substring(0, 16) + '...' : 'unknown')));
      item.appendChild(_tn(' '));
      item.appendChild(_buildEvidenceTagDom(needsApproval ? 'claimed' : 'proven'));
      item.lastChild.textContent = needsApproval ? 'review-required' : 'approved';
      item.appendChild(_tn(' (' + (d.draft_byte_count || 0) + ' bytes)'));
      draftList.appendChild(item);
    }
  }
}

function _renderInferenceRefusals(state) {
  var refusalList = _getEl('inference-refusals');
  if (!refusalList) return;

  var refusals = state.refusals || [];
  _clearEl(refusalList);
  refusalList.appendChild(_makeEl('h3', '', 'Refusals (' + refusals.length + ')'));

  if (refusals.length === 0) {
    var noRef = _makeEl('div', 'refusal-item', 'No refusals.');
    noRef.style.color = 'var(--text-secondary)';
    refusalList.appendChild(noRef);
  } else {
    for (var i = 0; i < refusals.length; i++) {
      var r = refusals[i];
      var item = _makeEl('div', 'refusal-item');
      item.appendChild(_strong(_escapeHtml(r.task_kind)));
      item.appendChild(_tn(': ' + _escapeHtml(r.refusal_reason || r.refusal_code || 'Refused')));
      item.appendChild(_tn(' (code: ' + _escapeHtml(r.refusal_code || 'UNKNOWN') + ')'));
      refusalList.appendChild(item);
    }
  }
}

// ── OMLX disclosure renderer ─────────────────────────────────────────
// Renders truthful blocked/deferred OMLX status from backend projection.
// Used by _renderInferenceRuntime when the surface state carries omlx_strategy
// and omlx_disclosure from the backend's InferenceStudioSurfaceProjection.

function _buildOMLXDisclosure(state) {
  var div = _makeEl('div', 'omlx-disclosure');
  div.style.cssText = 'margin-top:10px;padding:10px 14px;background:rgba(198,144,38,0.08);border:1px solid rgba(198,144,38,0.15);border-radius:var(--radius-sm);font-size:0.78rem;color:var(--warning-color)';
  var header = _makeEl('strong', '', 'Hardware-Accelerated Inference');
  div.appendChild(header);
  var statusLine = _makeEl('div', 'status-detail');
  statusLine.style.marginTop = '4px';
  statusLine.textContent = 'Strategy: ' + _escapeHtml(state.omlx_strategy || 'unknown') + '. ' + _escapeHtml(state.omlx_disclosure || '');
  div.appendChild(statusLine);
  return div;
}

function _renderPublishPreviewSurface() {
  var state = _surfaceStates['publish-preview'];
  _setPublishFixtureBanner(state);
  _renderPublishReadiness(state);
  _renderPublishSections(state);
  _renderPublishWithheld(state);
}

function _setPublishFixtureBanner(state) {
  // Status rendering handled by _setConsumerStatusChip
}

function _renderPublishReadiness(state) {
  var readinessEl = _getEl('publish-readiness');
  if (!readinessEl) return;

  if (state.status === 'unavailable') {
    _clearEl(readinessEl);
    readinessEl.appendChild(_makeEl('span', 'status-chip deferred', 'Not Available'));
    readinessEl.appendChild(_makeEl('div', 'status-detail', 'Publish service unavailable. No live projection received.'));
    return;
  }

  var repos = state.publishable_repositories || [];
  var studies = state.studies || [];
  var canPublish = repos.length > 0;
  _setConsumerStatusChip(readinessEl.querySelector('.status-chip') || readinessEl, canPublish ? 'available' : 'deferred',
    canPublish ? repos.length + ' repositories publishable' : 'Not Ready');
  var detail = readinessEl.querySelector('.status-detail');
  if (detail) _setText(detail, repos.length + ' repositories ready, ' + studies.length + ' studies available.');
}

function _renderPublishSections(state) {
  var sectionsGrid = _getEl('publish-sections');
  if (!sectionsGrid) return;

  _clearEl(sectionsGrid);

  if (state.status === 'unavailable') {
    var noCard = _makeEl('div', 'section-card not-ready');
    noCard.appendChild(_strong('No sections'));
    noCard.appendChild(_tn(' '));
    noCard.appendChild(_buildEvidenceTagDom('planned'));
    sectionsGrid.appendChild(noCard);
    return;
  }

  var repos = state.publishable_repositories || [];
  if (repos.length === 0) {
    sectionsGrid.appendChild(_makeEl('div', 'section-card not-ready', ''));
    sectionsGrid.lastChild.appendChild(_strong('No publishable sections'));
    return;
  }

  for (var i = 0; i < repos.length; i++) {
    var r = repos[i];
    var ready = r.publication_readiness_state === 'ready';
    var card = _makeEl('div', 'section-card ' + (ready ? 'ready' : 'not-ready'));
    card.appendChild(_strong(_escapeHtml(r.name || r.full_name || '')));
    card.appendChild(_tn(' '));
    card.appendChild(_buildEvidenceTagDom(ready ? 'proven' : 'claimed'));
    sectionsGrid.appendChild(card);
  }
}

function _renderPublishWithheld(state) {
  var withheldEl = _getEl('publish-withheld');
  if (!withheldEl) return;

  var studies = state.studies || [];
  _clearEl(withheldEl);
  withheldEl.appendChild(_makeEl('h3', '', 'Withheld from Public Preview'));

  if (studies.length > 0) {
    var study = studies[0];
    var reasons = study.withheld_reasons || [];
    if (reasons.length > 0) {
      for (var i = 0; i < reasons.length; i++) {
        withheldEl.appendChild(_makeEl('div', 'withheld-item', _escapeHtml(reasons[i]) + ' (internal_only)'));
      }
    } else {
      withheldEl.appendChild(_makeEl('div', 'withheld-item', 'No explicitly withheld sections.'));
    }
  } else {
    withheldEl.appendChild(_makeEl('div', 'withheld-item', 'No withheld data recorded.'));
  }
  var privNote = _makeEl('div', 'withheld-item', 'Any section not listed above is withheld by default. Private/internal-only material is never rendered.');
  privNote.style.cssText = 'margin-top:8px;color:var(--text-muted)';
  withheldEl.appendChild(privNote);
}

function _renderTimelineSurface() {
  var state = _surfaceStates['timeline'];
  if (!state) return;

  var tlEvents = _getEl('timeline-events');
  var tlDegradation = _getEl('timeline-degradation');
  var tlDomains = _getEl('timeline-domains');

  // Status rendering handled by _setConsumerStatusChip

  // Timeline events
  if (tlEvents) {
    _clearEl(tlEvents);
    if (state.status === 'unavailable') {
      tlEvents.appendChild(_makeEl('div', 'status-detail', 'Timeline service unavailable. ' + _escapeHtml(state.reason || 'No projection received.')));
    } else {
      var events = state.events || [];
      tlEvents.appendChild(_makeEl('h3', '', 'Timeline Events (' + String(state.event_count || events.length) + ')'));
      if (events.length === 0) {
        tlEvents.appendChild(_makeEl('div', 'status-detail', 'No timeline events recorded.'));
      } else {
        var tlList = _makeEl('div', 'timeline-list');
        for (var e = 0; e < events.length; e++) {
          var ev = events[e];
          var verificationCls = 'evidence-tag';
          switch (ev.verification_class) {
            case 'verified_canonical': verificationCls += ' proven'; break;
            case 'parsed_unverified': verificationCls += ' claimed'; break;
            case 'canonical_degraded': verificationCls += ' planned'; break;
            case 'corrupt': verificationCls += ' narrative'; break;
            case 'unsupported': verificationCls += ' narrative'; break;
            default: verificationCls += ' planned';
          }
          var card = _makeEl('div', 'timeline-event-card');
          card.appendChild(_makeEl('div', 'timeline-event-domain', _escapeHtml(ev.domain || 'unknown') + ' / ' + _escapeHtml(ev.event_kind || ev.kind || '')));
          card.appendChild(_makeEl('div', 'timeline-event-label', _escapeHtml(ev.label || ev.summary || '')));
          var meta = _makeEl('div', 'timeline-event-meta');
          meta.appendChild(_makeEl('span', verificationCls, _escapeHtml(ev.verification_class || 'unverified')));
          meta.appendChild(_tn(' \u00B7 ' + _escapeHtml(ev.source || '') + ' \u00B7 ' + _escapeHtml(ev.timestamp || ev.event_at || '')));
          card.appendChild(meta);
          tlList.appendChild(card);
        }
        tlEvents.appendChild(tlList);
      }
    }
  }

  // Degradation summary
  if (tlDegradation) {
    _clearEl(tlDegradation);
    var canDeg = state.canonical_degraded_count || 0;
    var corDeg = state.corrupt_count || 0;
    var unsDeg = state.unsupported_count || 0;
    var missDeg = state.missing_count || 0;
    var contDeg = state.contradictory_count || 0;
    var staleDeg = state.stale_count || 0;
    var totalDegraded = canDeg + corDeg + unsDeg + missDeg + contDeg + staleDeg;
    tlDegradation.appendChild(_makeEl('h3', '', 'Degradation Summary'));
    if (totalDegraded === 0) {
      tlDegradation.appendChild(_makeEl('div', 'status-detail', 'No degradation detected.'));
    } else {
      var degTable = _makeEl('table', 'kv');
      degTable.appendChild(_row('Canonical degraded', String(canDeg), 'warning'));
      degTable.appendChild(_row('Corrupt', String(corDeg), corDeg > 0 ? 'error' : 'ok'));
      degTable.appendChild(_row('Unsupported', String(unsDeg)));
      degTable.appendChild(_row('Missing', String(missDeg)));
      degTable.appendChild(_row('Contradictory', String(contDeg), contDeg > 0 ? 'error' : 'ok'));
      degTable.appendChild(_row('Stale', String(staleDeg), staleDeg > 0 ? 'warning' : 'ok'));
      tlDegradation.appendChild(degTable);
    }
    var assemblyWarnings = state.assembly_warnings || [];
    var assemblyErrors = state.assembly_errors || [];
    if (assemblyErrors.length > 0) {
      var errDiv = _makeEl('div', 'status-detail');
      errDiv.style.color = 'var(--error-color)';
      errDiv.appendChild(_strong('Assembly errors: '));
      errDiv.appendChild(_tn(_escapeHtml(assemblyErrors.join('; '))));
      tlDegradation.appendChild(errDiv);
    }
    if (assemblyWarnings.length > 0) {
      var warnDiv = _makeEl('div', 'status-detail');
      warnDiv.style.color = 'var(--warning-color)';
      warnDiv.appendChild(_strong('Assembly warnings: '));
      warnDiv.appendChild(_tn(_escapeHtml(assemblyWarnings.join('; '))));
      tlDegradation.appendChild(warnDiv);
    }
  }

  // Domain coverage
  if (tlDomains) {
    _clearEl(tlDomains);
    var domains = state.domain_coverage || {};
    var unsupportedDomains = state.unsupported_domains || [];
    var verifiedCanonical = state.verified_canonical_count || 0;
    var parsedUnverified = state.parsed_unverified_count || 0;
    tlDomains.appendChild(_makeEl('h3', '', 'Domain Coverage'));
    var domainKeys = Object.keys(domains);
    if (domainKeys.length > 0) {
      var domTable = _makeEl('table', 'kv');
      for (var d = 0; d < domainKeys.length; d++) {
        var domainKey = domainKeys[d];
        domTable.appendChild(_row(_escapeHtml(domainKey), _escapeHtml(String(domains[domainKey]))));
      }
      tlDomains.appendChild(domTable);
    }
    tlDomains.appendChild(_makeEl('div', 'status-detail', String(verifiedCanonical) + ' verified canonical \u00B7 ' + String(parsedUnverified) + ' parsed unverified \u00B7 ' + String(unsupportedDomains.length) + ' unsupported domains'));
    if (unsupportedDomains.length > 0) {
      var unsupDiv = _makeEl('div', 'status-detail', 'Unsupported: ' + _escapeHtml(unsupportedDomains.join(', ')));
      unsupDiv.style.color = 'var(--warning-color)';
      tlDomains.appendChild(unsupDiv);
    }
  }
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

// ── Consumer status chip helper ─────────────────────────────────────

function _setConsumerStatusChip(container, statusValue, statusDetail) {
  if (!container) return;
  var mapping = {
    'available':            { cls: 'available',       label: 'Available' },
    'derived':              { cls: 'derived',         label: 'Derived' },
    'setup_required':       { cls: 'setup-required',  label: 'Setup Required' },
    'verification_pending': { cls: 'setup-required',  label: 'Verification Pending' },
    'unavailable':          { cls: 'unavailable',     label: 'Unavailable' },
    'signing_required':     { cls: 'setup-required',  label: 'Signing Required' },
    'connection_required':  { cls: 'setup-required',  label: 'Connection Required' },
    'error':                { cls: 'error',           label: 'Error' },
    'blocked':              { cls: 'blocked',         label: 'Blocked' },
  };
  var entry = mapping[statusValue] || { cls: 'pending', label: statusValue || 'Unknown' };
  container.className = 'status-chip ' + entry.cls;
  _setText(container, entry.label);
  if (statusDetail) {
    var detail = container.querySelector('.status-detail');
    if (!detail) {
      detail = document.createElement('span');
      detail.className = 'status-detail';
      container.appendChild(detail);
    }
    _setText(detail, statusDetail);
  }
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
    case 'timeline': return window.__P0_FIXTURES__.timeline;
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
    case 'timeline':
      state.events = (fix.timeline_events || []).map(function(ev) {
        return {
          domain: ev.domain,
          event_kind: ev.kind,
          label: ev.label,
          summary: ev.summary,
          verification_class: ev.verification_class,
          source: ev.source,
          timestamp: ev.timestamp,
        };
      });
      state.event_count = fix.event_count || state.events.length;
      state.verified_canonical_count = fix.verified_canonical_count || 0;
      state.parsed_unverified_count = fix.parsed_unverified_count || 0;
      state.canonical_degraded_count = fix.canonical_degraded_count || 0;
      state.corrupt_count = fix.corrupt_count || 0;
      state.unsupported_count = fix.unsupported_count || 0;
      state.missing_count = fix.missing_count || 0;
      state.contradictory_count = fix.contradictory_count || 0;
      state.stale_count = fix.stale_count || 0;
      state.domain_coverage = fix.domain_coverage || {};
      state.unsupported_domains = fix.unsupported_domains || [];
      state.assembly_warnings = fix.assembly_warnings || [];
      state.assembly_errors = fix.assembly_errors || [];
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

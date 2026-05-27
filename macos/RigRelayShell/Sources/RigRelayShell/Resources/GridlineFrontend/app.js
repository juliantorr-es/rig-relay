// Rig Relay Cockpit Frontend Logic
import { state } from './js/state.js';
import { TransportState, createTransportStateAuthority, STATUS_LABELS } from './js/transportState.js';
import { renderStatusBar } from './js/status.js';
import * as GridlineAdapter from './js/protocol/adapter.js';
import { setupKeyboardNavigation } from './js/keyboardNav.js';
let wsClient = null;
let wsAuthFailed = false;
let currentMode = 'operate';

const _appAuthority = createTransportStateAuthority({
  onTransition(snap) {
    state.wsConnected = snap.wsConnected;
    state.transport.status = snap.transport.status;
    state.transport.phase = snap.transport.phase;
    state.transport.lastEvent = snap.transport.lastEvent;
    state.transport.lastError = snap.transport.lastError;
    state.transport.handshakeId = snap.transport.handshakeId;
    state.transport.updatedAt = snap.transport.updatedAt;
  },
});

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

// ── Surface Switching ──

const SURFACE_IDS = ['connect', 'repository-estate', 'project-studio', 'inference-studio', 'publish-preview', 'timeline'];

function switchSurface(surfaceId) {
  // ── S1: Deactivate all surfaces first ───────────────────────────
  SURFACE_IDS.forEach(function(id) {
    var container = document.getElementById('surface-' + id);
    if (container) container.classList.remove('active');
  });
  document.querySelectorAll('#surface-nav .surface-tab').forEach(function(tab) {
    tab.classList.remove('active');
    tab.setAttribute('aria-selected', 'false');
    tab.setAttribute('tabindex', '-1');
  });

  var activeTab = document.querySelector('#surface-nav .surface-tab[data-surface="' + surfaceId + '"]');
  if (activeTab) {
    activeTab.classList.add('active');
    activeTab.setAttribute('aria-selected', 'true');
    activeTab.setAttribute('tabindex', '0');
  }

  var surfaceContainer = document.getElementById('surface-' + surfaceId);
  var mainGrid = document.getElementById('main-grid');

  if (surfaceContainer) {
    surfaceContainer.classList.add('active');
    if (mainGrid) mainGrid.style.display = 'none';
  }

  // ── S1: Production mode — adapter renders based on projection state ──
  // Fixture mode — explicit gate, adapter handles fixture rendering
  // No silent fixture fallback in production mode.
  var adapterMode = GridlineAdapter.getMode();
  if (adapterMode === 'fixture') {
    GridlineAdapter.renderFixtureSurface(surfaceId);
  } else {
    // In production mode, the adapter already renders all surfaces
    // from the last accepted projection. Trigger a re-render to
    // pick up any surface state changes.
    GridlineAdapter._renderAllSurfaces();
  }

  // Emit surface-switched event for focus management
  var event = new CustomEvent('surface-switched', { detail: { surfaceId: surfaceId } });
  document.dispatchEvent(event);
}

function showCockpit() {
  SURFACE_IDS.forEach(function(id) {
    var container = document.getElementById('surface-' + id);
    if (container) container.classList.remove('active');
  });
  document.querySelectorAll('#surface-nav .surface-tab').forEach(function(tab) {
    tab.classList.remove('active');
    tab.setAttribute('aria-selected', 'false');
  });
  var mainGrid = document.getElementById('main-grid');
  if (mainGrid) mainGrid.style.display = '';
}

// ── Visual State System ──
// Proven/claimed/planned/narrative/redacted from E0 EvidenceStatus
// Connected/disconnected/deferred/pending/refused/blocked/error for service state

function renderStatusChip(el, status, label) {
  if (!el) return;
  var cls = 'status-chip';
  if (status === 'connected' || status === 'granted' || status === 'synced' || status === 'cloned' || status === 'ok' || status === 'available') cls += ' connected';
  else if (status === 'disconnected' || status === 'refused' || status === 'failed' || status === 'error') cls += ' disconnected';
  else if (status === 'deferred' || status === 'blocked' || status === 'warning') cls += ' deferred';
  else cls += ' pending';
  el.className = cls;
  setText(el, label || status);
}

function renderEvidenceTag(status) {
  var cls = 'evidence-tag';
  if (status === 'proven') cls += ' proven';
  else if (status === 'claimed') cls += ' claimed';
  else if (status === 'planned') cls += ' planned';
  else if (status === 'narrative') cls += ' narrative';
  else cls += ' narrative';
  return '<span class="' + cls + '">' + escapeHtml(status) + '</span>';
}

// ── P0 Intent Stubs (S1: upgraded) ──
// Emit typed intents through the Gridline adapter.
// Never call authority locally. These match the declared O0 intent contract.

function emitP0Intent(intentName, params) {
  // ── S1: Route through Gridline adapter for typed intent emission ──
  // The adapter enforces production vs fixture mode and provenance tracking.
  // Connect intents
  if (intentName === 'studio_connect_workspace' || intentName === 'connect_workspace') {
    return GridlineAdapter.emitConnectIntent(intentName, params);
  }
  // Repository estate intents
  if (intentName === 'studio_discover_repositories' || intentName === 'studio_select_repository' ||
      intentName === 'studio_import_repository' || intentName === 'discover_repositories') {
    return GridlineAdapter.emitRepositoryEstateIntent(intentName, params);
  }
  // Project studio intents
  if (intentName === 'studio_start_investigation' || intentName === 'studio_get_investigation' ||
      intentName === 'studio_close_investigation' || intentName === 'start_investigation') {
    return GridlineAdapter.emitProjectStudioIntent(intentName, params);
  }

  // Legacy fallback for non-studio intents
  var payload = {
    intent_name: intentName,
    parameters: params || {},
    source: 'p0_gridline_frontend',
    fixture_backed: GridlineAdapter.isFixture(),
    authority: 'none_local'
  };
  if (wsClient && _appAuthority.isConnected()) {
    wsClient.sendMessage({
      type: 'desktop_intent_request',
      intent_name: intentName,
      parameters: params || {},
      dry_run: true,
      source_surface: 'p0_gridline'
    });
  }
  console.log('[P0 Intent emitted]', intentName, JSON.stringify(payload).substring(0, 100));
  return payload;
}

// ── Surface Fixture Rendering ──
// Consumes window.__P0_FIXTURES__ fixture data. All rendering is fixture-backed
// until O0 publishes live bridge aggregation.

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

function renderSurfaceFixture(surfaceId) {
  var fix = _getFixture(surfaceId);
  if (!fix) return;

  switch (surfaceId) {
    case 'connect': renderConnectSurface(fix); break;
    case 'repository-estate': renderRepositoryEstateSurface(fix); break;
    case 'project-studio': renderProjectStudioSurface(fix); break;
    case 'inference-studio': renderInferenceStudioSurface(fix); break;
    case 'publish-preview': renderPublishPreviewSurface(fix); break;
    case 'timeline': renderTimelineSurface(fix); break;
  }
}

function renderConnectSurface(fix) {
  // ── Lane X0 Phase 2: Surface state path (from adapter projection) ──
  if (fix && fix.trust && fix.status) {
    _renderConnectFromState(fix);
    return;
  }

  // ── Legacy fixture path ──
  var cb = fix.carte_blanche || {};
  renderStatusChip(document.getElementById('cb-status-chip'), cb.status, cb.status === 'connected' ? 'Carte Blanche Connected' : cb.status);
  setText(document.getElementById('cb-detail'), fix._fixture_disclaimer || '');

  var ra = fix.repository_access || {};
  var raEl = document.getElementById('repo-access-status');
  if (raEl) {
    raEl.innerHTML = (ra.status === 'granted' ? renderEvidenceTag('proven') : renderEvidenceTag('planned')) +
      ' Repository access: <strong>' + escapeHtml(ra.status) + '</strong>' +
      (ra.token_present ? ' &middot; Token present' : ' &middot; No token');
  }

  var pa = fix.publication_approval || {};
  var paEl = document.getElementById('publication-approval-status');
  if (paEl) {
    paEl.innerHTML = renderEvidenceTag(pa.status === 'granted' ? 'proven' : 'planned') +
      ' Publication approval: <strong>' + escapeHtml(pa.status) + '</strong>' +
      (pa.reason ? '<br><span class="status-detail">' + escapeHtml(pa.reason) + '</span>' : '');
  }
}

// ── DOM-safe rendering helpers for X0 surface functions ──

function _clearEl(el) {
  if (!el) return;
  while (el.firstChild) el.firstChild.remove();
}

function _buildEvidenceTag(status) {
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

function _strong(text) {
  var s = document.createElement('strong');
  s.textContent = String(text);
  return s;
}

function _tn(text) {
  return document.createTextNode(String(text));
}

function _row(label, value, cls) {
  var tr = document.createElement('tr');
  tr.appendChild(_makeEl('td', 'k', label));
  tr.appendChild(_makeEl('td', cls || '', value));
  return tr;
}

// ── Lane X0 Phase 2: Connect surface state renderer ──
function _renderConnectFromState(state) {
  var cbEl = document.getElementById('cb-status-chip');
  if (cbEl) {
    var status = state.status || 'unavailable';
    var label = 'Carte Blanche ';
    switch (status) {
      case 'connected': label += 'Connected'; break;
      case 'deferred': label += 'Deferred'; break;
      case 'refused': label += 'Refused'; break;
      case 'fixture': label += '(Fixture)'; break;
      case 'error': label += 'Error'; break;
      default: label += escapeHtml(status);
    }
    renderStatusChip(cbEl, status, label);
  }
  var detailEl = document.getElementById('cb-detail');
  if (detailEl) {
    var detailText = '';
    if (state.status === 'unavailable') detailText = 'No connection available. Backend bridge not yet established.';
    else if (state.status === 'deferred') detailText = 'Connection deferred to live bridge aggregation milestone.';
    else if (state.status === 'refused') detailText = 'Connection refused by backend authority.';
    else if (state.status === 'connected') detailText = 'Live connection established.';
    else if (state.status === 'fixture') detailText = 'Fixture-backed projection — not live service data.';
    else detailText = 'Connection state: ' + escapeHtml(state.connection_state || 'unknown');
    if (state.trust) detailText += ' \u00B7 Trust: ' + escapeHtml(state.trust);
    setText(detailEl, detailText);
  }

  var raEl = document.getElementById('repo-access-status');
  if (raEl) {
    _clearEl(raEl);
    if (state.status === 'unavailable' || state.status === 'deferred') {
      raEl.appendChild(_buildEvidenceTag('planned'));
      raEl.appendChild(_tn(' Repository access: '));
      raEl.appendChild(_strong('unavailable'));
    } else if (state.status === 'connected') {
      raEl.appendChild(_buildEvidenceTag('proven'));
      raEl.appendChild(_tn(' Repository access: '));
      raEl.appendChild(_strong('granted'));
      raEl.appendChild(_tn(state.token_available ? ' · Token present' : ' · No token'));
      raEl.appendChild(_tn(' · ' + String(state.accessible_repository_count || 0) + ' repositories accessible'));
    } else {
      raEl.appendChild(_buildEvidenceTag('claimed'));
      raEl.appendChild(_tn(' Repository access: '));
      raEl.appendChild(_strong(state.status));
    }
  }

  var paEl = document.getElementById('publication-approval-status');
  if (paEl) {
    _clearEl(paEl);
    if (state.status === 'unavailable') {
      paEl.appendChild(_buildEvidenceTag('planned'));
      paEl.appendChild(_tn(' Publication approval: '));
      paEl.appendChild(_strong('unavailable'));
    } else if (state.status === 'connected') {
      paEl.appendChild(_buildEvidenceTag('proven'));
      paEl.appendChild(_tn(' Publication approval: '));
      paEl.appendChild(_strong('granted'));
    } else {
      paEl.appendChild(_buildEvidenceTag('planned'));
      paEl.appendChild(_tn(' Publication approval: '));
      paEl.appendChild(_strong('deferred'));
      paEl.appendChild(_makeEl('br'));
      var deferredDetail = _makeEl('span', 'status-detail', 'Live integration deferred to O0 bridge aggregation milestone');
      paEl.appendChild(deferredDetail);
    }
  }

  // Provider cache disclosure section
  var providers = state.providers || [];
  if (providers.length > 0 || state.providers_total > 0) {
    var connectCard = document.querySelector('#surface-connect .connect-card');
    if (connectCard) {
      // Remove old provider info if present
      var oldProvider = document.getElementById('connect-provider-cache');
      if (oldProvider) oldProvider.remove();

      var providerSection = document.createElement('div');
      providerSection.id = 'connect-provider-cache';
      providerSection.className = 'connect-section';
      providerSection.appendChild(_makeEl('h3', '', 'Provider Cache Disclosure'));
      providerSection.appendChild(_makeEl('div', 'status-detail', String(state.providers_configured || providers.length) + ' of ' + String(state.providers_total || 0) + ' providers configured'));
      var table = _makeEl('table', 'kv');
      table.style.marginTop = '8px';
      for (var p = 0; p < providers.length; p++) {
        var prov = providers[p];
        var cacheMode = prov.cache_mode || 'unknown';
        var retention = prov.retention_class || 'unknown';
        var ctxDisp = prov.confidential_context_disposition || 'none';
        var tr = document.createElement('tr');
        tr.appendChild(_makeEl('td', 'k', prov.display_name || prov.provider_name || 'unknown'));
        tr.appendChild(_makeEl('td', '', cacheMode + ' · ' + retention));
        var cellDetail = _makeEl('td', '', ctxDisp);
        cellDetail.style.cssText = 'font-size:0.7rem;color:var(--text-muted)';
        tr.appendChild(cellDetail);
        table.appendChild(tr);
      }
      providerSection.appendChild(table);
      connectCard.appendChild(providerSection);
    }
  }
}

function renderRepositoryEstateSurface(fix) {
  // ── Lane X0 Phase 2: Surface state path (from adapter projection) ──
  if (fix && fix.trust && fix.total_registered != null) {
    _renderRepoEstateFromState(fix);
    return;
  }

  // ── Legacy fixture path ──
  var repos = fix.repositories || [];
  var repoList = document.getElementById('repo-list-container');
  if (repoList) {
    var html = '';
    repos.forEach(function(r) {
      var statusTag = '';
      if (r.clone_status === 'cloned') statusTag = renderEvidenceTag('proven');
      else if (r.clone_status === 'failed') statusTag = renderEvidenceTag('claimed');
      else statusTag = renderEvidenceTag('planned');
      html += '<div class="repo-card">' +
        '<div class="repo-name">' + escapeHtml(r.display_name) + '</div>' +
        '<div class="repo-meta">' + statusTag +
        ' ' + escapeHtml(r.full_name) + ' &middot; ' + escapeHtml(r.branch) + ' &middot; ' + escapeHtml(r.clone_status) +
        (r.publication_ready ? ' <span class="evidence-tag proven">public-ready</span>' : ' <span class="evidence-tag planned">private</span>') +
        (r.publication_blockers && r.publication_blockers.length ? '<br><span class="status-detail">Blockers: ' + escapeHtml(r.publication_blockers.join(', ')) + '</span>' : '') +
        '</div></div>';
    });
    if (repos.length === 0) html = '<div class="status-detail">No repositories discovered.</div>';
    repoList.innerHTML = html;
  }

  var intake = fix.intake_status || {};
  var intakeEl = document.getElementById('repo-intake-status');
  if (intakeEl) {
    renderStatusChip(intakeEl.querySelector('.status-chip') || intakeEl, intake.status, 'Intake: ' + (intake.status || 'idle'));
    var detail = intakeEl.querySelector('.status-detail');
    if (detail) setText(detail, (intake.repos_discovered || 0) + ' discovered, ' + (intake.repos_imported || 0) + ' imported, ' + (intake.repos_failed || 0) + ' failed');
  }

  var sync = fix.sync_status || {};
  var syncEl = document.getElementById('repo-intake-status');
  if (syncEl && sync.status === 'synced') {
    syncEl.innerHTML += '<br><span class="status-detail">Last synced: ' + escapeHtml(sync.last_sync_at || 'never') + '</span>';
  }
}

// ── Lane X0 Phase 2: Repository Estate surface state renderer ──
function _renderRepoEstateFromState(state) {
  var repoList = document.getElementById('repo-list-container');
  if (repoList) {
    var repos = state.repositories || [];
    if (repos.length === 0) {
      _clearEl(repoList);
      if (state.status === 'unavailable') {
        repoList.appendChild(_makeEl('div', 'status-detail', 'Repository service unavailable. No live bridge projection received.'));
      } else if (state.status === 'deferred') {
        repoList.appendChild(_makeEl('div', 'status-detail', 'Repository discovery deferred. Awaiting live workspace integration.'));
      } else {
        repoList.appendChild(_makeEl('div', 'status-detail', 'No registered repositories.'));
      }
    } else {
      _clearEl(repoList);
      for (var i = 0; i < repos.length; i++) {
        var r = repos[i];
        var repoStatus = r.status || r.import_state || 'unknown';
        var evidenceStatus = 'planned';
        if (repoStatus === 'clean' || repoStatus === 'imported' || repoStatus === 'cloned') evidenceStatus = 'proven';
        else if (repoStatus === 'dirty') evidenceStatus = 'claimed';
        else if (repoStatus === 'failed' || repoStatus === 'inaccessible') evidenceStatus = 'planned';

        var statusChipClass = 'status-chip';
        var statusChipLabel = 'clean';
        if (repoStatus === 'dirty') { statusChipClass += ' pending'; statusChipLabel = 'dirty'; }
        else if (repoStatus === 'inaccessible') { statusChipClass += ' disconnected'; statusChipLabel = 'inaccessible'; }
        else if (repoStatus === 'detached') { statusChipClass += ' disconnected'; statusChipLabel = 'detached'; }
        else if (repoStatus === 'identity_mismatch') { statusChipClass += ' deferred'; statusChipLabel = 'identity mismatch'; }
        else if (repoStatus === 'disappeared') { statusChipClass += ' disconnected'; statusChipLabel = 'disappeared'; }
        else { statusChipClass += ' connected'; }

        var card = _makeEl('div', 'repo-card');
        var nameDiv = _makeEl('div', 'repo-name');
        nameDiv.appendChild(_tn(r.name || r.display_name || ''));
        var chip = _makeEl('span', statusChipClass, statusChipLabel);
        nameDiv.appendChild(_tn(' '));
        nameDiv.appendChild(chip);
        card.appendChild(nameDiv);

        var metaDiv = _makeEl('div', 'repo-meta');
        metaDiv.appendChild(_buildEvidenceTag(evidenceStatus));
        metaDiv.appendChild(_tn(' ' + (r.full_name || r.path || '') + ' · ' + (r.default_branch || r.branch || '')));
        if (r.remote_origin) metaDiv.appendChild(_tn(' · ' + r.remote_origin));
        card.appendChild(metaDiv);

        repoList.appendChild(card);
      }
    }
  }

  // Summary stats
  var intakeEl = document.getElementById('repo-intake-status');
  if (intakeEl) {
    var totalReg = state.total_registered || 0;
    var localOnly = state.local_only_count || 0;
    var githubBacked = state.github_backed_count || 0;
    var dirtyCount = state.dirty_count || 0;
    var inaccessibleCount = state.inaccessible_count || 0;
    var totalObs = state.total_observations || 0;
    _clearEl(intakeEl);
    var chip = _makeEl('span', 'status-chip', 'Estate: ' + String(totalReg) + ' registered (' + String(localOnly) + ' local, ' + String(githubBacked) + ' GitHub-backed)');
    intakeEl.appendChild(chip);
    intakeEl.appendChild(_makeEl('br'));
    intakeEl.appendChild(_makeEl('span', 'status-detail', String(dirtyCount) + ' dirty, ' + String(inaccessibleCount) + ' inaccessible · ' + String(totalObs) + ' observations'));
  }

  // Corruption events
  var corrEvents = state.corruption_events || [];
  var corrRegCount = state.corrupt_registration_count || 0;
  var corrObsCount = state.corrupt_observation_count || 0;
  var corrChainLinks = state.corrupt_chain_links || 0;
  var totalCorrupt = corrRegCount + corrObsCount + corrChainLinks;
  if (totalCorrupt > 0) {
    var repoContent = document.querySelector('#surface-repository-estate .surface-content');
    if (repoContent) {
      var oldCorr = document.getElementById('repo-corruption-status');
      if (oldCorr) oldCorr.remove();

      var corrSection = document.createElement('div');
      corrSection.id = 'repo-corruption-status';
      corrSection.className = 'withheld-section';
      corrSection.appendChild(_makeEl('h3', '', 'Corruption Events'));
      var korrTable = _makeEl('table', 'kv');
      korrTable.appendChild(_row('Corrupt registrations', String(corrRegCount), 'warning'));
      korrTable.appendChild(_row('Corrupt observations', String(corrObsCount), 'warning'));
      korrTable.appendChild(_row('Corrupt chain links', String(corrChainLinks), 'warning'));
      corrSection.appendChild(korrTable);
      if (corrEvents.length > 0) {
        corrSection.appendChild(_makeEl('div', 'status-detail', 'Events: ' + corrEvents.slice(0, 5).join('; ') + (corrEvents.length > 5 ? '...' : '')));
      }
      corrSection.style.cssText = 'margin-top:16px;';
      repoContent.appendChild(corrSection);
    }
  }

  // Recent changes
  var recentChanges = state.recent_changes || [];
  if (recentChanges.length > 0) {
    var repoContent = document.querySelector('#surface-repository-estate .surface-content');
    if (repoContent) {
      var oldChanges = document.getElementById('repo-recent-changes');
      if (oldChanges) oldChanges.remove();

      var changesSection = document.createElement('div');
      changesSection.id = 'repo-recent-changes';
      changesSection.className = 'status-block';
      changesSection.appendChild(_makeEl('h3', '', 'Recent Changes'));
      for (var c = 0; c < Math.min(recentChanges.length, 10); c++) {
        var ch = recentChanges[c];
        changesSection.appendChild(_makeEl('div', 'status-detail', (ch.repository_name || '') + ': ' + (ch.change_kind || '') + ' · ' + (ch.observed_at || '')));
      }
      changesSection.style.cssText = 'margin-top:16px;';
      repoContent.appendChild(changesSection);
    }
  }
}

function renderProjectStudioSurface(fix) {
  // ── Lane X0 Phase 2: Enrich with surface state if available ──
  var stateStudies = null;
  if (fix && fix.trust && fix.studies) {
    stateStudies = fix.studies;
  }

  // ── Legacy fixture path ──
  var os = fix.operator_session || {};
  var osEl = document.getElementById('operator-session-status');
  if (osEl) {
    osEl.innerHTML = '<span class="status-line">Session: <strong>' + escapeHtml(os.status || 'idle') + '</strong> &middot; Phase: ' + escapeHtml(os.phase || 'idle') + '</span>' +
      '<br><span class="status-detail">' + escapeHtml(os.purpose || '') + ' on ' + escapeHtml(os.repository_label || '') + '</span>';
    if (os.pending_decisions && os.pending_decisions.length) {
      osEl.innerHTML += '<br><span class="status-detail" style="color:var(--warning-color)">⚠ Pending: ' + escapeHtml(os.pending_decisions.join(', ')) + '</span>';
    }
    if (os.blocked_capabilities && os.blocked_capabilities.length) {
      osEl.innerHTML += '<br><span class="status-detail" style="color:var(--error-color)">Blocked: ' + escapeHtml(os.blocked_capabilities.join(', ')) + '</span>';
    }
  }

  var tsEl = document.getElementById('operator-tool-summary');
  if (tsEl && os.tool_summary) {
    var toolHtml = '<table class="kv">';
    os.tool_summary.forEach(function(t) {
      var hasFailure = t.failures > 0 || t.refusals > 0;
      toolHtml += '<tr><td class="k">' + escapeHtml(t.tool_name) + '</td><td class="' + (hasFailure ? 'warning' : 'ok') + '">' + t.calls + ' calls &middot; ' + t.successes + ' ok</td></tr>';
    });
    toolHtml += '</table>';
    tsEl.innerHTML = toolHtml;
  }

  var propEl = document.getElementById('operator-proposals');
  if (propEl && os.proposal_dispositions) {
    var disp = os.proposal_dispositions;
    var keys = Object.keys(disp);
    if (keys.length > 0) {
      var propHtml = '<div class="status-line">Proposals: ' + (os.proposal_count || 0) + '</div>';
      keys.forEach(function(k) {
        propHtml += '<span class="evidence-tag ' + (k === 'refused' ? 'narrative' : 'claimed') + '">' + escapeHtml(k) + ': ' + disp[k] + '</span> ';
      });
      propEl.innerHTML = propHtml;
    } else {
      setText(propEl, 'No proposals yet.');
    }
  }

  // L0 context enrichment from surface state studies
  if (stateStudies && stateStudies.length > 0) {
    _renderStudioFromStateStudies(stateStudies);
  } else {
    var pu = fix.project_understanding || {};
    var usEl = document.getElementById('understanding-status');
    if (usEl) {
      usEl.innerHTML = '<span class="status-line">Study status: <strong>' + escapeHtml(pu.study_status || 'not_started') + '</strong></span>' +
        '<br><span class="status-detail">' + (pu.facts_discovered || 0) + ' facts (' + (pu.facts_with_provenance || 0) + ' with provenance) &middot; ' + (pu.draft_narrative_count || 0) + ' drafts (' + (pu.draft_narrative_awaiting_approval || 0) + ' awaiting approval)</span>';
    }

    var udEl = document.getElementById('understanding-details');
    if (udEl) {
      var detailsHtml = '<table class="kv">';
      if (pu.languages_detected) detailsHtml += '<tr><td class="k">Languages</td><td>' + escapeHtml(pu.languages_detected.join(', ')) + '</td></tr>';
      if (pu.frameworks_detected) detailsHtml += '<tr><td class="k">Frameworks</td><td>' + escapeHtml(pu.frameworks_detected.join(', ')) + '</td></tr>';
      if (pu.withheld_reasons) detailsHtml += '<tr><td class="k warning">Withheld</td><td>' + escapeHtml(pu.withheld_material_count + ' items: ' + pu.withheld_reasons.join(', ')) + '</td></tr>';
      detailsHtml += '<tr><td class="k">Portfolio</td><td>' + escapeHtml(pu.portfolio_eligibility || 'unknown') + '</td></tr>';
      detailsHtml += '<tr><td class="k">Approval</td><td>' + escapeHtml(pu.approval_status || 'unknown') + '</td></tr>';
      detailsHtml += '</table>';
      udEl.innerHTML = detailsHtml;
    }
  }
}

// ── Lane X0 Phase 2: Render project studio from surface state studies ──
function _renderStudioFromStateStudies(studies) {
  var usEl = document.getElementById('understanding-status');
  if (usEl && studies.length > 0) {
    var s = studies[0];
    _clearEl(usEl);
    var line = _makeEl('span', 'status-line');
    line.appendChild(_tn('Study status: '));
    line.appendChild(_strong(s.study_status || 'unknown'));
    usEl.appendChild(line);
    usEl.appendChild(_makeEl('br'));
    usEl.appendChild(_makeEl('span', 'status-detail', (s.facts_discovered || 0) + ' facts (' + (s.facts_with_provenance || 0) + ' with provenance) · ' + (s.draft_narrative_count || 0) + ' drafts (' + (s.draft_narrative_awaiting_approval || 0) + ' awaiting approval)'));
  }

  var udEl = document.getElementById('understanding-details');
  if (udEl && studies.length > 0) {
    var s = studies[0];
    _clearEl(udEl);
    var table = _makeEl('table', 'kv');
    if (s.languages_detected) table.appendChild(_row('Languages', s.languages_detected.join(', ')));
    if (s.frameworks_detected) table.appendChild(_row('Frameworks', s.frameworks_detected.join(', ')));
    if (s.withheld_reasons && s.withheld_reasons.length) {
      table.appendChild(_row('Withheld', (s.withheld_material_count || 0) + ' items: ' + s.withheld_reasons.join(', '), 'warning'));
    }
    table.appendChild(_row('Portfolio', s.portfolio_eligibility || 'unknown'));
    table.appendChild(_row('Approval', s.approval_status || 'unknown'));
    udEl.appendChild(table);
  }
}

function renderInferenceStudioSurface(fix) {
  // ── Lane X0 Phase 2: Surface state path (from adapter projection) ──
  if (fix && fix.trust && (fix.omlx_strategy || fix.omlx_disclosure)) {
    _renderInferenceFromState(fix);
    return;
  }

  // ── Legacy fixture path ──
  var lr = fix.local_runtime || {};
  var irEl = document.getElementById('inference-runtime-status');
  if (irEl) {
    renderStatusChip(irEl.querySelector('.status-chip') || irEl, lr.available ? 'available' : 'offline', (lr.available ? 'Runtime Available' : 'Runtime Offline'));
    var detail = irEl.querySelector('.status-detail');
    if (detail) setText(detail, (lr.available ? 'Local inference ready (' + escapeHtml(lr.runtime_kind || 'unknown') + ')' : 'No local runtime configured'));
  }

  var ts = fix.task_suitability || [];
  var tasksGrid = document.getElementById('inference-tasks');
  if (tasksGrid) {
    var taskHtml = '';
    ts.forEach(function(t) {
      var suitable = t.suitable;
      taskHtml += '<div class="task-card ' + (suitable ? 'suitable' : 'unsuitable') + '">' +
        '<div class="task-name">' + escapeHtml(t.task_kind) + '</div>' +
        '<div class="task-status">' + renderEvidenceTag(suitable ? 'proven' : 'claimed') + ' ' +
        (suitable ? 'JSON_OBJECT_FORMATTING_ONLY admitted' : escapeHtml(t.refusal_reason || 'Refused')) +
        '</div></div>';
    });
    tasksGrid.innerHTML = taskHtml;
  }

  var drafts = fix.drafts || [];
  var draftList = document.getElementById('inference-drafts');
  if (draftList) {
    var draftHtml = '<h3>Drafts (' + drafts.length + ')</h3>';
    if (drafts.length === 0) draftHtml += '<div class="draft-item">No drafts.</div>';
    drafts.forEach(function(d) {
      var needsApproval = d.requires_approval || d.output_disposition === 'review_required';
      draftHtml += '<div class="draft-item">' +
        '<strong>' + escapeHtml(d.task_kind) + '</strong>: ' + escapeHtml(d.draft_sha256 ? d.draft_sha256.substring(0, 16) + '...' : 'unknown') +
        ' <span class="evidence-tag ' + (needsApproval ? 'claimed' : 'proven') + '">' + (needsApproval ? 'review-required' : 'approved') + '</span>' +
        ' (' + (d.draft_byte_count || 0) + ' bytes)' +
        '</div>';
    });
    draftList.innerHTML = draftHtml;
  }

  var refusals = fix.refusal_explanations || [];
  var refusalList = document.getElementById('inference-refusals');
  if (refusalList) {
    var refHtml = '<h3>Refusals (' + refusals.length + ')</h3>';
    if (refusals.length === 0) {
      refHtml += '<div class="refusal-item" style="color:var(--text-secondary)">No refusals — all suitable tasks executed.</div>';
    } else {
      refusals.forEach(function(r) {
        refHtml += '<div class="refusal-item">' +
          '<strong>' + escapeHtml(r.task_kind) + '</strong>: ' + escapeHtml(r.refusal_reason || r.status) +
          ' (code: ' + escapeHtml(r.refusal_code || 'UNKNOWN') + ')' +
          '</div>';
      });
    }
    refusalList.innerHTML = refHtml;
  }
}

// ── Lane X0 Phase 2: Inference Studio surface state renderer ──
function _renderInferenceFromState(state) {
  var irEl = document.getElementById('inference-runtime-status');
  if (irEl) {
    if (state.status === 'unavailable' || state.status === 'deferred') {
      _clearEl(irEl);
      var chip = _makeEl('span', 'status-chip disconnected', 'Inference Unavailable');
      irEl.appendChild(chip);
    } else {
      var available = state.runtime_available;
      renderStatusChip(irEl.querySelector('.status-chip') || irEl, available ? 'available' : 'offline',
        available ? 'Runtime Available' : 'Runtime Offline');
      var detail = irEl.querySelector('.status-detail');
      if (detail) setText(detail, (available ? 'Local inference ready (' + escapeHtml(state.runtime_kind || 'unknown') + ')' : 'No local runtime configured'));
    }
  }

  // OMLX disclosure
  var omlxEl = document.getElementById('inference-tasks');
  if (omlxEl) {
    var omlxDisclosure = state.omlx_disclosure || 'OMLX Rigged runtime expansion is pending X2 integration milestone.';
    var omlxStrategy = state.omlx_strategy || 'post_v1';
    var omlxAvailable = state.omlx_available || false;
    _clearEl(omlxEl);
    var taskCard = _makeEl('div', 'task-card ' + (omlxAvailable ? 'suitable' : 'unsuitable'));
    taskCard.appendChild(_makeEl('div', 'task-name', 'OMLX Expansion'));
    var taskStatus = _makeEl('div', 'task-status');
    taskStatus.appendChild(_buildEvidenceTag(omlxAvailable ? 'proven' : 'planned'));
    taskStatus.appendChild(_tn(' Strategy: ' + omlxStrategy + '. ' + omlxDisclosure));
    taskCard.appendChild(taskStatus);
    omlxEl.appendChild(taskCard);
  }

  // Capability claims
  var draftsEl = document.getElementById('inference-drafts');
  if (draftsEl) {
    _clearEl(draftsEl);
    draftsEl.appendChild(_makeEl('h3', '', 'Capability Status'));
    var capTable = _makeEl('table', 'kv');
    capTable.appendChild(_row('Native Schema Claimed', state.native_schema_capability_claimed ? 'Yes' : 'No', state.native_schema_capability_claimed ? 'ok' : 'warning'));
    capTable.appendChild(_row('Native Schema Proven', state.native_schema_capability_proven ? 'Yes' : 'No', state.native_schema_capability_proven ? 'ok' : 'warning'));
    capTable.appendChild(_row('Grammar Claimed', state.grammar_capability_claimed ? 'Yes' : 'No', state.grammar_capability_claimed ? 'ok' : 'warning'));
    capTable.appendChild(_row('Grammar Proven', state.grammar_capability_proven ? 'Yes' : 'No', state.grammar_capability_proven ? 'ok' : 'warning'));
    capTable.appendChild(_row('Results', String(state.total_results || 0) + ' total (' + String(state.total_executed || 0) + ' executed, ' + String(state.total_refused || 0) + ' refused)'));
    capTable.appendChild(_row('Drafts Awaiting', String(state.drafts_awaiting_review || 0)));
    draftsEl.appendChild(capTable);
  }

  // Refusals
  var refusalList = document.getElementById('inference-refusals');
  if (refusalList) {
    var totalRefused = state.total_refused || 0;
    _clearEl(refusalList);
    refusalList.appendChild(_makeEl('h3', '', 'Runtime Refusals (' + String(totalRefused) + ')'));
    if (totalRefused === 0) {
      var noRef = _makeEl('div', 'refusal-item', 'No refusals recorded.');
      noRef.style.color = 'var(--text-secondary)';
      refusalList.appendChild(noRef);
    } else {
      refusalList.appendChild(_makeEl('div', 'refusal-item', String(totalRefused) + ' task proposals refused by runtime authority.'));
    }
  }
}

function renderPublishPreviewSurface(fix) {
  // ── Lane X0 Phase 2: Surface state path (from adapter projection) ──
  if (fix && fix.trust && (fix.operation_id || fix.last_result_status)) {
    _renderPublishFromState(fix);
    return;
  }

  // ── Legacy fixture path ──
  var pr = fix.publication_readiness || {};
  var readinessEl = document.getElementById('publish-readiness');
  if (readinessEl) {
    renderStatusChip(readinessEl.querySelector('.status-chip') || readinessEl, pr.can_publish ? 'ready' : 'deferred', pr.can_publish ? 'Ready to Publish' : 'Not Ready');
    var detail = readinessEl.querySelector('.status-detail');
    if (detail) {
      var detailText = pr.content_light_check_passed ? 'Content-light check: passed. ' : 'Content-light check: NOT passed! ';
      detailText += pr.public_safety_check_passed ? 'Public safety: passed. ' : 'Public safety: NOT passed! ';
      if (pr.blockers && pr.blockers.length) detailText += 'Blockers: ' + pr.blockers.join('; ') + '.';
      setText(detail, detailText);
    }
  }

  var pc = fix.profile_candidate || {};
  var sectionsGrid = document.getElementById('publish-sections');
  if (sectionsGrid) {
    var sectionsHtml = '';
    (pc.public_sections || []).forEach(function(s) {
      sectionsHtml += '<div class="section-card ' + (s.ready ? 'ready' : 'not-ready') + '">' +
        '<strong>' + escapeHtml(s.title) + '</strong> ' + renderEvidenceTag(s.status) +
        (s.reason ? '<br><span class="status-detail" style="font-size:0.7rem">' + escapeHtml(s.reason) + '</span>' : '') +
        '</div>';
    });
    sectionsGrid.innerHTML = sectionsHtml;
  }

  var withheldEl = document.getElementById('publish-withheld');
  if (withheldEl) {
    var withheldHtml = '<h3>Withheld from Public Preview</h3>';
    if (pc.withoutheld_sections) {
      pc.withheld_sections.forEach(function(w) {
        withheldHtml += '<div class="withheld-item"><strong>' + escapeHtml(w.section_id) + '</strong>: ' + escapeHtml(w.reason) + ' (' + escapeHtml(w.privacy_class) + ')</div>';
      });
    } else {
      withheldHtml += '<div class="withheld-item">No explicitly withheld sections.</div>';
    }
    withheldHtml += '<div class="withheld-item" style="margin-top:8px;color:var(--text-muted)">Any section not in public_sections above is withheld by default. Private/internal-only material is never rendered in this preview.</div>';
    withheldEl.innerHTML = withheldHtml;
  }
}

// ── Lane X0 Phase 2: Publish Preview surface state renderer ──
function _renderPublishFromState(state) {
  var readinessEl = document.getElementById('publish-readiness');
  if (readinessEl) {
    if (state.status === 'unavailable') {
      _clearEl(readinessEl);
      var chip = _makeEl('span', 'status-chip deferred', 'Not Available');
      readinessEl.appendChild(chip);
      readinessEl.appendChild(_makeEl('div', 'status-detail', 'Publish service unavailable. ' + (state.reason || 'No live projection received.')));
    } else {
      var lastStatus = state.last_result_status || 'none';
      var canPublish = (state.publishable_repository_count || 0) > 0 || (state.publishable_repositories && state.publishable_repositories.length > 0);
      renderStatusChip(readinessEl.querySelector('.status-chip') || readinessEl, canPublish ? 'available' : 'deferred',
        canPublish ? 'Preview Available' : 'Not Ready');
      var detail = readinessEl.querySelector('.status-detail');
      if (detail) {
        var detailText = 'Last result: ' + escapeHtml(lastStatus) + '. ';
        detailText += escapeHtml(String(state.publishable_repository_count || 0)) + ' repositories publishable.';
        if (state.operation_id) detailText += ' \u00B7 Op: ' + escapeHtml(state.operation_id);
        setText(detail, detailText);
      }
    }
  }

  // Preview result / refusal
  var sectionsGrid = document.getElementById('publish-sections');
  if (sectionsGrid) {
    if (state.status === 'unavailable') {
      _clearEl(sectionsGrid);
      var noCard = _makeEl('div', 'section-card not-ready');
      noCard.appendChild(_strong('No sections'));
      noCard.appendChild(_tn(' '));
      noCard.appendChild(_buildEvidenceTag('planned'));
      sectionsGrid.appendChild(noCard);
    } else {
      _clearEl(sectionsGrid);
      var hasContent = false;
      if (state.preview_result) {
        var prCard = _makeEl('div', 'section-card ready');
        prCard.appendChild(_strong('Preview Result'));
        prCard.appendChild(_tn(' '));
        prCard.appendChild(_buildEvidenceTag('proven'));
        var prBr = _makeEl('br');
        prCard.appendChild(prBr);
        var prDetail = _makeEl('span', 'status-detail', (state.preview_result.status || '') + ' · ' + (state.preview_result.summary || ''));
        prDetail.style.fontSize = '0.7rem';
        prCard.appendChild(prDetail);
        sectionsGrid.appendChild(prCard);
        hasContent = true;
      }
      if (state.refusal) {
        var refCard = _makeEl('div', 'section-card not-ready');
        refCard.appendChild(_strong('Refusal'));
        refCard.appendChild(_tn(' '));
        refCard.appendChild(_buildEvidenceTag('refused'));
        var refBr = _makeEl('br');
        refCard.appendChild(refBr);
        var refDetail = _makeEl('span', 'status-detail', (state.refusal.reason || '') + ' (code: ' + (state.refusal.code || 'UNKNOWN') + ')');
        refDetail.style.fontSize = '0.7rem';
        refCard.appendChild(refDetail);
        sectionsGrid.appendChild(refCard);
        hasContent = true;
      }
      if (!hasContent) {
        sectionsGrid.appendChild(_makeEl('div', 'section-card not-ready', ''));
        sectionsGrid.lastChild.appendChild(_strong('No publishable sections'));
      }
    }
  }

  // Ledger summary
  var withheldEl = document.getElementById('publish-withheld');
  if (withheldEl) {
    _clearEl(withheldEl);
    withheldEl.appendChild(_makeEl('h3', '', 'Publication Ledger'));
    var totalEv = state.ledger_total_events || 0;
    var validRows = state.ledger_valid_rows || 0;
    var corruptRows = state.ledger_corrupt_rows || 0;
    var corrDetected = state.ledger_corruption_detected || false;

    var ledgerTable = _makeEl('table', 'kv');
    ledgerTable.appendChild(_row('Total events', String(totalEv)));
    ledgerTable.appendChild(_row('Valid rows', String(validRows), 'ok'));
    ledgerTable.appendChild(_row('Corrupt rows', String(corruptRows), corruptRows > 0 ? 'error' : 'ok'));
    ledgerTable.appendChild(_row('Corruption detected', corrDetected ? '⚠ Yes' : 'No', corrDetected ? 'error' : 'ok'));
    withheldEl.appendChild(ledgerTable);

    // Deployment status
    var depAvailable = state.deployment_available || false;
    var depReason = state.deployment_deferred_reason || 'Deployment not available in this release';
    withheldEl.appendChild(_makeEl('h3', '', 'Deployment'));
    var depDiv = _makeEl('div', 'status-detail');
    depDiv.appendChild(_buildEvidenceTag(depAvailable ? 'proven' : 'planned'));
    depDiv.appendChild(_tn(' '));
    depDiv.appendChild(_tn(depAvailable ? 'Deployment available' : depReason));
    withheldEl.appendChild(depDiv);

    var privNote = _makeEl('div', 'withheld-item', 'Private/internal-only material is never included in publication preview.');
    privNote.style.cssText = 'margin-top:8px;color:var(--text-muted)';
    withheldEl.appendChild(privNote);
  }
}

// ── Lane X0 Phase 2: Timeline History surface ──
function renderTimelineSurface(fix) {
  if (!fix) return;

  // ── Surface state path (from adapter projection) ──
  if (fix.trust && (fix.events || fix.event_count != null)) {
    _renderTimelineFromState(fix);
    return;
  }

  // ── Legacy fixture path ──
  var events = fix.timeline_events || [];
  var tlEvents = document.getElementById('timeline-events');
  if (tlEvents) {
    var html = '<h3>Timeline Events (' + (fix.event_count || events.length) + ')</h3>';
    if (events.length === 0) {
      html += '<div class="status-detail">No timeline events recorded.</div>';
    } else {
      html += '<div class="timeline-list">';
      events.forEach(function(ev) {
        var verificationCls = 'evidence-tag';
        switch (ev.verification_class) {
          case 'verified_canonical': verificationCls += ' proven'; break;
          case 'parsed_unverified': verificationCls += ' claimed'; break;
          case 'canonical_degraded': verificationCls += ' planned'; break;
          default: verificationCls += ' narrative';
        }
        html += '<div class="timeline-event-card">' +
          '<div class="timeline-event-domain">' + escapeHtml(ev.domain || 'unknown') + ' / ' + escapeHtml(ev.kind || '') + '</div>' +
          '<div class="timeline-event-label">' + escapeHtml(ev.label || ev.summary || '') + '</div>' +
          '<div class="timeline-event-meta">' +
          '<span class="' + verificationCls + '">' + escapeHtml(ev.verification_class || 'unverified') + '</span>' +
          ' \u00B7 ' + escapeHtml(ev.source || '') + ' \u00B7 ' + escapeHtml(ev.timestamp || '') +
          '</div></div>';
      });
      html += '</div>';
    }
    tlEvents.innerHTML = html;
  }

  var tlDegradation = document.getElementById('timeline-degradation');
  if (tlDegradation) {
    var canDeg = fix.canonical_degraded_count || 0;
    var corDeg = fix.corrupt_count || 0;
    var unsDeg = fix.unsupported_count || 0;
    var missDeg = fix.missing_count || 0;
    var contDeg = fix.contradictory_count || 0;
    var staleDeg = fix.stale_count || 0;
    var degHtml = '<h3>Degradation Summary</h3>';
    degHtml += '<table class="kv">' +
      '<tr><td class="k">Canonical degraded</td><td class="warning">' + canDeg + '</td></tr>' +
      '<tr><td class="k">Corrupt</td><td class="' + (corDeg > 0 ? 'error' : 'ok') + '">' + corDeg + '</td></tr>' +
      '<tr><td class="k">Unsupported</td><td>' + unsDeg + '</td></tr>' +
      '<tr><td class="k">Missing</td><td>' + missDeg + '</td></tr>' +
      '<tr><td class="k">Contradictory</td><td class="' + (contDeg > 0 ? 'error' : 'ok') + '">' + contDeg + '</td></tr>' +
      '<tr><td class="k">Stale</td><td class="' + (staleDeg > 0 ? 'warning' : 'ok') + '">' + staleDeg + '</td></tr>' +
      '</table>';
    tlDegradation.innerHTML = degHtml;
  }

  var tlDomains = document.getElementById('timeline-domains');
  if (tlDomains) {
    var domains = fix.domain_coverage || {};
    var domainKeys = Object.keys(domains);
    var domainHtml = '<h3>Domain Coverage</h3>';
    if (domainKeys.length > 0) {
      domainHtml += '<table class="kv">';
      domainKeys.forEach(function(k) {
        domainHtml += '<tr><td class="k">' + escapeHtml(k) + '</td><td>' + escapeHtml(String(domains[k])) + '</td></tr>';
      });
      domainHtml += '</table>';
    } else {
      domainHtml += '<div class="status-detail">No domain coverage data.</div>';
    }
    tlDomains.innerHTML = domainHtml;
  }
}

// ── Lane X0 Phase 2: Timeline surface state renderer ──
function _renderTimelineFromState(state) {
  var tlEvents = document.getElementById('timeline-events');
  if (tlEvents) {
    if (state.status === 'unavailable') {
      _clearEl(tlEvents);
      tlEvents.appendChild(_makeEl('div', 'status-detail', 'Timeline service unavailable. ' + (state.reason || 'No projection received.')));
    } else {
      _clearEl(tlEvents);
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
          card.appendChild(_makeEl('div', 'timeline-event-domain', (ev.domain || 'unknown') + ' / ' + (ev.event_kind || ev.kind || '')));
          card.appendChild(_makeEl('div', 'timeline-event-label', ev.label || ev.summary || ''));
          var meta = _makeEl('div', 'timeline-event-meta');
          meta.appendChild(_makeEl('span', verificationCls, ev.verification_class || 'unverified'));
          meta.appendChild(_tn(' · ' + (ev.source || '') + ' · ' + (ev.timestamp || ev.event_at || '')));
          card.appendChild(meta);
          tlList.appendChild(card);
        }
        tlEvents.appendChild(tlList);
      }
    }
  }

  // Degradation summary
  var tlDegradation = document.getElementById('timeline-degradation');
  if (tlDegradation) {
    var canDeg = state.canonical_degraded_count || 0;
    var corDeg = state.corrupt_count || 0;
    var unsDeg = state.unsupported_count || 0;
    var missDeg = state.missing_count || 0;
    var contDeg = state.contradictory_count || 0;
    var staleDeg = state.stale_count || 0;
    var totalDegraded = canDeg + corDeg + unsDeg + missDeg + contDeg + staleDeg;
    _clearEl(tlDegradation);
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
      errDiv.appendChild(_tn(assemblyErrors.join('; ')));
      tlDegradation.appendChild(errDiv);
    }
    if (assemblyWarnings.length > 0) {
      var warnDiv = _makeEl('div', 'status-detail');
      warnDiv.style.color = 'var(--warning-color)';
      warnDiv.appendChild(_strong('Assembly warnings: '));
      warnDiv.appendChild(_tn(assemblyWarnings.join('; ')));
      tlDegradation.appendChild(warnDiv);
    }
  }

  // Domain coverage
  var tlDomains = document.getElementById('timeline-domains');
  if (tlDomains) {
    var domains = state.domain_coverage || {};
    var unsupportedDomains = state.unsupported_domains || [];
    var verifiedCanonical = state.verified_canonical_count || 0;
    var parsedUnverified = state.parsed_unverified_count || 0;
    _clearEl(tlDomains);
    tlDomains.appendChild(_makeEl('h3', '', 'Domain Coverage'));
    var domainKeys = Object.keys(domains);
    if (domainKeys.length > 0) {
      var domTable = _makeEl('table', 'kv');
      for (var d = 0; d < domainKeys.length; d++) {
        var domainKey = domainKeys[d];
        domTable.appendChild(_row(domainKey, String(domains[domainKey])));
      }
      tlDomains.appendChild(domTable);
    }
    tlDomains.appendChild(_makeEl('div', 'status-detail', String(verifiedCanonical) + ' verified canonical · ' + String(parsedUnverified) + ' parsed unverified · ' + String(unsupportedDomains.length) + ' unsupported domains'));
    if (unsupportedDomains.length > 0) {
      var unsupDiv = _makeEl('div', 'status-detail', 'Unsupported: ' + unsupportedDomains.join(', '));
      unsupDiv.style.color = 'var(--warning-color)';
      tlDomains.appendChild(unsupDiv);
    }
  }
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
  setText(wsStatus, _appAuthority.isConnected() ? 'Connected' : 'Disconnected');
  setText(bridgeStatus, window.pywebview && window.pywebview.api ? 'Available' : 'Unavailable');

  if (wsPill) {
    if (_appAuthority.isConnected()) {
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

  if (wsClient && _appAuthority.isConnected()) {
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
  if (wsClient && _appAuthority.isConnected()) {
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

  if (wsClient && _appAuthority.isConnected()) {
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

  if (wsClient && _appAuthority.isConnected()) {
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

  // Show auth URL if present — offer in-app browser or system browser
  var extra = result.extra_fields || {};
  if (extra.auth_url && extra.loopback_port) {
    html += '<div class="detail-line">';
    var providerName = extra.provider || 'github';
    html += '<button class="auth-btn" onclick="window.RigRelay.openInAppAuth(\'' + escapeHtml(extra.auth_url) + '\', ' + escapeHtml(String(extra.loopback_port)) + ', \'' + escapeHtml(extra.state_hash || '') + '\', \'' + escapeHtml(providerName) + '\')">Sign in in-app</button>';
    html += ' <a href="' + escapeHtml(extra.auth_url) + '" target="_blank" class="auth-link">Open system browser</a>';
    html += '</div>';
    html += '<div class="detail-line small-note">Or copy the code from the provider page and paste below:</div>';
    html += '<div class="detail-line"><input id="oauth-code-input" type="text" placeholder="Paste authorization code here" style="width:60%"> ';
    html += '<button onclick="window.RigRelay.submitOAuthCode()">Submit</button></div>';
  } else if (extra.auth_url) {
    html += '<div class="detail-line"><a href="' + escapeHtml(extra.auth_url) + '" target="_blank" class="auth-link">Open browser to sign in</a></div>';
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
      displayOperateIntentResult(message.data || message.result || message);
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

async function initWebSocket() {
  if (typeof ProjectionWebSocketClient === 'undefined') return;

  const urlParams = new URLSearchParams(window.location.search);
  const wsConfig = window.pywebview && window.pywebview.api && window.pywebview.api.get_runtime_config
    ? await window.pywebview.api.get_runtime_config()
    : {
        ws_url: deriveWebSocketUrl({
          pageProtocol: window.location.protocol,
          host: window.location.hostname || '127.0.0.1',
          port: parseInt(urlParams.get('ws_port')) || 9876,
        }),
        token: urlParams.get('ws_token') || '',
        handshake_id: window.__RIG_RELAY_RUNTIME_CONFIG__ && window.__RIG_RELAY_RUNTIME_CONFIG__.handshake_id
          ? window.__RIG_RELAY_RUNTIME_CONFIG__.handshake_id
          : ''
      };

  wsClient = new ProjectionWebSocketClient({
    wsUrl: wsConfig.ws_url || deriveWebSocketUrl({
      pageProtocol: window.location.protocol,
      host: window.location.hostname || '127.0.0.1',
      port: parseInt(urlParams.get('ws_port')) || 9876,
    }),
    token: wsConfig.token,
    handshakeId: wsConfig.handshake_id || wsConfig.handshakeId || '',
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
        _appAuthority.dispatch('auth_ok', {
          reason: 'websocket authenticated',
          ws_url: wsConfig.ws_url,
        });
        renderStatusBar();
        wsClient.sendMessage({ type: 'get_chat_state' });
      } else if (status === 'offline' || status === 'auth_failed') {
        _appAuthority.dispatch(
          status === 'auth_failed' ? 'auth_failed' : 'websocket_close',
          { reason: detail || status, ws_url: wsConfig.ws_url }
        );
        renderStatusBar();
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

function deriveWebSocketUrl({ pageProtocol, host, port, explicitUrl } = {}) {
  if (explicitUrl) return explicitUrl;
  const scheme = pageProtocol === 'https:' ? 'wss' : 'ws';
  const resolvedHost = host || '127.0.0.1';
  const resolvedPort = port || 9876;
  return `${scheme}://${resolvedHost}:${resolvedPort}`;
}

// ── S1: Global bridge for HTML inline handlers and keyboard nav ──────
// Module-scoped functions exposed on window for backward compatibility
// with inline onclick handlers and the keyboard navigation module.
window.switchSurface = switchSurface;
window.showCockpit = showCockpit;
window.switchMode = switchMode;
window.emitP0Intent = emitP0Intent;
window.renderProjection = renderProjection;
window.setWidgetHTML = setWidgetHTML;
window.escapeHtml = escapeHtml;
window.setStatusChip = renderStatusChip;
window.renderEvidenceTag = renderEvidenceTag;
window.runIntent = runIntent;
window.renderSurfaceFixture = renderSurfaceFixture;
window.renderTimelineSurface = renderTimelineSurface;

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

  // Surface tab listeners
  document.querySelectorAll('#surface-nav .surface-tab').forEach(function(tab) {
    tab.addEventListener('click', function() {
      var surface = this.getAttribute('data-surface');
      if (!surface) return;
      if (this.classList.contains('active')) {
        showCockpit();
      } else {
        switchSurface(surface);
      }
    });
  });

  // Start with cockpit visible, deactivate hardcoded surface active class
  showCockpit();

  // Init
  if (typeof ProjectionWebSocketClient !== 'undefined') {
    initWebSocket();
  } else {
    loadFromBridge();
  }

  // Periodic refresh
  setInterval(async function() {
    const wsConfig = window.pywebview && window.pywebview.api && window.pywebview.api.get_runtime_config
      ? await window.pywebview.api.get_runtime_config()
      : null;
    if (!_appAuthority.isConnected() && window.pywebview && window.pywebview.api) {
      loadFromBridge();
    }
  }, 10000);
});

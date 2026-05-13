// Rig Relay Desktop Cockpit — Read-Only Frontend
// Receives content-light projection from WebSocket stream or pywebview JS bridge.
// No mutation authority.

// Connection state
let wsClient = null;
let wsConnected = false;

function renderProjection(projection) {
  // Header info
  const versionEl = document.getElementById('version-badge');
  versionEl.textContent = 'v' + projection.app_version;

  const avail = projection.source_status;
  const availableCount = Object.values(avail).filter(Boolean).length;
  const totalCount = Object.keys(avail).length;
  const statusEl = document.getElementById('source-status');
  statusEl.textContent = availableCount + '/' + totalCount + ' sources';
  statusEl.className = 'source-status ' + (availableCount === totalCount ? 'ok' : 'warning');

  // Connection indicator
  const connEl = document.getElementById('connection-status');
  if (wsConnected) {
    connEl.textContent = 'WS';
    connEl.className = 'source-status ok';
    connEl.title = 'Connected via WebSocket projection stream';
  } else if (window.pywebview && window.pywebview.api) {
    connEl.textContent = 'Bridge';
    connEl.className = 'source-status ok';
    connEl.title = 'Connected via pywebview JS bridge';
  } else {
    connEl.textContent = 'Offline';
    connEl.className = 'source-status warning';
    connEl.title = 'No active connection';
  }

  // Warning banner
  const warnBanner = document.getElementById('warning-banner');
  if (projection.warnings && projection.warnings.length > 0) {
    warnBanner.style.display = 'block';
    warnBanner.innerHTML = '<strong>Warnings:</strong><ul>' +
      projection.warnings.map(w => '<li>' + escapeHtml(w) + '</li>').join('') + '</ul>';
  } else {
    warnBanner.style.display = 'none';
  }

  // Render each category
  renderCurrentState(projection.current_state);
  renderQueue(projection.queue);
  renderDataset(projection.dataset);
  renderSemanticSnippets(projection.semantic_snippets);
  renderTelemetryBundle(projection.telemetry_bundle);
  renderUpdate(projection.update);
}

function renderCurrentState(data) {
  const el = document.getElementById('content-current_state');
  if (!data || !data.available) {
    el.innerHTML = '<span class="missing">Not generated yet.</span>';
    return;
  }
  el.innerHTML = '<table class="kv">' +
    row('Active Children', data.active_children) +
    row('Max Children', data.max_children) +
    row('Available Slots', data.available_child_slots) +
    row('Active Writers', data.active_writers) +
    row('Active Readers', data.active_readers) +
    row('Conflicts', data.conflicts, data.conflicts > 0 ? 'error' : '') +
    row('Stale Leases', data.stale_leases, data.stale_leases > 0 ? 'warning' : '') +
    row('Checkpoint Commits', data.checkpoint_commits) +
    row('Checkpoint Refusals', data.checkpoint_refusals, data.checkpoint_refusals > 0 ? 'warning' : '') +
    '</table>';
}

function renderQueue(data) {
  const el = document.getElementById('content-queue');
  if (!data || !data.available) {
    el.innerHTML = '<span class="missing">Not generated yet.</span>';
    return;
  }
  el.innerHTML = '<table class="kv">' +
    row('Ready Items', data.ready_items) +
    row('Blocked Items', data.blocked_items, data.blocked_items > 0 ? 'warning' : '') +
    row('Waiting Items', data.waiting_items) +
    row('Total Items', data.total_items) +
    '</table>';
}

function renderDataset(data) {
  const el = document.getElementById('content-dataset');
  if (!data || !data.available) {
    el.innerHTML = '<span class="missing">Not generated yet.</span>';
    return;
  }
  el.innerHTML = '<table class="kv">' +
    row('Sessions Observed', data.sessions_observed) +
    row('Coordination Events', data.coordination_events_total) +
    row('Tool Calls', data.tool_calls_total) +
    row('Coordination Rows', data.coordination_rows) +
    row('Tool Failure Rows', data.tool_failure_rows) +
    row('Provider Perf Rows', data.provider_perf_rows) +
    row('Findings Rows', data.findings_rows) +
    row('Artifact Reuse Rows', data.artifact_reuse_rows) +
    row('Checkpoint Rows', data.checkpoint_rows) +
    row('Skipped Events', data.skipped_event_count, data.skipped_event_count > 0 ? 'warning' : '') +
    row('Strict Mode', data.strict ? 'Yes' : 'No') +
    row('Datasets Generated', data.datasets_generated ? 'Yes' : 'No') +
    '</table><div class="small-note">Exported: ' + (data.exported_at || 'unknown') + '</div>';
}

function renderSemanticSnippets(data) {
  const el = document.getElementById('content-semantic_snippets');
  if (!data || !data.available) {
    el.innerHTML = '<span class="missing">Not generated yet.</span>';
    return;
  }
  el.innerHTML = '<table class="kv">' +
    row('Snippet Count', data.snippet_count) +
    row('Skipped', data.skipped_count) +
    row('Forbidden', data.forbidden_count, data.forbidden_count > 0 ? 'error' : '') +
    row('Strict Mode', data.strict_mode ? 'Yes' : 'No') +
    row('Remote Sharing Safe', data.remote_sharing_safe ? 'Yes' : 'No') +
    '</table><div class="small-note">Created: ' + (data.created_at || 'unknown') + '</div>';
}

function renderTelemetryBundle(data) {
  const el = document.getElementById('content-telemetry_bundle');
  if (!data || !data.available) {
    el.innerHTML = '<span class="missing">Not generated yet.</span>';
    return;
  }
  el.innerHTML = '<table class="kv">' +
    row('Bundle ID', data.bundle_id) +
    row('Share Level', data.share_level) +
    row('Status', data.status) +
    row('SHA256', (data.bundle_sha256 || '').substring(0, 16) + '...') +
    '</table><div class="small-note">Created: ' + (data.created_at || 'unknown') + '</div>';
}

function renderUpdate(data) {
  const el = document.getElementById('content-update');
  if (!data || !data.available) {
    el.innerHTML = '<span class="missing">Not available.</span>';
    return;
  }
  const hasUpdate = data.update_available;
  el.innerHTML = '<table class="kv">' +
    row('Current', data.current_version) +
    row('Latest', data.latest_version) +
    row('Update Available', hasUpdate ? '<span class="ok">Yes</span>' : 'No') +
    row('State', data.update_state) +
    row('Restart Required', data.restart_required ? '<span class="warning">Yes</span>' : 'No') +
    row('Restart Safe', data.restart_safe ? 'Yes' : 'No') +
    row('Blocked By Sessions', data.blocked_by_active_sessions, data.blocked_by_active_sessions > 0 ? 'warning' : '') +
    '</table>';
}

// Helper: escape HTML entities
function escapeHtml(str) {
  if (typeof str !== 'string') return String(str);
  return str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

// Helper: key-value table row
function row(key, value, cls) {
  const valStr = value === null || value === undefined ? '—' : String(value);
  const clsAttr = cls ? ' class="' + cls + '"' : '';
  return '<tr><td class="k">' + escapeHtml(key) + '</td><td' + clsAttr + '>' + valStr + '</td></tr>';
}

async function refreshAll() {
  const btn = document.getElementById('refresh-btn');
  btn.disabled = true;
  btn.textContent = 'Refreshing...';

  try {
    if (wsConnected && wsClient) {
      wsClient.requestProjection();
    } else if (window.pywebview && window.pywebview.api) {
      const projection = await window.pywebview.api.get_projection();
      renderProjection(projection);
    } else {
      document.querySelectorAll('.card-content').forEach(el => {
        el.innerHTML = '<span class="missing">No active connection. Open via cockpit or start WebSocket server.</span>';
      });
    }
  } catch (e) {
    document.querySelectorAll('.card-content').forEach(el => {
      el.innerHTML = '<span class="error">Error: ' + escapeHtml(e.message) + '</span>';
    });
  } finally {
    btn.disabled = false;
    btn.textContent = 'Refresh';
  }
}

// Set up WebSocket connection
function initWebSocket() {
  wsClient = new ProjectionWebSocketClient({
    wsUrl: 'ws://127.0.0.1:9876',
    onProjection: (data) => {
      wsConnected = true;
      renderProjection(data);
    },
    onStatusChange: (status, delay, attempt) => {
      const connEl = document.getElementById('connection-status');
      switch (status) {
        case 'connected':
          wsConnected = true;
          connEl.textContent = 'WS';
          connEl.className = 'source-status ok';
          connEl.title = 'Connected via WebSocket projection stream';
          break;
        case 'disconnected':
          wsConnected = false;
          connEl.textContent = 'WS Disconnected';
          connEl.className = 'source-status warning';
          connEl.title = 'WebSocket disconnected';
          break;
        case 'reconnecting':
          connEl.textContent = 'WS Reconnect (' + attempt + ')';
          connEl.className = 'source-status warning';
          connEl.title = 'Reconnecting in ' + delay + 'ms';
          break;
        case 'closed':
          wsConnected = false;
          break;
      }
    },
    onError: (message) => {
      console.warn('WebSocket:', message);
    }
  });
}

// Try WebSocket on page ready; fall back to pywebview JS bridge
document.addEventListener('DOMContentLoaded', () => {
  // Try WebSocket first
  if (typeof ProjectionWebSocketClient !== 'undefined') {
    initWebSocket();
  }

  // If no pywebview and no WS after 2s, show offline state
  setTimeout(() => {
    if (!wsConnected && !(window.pywebview && window.pywebview.api)) {
      const connEl = document.getElementById('connection-status');
      connEl.textContent = 'Offline';
      connEl.className = 'source-status warning';
      connEl.title = 'No active connection';
    }
  }, 2000);
});

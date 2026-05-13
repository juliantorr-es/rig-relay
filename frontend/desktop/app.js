// Rig Relay Cockpit Frontend Logic
let wsClient = null;
let wsConnected = false;
let wsAuthFailed = false;

let chatState = {
  messages: [],
  backend_wired: false,
  pending_response: false
};

// --- Projection Rendering ---

function renderProjection(data) {
  if (!data) return;

  // Version
  document.getElementById('version-badge').textContent = (data.alpha_label || 'Alpha') + ' ' + (data.app_version || '');

  // Cards
  renderCurrentState(data.current_state);
  renderQueue(data.queue);
  renderDataset(data.dataset);
  renderSemanticSnippets(data.semantic_snippets);
  renderTelemetryBundle(data.telemetry_bundle);
  renderUpdate(data.update);

  // Connection status (managed by WS client or loadFromBridge)
}

function renderCurrentState(data) {
  const el = document.getElementById('content-current_state');
  const status = document.getElementById('status-current_state');
  if (!data || !data.available) {
    el.innerHTML = '<span class="missing">Not generated yet. Run: coord status</span>';
    status.className = 'source-status warning';
    status.textContent = 'Wait';
    return;
  }
  status.className = 'source-status ok';
  status.textContent = 'OK';
  el.innerHTML = '<table class="kv">' +
    row('Session ID', (data.session_id || '').substring(0, 16) + '...') +
    row('Provider', data.provider_id) +
    row('Model', data.model_id) +
    row('Role', data.agent_role) +
    row('Files Changed', data.files_changed_count) +
    row('Tool Calls', data.tool_calls_count) +
    '</table><div class="small-note">Updated: ' + (data.updated_at || 'unknown') + '</div>';
}

function renderQueue(data) {
  const el = document.getElementById('content-queue');
  const status = document.getElementById('status-queue');
  if (!data || !data.available) {
    el.innerHTML = '<span class="missing">Not generated yet. Run: queue plan</span>';
    status.className = 'source-status warning';
    status.textContent = 'Wait';
    return;
  }
  status.className = 'source-status ok';
  status.textContent = 'OK';
  el.innerHTML = '<table class="kv">' +
    row('Plan ID', (data.plan_id || '').substring(0, 16) + '...') +
    row('Ready', data.ready_count, data.ready_count > 0 ? 'ok' : '') +
    row('Blocked', data.blocked_count, data.blocked_count > 0 ? 'warning' : '') +
    row('Waiting', data.waiting_count) +
    row('Completed', data.completed_count) +
    '</table><div class="small-note">Planned: ' + (data.planned_at || 'unknown') + '</div>';
}

function renderDataset(data) {
  const el = document.getElementById('content-dataset');
  const status = document.getElementById('status-dataset');
  if (!data || !data.available) {
    el.innerHTML = '<span class="missing">Not exported yet.</span>';
    status.className = 'source-status warning';
    status.textContent = 'Wait';
    return;
  }
  status.className = 'source-status ok';
  status.textContent = 'OK';
  el.innerHTML = '<table class="kv">' +
    row('Rows', data.row_count) +
    row('Sources', data.source_count) +
    row('Size', data.size_bytes ? (data.size_bytes / 1024).toFixed(1) + ' KiB' : '0') +
    '</table><div class="small-note">Exported: ' + (data.exported_at || 'unknown') + '</div>';
}

function renderSemanticSnippets(data) {
  const el = document.getElementById('content-semantic_snippets');
  const status = document.getElementById('status-semantic_snippets');
  if (!data || !data.available) {
    el.innerHTML = '<span class="missing">Not generated yet.</span>';
    status.className = 'source-status warning';
    status.textContent = 'Wait';
    return;
  }
  status.className = 'source-status ok';
  status.textContent = 'OK';
  el.innerHTML = '<table class="kv">' +
    row('Snippets', data.snippet_count) +
    row('Skipped', data.skipped_count) +
    row('Strict Mode', data.strict_mode ? 'Yes' : 'No') +
    '</table><div class="small-note">Created: ' + (data.created_at || 'unknown') + '</div>';
}

function renderTelemetryBundle(data) {
  const el = document.getElementById('content-telemetry_bundle');
  const status = document.getElementById('status-telemetry_bundle');
  if (!data || !data.available) {
    el.innerHTML = '<span class="missing">Not generated yet.</span>';
    status.className = 'source-status warning';
    status.textContent = 'Wait';
    return;
  }
  status.className = 'source-status ok';
  status.textContent = 'OK';
  el.innerHTML = '<table class="kv">' +
    row('Bundle ID', (data.bundle_id || '').substring(0, 16) + '...') +
    row('Status', data.status) +
    row('Share', data.share_level) +
    '</table><div class="small-note">Created: ' + (data.created_at || 'unknown') + '</div>';
}

function renderUpdate(data) {
  const el = document.getElementById('content-update');
  const status = document.getElementById('status-update');
  if (!data || !data.available) {
    el.innerHTML = '<span class="missing">Not available.</span>';
    status.className = 'source-status warning';
    status.textContent = 'Wait';
    return;
  }
  status.className = 'source-status ok';
  status.textContent = 'OK';
  const hasUpdate = data.update_available;
  el.innerHTML = '<table class="kv">' +
    row('Current', data.current_version) +
    row('Latest', data.latest_version) +
    row('Update', hasUpdate ? '<span class="ok">Yes</span>' : 'No') +
    '</table>';
}

// --- Chat Rendering ---

function renderChat(state) {
  if (!state) return;
  chatState = state;

  const badge = document.getElementById('chat-status-badge');
  if (state.backend_wired) {
    badge.textContent = 'Backend Online';
    badge.className = 'source-status ok';
  } else {
    badge.textContent = 'Backend Offline';
    badge.className = 'source-status warning';
  }

  const transcript = document.getElementById('chat-transcript');
  transcript.innerHTML = '';
  
  if (state.messages.length === 0) {
    transcript.innerHTML = '<div class="message system">No messages yet.</div>';
  }

  state.messages.forEach(msg => {
    const msgEl = document.createElement('div');
    msgEl.className = 'message ' + msg.role.toLowerCase();
    if (msg.status) msgEl.classList.add(msg.status);
    
    // SAFE RENDERING: use textContent
    msgEl.textContent = msg.content;
    
    transcript.appendChild(msgEl);
  });
  
  transcript.scrollTop = transcript.scrollHeight;
}

async function sendMessage() {
  const input = document.getElementById('chat-input');
  const text = input.value.trim();
  if (!text) return;

  const sendBtn = document.getElementById('send-btn');
  sendBtn.disabled = true;
  input.disabled = true;

  try {
    if (window.pywebview && window.pywebview.api) {
      const clientMessageId = Date.now().toString();
      const newState = await window.pywebview.api.send_chat_message(text, clientMessageId);
      if (newState.error) {
        console.warn('Backend error:', newState.error);
        // Show as a system message instead of alert
        const transcript = document.getElementById('chat-transcript');
        const errEl = document.createElement('div');
        errEl.className = 'message system error';
        errEl.textContent = 'Error: ' + newState.error;
        transcript.appendChild(errEl);
        transcript.scrollTop = transcript.scrollHeight;
      } else {
        renderChat(newState);
        input.value = '';
        updateCharCount();
      }
    } else {
      console.warn('Bridge not available');
    }
  } catch (e) {
    console.error('Failed to send message:', e);
  } finally {
    sendBtn.disabled = false;
    input.disabled = false;
    input.focus();
  }
}

async function clearChat() {
  if (window.pywebview && window.pywebview.api) {
    const newState = await window.pywebview.api.clear_chat_view();
    renderChat(newState);
  }
}

function updateCharCount() {
  const input = document.getElementById('chat-input');
  const count = input.value.length;
  const countEl = document.getElementById('char-count');
  countEl.textContent = count + '/4000';
  
  const sendBtn = document.getElementById('send-btn');
  sendBtn.disabled = count === 0 || count > 4000;
}

// --- Helpers ---

function escapeHtml(str) {
  if (typeof str !== 'string') return String(str);
  return str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

function row(key, value, cls) {
  const valStr = value === null || value === undefined ? '—' : String(value);
  const clsAttr = cls ? ' class="' + cls + '"' : '';
  return '<tr><td class="k">' + escapeHtml(key) + '</td><td' + clsAttr + '>' + valStr + '</td></tr>';
}

// --- Main Loop ---

async function runIntent(intentName) {
  const resultEl = document.getElementById('intent-result');
  resultEl.textContent = 'Running ' + intentName + '...';
  resultEl.className = 'intent-result pending';

  const intentId = Date.now().toString(36) + '_' + Math.random().toString(36).substring(2, 10);
  const request = {
    type: 'desktop_intent',
    schema_version: 'rig.relay.desktop_intent_request.v1',
    intent_id: intentId,
    created_at: new Date().toISOString(),
    intent_name: intentName,
    parameters: {},
    dry_run: true,
  };

  try {
    // Try WebSocket first
    if (wsConnected && wsClient) {
      wsClient.sendMessage(request);
      // Result comes back as a separate message, set up a one-time handler
      const origOnMessage = wsClient.onMessage;
      wsClient.onMessage = (msg) => {
        if (msg.type === 'desktop_intent_result' && msg.data && msg.data.intent_name === intentName) {
          displayIntentResult(msg.data);
          wsClient.onMessage = origOnMessage;
        } else if (origOnMessage) {
          origOnMessage(msg);
        }
      };
      // Fallback: if no response in 10s, show pending
      setTimeout(() => {
        if (resultEl.textContent === 'Running ' + intentName + '...') {
          resultEl.textContent = 'Intent sent via WebSocket, waiting for response...';
        }
      }, 10000);
    } else if (window.pywebview && window.pywebview.api) {
      const result = await window.pywebview.api.run_desktop_intent(request);
      displayIntentResult(result);
    } else {
      resultEl.textContent = 'No WebSocket or pywebview bridge available.';
      resultEl.className = 'intent-result error';
    }
  } catch (e) {
    resultEl.textContent = 'Error: ' + e.message;
    resultEl.className = 'intent-result error';
  }
}

function displayIntentResult(result) {
  const resultEl = document.getElementById('intent-result');
  if (!result) {
    resultEl.textContent = 'No result returned.';
    resultEl.className = 'intent-result error';
    return;
  }
  const status = result.status || 'unknown';
  const kind = result.result_kind || 'summary';
  const summary = result.summary || 'No summary.';
  const warnings = result.warnings || [];
  const outputRefs = result.output_refs || [];
  let html = '<div class="status-line">' + escapeHtml(status.toUpperCase()) + '</div>';
  // Structured card per result kind
  html += renderStructuredCard(kind, summary, result);
  if (warnings.length > 0) {
    html += '<div class="small-note">Warnings: ' + escapeHtml(warnings.join('; ')) + '</div>';
  }
  if (outputRefs.length > 0) {
    html += '<div class="small-note">Artifacts: ' + escapeHtml(outputRefs.join(', ')) + '</div>';
  }
  if (result.projection_refresh_recommended) {
    html += '<div class="small-note">Projection refresh recommended.</div>';
  }
  resultEl.innerHTML = html;
  resultEl.className = 'intent-result ' + (status === 'completed' ? 'ok' : status === 'refused' ? 'warning' : 'error');
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
    case 'summary':
    default:
      return '<div class="detail-line">' + escapeHtml(summary) + '</div>';
  }
}

function renderValidationSuiteCard(summary) {
  // Format: "Validation suite 'name': status. N executed, M skipped. Steps: [kind:status; ...]. sha256: hash"
  const m = summary.match(/Validation suite '(.+?)':\s*(\w+)\.\s*(\d+)\s+executed,\s*(\d+)\s+skipped\.\s*Steps:\s*\[(.+?)\]\s*\.\s*sha256:\s*(\S+)/);
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
  // Format: "Storage audit: X.X MB, budget=status, stale_leases=N, rollup_candidates=M, prune_candidates=P, R recommendations."
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
  // Format: "Refinement report generated: N backlog items."
  var m = summary.match(/(\d+)\s+backlog items/);
  if (!m) return '<div class="detail-line">' + escapeHtml(summary) + '</div>';
  return '<table class="kv">' +
    row('Backlog Items', m[1]) +
    row('Summary', summary) +
    '</table>';
}

function renderPacketsCard(summary) {
  // Format: "Refinement packets: N packets (dry-run)."
  var m = summary.match(/(\d+)\s+packets/);
  if (!m) return '<div class="detail-line">' + escapeHtml(summary) + '</div>';
  return '<table class="kv">' +
    row('Packets Created', m[1]) +
    row('Mode', 'dry-run') +
    '</table>';
}

function renderProjectionCard(summary) {
  // Format: "Projection rebuilt: N/M sources available."
  var m = summary.match(/(\d+)\/(\d+)\s+sources/);
  if (!m) return '<div class="detail-line">' + escapeHtml(summary) + '</div>';
  return '<table class="kv">' +
    row('Sources', m[1] + ' / ' + m[2] + ' available') +
    '</table>';
}

function renderCheckpointCard(summary) {
  // Format: "Checkpoint committed: SHA. N files. sha256: HASH"
  var m = summary.match(/committed:\s*(\S+)\.\s*(\d+)\s+files/);
  if (!m) return '<div class="detail-line">' + escapeHtml(summary) + '</div>';
  var shaM = summary.match(/sha256:\s*(\S+)/);
  return '<table class="kv">' +
    row('Commit', m[1]) +
    row('Files', m[2]) +
    row('SHA256', shaM ? shaM[1] : '—') +
    '</table>';
}

function renderLeaseCleanupCard(summary) {
  // Format: "Lease cleanup archive: action. N entries processed."
  var m = summary.match(/archive:\s*(\w+)\.\s*(\d+)\s+entries/);
  if (!m) return '<div class="detail-line">' + escapeHtml(summary) + '</div>';
  return '<table class="kv">' +
    row('Action', m[1]) +
    row('Entries', m[2]) +
    '</table>';
}

async function mintDevReceipt() {
  const resultEl = document.getElementById('receipt-result');
  const action = document.getElementById('receipt-action').value;
  const ttl = Number(document.getElementById('receipt-ttl').value || 300);
  resultEl.textContent = 'Minting receipt...';
  resultEl.className = 'intent-result pending';
  try {
    if (window.pywebview && window.pywebview.api) {
      const result = await window.pywebview.api.mint_authorization_receipt_dev(action, ttl, '');
      displayReceiptResult(result);
    } else {
      resultEl.textContent = 'Bridge unavailable.';
      resultEl.className = 'intent-result error';
    }
  } catch (e) {
    resultEl.textContent = 'Error: ' + e.message;
    resultEl.className = 'intent-result error';
  }
}

async function mintLocalAuthReceipt() {
  const resultEl = document.getElementById('receipt-result');
  const action = document.getElementById('receipt-action').value;
  const ttl = Number(document.getElementById('receipt-ttl').value || 300);
  resultEl.textContent = 'Authenticating local user...';
  resultEl.className = 'intent-result pending';
  try {
    if (window.pywebview && window.pywebview.api) {
      const result = await window.pywebview.api.mint_authorization_receipt_local(
        action,
        ttl,
        ''
      );
      displayReceiptResult(result);
    } else {
      resultEl.textContent = 'Bridge unavailable.';
      resultEl.className = 'intent-result error';
    }
  } catch (e) {
    resultEl.textContent = 'Error: ' + e.message;
    resultEl.className = 'intent-result error';
  }
}

async function inspectDevReceipt() {
  const resultEl = document.getElementById('receipt-result');
  const raw = document.getElementById('receipt-json').value.trim();
  resultEl.textContent = 'Inspecting receipt...';
  resultEl.className = 'intent-result pending';
  try {
    const receipt = raw ? JSON.parse(raw) : {};
    if (window.pywebview && window.pywebview.api) {
      const result = await window.pywebview.api.inspect_authorization_receipt(receipt);
      displayReceiptResult(result);
    } else {
      resultEl.textContent = 'Bridge unavailable.';
      resultEl.className = 'intent-result error';
    }
  } catch (e) {
    resultEl.textContent = 'Error: ' + e.message;
    resultEl.className = 'intent-result error';
  }
}

function displayReceiptResult(result) {
  const resultEl = document.getElementById('receipt-result');
  if (!result) {
    resultEl.textContent = 'No result returned.';
    resultEl.className = 'intent-result error';
    return;
  }
  const summary = [
    '<strong>' + escapeHtml(result.status || 'unknown').toUpperCase() + '</strong>',
    escapeHtml(result.action || 'unknown'),
    'Method: ' + escapeHtml(result.method || 'unknown'),
    escapeHtml(result.receipt_sha256 || ''),
    escapeHtml(result.expires_at || ''),
  ].join('<br>');
  let html = summary;
  if (result.receipt_ref) {
    html += '<div class="small-note">Receipt ref: ' + escapeHtml(result.receipt_ref) + '</div>';
  }
  if (Array.isArray(result.warnings) && result.warnings.length > 0) {
    html += '<div class="small-note">Warnings: ' + escapeHtml(result.warnings.join('; ')) + '</div>';
  }
  resultEl.innerHTML = html;
  resultEl.className = 'intent-result ' + (result.valid ? 'ok' : 'warning');
}

async function refreshAll() {
  const btn = document.getElementById('refresh-btn');
  btn.disabled = true;
  btn.textContent = 'Refreshing...';

  try {
    // Refresh projection
    if (wsConnected && wsClient) {
      wsClient.requestProjection();
      wsClient.sendMessage({"type": "get_chat_state"});
    } else if (window.pywebview && window.pywebview.api) {
      const projection = await window.pywebview.api.get_projection();
      renderProjection(projection);
      const chat = await window.pywebview.api.get_chat_state();
      renderChat(chat);
    }
  } catch (e) {
    console.error('Refresh failed:', e);
  } finally {
    btn.disabled = false;
    btn.textContent = 'Refresh';
  }
}

async function initWebSocket() {
  let wsToken = null;
  let wsPort = 9876;

  if (window.pywebview && window.pywebview.api) {
    try {
      if (typeof window.pywebview.api.get_ws_config === 'function') {
        const config = await window.pywebview.api.get_ws_config();
        wsToken = config.token || null;
        wsPort = config.port || 9876;
      }
    } catch (e) {
      console.warn('Could not get WS config from bridge:', e);
    }
  }

  const wsUrl = 'ws://127.0.0.1:' + wsPort;

  wsClient = new ProjectionWebSocketClient({
    wsUrl: wsUrl,
    token: wsToken,
    onProjection: (data) => {
      wsConnected = true;
      renderProjection(data);
    },
    onMessage: (msg) => {
      if (msg.type === 'chat_state') {
        renderChat(msg.data);
      } else if (msg.type === 'chat_state_updated') {
        wsClient.sendMessage({"type": "get_chat_state"});
      }
    },
    onStatusChange: (status, detail, attempt) => {
      const connEl = document.getElementById('connection-status');
      connEl.className = 'source-status ' + (status === 'connected' ? 'ok' : 'warning');
      connEl.textContent = status === 'connected' ? 'WS' : 'WS ' + status;
      
      if (status === 'connected') {
        wsConnected = true;
        // Request initial chat state too
        wsClient.sendMessage({"type": "get_chat_state"});
      } else if (status === 'offline' || status === 'auth_failed') {
        wsConnected = false;
        loadFromBridge();
      }
    }
  });
}

async function loadFromBridge() {
  if (!window.pywebview || !window.pywebview.api) return;
  const connEl = document.getElementById('connection-status');
  connEl.textContent = 'Bridge';
  connEl.className = 'source-status ok';

  try {
    const projection = await window.pywebview.api.get_projection();
    renderProjection(projection);
    const chat = await window.pywebview.api.get_chat_state();
    renderChat(chat);
  } catch (e) {
    console.warn('Bridge fallback failed:', e);
  }
}

document.addEventListener('DOMContentLoaded', () => {
  // Chat UI listeners
  document.getElementById('chat-input').addEventListener('input', updateCharCount);
  document.getElementById('send-btn').addEventListener('click', sendMessage);
  document.getElementById('clear-chat-btn').addEventListener('click', clearChat);
  document.getElementById('chat-input').addEventListener('keydown', (e) => {
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
  
  // Periodic refresh for projection if no WS
  setInterval(() => {
    if (!wsConnected && window.pywebview && window.pywebview.api) {
      loadFromBridge();
    }
  }, 10000);
});

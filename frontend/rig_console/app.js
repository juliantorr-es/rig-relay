// Rig Console Frontend — WebSocket client + idempotent reducer + reconnect.
// Backend is authoritative. Frontend is a dumb projection renderer.

// ── State ──

const store = {
  turnId: '',
  turnStatus: 'idle',
  sessionId: '',
  droppedCount: 0,
  transcript: [],
};

const seenEventIds = new Set();
let lastSeq = 0;
let pendingIntentId = 0;
let ws = null;
let intentionalClose = false;

// ── Render Scheduler ──

let renderPending = false;

function scheduleRender() {
  if (renderPending) return;
  renderPending = true;
  requestAnimationFrame(() => { renderPending = false; render(); });
}

function render() {
  renderTranscript();
  renderStatus();
  renderComposer();
}

// ── Transcript ──

function renderTranscript() {
  const el = document.getElementById('transcript');
  let html = '';
  for (const item of store.transcript) {
    const k = item.kind;
    const cls = k === 'user_message' ? 'msg user'
      : k === 'assistant_message' ? 'msg assistant'
      : k === 'turn_status' ? 'msg status'
      : k === 'context_envelope' ? 'msg context'
      : k === 'error' ? 'msg error'
      : k === 'tool_result' || k === 'tool_activity' ? 'msg tool'
      : 'msg system';
    const label = item.title || item.kind;
    const body = item.body_text ? escapeHtml(item.body_text) : '';
    html += `<div class="${cls}"><span class="msg-label">${escapeHtml(label)}</span><span class="msg-body">${body}</span></div>`;
  }
  el.innerHTML = html;
  el.scrollTop = el.scrollHeight;
}

// ── Status Sidebar ──

function renderStatus() {
  document.getElementById('turn-status').textContent = store.turnStatus;
  document.getElementById('sid').textContent = store.sessionId || '\u2014';
  document.getElementById('dropped').textContent = String(store.droppedCount);
  const badge = document.getElementById('status-badge');
  badge.textContent = store.turnStatus;
  badge.className = 'status-' + store.turnStatus;
}

// ── Composer ──

function renderComposer() {
  const active = store.turnStatus === 'running' || store.turnStatus === 'starting' || store.turnStatus === 'cancelling';
  document.getElementById('send-btn').disabled = active;
  document.getElementById('cancel-btn').style.display = active ? 'inline-block' : 'none';
  document.getElementById('prompt-input').disabled = active;
}

// ── WebSocket ──

function connect() {
  ws = new WebSocket(WS_URL);

  ws.onopen = () => {
    document.getElementById('connection-badge').textContent = 'Connected';
    document.getElementById('connection-badge').className = 'source-status ok';
    ws.send(JSON.stringify({
      schema: 'rig.ws.client.auth.v1',
      token: WS_TOKEN,
      last_seen_seq: lastSeq || undefined,
    }));
  };

  ws.onclose = () => {
    if (!intentionalClose) {
      document.getElementById('connection-badge').textContent = 'Disconnected';
      document.getElementById('connection-badge').className = 'source-status error';
      setTimeout(connect, 2000);
    }
  };

  ws.onerror = () => {};

  ws.onmessage = (event) => {
    let msg;
    try { msg = JSON.parse(event.data); } catch { return; }
    handleMessage(msg);
  };
}

function sendIntent(kind, payload) {
  if (!ws || ws.readyState !== WebSocket.OPEN) return;
  pendingIntentId++;
  ws.send(JSON.stringify({
    schema: 'rig.ws.client.intent.v1',
    intent_id: 'intent_' + pendingIntentId,
    intent_kind: kind,
    payload: payload || {},
  }));
}

// ── Message Handler / Reducer ──

function handleMessage(msg) {
  const schema = msg.schema || '';

  // Stale seq guard
  if (msg.seq && msg.seq <= lastSeq) return;
  if (msg.seq) lastSeq = msg.seq;

  switch (schema) {
    case 'rig.ws.server.auth_ok.v1':
      // Server sent auth_ok; snapshot or replay follows
      break;

    case 'rig.ws.server.snapshot.v1':
      applySnapshot(msg.data);
      scheduleRender();
      break;

    case 'rig.ws.server.delta.v1':
      if (applyDelta(msg)) scheduleRender();
      break;

    case 'rig.ws.server.ack.v1':
      handleAck(msg);
      break;

    case 'rig.ws.server.warning.v1':
      addWarning(msg.message || 'Protocol warning');
      scheduleRender();
      break;

    default:
      addWarning('Unknown server message: ' + schema);
      scheduleRender();
  }
}

function addWarning(text) {
  store.transcript.push({
    kind: 'system',
    title: 'Protocol',
    body_text: text,
  });
}

function handleAck(msg) {
  if (msg.status === 'refused') {
    const reason = msg.reason || 'Prompt refused';
    store.transcript.push({ kind: 'turn_status', title: 'Refused', body_text: reason });
    scheduleRender();
  }
}

function applySnapshot(data) {
  if (!data) return;
  store.sessionId = data.session_id || store.sessionId;
  store.turnStatus = data.turn_status || store.turnStatus;
  store.droppedCount = data.dropped_count || 0;
  seenEventIds.clear();
  store.transcript = [];
  if (data.transcript) {
    for (const t of data.transcript) {
      store.transcript.push({
        id: t.item_id, kind: t.kind, title: t.title,
        body_text: t.body_text, tool_name: t.tool_name, status: t.status,
      });
      if (t.item_id) seenEventIds.add(t.item_id);
    }
  }
}

function applyDelta(msg) {
  const eventId = msg.event_id || (msg.value && msg.value.item_id);
  if (eventId && seenEventIds.has(eventId)) return false;
  if (eventId) seenEventIds.add(eventId);

  if (msg.op === 'append' && msg.path === '/transcript') {
    const v = msg.value;
    if (!v || !v.kind) {
      addWarning('Malformed delta: missing kind');
      return true;
    }
    store.transcript.push({
      id: v.item_id, kind: v.kind, title: v.title,
      body_text: v.body_text, tool_name: v.tool_name, status: v.status,
    });
    if (v.kind === 'turn_status') {
      store.turnStatus = v.status || 'completed';
    }
    return true;
  }
  return false;
}

// ── UI Event Handlers ──

document.addEventListener('DOMContentLoaded', () => {
  connect();

  const input = document.getElementById('prompt-input');
  const sendBtn = document.getElementById('send-btn');
  const cancelBtn = document.getElementById('cancel-btn');

  input.addEventListener('input', () => {
    input.style.height = 'auto';
    input.style.height = Math.min(input.scrollHeight, 120) + 'px';
  });

  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendPrompt();
    }
  });

  sendBtn.addEventListener('click', sendPrompt);
  cancelBtn.addEventListener('click', () => sendIntent('cancel_turn', {}));

  function sendPrompt() {
    const text = input.value.trim();
    if (!text) return;
    input.value = '';
    input.style.height = 'auto';
    sendIntent('start_turn', { text });
  }
});

// ── Helpers ──

function escapeHtml(str) {
  if (typeof str !== 'string') return String(str || '');
  return str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

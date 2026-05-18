// CONTRACT: Bridge Transport Pipeline
// ────────────────────────────────────
// Owner: frontend/desktop/js/transport.js
// Safety: Never logs, renders, or serializes the WS auth token.
//         Token check is existence-only (bool/token_present).
//         Outbound intents queued until STAGE 4 (Ready).
//         Reconnect resets _firstProjectionReceived but preserves queue.
//
// Rig Relay — Transport
// WebSocket + pywebview bridge abstraction.
// Uses ProjectionWebSocketClient for the WebSocket connection (reconnect,
// auth, subscription handling). Falls back to pywebview JS bridge.
// All transport state mutations route through the canonical authority.

import { state } from './state.js';
import { ProjectionWebSocketClient } from '../websocket.js';

export { ProjectionWebSocketClient };
import { auditLog, audit } from './audit.js';
import { renderStatusBar } from './status.js';
import { recordFrontendEvent } from './telemetry/frontendTrace.js';

let _wsClient = null;
let _transportAuthority = null;
let _firstProjectionReceived = false;
let _wsAuthenticated = false;
let _outboundQueue = [];
let _wsUrl = '';
let _handshakeId = '';
let _onMessage = null;

function _newIntentId() {
  if (
    globalThis.crypto &&
    typeof globalThis.crypto.randomUUID === 'function'
  ) {
    return 'intent_' + globalThis.crypto.randomUUID();
  }
  return (
    'intent_' +
    Date.now().toString(36) +
    '_' +
    Math.random().toString(36).slice(2, 8)
  );
}

function _normalizeDesktopIntentRequest(msg) {
  if (!msg || msg.type !== 'desktop_intent_request') return msg;
  return {
    ...msg,
    schema_version: msg.schema_version || 'rig.relay.desktop_intent_request.v1',
    intent_id: msg.intent_id || _newIntentId(),
    created_at: msg.created_at || new Date().toISOString(),
  };
}

function _applySnapshot(snap) {
  state.wsConnected = snap.wsConnected;
  state.transport.status = snap.transport.status;
  state.transport.phase = snap.transport.phase;
  state.transport.lastEvent = snap.transport.lastEvent;
  state.transport.lastError = snap.transport.lastError;
  state.transport.handshakeId = snap.transport.handshakeId;
  state.transport.updatedAt = snap.transport.updatedAt;
}

function _dispatch(event, detail) {
  if (!_transportAuthority) return;
  const snap = _transportAuthority.dispatch(event, detail);
  _applySnapshot(snap);
  return snap;
}

// ════════════════════════════════════════════════════════════════
// STAGE 4: Ready — both auth and projection received, signal ready
// Ownership: frontend/desktop/js/transport.js
// ════════════════════════════════════════════════════════════════
function _signalReady() {
  console.log("[bridge:frontend] transport ready (WS auth + first projection)");
  _dispatch('auth_ok', {
    reason: 'transport ready',
    ws_url: _wsUrl,
    transport: _wsUrl.startsWith('wss://') ? 'wss' : 'ws',
    handshake_id: _handshakeId,
  });
  renderStatusBar();
  if (_onMessage) _onMessage({ type: '_transport', status: 'connected' });
  _wsClient.send({ type: 'get_chat_state' });
  for (const msg of _outboundQueue) {
    _wsClient.send(_normalizeDesktopIntentRequest(msg));
  }
  _outboundQueue = [];
}

// ════════════════════════════════════════════════════════════════
// STAGE 3: Projection Wait — waiting for first projection before declaring ready
// Ownership: frontend/desktop/js/transport.js
// ════════════════════════════════════════════════════════════════
export function onProjectionReceived() {
  _firstProjectionReceived = true;
  if (_wsAuthenticated && _transportAuthority) {
    _signalReady();
  }
}

// ════════════════════════════════════════════════════════════════
// STAGE 0: Init — token validation, WebSocket API presence check
// Ownership: frontend/desktop/js/transport.js
// ════════════════════════════════════════════════════════════════
export function initTransport(wsUrl, token, onMessage, transportAuthority, handshakeId) {
  _wsUrl = wsUrl;
  _handshakeId = handshakeId || '';
  _onMessage = onMessage || null;
  _transportAuthority = transportAuthority || null;
  if (_transportAuthority && handshakeId) {
    _transportAuthority.setHandshakeId(handshakeId);
  }

  if (typeof WebSocket === 'undefined') {
    _dispatch('websocket_error', { reason: 'WebSocket API unavailable' });
    if (onMessage) onMessage({ type: '_transport', status: 'offline' });
    return;
  }

  if (!token) {
    _dispatch('runtime_config_invalid', { reason: 'Pywebview runtime token was not provided.' });
    if (onMessage) onMessage({ type: '_transport', status: 'token_missing', detail: 'Pywebview runtime token was not provided.' });
    return;
  }

  // ════════════════════════════════════════════════════════════════
  // STAGE 1: Connect — WebSocket construction, auth
  // Ownership: frontend/desktop/js/transport.js
  // ════════════════════════════════════════════════════════════════
  const secureTransport = typeof wsUrl === 'string' && wsUrl.startsWith('wss://');
  _wsClient = new ProjectionWebSocketClient({
    wsUrl,
    token,
    handshakeId: handshakeId || null,
    transportMachine: transportAuthority,
    onProjection(data) {
      if (onMessage) onMessage({ type: 'projection', data });
    },
    onStatusChange(status, detail, attempts) {
      // ════════════════════════════════════════════════════════════════
      // STAGE 2: Auth — token exchange
      // Ownership: frontend/desktop/js/transport.js
      // ════════════════════════════════════════════════════════════════
      if (status === 'authenticating') {
        _dispatch('websocket_open', {
          reason: detail || 'websocket opened',
          ws_url: wsUrl,
        });
        recordFrontendEvent('frontend_socket_open', { ws_url: wsUrl });
      } else if (status === 'connected') {
        _wsAuthenticated = true;
        recordFrontendEvent('frontend_auth_ok', { handshake_id: handshakeId || '' });
        console.log("[bridge:frontend] WebSocket connected + authenticated, waiting for first projection");
        if (_firstProjectionReceived) {
          _signalReady();
        }
      } else if (status === 'auth_failed') {
        console.error("[bridge:frontend] WebSocket auth failed:", detail);
        _dispatch('auth_failed', {
          reason: detail || 'unknown',
          ws_url: wsUrl,
        });
        audit.auth.failed(detail || 'unknown');
        renderStatusBar();
        if (onMessage) onMessage({ type: '_transport', status: 'auth_failed', detail });
      } else if (status === 'disconnected' || status === 'closed') {
        console.warn("[bridge:frontend] WebSocket disconnected");
        _dispatch('websocket_close', {
          reason: detail || 'websocket closed',
          ws_url: wsUrl,
        });
        audit.transport.disconnected();
        renderStatusBar();
        if (onMessage) onMessage({ type: '_transport', status: 'offline' });
      } else if (status === 'reconnecting') {
        console.log("[bridge:frontend] WebSocket reconnecting (attempt " + (attempts || '?') + ")");
        _dispatch('websocket_connecting', {
          reason: detail || 'reconnecting',
          ws_url: wsUrl,
        });
        audit.transport.reconnecting(detail, attempts);
        if (onMessage) onMessage({ type: '_transport', status: 'reconnecting', delay: detail, attempts });
      } else if (status === 'offline') {
        console.warn("[bridge:frontend] WebSocket offline");
        _dispatch('websocket_error', {
          reason: detail || 'websocket offline',
          ws_url: wsUrl,
        });
        renderStatusBar();
        if (onMessage) onMessage({ type: '_transport', status: 'offline' });
      }
    },
    onError(msg) {
      auditLog('transport', 'error', { msg: msg });
    },
    onAuthFailed(msg) {
      audit.auth.failed(msg);
    },
    onMessage(msg) {
      // Forward all other messages (chat_state, intent_result, progress_event, etc.)
      if (onMessage) onMessage(msg);
    },
  });
}

export function setWsClient(client) {
  _wsClient = client;
}

// ════════════════════════════════════════════════════════════════
// STAGE 5: Operational — intents flow, reconnect handling
// Ownership: frontend/desktop/js/transport.js
// ════════════════════════════════════════════════════════════════
export function sendMessage(msg) {
  if (_wsClient && _wsClient.connected && _wsClient.authenticated && _firstProjectionReceived) {
    return _wsClient.send(_normalizeDesktopIntentRequest(msg));
  }
  if (_wsClient && _wsClient.connected && _wsClient.authenticated && !_firstProjectionReceived) {
    _outboundQueue.push(msg);
    return 'queued';
  }
  return false;
}

export function isConnected() {
  if (_transportAuthority) return _transportAuthority.isConnected();
  return state.wsConnected;
}

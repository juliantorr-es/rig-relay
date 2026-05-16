// Rig Relay — Transport
// WebSocket + pywebview bridge abstraction.
// Uses ProjectionWebSocketClient for the WebSocket connection (reconnect,
// auth, subscription handling). Falls back to pywebview JS bridge.
// All transport state mutations route through the canonical authority.

import { state } from './state.js';
import { ProjectionWebSocketClient } from '../websocket.js';
import { auditLog, audit } from './audit.js';
import { renderStatusBar } from './status.js';

let _wsClient = null;
let _transportAuthority = null;

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

export function initTransport(wsUrl, token, onMessage, transportAuthority, handshakeId) {
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
      if (status === 'authenticating') {
        _dispatch('websocket_open', {
          reason: detail || 'websocket opened',
          ws_url: wsUrl,
        });
      } else if (status === 'connected') {
        console.log("[bridge:frontend] WebSocket connected + authenticated");
        _dispatch('auth_ok', {
          reason: 'websocket authenticated',
          ws_url: wsUrl,
          transport: secureTransport ? 'wss' : 'ws',
          handshake_id: handshakeId || '',
        });
        renderStatusBar();
        if (onMessage) onMessage({ type: '_transport', status: 'connected' });
        _wsClient.send({ type: 'get_chat_state' });
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

export function sendMessage(msg) {
  if (_wsClient && _wsClient.connected && _wsClient.authenticated) {
    return _wsClient.send(msg);
  }
  return false;
}

export function isConnected() {
  if (_transportAuthority) return _transportAuthority.isConnected();
  return state.wsConnected;
}

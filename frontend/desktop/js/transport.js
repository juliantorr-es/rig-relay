// Rig Relay — Transport
// WebSocket + pywebview bridge abstraction.
// Uses ProjectionWebSocketClient for the WebSocket connection (reconnect,
// auth, subscription handling). Falls back to pywebview JS bridge.

import { state } from './state.js';
import { ProjectionWebSocketClient } from '../websocket.js';
import { auditLog, audit } from './audit.js';

let _wsClient = null;

export function initTransport(wsUrl, token, onMessage) {
  if (typeof WebSocket === 'undefined') {
    state.transport = 'none';
    if (onMessage) onMessage({ type: '_transport', status: 'offline' });
    return;
  }

  if (!token) {
    state.transport = 'none';
    if (onMessage) onMessage({ type: '_transport', status: 'offline' });
    return;
  }

  _wsClient = new ProjectionWebSocketClient({
    wsUrl,
    token,
    onProjection(data) {
      if (onMessage) onMessage({ type: 'projection', data });
    },
    onStatusChange(status, detail, attempts) {
      if (status === 'connected') {
        state.wsConnected = true;
        state.transport = 'ws';
        if (onMessage) onMessage({ type: '_transport', status: 'connected' });
        // Request chat state — already get_projection in ProjectionWebSocketClient
        _wsClient.send({ type: 'get_chat_state' });
      } else if (status === 'auth_failed') {
        state.wsConnected = false;
        audit.auth.failed(detail || 'unknown');
        if (onMessage) onMessage({ type: '_transport', status: 'auth_failed', detail });
      } else if (status === 'disconnected' || status === 'closed') {
        state.wsConnected = false;
        audit.transport.disconnected();
        if (onMessage) onMessage({ type: '_transport', status: 'offline' });
      } else if (status === 'reconnecting') {
        state.wsConnected = false;
        audit.transport.reconnecting(detail, attempts);
        if (onMessage) onMessage({ type: '_transport', status: 'reconnecting', delay: detail, attempts });
      } else if (status === 'offline') {
        state.wsConnected = false;
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
  return state.transport === 'ws' && state.wsConnected;
}

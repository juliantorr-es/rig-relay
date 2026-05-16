// Rig Relay — Transport
// WebSocket + pywebview bridge abstraction.
// Uses ProjectionWebSocketClient for the WebSocket connection (reconnect,
// auth, subscription handling). Falls back to pywebview JS bridge.

import { state } from './state.js';
import { ProjectionWebSocketClient } from '../websocket.js';
import { auditLog, audit } from './audit.js';
import { TransportState } from './transportState.js';

let _wsClient = null;
let _transportMachine = null;

function _recordFrontendEvent(type, message) {
  if (window.pywebview && window.pywebview.api && window.pywebview.api.record_frontend_event) {
    window.pywebview.api.record_frontend_event({type: type, message: message || ''}).catch(function() {});
  }
}

export function initTransport(wsUrl, token, onMessage, transportMachine) {
  _transportMachine = transportMachine || null;
  if (typeof WebSocket === 'undefined') {
    state.transport = TransportState.BACKEND_UNAVAILABLE;
    if (onMessage) onMessage({ type: '_transport', status: 'offline' });
    return;
  }

  if (!token) {
    state.transport = TransportState.TOKEN_MISSING;
    if (onMessage) onMessage({ type: '_transport', status: 'token_missing', detail: 'Pywebview runtime token was not provided.' });
    return;
  }

  const secureTransport = typeof wsUrl === 'string' && wsUrl.startsWith('wss://');
  _wsClient = new ProjectionWebSocketClient({
    wsUrl,
    token,
    onProjection(data) {
      if (onMessage) onMessage({ type: 'projection', data });
    },
    onStatusChange(status, detail, attempts) {
      if (status === 'authenticating') {
        state.transport = TransportState.AUTHENTICATING;
        _transportMachine?.transition('websocket_open', {
          reason: detail || 'websocket opened',
          ws_url: wsUrl,
        });
      } else if (status === 'connected') {
        _recordFrontendEvent("frontend_auth_ok");
        console.log("[bridge:frontend] WebSocket connected + authenticated");
        state.wsConnected = true;
        state.transport = TransportState.CONNECTED;
        _transportMachine?.transition('auth_ok', {
          reason: 'websocket authenticated',
          ws_url: wsUrl,
          transport: secureTransport ? 'wss' : 'ws',
        });
        if (onMessage) onMessage({ type: '_transport', status: 'connected' });
        // Request chat state — already get_projection in ProjectionWebSocketClient
        _wsClient.send({ type: 'get_chat_state' });
      } else if (status === 'auth_failed') {
        console.error("[bridge:frontend] WebSocket auth failed:", detail);
        state.wsConnected = false;
        state.transport = TransportState.AUTH_FAILED;
        audit.auth.failed(detail || 'unknown');
        _transportMachine?.transition('auth_failed', {
          reason: detail || 'unknown',
          ws_url: wsUrl,
        });
        if (onMessage) onMessage({ type: '_transport', status: 'auth_failed', detail });
      } else if (status === 'disconnected' || status === 'closed') {
        console.warn("[bridge:frontend] WebSocket disconnected");
        state.wsConnected = false;
        state.transport = TransportState.BACKEND_UNAVAILABLE;
        audit.transport.disconnected();
        _transportMachine?.transition('websocket_closed', {
          reason: detail || 'websocket closed',
          ws_url: wsUrl,
        });
        if (onMessage) onMessage({ type: '_transport', status: 'offline' });
      } else if (status === 'reconnecting') {
        console.log("[bridge:frontend] WebSocket reconnecting (attempt " + (attempts || '?') + ")");
        state.wsConnected = false;
        state.transport = TransportState.CONNECTING;
        audit.transport.reconnecting(detail, attempts);
        if (onMessage) onMessage({ type: '_transport', status: 'reconnecting', delay: detail, attempts });
      } else if (status === 'offline') {
        console.warn("[bridge:frontend] WebSocket offline");
        state.wsConnected = false;
        state.transport = TransportState.BACKEND_UNAVAILABLE;
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
  return state.transport === TransportState.CONNECTED && state.wsConnected;
}

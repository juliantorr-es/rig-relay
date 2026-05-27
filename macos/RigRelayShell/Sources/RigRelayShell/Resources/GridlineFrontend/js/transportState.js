// Rig Relay — Transport State Authority
// Canonical frontend transport state reducer.
// Every frontend path MUST route through this reducer to update transport state.
// No direct writes to wsConnected, state.transport.status, etc. outside this file.

// ── Canonical states ────────────────────────────────────────────────
const TransportStatus = Object.freeze({
  IDLE: 'idle',
  CONFIGURING: 'configuring',
  CONNECTING: 'connecting',
  SOCKET_OPEN: 'socket_open',
  AUTHENTICATING: 'authenticating',
  AUTHENTICATED: 'authenticated',
  PROJECTION_WAITING: 'projection_waiting',
  READY: 'ready',
  DEGRADED: 'degraded',
  BACKEND_STALE: 'backend_stale',
  DISCONNECTED: 'disconnected',
  FAILED: 'failed',
});

// Legacy aliases so that existing code that references TransportState.CONNECTED,
// TransportState.BACKEND_UNAVAILABLE, etc. can be progressively migrated.
const TransportState = Object.freeze({
  IDLE: TransportStatus.IDLE,
  WAITING_FOR_PYWEBVIEW: TransportStatus.CONFIGURING,
  LOADING_CONFIG: TransportStatus.CONFIGURING,
  CONFIG_LOADED: TransportStatus.CONFIGURING,
  TOKEN_MISSING: TransportStatus.FAILED,
  CONNECTING: TransportStatus.CONNECTING,
  AUTHENTICATING: TransportStatus.AUTHENTICATING,
  CONNECTED: TransportStatus.AUTHENTICATED,
  PROJECTION_READY: TransportStatus.READY,
  BACKEND_UNAVAILABLE: TransportStatus.DISCONNECTED,
  AUTH_FAILED: TransportStatus.FAILED,
  FAILED: TransportStatus.FAILED,
});

// ── Canonical events ────────────────────────────────────────────────
const TransportEvent = Object.freeze({
  RUNTIME_CONFIG_LOADED: 'runtime_config_loaded',
  RUNTIME_CONFIG_INVALID: 'runtime_config_invalid',
  WEBSOCKET_CONNECTING: 'websocket_connecting',
  WEBSOCKET_OPEN: 'websocket_open',
  AUTH_SENT: 'auth_sent',
  AUTH_OK: 'auth_ok',
  AUTH_FAILED: 'auth_failed',
  PROJECTION_RECEIVED: 'projection_received',
  PROJECTION_RENDERED: 'projection_rendered',
  WEBSOCKET_CLOSE: 'websocket_close',
  WEBSOCKET_ERROR: 'websocket_error',
  FRONTEND_FATAL: 'frontend_fatal',
  BRIDGE_BACKEND_STALE: 'bridge_backend_stale',
});

// Legacy event aliases — old code emits these; map them to canonical events.
const LEGACY_EVENT_MAP = Object.freeze({
  boot_started: TransportEvent.RUNTIME_CONFIG_LOADED,
  pywebview_wait_started: TransportEvent.RUNTIME_CONFIG_LOADED,
  config_requested: TransportEvent.RUNTIME_CONFIG_LOADED,
  config_loaded: TransportEvent.RUNTIME_CONFIG_LOADED,
  config_token_missing: TransportEvent.RUNTIME_CONFIG_INVALID,
  websocket_connecting: TransportEvent.WEBSOCKET_CONNECTING,
  websocket_open: TransportEvent.WEBSOCKET_OPEN,
  auth_sent: TransportEvent.AUTH_SENT,
  auth_ok: TransportEvent.AUTH_OK,
  auth_failed: TransportEvent.AUTH_FAILED,
  websocket_closed: TransportEvent.WEBSOCKET_CLOSE,
  projection_received: TransportEvent.PROJECTION_RECEIVED,
  projection_rendered: TransportEvent.PROJECTION_RENDERED,
  boot_error: TransportEvent.FRONTEND_FATAL,
});

// ── Event → next status mapping ─────────────────────────────────────
const EVENT_TO_STATUS = Object.freeze({
  [TransportEvent.RUNTIME_CONFIG_LOADED]: TransportStatus.CONFIGURING,
  [TransportEvent.RUNTIME_CONFIG_INVALID]: TransportStatus.FAILED,
  [TransportEvent.WEBSOCKET_CONNECTING]: TransportStatus.CONNECTING,
  [TransportEvent.WEBSOCKET_OPEN]: TransportStatus.SOCKET_OPEN,
  [TransportEvent.AUTH_SENT]: TransportStatus.AUTHENTICATING,
  [TransportEvent.AUTH_OK]: TransportStatus.AUTHENTICATED,
  [TransportEvent.AUTH_FAILED]: TransportStatus.FAILED,
  [TransportEvent.PROJECTION_RECEIVED]: TransportStatus.PROJECTION_WAITING,
  [TransportEvent.PROJECTION_RENDERED]: TransportStatus.READY,
  [TransportEvent.WEBSOCKET_CLOSE]: TransportStatus.DISCONNECTED,
  [TransportEvent.WEBSOCKET_ERROR]: TransportStatus.DEGRADED,
  [TransportEvent.FRONTEND_FATAL]: TransportStatus.FAILED,
  [TransportEvent.BRIDGE_BACKEND_STALE]: TransportStatus.BACKEND_STALE,
});

// ── Human-readable labels ───────────────────────────────────────────
const STATUS_LABELS = Object.freeze({
  [TransportStatus.IDLE]: 'Idle',
  [TransportStatus.CONFIGURING]: 'Configuring…',
  [TransportStatus.CONNECTING]: 'Connecting…',
  [TransportStatus.SOCKET_OPEN]: 'Socket Open',
  [TransportStatus.AUTHENTICATING]: 'Authenticating…',
  [TransportStatus.AUTHENTICATED]: 'Connected',
  [TransportStatus.PROJECTION_WAITING]: 'Projection Waiting…',
  [TransportStatus.READY]: 'Ready',
  [TransportStatus.DEGRADED]: 'Degraded',
  [TransportStatus.BACKEND_STALE]: 'Backend Stale',
  [TransportStatus.DISCONNECTED]: 'Disconnected',
  [TransportStatus.FAILED]: 'Failed',
});

// CSS class hints for the status bar
const STATUS_CHIP_CLASS = Object.freeze({
  [TransportStatus.IDLE]: 'warn',
  [TransportStatus.CONFIGURING]: '',
  [TransportStatus.CONNECTING]: '',
  [TransportStatus.SOCKET_OPEN]: '',
  [TransportStatus.AUTHENTICATING]: '',
  [TransportStatus.AUTHENTICATED]: 'ok',
  [TransportStatus.PROJECTION_WAITING]: 'ok',
  [TransportStatus.READY]: 'ok',
  [TransportStatus.DEGRADED]: 'warn',
  [TransportStatus.BACKEND_STALE]: 'warn',
  [TransportStatus.DISCONNECTED]: 'warn',
  [TransportStatus.FAILED]: 'warn',
});

// ── Allowed transitions ─────────────────────────────────────────────
const ALLOWED_TRANSITIONS = Object.freeze({
  [TransportStatus.IDLE]: new Set([
    TransportStatus.CONFIGURING,
    TransportStatus.CONNECTING,
    TransportStatus.FAILED,
  ]),
  [TransportStatus.CONFIGURING]: new Set([
    TransportStatus.CONNECTING,
    TransportStatus.FAILED,
  ]),
  [TransportStatus.CONNECTING]: new Set([
    TransportStatus.SOCKET_OPEN,
    TransportStatus.DISCONNECTED,
    TransportStatus.DEGRADED,
    TransportStatus.FAILED,
  ]),
  [TransportStatus.SOCKET_OPEN]: new Set([
    TransportStatus.AUTHENTICATING,
    TransportStatus.DISCONNECTED,
    TransportStatus.DEGRADED,
    TransportStatus.FAILED,
  ]),
  [TransportStatus.AUTHENTICATING]: new Set([
    TransportStatus.AUTHENTICATED,
    TransportStatus.DISCONNECTED,
    TransportStatus.DEGRADED,
    TransportStatus.FAILED,
  ]),
  [TransportStatus.AUTHENTICATED]: new Set([
    TransportStatus.PROJECTION_WAITING,
    TransportStatus.READY,
    TransportStatus.DISCONNECTED,
    TransportStatus.DEGRADED,
    TransportStatus.FAILED,
  ]),
  [TransportStatus.PROJECTION_WAITING]: new Set([
    TransportStatus.READY,
    TransportStatus.DISCONNECTED,
    TransportStatus.DEGRADED,
    TransportStatus.FAILED,
  ]),
  [TransportStatus.READY]: new Set([
    TransportStatus.PROJECTION_WAITING,
    TransportStatus.BACKEND_STALE,
    TransportStatus.DISCONNECTED,
    TransportStatus.DEGRADED,
    TransportStatus.FAILED,
  ]),
  [TransportStatus.DEGRADED]: new Set([
    TransportStatus.CONNECTING,
    TransportStatus.DISCONNECTED,
    TransportStatus.FAILED,
  ]),
  [TransportStatus.BACKEND_STALE]: new Set([
    TransportStatus.READY,
    TransportStatus.DEGRADED,
    TransportStatus.DISCONNECTED,
    TransportStatus.FAILED,
  ]),
  [TransportStatus.DISCONNECTED]: new Set([
    TransportStatus.CONNECTING,
    TransportStatus.CONFIGURING,
    TransportStatus.FAILED,
  ]),
  [TransportStatus.FAILED]: new Set([
    TransportStatus.CONFIGURING,
    TransportStatus.CONNECTING,
  ]),
});

// ── Frontend breadcrumb emitter ─────────────────────────────────────
function emitBreadcrumb(payload) {
  // pywebview bridge path
  if (window.pywebview && window.pywebview.api && window.pywebview.api.record_frontend_event) {
    window.pywebview.api.record_frontend_event({
      type: payload.type,
      message: payload.message || '',
      from_status: payload.from_status || '',
      to_status: payload.to_status || '',
      handshake_id: payload.handshake_id || '',
    }).catch(function() {});
    return { sent: true, path: 'pywebview' };
  }
  // HTTP /frontend-event sink fallback
  const runtimeConfig = window.__RIG_RELAY_RUNTIME_CONFIG__ || {};
  const handshakeId = runtimeConfig.handshake_id || runtimeConfig.handshakeId || '';
  const detailParam = encodeURIComponent(JSON.stringify(payload));
  const url = '/frontend-event?type=' + encodeURIComponent(payload.type) +
    '&handshake_id=' + encodeURIComponent(handshakeId) +
    '&detail=' + detailParam;
  if (typeof fetch === 'function') {
    fetch(url, {
      method: 'GET',
      credentials: 'same-origin',
      cache: 'no-store',
      keepalive: true,
    }).catch(function() {});
    return { sent: true, path: 'http' };
  }
  return { sent: false, path: 'none' };
}

// ── Canonical state reducer / authority ──────────────────────────────
export function createTransportStateAuthority(options = {}) {
  const _state = {
    wsConnected: false,
    transport: {
      status: TransportStatus.IDLE,
      phase: 'boot',
      lastEvent: null,
      lastError: null,
      handshakeId: options.handshakeId || '',
      updatedAt: new Date().toISOString(),
    },
  };

  let _previousStatus = null;
  let _transitionCount = 0;
  let _lastBreadcrumbResult = null;
  let _lastProjectionTimestamp = null;
  let _backendState = {
    state: '',
    lastAt: null,
    sessionId: '',
    idleSequence: 0,
    activeWorkCount: 0,
    isStale: false,
  };
  let _closeInfo = {
    code: null,
    reason: '',
    wasClean: false,
  };
  let _onTransition = typeof options.onTransition === 'function' ? options.onTransition : null;
  let _onGlobalStateChange = typeof options.onGlobalStateChange === 'function' ? options.onGlobalStateChange : null;

  function _resolveEvent(rawEvent) {
    if (LEGACY_EVENT_MAP[rawEvent]) return LEGACY_EVENT_MAP[rawEvent];
    if (EVENT_TO_STATUS[rawEvent]) return rawEvent;
    return null;
  }

  function dispatch(rawEvent, detail = {}) {
    const event = _resolveEvent(rawEvent);
    if (!event) {
      console.warn('[transport-authority] Unknown event: ' + rawEvent);
      return snapshot();
    }

    const targetStatus = EVENT_TO_STATUS[event];
    if (!targetStatus) return snapshot();

    const currentStatus = _state.transport.status;

    // Idempotent: same status + same event → no-op
    if (currentStatus === targetStatus && _state.transport.lastEvent === event) {
      return snapshot();
    }

    // Validate transition (unless same status — allows re-entry for degraded recovery)
    if (currentStatus !== targetStatus) {
      const allowed = ALLOWED_TRANSITIONS[currentStatus];
      if (allowed && !allowed.has(targetStatus)) {
        console.warn(
          '[transport-authority] Blocked transition: ' + currentStatus + ' → ' + targetStatus + ' via ' + event
        );
        return snapshot();
      }
    }

    // Apply transition
    _previousStatus = currentStatus;
    _state.transport.status = targetStatus;
    _state.transport.lastEvent = event;
    _state.transport.updatedAt = new Date().toISOString();
    _state.transport.phase = _phaseFor(targetStatus);

    // wsConnected is derived from status
    _state.wsConnected = _isConnectedStatus(targetStatus);

    // Error tracking
    if (event === TransportEvent.WEBSOCKET_ERROR || event === TransportEvent.AUTH_FAILED || event === TransportEvent.FRONTEND_FATAL) {
      _state.transport.lastError = detail.reason || detail.message || event;
    }

    // Close code/reason tracking from websocket_close event
    if (event === TransportEvent.WEBSOCKET_CLOSE) {
      if (detail.close_code !== undefined) _closeInfo.code = detail.close_code;
      if (detail.close_reason !== undefined) _closeInfo.reason = detail.close_reason;
      if (detail.was_clean !== undefined) _closeInfo.wasClean = detail.was_clean;
    }

    // Handshake ID forwarding
    if (detail.handshake_id) {
      _state.transport.handshakeId = detail.handshake_id;
    }

    // Projection timestamp tracking
    if (event === TransportEvent.PROJECTION_RENDERED && detail.projection_digest) {
      _lastProjectionTimestamp = _state.transport.updatedAt;
    }

    _transitionCount++;

    // Emit breadcrumb — uses `type` field as required by backend
    _lastBreadcrumbResult = emitBreadcrumb({
      type: 'transport_state_transition',
      message: currentStatus + ' → ' + targetStatus + ' via ' + event,
      from_status: currentStatus,
      to_status: targetStatus,
      event: event,
      handshake_id: _state.transport.handshakeId,
    });

    const snap = snapshot();

    if (_onTransition) {
      _onTransition(snap);
    }

    if (_onGlobalStateChange) {
      try {
        _onGlobalStateChange(snap);
      } catch (e) {
        console.error('[transport-authority] onGlobalStateChange error:', e);
      }
    }

    return snap;
  }

  function snapshot() {
    return {
      wsConnected: _state.wsConnected,
      transport: {
        status: _state.transport.status,
        phase: _state.transport.phase,
        lastEvent: _state.transport.lastEvent,
        lastError: _state.transport.lastError,
        handshakeId: _state.transport.handshakeId,
        updatedAt: _state.transport.updatedAt,
      },
      label: STATUS_LABELS[_state.transport.status] || 'Unknown',
      chipClass: STATUS_CHIP_CLASS[_state.transport.status] || 'warn',
      previousStatus: _previousStatus,
      transitionCount: _transitionCount,
      lastBreadcrumbResult: _lastBreadcrumbResult,
      lastProjectionTimestamp: _lastProjectionTimestamp,
      backendState: { ..._backendState },
      closeInfo: { ..._closeInfo },
    };
  }

  function getStatus() {
    return _state.transport.status;
  }

  function isConnected() {
    return _state.wsConnected;
  }

  function setHandshakeId(id) {
    _state.transport.handshakeId = id || '';
  }

  function setOnTransition(callback) {
    _onTransition = typeof callback === 'function' ? callback : null;
  }

  function setOnGlobalStateChange(callback) {
    _onGlobalStateChange = typeof callback === 'function' ? callback : null;
  }

  function setBackendState(info) {
    if (info) {
      _backendState.state = info.state || '';
      _backendState.lastAt = info.last_at || null;
      _backendState.sessionId = info.session_id || '';
      if (typeof info.idle_sequence === 'number') _backendState.idleSequence = info.idle_sequence;
      if (typeof info.active_work_count === 'number') _backendState.activeWorkCount = info.active_work_count;
      _backendState.isStale = _backendState.lastAt ? (Date.now() - _backendState.lastAt > 30000) : false;
    }
  }

  function getBackendState() {
    return { ..._backendState };
  }

  function getCloseInfo() {
    return { ..._closeInfo };
  }

  // Legacy compat: the old machine exposed .transition() — alias to dispatch
  function transition(event, detail) {
    return dispatch(event, detail);
  }

  return {
    dispatch,
    transition,
    snapshot,
    getStatus,
    isConnected,
    setHandshakeId,
    setOnTransition,
    setOnGlobalStateChange,
    setBackendState,
    getBackendState,
    getCloseInfo,
  };
}

// ── Helpers ─────────────────────────────────────────────────────────

function _phaseFor(status) {
  switch (status) {
    case TransportStatus.IDLE:
    case TransportStatus.CONFIGURING:
      return 'boot';
    case TransportStatus.CONNECTING:
    case TransportStatus.SOCKET_OPEN:
    case TransportStatus.AUTHENTICATING:
      return 'handshake';
    case TransportStatus.AUTHENTICATED:
    case TransportStatus.PROJECTION_WAITING:
    case TransportStatus.READY:
      return 'operational';
    case TransportStatus.DEGRADED:
      return 'degraded';
    case TransportStatus.DISCONNECTED:
      return 'recovery';
    case TransportStatus.FAILED:
      return 'terminal';
    default:
      return 'unknown';
  }
}

function _isConnectedStatus(status) {
  return (
    status === TransportStatus.AUTHENTICATED ||
    status === TransportStatus.PROJECTION_WAITING ||
    status === TransportStatus.READY
  );
}

// Legacy compat: createTransportStateMachine → createTransportStateAuthority
export function createTransportStateMachine(options = {}) {
  return createTransportStateAuthority(options);
}

// ── Status contradiction detector ───────────────────────────────────
// Compares the rendered status label to the canonical transport state.
// Emits frontend.status_contradiction_detected if they don't agree.
function detectStatusContradiction(snap, renderedLabel) {
  if (!snap) return null;
  const canonical = snap.transport.status;
  const connectedStatuses = new Set([
    TransportStatus.AUTHENTICATED,
    TransportStatus.PROJECTION_WAITING,
    TransportStatus.READY,
  ]);
  const disconnectedRendered = (
    renderedLabel === 'Disconnected' ||
    renderedLabel === 'Connecting' ||
    renderedLabel === (STATUS_LABELS[TransportStatus.DISCONNECTED] || 'Disconnected')
  );
  if (connectedStatuses.has(canonical) && disconnectedRendered) {
    const contradiction = {
      type: 'frontend.status_contradiction_detected',
      canonical_status: canonical,
      rendered_label: renderedLabel,
      canonical_phase: snap.transport.phase,
      ws_connected: snap.wsConnected,
      handshake_id: snap.transport.handshakeId,
      timestamp: new Date().toISOString(),
    };
    emitBreadcrumb(contradiction);
    return contradiction;
  }
  return null;
}

export {
  TransportStatus,
  TransportState,
  TransportEvent,
  STATUS_LABELS,
  STATUS_CHIP_CLASS,
  LEGACY_EVENT_MAP,
  EVENT_TO_STATUS,
  ALLOWED_TRANSITIONS,
  emitBreadcrumb,
  detectStatusContradiction,
};

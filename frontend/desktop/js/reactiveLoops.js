// Rig Relay — Reactive Loops

import { state } from './state.js';
import { TransportStatus } from './transportState.js';
import { createNotification, resolveNotification, getActiveNotifications } from './notifications.js';
import { recordFrontendEvent } from './telemetry/frontendTrace.js';

const PROJECTION_STALE_KEY = 'projection_stale';
const CONNECTION_DEGRADED_KEY = 'connection_degraded';
const CONNECTION_LOST_KEY = 'connection_lost';
const CONNECTION_RECONNECTING_KEY = 'connection_reconnecting';
const PROVIDER_MISSING_KEY = 'provider_missing';
const RELEASE_GATE_BLOCKED_KEY = 'release_gate_blocked';
const TELEMETRY_DEGRADED_KEY = 'telemetry_degraded';
const FIRST_LAUNCH_SETUP_KEY = 'first_launch_setup';
const INTENT_REFUSAL_KEY_PREFIX = 'intent_refusal_';
const TRANSPORT_ERROR_KEY = 'transport_error';

const CONNECTION_DEGRADED_THRESHOLD = 3;
const PROJECTION_STALE_THRESHOLD = 2;
const PROJECTION_STALE_WARNING_MS = 30000;
const PROJECTION_STALE_ERROR_MS = 60000;
const PROJECTION_FRESH_MS = 10000;
const INFO_EXPIRE_MS = 300000;

const RECOVERY_STATUSES = new Set([
  TransportStatus.READY,
  TransportStatus.AUTHENTICATED,
]);

const _loops = [];
const _loopStates = new Map();
let _paused = false;
let _visibilityHandler = null;
export let _isRunning = false;

function _nowMs() {
  return Date.now();
}

// ── Loop registry ────────────────────────────────────────────────────

export function registerLoop(name, fn, intervalMs) {
  _loops.push({ name, fn, intervalMs, id: null });
}

function _ensureLoopState(name) {
  if (!_loopStates.has(name)) {
    _loopStates.set(name, {});
  }
  return _loopStates.get(name);
}

// ── Start / Stop / Pause / Resume ────────────────────────────────────

export function startReactiveLoops() {
  if (_isRunning) return;
  _registerBuiltins();
  _isRunning = true;
  for (const loop of _loops) {
    loop.id = setInterval(loop.fn, loop.intervalMs);
    if (loop.name === 'first_launch_setup') {
      loop.fn();
    }
  }
  _attachVisibility();
}

export function stopReactiveLoops() {
  _isRunning = false;
  for (const loop of _loops) {
    if (loop.id !== null) {
      clearInterval(loop.id);
      loop.id = null;
    }
  }
  _detachVisibility();
  _loopStates.clear();
}

export function pauseLoops() {
  if (_paused || !_isRunning) return;
  _paused = true;
  for (const loop of _loops) {
    if (loop.id !== null) {
      clearInterval(loop.id);
      loop.id = null;
    }
  }
}

export function resumeLoops() {
  if (!_paused || !_isRunning) return;
  _paused = false;
  for (const loop of _loops) {
    if (loop.id === null) {
      loop.id = setInterval(loop.fn, loop.intervalMs);
    }
  }
}

function _attachVisibility() {
  _visibilityHandler = function () {
    if (document.hidden) {
      pauseLoops();
    } else {
      resumeLoops();
    }
  };
  document.addEventListener('visibilitychange', _visibilityHandler);
}

function _detachVisibility() {
  if (_visibilityHandler) {
    document.removeEventListener('visibilitychange', _visibilityHandler);
    _visibilityHandler = null;
  }
}

// ── Notification helpers ──────────────────────────────────────────────

function _notify(kind, source, dedupeKey, title, body, opts) {
  const defaults = {
    priority: 'normal',
    requiresAck: true,
    expiresIn: null,
    action: null,
  };
  if (kind === 'error') defaults.priority = 'high';
  if (kind === 'info') {
    defaults.priority = 'low';
    defaults.requiresAck = false;
    defaults.expiresIn = INFO_EXPIRE_MS;
  }
  const o = opts || {};
  const expiresInMs = o.expiresIn !== undefined ? o.expiresIn : defaults.expiresIn;
  const actionObj = o.action || defaults.action;
  createNotification({
    kind,
    source,
    title,
    body: body || '',
    priority: o.priority || defaults.priority,
    requiresAck: o.requiresAck !== undefined ? o.requiresAck : defaults.requiresAck,
    expires_at: expiresInMs ? new Date(Date.now() + expiresInMs).toISOString() : null,
    action_buttons: actionObj ? [actionObj] : [],
  });
  recordFrontendEvent('feedback_notification_created', {
    dedup_key: dedupeKey || '',
    kind: kind || '',
    source: 'reactive_loops',
  })
}

function _resolve(dedupeKey) {
  resolveNotification(dedupeKey);
  recordFrontendEvent('feedback_notification_resolved', {
    dedup_key: dedupeKey || '',
    source: 'reactive_loops',
  })
}

// ── Projection Freshness Monitor ──────────────────────────────────────

function _projectionFreshness() {
  const ls = _ensureLoopState('projection_freshness');
  const proj = state.projection;
  if (!proj || !proj.generated_at) return;

  const age = _nowMs() - new Date(proj.generated_at).getTime();
  const fresh = age <= PROJECTION_FRESH_MS;
  const staleWarning = age > PROJECTION_STALE_WARNING_MS;
  const staleError = age > PROJECTION_STALE_ERROR_MS;

  if (staleError) {
    ls.consecutiveBad = (ls.consecutiveBad || 0) + 1;
    if (ls.consecutiveBad >= PROJECTION_STALE_THRESHOLD && ls.lastEmitted !== 'error') {
      _notify('error', 'projection', PROJECTION_STALE_KEY,
        'Projection Stale',
        'The cockpit projection is over 60 seconds old. The backend may have failed.');
      ls.lastEmitted = 'error';
    }
    return;
  }

  if (staleWarning) {
    ls.consecutiveBad = (ls.consecutiveBad || 0) + 1;
    if (ls.consecutiveBad >= PROJECTION_STALE_THRESHOLD && ls.lastEmitted !== 'warning' && ls.lastEmitted !== 'error') {
      _notify('warning', 'projection', PROJECTION_STALE_KEY,
        'Projection Stale',
        'The cockpit projection is over 30 seconds old. The backend may be degraded.');
      ls.lastEmitted = 'warning';
    }
    return;
  }

  if (fresh && ls.lastEmitted) {
    ls.consecutiveBad = 0;
    _resolve(PROJECTION_STALE_KEY);
    ls.lastEmitted = null;
    return;
  }

  ls.consecutiveBad = 0;
}

// ── Connection Degraded Monitor ───────────────────────────────────────

function _connectionDegraded() {
  const ls = _ensureLoopState('connection_degraded');
  const status = state.transport.status;

  if (ls.lastStatus !== status) {
    ls.lastStatus = status;
    ls.degradedCount = 0;
  }

  if (status === TransportStatus.DEGRADED) {
    ls.degradedCount = (ls.degradedCount || 0) + 1;
    if (ls.degradedCount >= CONNECTION_DEGRADED_THRESHOLD && !ls.degradedNotified) {
      _notify('warning', 'transport', CONNECTION_DEGRADED_KEY,
        'Connection Degraded',
        'The WebSocket connection is experiencing issues.');
      ls.degradedNotified = true;
    }
    return;
  }

  if (status === TransportStatus.DISCONNECTED || status === TransportStatus.FAILED) {
    if (!ls.disconnectedNotified) {
      if (ls.degradedNotified) {
        _resolve(CONNECTION_DEGRADED_KEY);
        ls.degradedNotified = false;
      }
      _notify('error', 'transport', CONNECTION_LOST_KEY,
        'Connection Lost',
        'The WebSocket connection has been lost. Attempting to reconnect.');
      ls.disconnectedNotified = true;
    }
    return;
  }

  if (status === TransportStatus.CONNECTING) {
    if (!ls.reconnectingNotified) {
      _notify('info', 'transport', CONNECTION_RECONNECTING_KEY,
        'Reconnecting...',
        'Attempting to reconnect to the Rig Relay backend.');
      ls.reconnectingNotified = true;
    }
    return;
  }

  if (RECOVERY_STATUSES.has(status)) {
    if (ls.degradedNotified) {
      _resolve(CONNECTION_DEGRADED_KEY);
      ls.degradedNotified = false;
    }
    if (ls.disconnectedNotified) {
      _resolve(CONNECTION_LOST_KEY);
      ls.disconnectedNotified = false;
    }
    if (ls.reconnectingNotified) {
      _resolve(CONNECTION_RECONNECTING_KEY);
      ls.reconnectingNotified = false;
    }
    ls.degradedCount = 0;
  }
}

// ── Provider Missing Nudge ────────────────────────────────────────────

function _providerMissingNudge() {
  const ls = _ensureLoopState('provider_missing');
  const proj = state.projection;
  if (!proj) return;

  const configuredCount = proj.providers && typeof proj.providers.configured === 'number'
    ? proj.providers.configured
    : 0;

  if (configuredCount === 0) {
    if (!ls.notified) {
      _notify('warning', 'provider', PROVIDER_MISSING_KEY,
        'No Model Provider Configured',
        'Set up an API key to enable AI features.',
        { action: { label: 'Open System', intent: 'navigate_to', params: { mode: 'system' } } });
      ls.notified = true;
    }
  } else if (ls.notified) {
    _resolve(PROVIDER_MISSING_KEY);
    ls.notified = false;
  }
}

// ── Release Gate Blocked Nudge ────────────────────────────────────────

function _releaseGateBlockedNudge() {
  const ls = _ensureLoopState('release_gate_blocked');
  const proj = state.projection;
  if (!proj || !proj._release_gate) return;

  const rg = proj._release_gate;
  const blocked = rg.overall_status === 'blocked' || rg.open_blocker_count > 0;

  if (blocked) {
    if (!ls.notified || ls.lastBlockerCount !== rg.open_blocker_count) {
      _notify('warning', 'release_gate', RELEASE_GATE_BLOCKED_KEY,
        'Release Gate Blocked',
        rg.open_blocker_count + ' blocker(s) are preventing release. See the release gate widget for details.');
      ls.notified = true;
      ls.lastBlockerCount = rg.open_blocker_count;
    }
  } else if (ls.notified) {
    _resolve(RELEASE_GATE_BLOCKED_KEY);
    ls.notified = false;
    ls.lastBlockerCount = 0;
  }
}

// ── Telemetry Degraded Disclosure ─────────────────────────────────────

function _telemetryDegradedDisclosure() {
  const ls = _ensureLoopState('telemetry_degraded');
  const proj = state.projection;
  if (!proj) return;

  if (proj.telemetry_degraded) {
    if (!ls.notified) {
      _notify('info', 'telemetry', TELEMETRY_DEGRADED_KEY,
        'Telemetry in Degraded Mode',
        'Telemetry is currently disabled. Some observability features are unavailable.');
      ls.notified = true;
    }
  } else if (ls.notified) {
    _resolve(TELEMETRY_DEGRADED_KEY);
    ls.notified = false;
  }
}

// ── First Launch Setup Nudge ──────────────────────────────────────────

function _firstLaunchSetupNudge() {
  const ls = _ensureLoopState('first_launch_setup');
  if (ls.hasRun && ls.dismissed) return;
  ls.hasRun = true;

  const proj = state.projection;
  const hasProviders = proj && proj.providers && proj.providers.configured > 0;
  const hasIdentity = !!(state.identity && (state.identity.signed_in || state.identity.authenticated));
  const hasReleaseGate = !!(proj && proj._release_gate);

  if (!hasProviders && !hasIdentity && !hasReleaseGate) {
    if (!ls.notified) {
      _notify('info', 'projection', FIRST_LAUNCH_SETUP_KEY,
        'Welcome to Rig Relay',
        'Set up a model provider to get started. Use /help for available commands.',
        { expiresIn: INFO_EXPIRE_MS * 2 });
      ls.notified = true;
    }
  } else if (ls.notified) {
    _resolve(FIRST_LAUNCH_SETUP_KEY);
    ls.dismissed = true;
  }
}

// ── Intent Refusal Monitor ────────────────────────────────────────────

function _intentRefusalMonitor() {
  const ls = _ensureLoopState('intent_refusal');
  const intent = state.ralph && state.ralph.lastIntent;
  if (!intent || intent.status !== 'refused') return;

  const name = intent.name || 'unknown';
  const dedupeKey = INTENT_REFUSAL_KEY_PREFIX + name;

  if (!ls.seenRefusals) ls.seenRefusals = new Set();
  if (ls.seenRefusals.has(name)) return;

  const errorCode = intent.error_code || 'refused';
  const hint = intent.hint || '';
  let body = 'Error code: ' + errorCode;
  if (hint) body += '\nHint: ' + hint;

  _notify('warning', 'intent', dedupeKey,
    'Intent Refused: ' + name,
    body);

  ls.seenRefusals.add(name);
}

// ── Transport Trace Failure Monitor ───────────────────────────────────

function _transportTraceFailure() {
  const ls = _ensureLoopState('trace_failure');
  const lastError = state.transport.lastError;

  if (lastError && lastError !== ls.lastSeenError) {
    _notify('error', 'transport', TRANSPORT_ERROR_KEY,
      'Transport Error',
      lastError);
    ls.lastSeenError = lastError;
  }
}

// ── Built-in registration ─────────────────────────────────────────────

function _registerBuiltins() {
  registerLoop('projection_freshness', _projectionFreshness, 10000);
  registerLoop('connection_degraded', _connectionDegraded, 5000);
  registerLoop('provider_missing', _providerMissingNudge, 30000);
  registerLoop('release_gate_blocked', _releaseGateBlockedNudge, 30000);
  registerLoop('telemetry_degraded', _telemetryDegradedDisclosure, 15000);
  registerLoop('first_launch_setup', _firstLaunchSetupNudge, 60000);
  registerLoop('intent_refusal', _intentRefusalMonitor, 10000);
  registerLoop('trace_failure', _transportTraceFailure, 10000);
}

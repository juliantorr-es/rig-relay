// Rig Relay — Runtime Kernel: Action Type & Enum Constants
// Browser-side runtime kernel. No React, Redux, Vue, or new dependencies.
// Plain ES modules. Actions are pure data; the kernel reducer owns all transitions.

// ── Action type constants ─────────────────────────────────────────────

const ActionTypes = Object.freeze({
  // Boot state machine: orchestrator.js drives the boot lifecycle
  BOOT_PHASE_TRANSITION: 'BOOT_PHASE_TRANSITION',
  // Transport authority: transportState.js reducer owns transport status transitions
  TRANSPORT_STATUS_CHANGE: 'TRANSPORT_STATUS_CHANGE',
  // Projection pipeline: projection.js drives digest comparison and widget dispatch
  PROJECTION_RECEIVED: 'PROJECTION_RECEIVED',
  PROJECTION_STALE: 'PROJECTION_STALE',
  // Widget lifecycle: widgets acquire a projection snapshot before reaching READY
  WIDGET_STATUS_CHANGE: 'WIDGET_STATUS_CHANGE',
  WIDGET_MOUNT: 'WIDGET_MOUNT',
  WIDGET_UNMOUNT: 'WIDGET_UNMOUNT',
  // Intent dispatch: intents are queued, sent, acknowledged, and resolved
  INTENT_QUEUED: 'INTENT_QUEUED',
  INTENT_DISPATCHED: 'INTENT_DISPATCHED',
  INTENT_ACKNOWLEDGED: 'INTENT_ACKNOWLEDGED',
  INTENT_RESULT: 'INTENT_RESULT',
  INTENT_CLEAR: 'INTENT_CLEAR',
  // Mode transitions: operator/review/system/technical layout switch
  MODE_CHANGE: 'MODE_CHANGE',
  // Notification ring buffer: add at head, drain from tail when locked
  NOTIFICATION_ADD: 'NOTIFICATION_ADD',
  NOTIFICATION_DRAIN: 'NOTIFICATION_DRAIN',
  NOTIFICATION_LOCK: 'NOTIFICATION_LOCK',
  NOTIFICATION_UNLOCK: 'NOTIFICATION_UNLOCK',
  // Agent loop surface: signals from the backend agent loop
  LOOP_STARTED: 'LOOP_STARTED',
  LOOP_CANCELLED: 'LOOP_CANCELLED',
  LOOP_COMPLETED: 'LOOP_COMPLETED',
  LOOP_FAILED: 'LOOP_FAILED',
  // Multi-tab coordinator: only one tab is primary; secondaries detect via BroadcastChannel
  MULTI_TAB_SECONDARY_DETECTED: 'MULTI_TAB_SECONDARY_DETECTED',
  MULTI_TAB_PRIMARY_CLAIMED: 'MULTI_TAB_PRIMARY_CLAIMED',
  MULTI_TAB_PRIMARY_LOST: 'MULTI_TAB_PRIMARY_LOST',
  // Degradation: graceful mode when a subsystem is unhealthy
  DEGRADATION_SET: 'DEGRADATION_SET',
  DEGRADATION_CLEARED: 'DEGRADATION_CLEARED',
  // Evidence flush: triggers telemetry/evidence bundle drain
  EVIDENCE_FLUSH: 'EVIDENCE_FLUSH',
  // User preferences: animation and sound toggles
  PREFERENCE_CHANGE: 'PREFERENCE_CHANGE',
  // Reset: full state reset (e.g., transport reconnect after fatal)
  RESET: 'RESET',
});

// ── Boot phase enum ───────────────────────────────────────────────────
// Owned by the boot state machine. Precondition: static shell rendered.
// Terminal phases: READY (operational), DEGRADED (reduced), FAILED (fatal).

const BootPhase = Object.freeze({
  STATIC_SHELL_LOADED: 'static_shell_loaded',
  RUNTIME_CONFIG_LOADING: 'runtime_config_loading',
  RUNTIME_CONFIG_LOADED: 'runtime_config_loaded',
  RUNTIME_CONFIG_FAILED: 'runtime_config_failed',
  TRANSPORT_CONNECTING: 'transport_connecting',
  AUTHENTICATING: 'authenticating',
  PROJECTION_WAITING: 'projection_waiting',
  RENDERING: 'rendering',
  READY: 'ready',
  DEGRADED: 'degraded',
  FAILED: 'failed',
});

// ── Intent status enum ────────────────────────────────────────────────
// Owned by the intent queue. Precondition: intent must be dispatched
// before it can be acknowledged, succeeded, or refused.
// Terminal: SUCCEEDED, REFUSED, FAILED, CANCELLED.

const IntentStatus = Object.freeze({
  IDLE: 'idle',
  QUEUED: 'queued',
  SENDING: 'sending',
  ACKNOWLEDGED: 'acknowledged',
  SUCCEEDED: 'succeeded',
  REFUSED: 'refused',
  FAILED: 'failed',
  CANCELLED: 'cancelled',
});

// ── Widget status enum ────────────────────────────────────────────────
// Owned by the widget lifecycle. Precondition: widget must be mounted
// before it can wait for projection. Only READY widgets render content.
// STALE: projection digest changed but widget has not re-rendered yet.

const WidgetStatus = Object.freeze({
  UNAVAILABLE: 'unavailable',
  WAITING_FOR_PROJECTION: 'waiting_for_projection',
  RENDERING: 'rendering',
  READY: 'ready',
  STALE: 'stale',
  FAILED: 'failed',
});

// ── Mode type enum ────────────────────────────────────────────────────
// Owned by the mode selector. Precondition: mode change triggers
// widget panel re-layout and disclosure defaults reset.

const ModeType = Object.freeze({
  OPERATOR: 'operator',
  REVIEW: 'review',
  SYSTEM: 'system',
  TECHNICAL: 'technical',
});

// ── Loop type enum ────────────────────────────────────────────────────
// Owned by the kernel loop manager. Each loop has a distinct lifecycle.
// Evidence event emitted on start and cancel.

const LoopType = Object.freeze({
  PROJECTION_FRESHNESS: 'projectionFreshness',
  RECONNECT_BACKOFF: 'reconnectBackoff',
  AUTH_POLLING: 'authPolling',
  NOTIFICATION_DRAIN: 'notificationDrain',
  EVIDENCE_FLUSH: 'evidenceFlush',
});

export {
  ActionTypes,
  BootPhase,
  IntentStatus,
  WidgetStatus,
  ModeType,
  LoopType,
};

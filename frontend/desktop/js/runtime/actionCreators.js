// Rig Relay — Runtime Kernel: Action Creators
// Browser-side runtime kernel. No React, Redux, Vue, or new dependencies.
// Plain ES modules. Actions are pure data; the kernel reducer owns all transitions.

import { ActionTypes, BootPhase, IntentStatus, WidgetStatus, ModeType, LoopType } from './constants.js';

// ── Action creators ───────────────────────────────────────────────────

// Boot phase transition: valid transitions are gated by the boot state
// machine. phase must be a BootPhase value. error is set on FAILED/DEGRADED.
function bootPhaseTransition(phase, error) {
  return {
    type: ActionTypes.BOOT_PHASE_TRANSITION,
    payload: { phase: phase, error: error || null },
  };
}

// Transport status change: the transport authority owns the status transition.
// detail carries handshake_id, reason, ws_url as applicable.
function transportStatusChange(status, detail) {
  return {
    type: ActionTypes.TRANSPORT_STATUS_CHANGE,
    payload: { status: status, detail: detail || {} },
  };
}

// Projection received: data is the projection object, digest is server-provided
// or computed. Evidence event: rig.relay.frontend.projection.received
function projectionReceived(data, digest) {
  return {
    type: ActionTypes.PROJECTION_RECEIVED,
    payload: { data: data, digest: digest || '', receivedAt: new Date().toISOString() },
  };
}

// Projection stale: marks the projection as stale (digest mismatch detected
// by freshness loop). No data payload — the next PROJECTION_RECEIVED refreshes.
function projectionStale() {
  return {
    type: ActionTypes.PROJECTION_STALE,
    payload: { staleAt: new Date().toISOString() },
  };
}

// Widget status change: widgetId identifies the widget in the registry.
// status must be a WidgetStatus value.
function widgetStatusChange(widgetId, status, error) {
  return {
    type: ActionTypes.WIDGET_STATUS_CHANGE,
    payload: { widgetId: widgetId, status: status, error: error || null },
  };
}

// Widget mount: adds a widget entry with UNAVAILABLE status.
function widgetMount(widgetId) {
  return {
    type: ActionTypes.WIDGET_MOUNT,
    payload: { widgetId: widgetId, mountedAt: new Date().toISOString() },
  };
}

// Widget unmount: removes a widget entry from the registry.
function widgetUnmount(widgetId) {
  return {
    type: ActionTypes.WIDGET_UNMOUNT,
    payload: { widgetId: widgetId },
  };
}

// Intent queued: places the intent into the queue before dispatch.
function intentQueued(intentId, name, params) {
  return {
    type: ActionTypes.INTENT_QUEUED,
    payload: { intentId: intentId, name: name, params: params || {} },
  };
}

// Intent dispatched: marks the intent as SENDING. Precondition: intent
// must be QUEUED. Evidence event: rig.relay.frontend.intent.dispatched
function intentDispatched(intentId) {
  return {
    type: ActionTypes.INTENT_DISPATCHED,
    payload: { intentId: intentId, dispatchedAt: new Date().toISOString() },
  };
}

// Intent acknowledged: backend confirmed receipt. Precondition: intent
// must be SENDING.
function intentAcknowledged(intentId) {
  return {
    type: ActionTypes.INTENT_ACKNOWLEDGED,
    payload: { intentId: intentId, acknowledgedAt: new Date().toISOString() },
  };
}

// Intent result: terminal action. status must be a terminal IntentStatus
// (SUCCEEDED, REFUSED, FAILED, CANCELLED). result carries the backend response.
// Evidence event: rig.relay.frontend.intent.resolved
function intentResult(intentId, status, result, error) {
  return {
    type: ActionTypes.INTENT_RESULT,
    payload: {
      intentId: intentId,
      status: status,
      result: result || null,
      error: error || null,
      resolvedAt: new Date().toISOString(),
    },
  };
}

// Intent clear: removes the intent from the registry and queue.
function intentClear(intentId) {
  return {
    type: ActionTypes.INTENT_CLEAR,
    payload: { intentId: intentId },
  };
}

// Mode change: triggers widget panel re-layout and disclosure defaults reset.
// mode must be a ModeType value.
function modeChange(mode) {
  return {
    type: ActionTypes.MODE_CHANGE,
    payload: { mode: mode },
  };
}

// Notification add: pushes notification onto the ring buffer head.
// Evidence event: rig.relay.frontend.notification.emitted
function notificationAdd(notification) {
  return {
    type: ActionTypes.NOTIFICATION_ADD,
    payload: {
      id: notification.id,
      level: notification.level || 'info',
      message: notification.message || '',
      timestamp: notification.timestamp || new Date().toISOString(),
      source: notification.source || 'kernel',
    },
  };
}

// Notification drain: removes drained notifications. Only valid when
// notificationsLocked is true.
function notificationDrain(ids) {
  return {
    type: ActionTypes.NOTIFICATION_DRAIN,
    payload: { ids: ids || [] },
  };
}

// Notification lock: locks the buffer for drain; new notifications
// accumulate in a pending queue while locked.
function notificationLock() {
  return { type: ActionTypes.NOTIFICATION_LOCK };
}

// Notification unlock: unlocks the buffer; pending notifications
// are merged in after unlock.
function notificationUnlock() {
  return { type: ActionTypes.NOTIFICATION_UNLOCK };
}

// Loop started: registers a loop in the loop manager. loopId is unique.
// Evidence event: rig.relay.frontend.loop.started
function loopStarted(loopId, loopType, abortController) {
  return {
    type: ActionTypes.LOOP_STARTED,
    payload: {
      loopId: loopId,
      loopType: loopType,
      status: 'running',
      abortController: abortController || null,
      startedAt: new Date().toISOString(),
    },
  };
}

// Loop cancelled: aborts the loop via its abortController. Precondition:
// loop must be running. Evidence event: rig.relay.frontend.loop.cancelled
function loopCancelled(loopId) {
  return {
    type: ActionTypes.LOOP_CANCELLED,
    payload: { loopId: loopId, cancelledAt: new Date().toISOString() },
  };
}

// Loop completed: the loop finished successfully. Precondition: loop
// must be running.
function loopCompleted(loopId) {
  return {
    type: ActionTypes.LOOP_COMPLETED,
    payload: { loopId: loopId, completedAt: new Date().toISOString() },
  };
}

// Loop failed: the loop encountered an error. Precondition: loop must
// be running.
function loopFailed(loopId, error) {
  return {
    type: ActionTypes.LOOP_FAILED,
    payload: { loopId: loopId, error: error || null, failedAt: new Date().toISOString() },
  };
}

// Multi-tab secondary detected: another tab claimed primary.
function multiTabSecondaryDetected(channelName) {
  return {
    type: ActionTypes.MULTI_TAB_SECONDARY_DETECTED,
    payload: { channelName: channelName || 'rig-relay-cockpit' },
  };
}

// Multi-tab primary claimed: this tab is now primary.
function multiTabPrimaryClaimed(channelName) {
  return {
    type: ActionTypes.MULTI_TAB_PRIMARY_CLAIMED,
    payload: { channelName: channelName || 'rig-relay-cockpit' },
  };
}

// Multi-tab primary lost: this tab is no longer primary (e.g., closed).
function multiTabPrimaryLost(channelName) {
  return {
    type: ActionTypes.MULTI_TAB_PRIMARY_LOST,
    payload: { channelName: channelName || 'rig-relay-cockpit' },
  };
}

// Degradation set: a subsystem is unhealthy. reason is human-readable.
// Evidence event: rig.relay.frontend.degradation.set
function degradationSet(reason) {
  return {
    type: ActionTypes.DEGRADATION_SET,
    payload: { reason: reason, setAt: new Date().toISOString() },
  };
}

// Degradation cleared: all degradation reasons resolved.
// Evidence event: rig.relay.frontend.degradation.cleared
function degradationCleared() {
  return {
    type: ActionTypes.DEGRADATION_CLEARED,
    payload: { clearedAt: new Date().toISOString() },
  };
}

// Evidence flush: triggers telemetry/evidence drain to backend.
// Evidence event: rig.relay.frontend.evidence.flush
function evidenceFlush() {
  return {
    type: ActionTypes.EVIDENCE_FLUSH,
    payload: { flushAt: new Date().toISOString() },
  };
}

// Preference change: toggles animation or sound.
function preferenceChange(key, value) {
  return {
    type: ActionTypes.PREFERENCE_CHANGE,
    payload: { key: key, value: value },
  };
}

// Reset: full state reset (e.g., after transport fatal or reconnect).
// Preserves preferences (animation, sound) but clears everything else.
function reset() {
  return {
    type: ActionTypes.RESET,
    payload: { resetAt: new Date().toISOString() },
  };
}

export {
  bootPhaseTransition,
  transportStatusChange,
  projectionReceived,
  projectionStale,
  widgetStatusChange,
  widgetMount,
  widgetUnmount,
  intentQueued,
  intentDispatched,
  intentAcknowledged,
  intentResult,
  intentClear,
  modeChange,
  notificationAdd,
  notificationDrain,
  notificationLock,
  notificationUnlock,
  loopStarted,
  loopCancelled,
  loopCompleted,
  loopFailed,
  multiTabSecondaryDetected,
  multiTabPrimaryClaimed,
  multiTabPrimaryLost,
  degradationSet,
  degradationCleared,
  evidenceFlush,
  preferenceChange,
  reset,
};

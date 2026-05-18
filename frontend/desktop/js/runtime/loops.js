// Rig Relay — Frontend Runtime Loop Helpers
// Owned by: LoopSupervisor. Manages loop lifecycle via AbortController.
// Evidence: LOOP_STARTED / LOOP_CANCELLED dispatched on lifecycle changes.

import {
  ActionTypes as AT,
  LoopType,
  WidgetStatus,
  IntentStatus,
  projectionStale,
  widgetStatusChange,
} from './actions.js';
import {
  getBootPhase,
  isBootReady,
  isTransportConnected,
  getVisibleWidgets,
  getCurrentMode,
  buildStateSummary,
} from './selectors.js';
import { EvidenceEventType } from './evidence.js';

export function createLoopSupervisor(dispatch) {
  const controllers = {};
  const intervals = {};

  function startLoop(loopId, fn, intervalMs) {
    if (controllers[loopId]) return;
    const controller = new AbortController();
    controllers[loopId] = controller;
    intervals[loopId] = setInterval(() => {
      if (controller.signal.aborted) return;
      try { fn(); } catch (_) { /* swallow */ }
    }, intervalMs);
    dispatch({ type: AT.LOOP_STARTED, payload: { loopId } });
  }

  function cancelLoop(loopId) {
    const controller = controllers[loopId];
    if (controller) {
      controller.abort();
      delete controllers[loopId];
    }
    const intervalId = intervals[loopId];
    if (intervalId != null) {
      clearInterval(intervalId);
      delete intervals[loopId];
    }
    dispatch({ type: AT.LOOP_CANCELLED, payload: { loopId } });
  }

  function cancelAllLoops() {
    for (const loopId of Object.keys(controllers)) {
      cancelLoop(loopId);
    }
  }

  function isLoopRunning(loopId) {
    return controllers[loopId] != null && !controllers[loopId].signal.aborted;
  }

  return Object.freeze({ startLoop, cancelLoop, cancelAllLoops, isLoopRunning });
}

export function startFreshnessLoop(getState, dispatch, loopSupervisor) {
  loopSupervisor.startLoop(
    LoopType.PROJECTION_FRESHNESS,
    () => {
      const st = getState();
      const lastReceived = st.projection.lastReceivedAt;
      if (lastReceived && Date.now() - lastReceived > 30000) {
        dispatch(projectionStale());
      }
    },
    15000,
  );
}

export function startIntentFlushLoop(getState, dispatch, loopSupervisor, intentSendFn) {
  loopSupervisor.startLoop(
    'intentFlush',
    () => {
      const st = getState();
      if (!isBootReady(st) || !isTransportConnected(st)) return;
      if (st.intentQueue.length === 0) return;

      for (const intentId of st.intentQueue) {
        const intent = st.intents[intentId];
        if (intent && intent.status === IntentStatus.QUEUED && intentSendFn) {
          intentSendFn(intentId, intent);
        }
      }
    },
    1000,
  );
}

export function startNotificationDrainLoop(getState, dispatch, loopSupervisor) {
  loopSupervisor.startLoop(
    LoopType.NOTIFICATION_DRAIN,
    () => {
      const st = getState();
      if (st.notificationsLocked) return;
      if (st.notifications.length === 0) return;
      dispatch({ type: AT.NOTIFICATION_DRAIN });
    },
    2000,
  );
}

export function startEvidenceFlushLoop(getState, evidence, loopSupervisor) {
  loopSupervisor.startLoop(
    LoopType.EVIDENCE_FLUSH,
    () => {
      const st = getState();
      evidence.record(EvidenceEventType.KERNEL_SNAPSHOT, buildStateSummary(st));
    },
    30000,
  );
}

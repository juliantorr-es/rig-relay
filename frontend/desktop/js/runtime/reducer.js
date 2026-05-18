// Rig Relay — Runtime Kernel: Pure Root Reducer
// Extracted from kernel.js. No side effects, no DOM, no network.
// Plain ES module.

import { ActionTypes as AT, BootPhase as BP, IntentStatus, INITIAL_STATE } from './actions.js'

// ── Deep-freeze utility (fail-safe — frozen objects pass through) ────

export function _deepFreeze(obj) {
  if (obj == null || typeof obj !== 'object') return obj;
  if (Object.isFrozen(obj)) return obj;
  Object.freeze(obj);
  for (const key of Object.keys(obj)) {
    _deepFreeze(obj[key]);
  }
  return obj;
}

function _uid() {
  return Date.now().toString(36) + '_' + Math.random().toString(36).slice(2, 8);
}

export function _freshState() {
  return JSON.parse(JSON.stringify(INITIAL_STATE));
}

// ── Root reducer (pure — no side effects, no DOM, no network) ───────
// Every case creates a new state object. Never mutates previous state.
// Each case is owned by a specific state machine.

export function rootReducer(state, action) {
  switch (action.type) {

    // BootFSM owns this transition
    // Precondition: payload.phase must be a valid BootPhase value
    // Evidence: emitted by post-reducer effects
    case AT.BOOT_PHASE_TRANSITION: {
      const nextBoot = { ...state.boot, phase: action.payload.phase };
      if (action.payload.error) {
        nextBoot.error = action.payload.error;
      }
      if (action.payload.phase === BP.READY) {
        nextBoot.readyAt = Date.now();
      }
      return { ...state, boot: nextBoot };
    }

    // Transport authority owns this transition
    // Precondition: payload contains transport status fields
    case AT.TRANSPORT_STATUS_CHANGE: {
      const { status, detail } = action.payload;
      return {
        ...state,
        transport: {
          ...state.transport,
          status: status || state.transport.status,
          lastError: detail?.reason || detail?.message || state.transport.lastError,
          handshakeId: detail?.handshake_id || state.transport.handshakeId,
          wsConnected: status === 'authenticated' || status === 'projection_waiting' || status === 'ready',
          updatedAt: Date.now(),
          lastEvent: action.type,
        },
      };
    }

    // Projection pipeline owns this transition
    // Precondition: payload must contain projection data + digest
    case AT.PROJECTION_RECEIVED: {
      return {
        ...state,
        projection: {
          data: action.payload.data,
          digest: action.payload.digest || '',
          lastReceivedAt: action.payload.receivedAt || Date.now(),
          stale: false,
        },
      };
    }

    // ProjectionFreshnessLoop owns this transition
    // Effect: widgets may show stale badge
    case AT.PROJECTION_STALE: {
      return {
        ...state,
        projection: { ...state.projection, stale: true },
      };
    }

    // Widget manager owns this transition
    case AT.WIDGET_STATUS_CHANGE: {
      return {
        ...state,
        widgets: {
          ...state.widgets,
          [action.payload.widgetId]: {
            ...(state.widgets[action.payload.widgetId] || {}),
            status: action.payload.status,
            error: action.payload.error || null,
            mountedAt: action.payload.mountedAt || null,
          },
        },
      };
    }

    // IntentFSM owns these transitions
    // Effect: if not ready, intentId is pushed to intentQueue via reducer
    case AT.INTENT_QUEUED: {
      return {
        ...state,
        intents: {
          ...state.intents,
          [action.payload.intentId]: {
            status: IntentStatus.QUEUED,
            name: action.payload.name || '',
            params: action.payload.params || {},
            dispatchedAt: Date.now(),
            result: null,
            resolvedAt: null,
            error: null,
          },
        },
        intentQueue: [...state.intentQueue, action.payload.intentId],
      };
    }

    case AT.INTENT_DISPATCHED: {
      const id = action.payload.intentId;
      const existing = state.intents[id];
      if (!existing) return state;
      return {
        ...state,
        intents: {
          ...state.intents,
          [id]: { ...existing, status: IntentStatus.SENDING, dispatchedAt: Date.now() },
        },
      };
    }

    case AT.INTENT_ACKNOWLEDGED: {
      const id = action.payload.intentId;
      const existing = state.intents[id];
      if (!existing) return state;
      return {
        ...state,
        intents: {
          ...state.intents,
          [id]: { ...existing, status: IntentStatus.ACKNOWLEDGED },
        },
      };
    }

    // IntentFSM terminal transition
    // Precondition: intent must exist in state.intents
    // Evidence: emitted by post-effect
    case AT.INTENT_RESULT: {
      const id = action.payload.intentId;
      const existing = state.intents[id];
      if (!existing) return state;
      return {
        ...state,
        intents: {
          ...state.intents,
          [id]: {
            ...existing,
            status: action.payload.status,
            result: action.payload.result || null,
            error: action.payload.error || null,
            resolvedAt: action.payload.resolvedAt || Date.now(),
          },
        },
        intentQueue: state.intentQueue.filter((qid) => qid !== id),
      };
    }

    case AT.INTENT_CLEAR: {
      const id = action.payload.intentId;
      const nextIntents = { ...state.intents };
      delete nextIntents[id];
      return {
        ...state,
        intents: nextIntents,
        intentQueue: state.intentQueue.filter((qid) => qid !== id),
      };
    }

    // ModeFSM owns this transition
    // Effect: rebuild widget panel
    case AT.MODE_CHANGE: {
      return { ...state, mode: action.payload.mode };
    }

    // Notification domain
    case AT.NOTIFICATION_ADD: {
      return {
        ...state,
        notifications: [
          ...state.notifications,
          { id: action.payload.id || _uid(), text: action.payload.text || '', at: Date.now() },
        ],
      };
    }

    // NotificationDrainLoop owns this transition
    case AT.NOTIFICATION_DRAIN: {
      return { ...state, notifications: [] };
    }

    case AT.NOTIFICATION_LOCK: {
      return { ...state, notificationsLocked: true };
    }

    case AT.NOTIFICATION_UNLOCK: {
      return { ...state, notificationsLocked: false };
    }

    // LoopSupervisor owns these transitions
    // Evidence: loop lifecycle changes emitted by loop helpers
    case AT.LOOP_STARTED: {
      return {
        ...state,
        loops: {
          ...state.loops,
          [action.payload.loopId]: { status: 'running', startedAt: Date.now() },
        },
      };
    }
    case AT.LOOP_CANCELLED: {
      return {
        ...state,
        loops: {
          ...state.loops,
          [action.payload.loopId]: { status: 'cancelled', cancelledAt: Date.now() },
        },
      };
    }

    // BroadcastChannel detection — NEVER transmits tokens
    case AT.MULTI_TAB_SECONDARY_DETECTED: {
      return {
        ...state,
        multiTab: { ...state.multiTab, isSecondary: true },
      };
    }

    case AT.DEGRADATION_SET: {
      const reason = typeof action.payload === 'string'
        ? action.payload
        : action.payload?.reason || action.payload?.message || '';
      return {
        ...state,
        degraded: true,
        degradationReasons: [...state.degradationReasons, reason],
      };
    }

    case AT.DEGRADATION_CLEARED: {
      return { ...state, degraded: false, degradationReasons: [] };
    }

    case AT.PREFERENCE_CHANGE: {
      const { animationEnabled, soundEnabled } = action.payload;
      return {
        ...state,
        ...(animationEnabled !== undefined ? { animationEnabled } : {}),
        ...(soundEnabled !== undefined ? { soundEnabled } : {}),
      };
    }

    case AT.EVIDENCE_FLUSH:
      return state;

    case AT.RESET: {
      return _freshState();
    }

    default:
      return state;
  }
}

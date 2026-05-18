// Rig Relay — Frontend Runtime Kernel
// Central coordination point for the browser-side runtime.
// Owns app state, dispatch, subscriptions, finite-state machines,
// loop supervisors, and evidence. No React, Redux, Vue, or new dependencies.
// Plain ES modules.

import { createStateMachine } from './stateMachine.js';
import {
  ActionTypes as AT,
  BootPhase as BP,
  IntentStatus,
  WidgetStatus,
  ModeType,
  LoopType,
  INITIAL_STATE,
  bootPhaseTransition,
  transportStatusChange,
  projectionReceived,
  projectionStale,
  widgetStatusChange,
  intentQueued,
  intentDispatched,
  intentAcknowledged,
  intentResult,
} from './actions.js';
import {
  getBootPhase,
  isBootReady,
  isTransportConnected,
  getFailedWidgets,
  getVisibleWidgets,
  getPendingIntentCount,
  buildStateSummary,
  isSecondaryTab,
  getCurrentMode,
} from './selectors.js';
import { createEvidenceRecorder, EvidenceEventType } from './evidence.js';
import { createEffectRunner } from './effects.js';

// ── Deep-freeze utility (fail-safe — frozen objects pass through) ────

function _deepFreeze(obj) {
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

// ── Root reducer (pure — no side effects, no DOM, no network) ───────
// Every case creates a new state object. Never mutates previous state.
// Each case is owned by a specific state machine.

function rootReducer(state, action) {
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

function _freshState() {
  return JSON.parse(JSON.stringify(INITIAL_STATE));
}

// ── Boot FSM factory ─────────────────────────────────────────────────
// Owned by: BootFSM. Precondition: static shell loaded.
// Terminal phases: ready (operational), degraded (reduced), failed (fatal).
// Evidence: BOOT_PHASE_CHANGE emitted on every transition.

function _createBootFSM(dispatch, evidence, config) {
  function _bootEntry(phase) {
    evidence.record(EvidenceEventType.BOOT_PHASE_CHANGE, {
      lifecycle_step: phase,
      source: 'boot_fsm',
      status: phase === BP.FAILED ? 'error' : phase === BP.DEGRADED ? 'degraded' : 'ok',
    });
    dispatch(bootPhaseTransition(phase, phase === BP.FAILED || phase === BP.DEGRADED ? 'boot_' + phase : null));
  }

  function wsUrlGuard() {
    const wsUrl = config?.wsUrl || config?.ws_url || '';
    return typeof wsUrl === 'string' && wsUrl.length > 0;
  }

  const states = {
    [BP.STATIC_SHELL_LOADED]: { entry() { _bootEntry(BP.STATIC_SHELL_LOADED); } },
    [BP.RUNTIME_CONFIG_LOADING]: { entry() { _bootEntry(BP.RUNTIME_CONFIG_LOADING); } },
    [BP.RUNTIME_CONFIG_LOADED]: { entry() { _bootEntry(BP.RUNTIME_CONFIG_LOADED); } },
    [BP.TRANSPORT_CONNECTING]: { entry() { _bootEntry(BP.TRANSPORT_CONNECTING); } },
    [BP.AUTHENTICATING]: { entry() { _bootEntry(BP.AUTHENTICATING); } },
    [BP.PROJECTION_WAITING]: { entry() { _bootEntry(BP.PROJECTION_WAITING); } },
    [BP.RENDERING]: { entry() { _bootEntry(BP.RENDERING); } },
    [BP.READY]: { entry() { _bootEntry(BP.READY); } },
    [BP.DEGRADED]: {
      entry() {
        _bootEntry(BP.DEGRADED);
        dispatch({ type: AT.DEGRADATION_SET, payload: { reason: 'boot_degraded' } });
      },
    },
    [BP.FAILED]: { entry() { _bootEntry(BP.FAILED); } },
  };

  const transitions = [
    { from: BP.STATIC_SHELL_LOADED, to: BP.RUNTIME_CONFIG_LOADING, event: 'boot:config_loading' },
    { from: BP.RUNTIME_CONFIG_LOADING, to: BP.RUNTIME_CONFIG_LOADED, event: 'boot:config_loaded' },
    { from: BP.RUNTIME_CONFIG_LOADING, to: BP.RUNTIME_CONFIG_FAILED, event: 'boot:config_failed' },
    { from: BP.RUNTIME_CONFIG_LOADED, to: BP.TRANSPORT_CONNECTING, event: 'boot:transport_connecting', guard: wsUrlGuard },
    { from: BP.RUNTIME_CONFIG_LOADED, to: BP.FAILED, event: 'boot:config_failed' },
    { from: BP.TRANSPORT_CONNECTING, to: BP.AUTHENTICATING, event: 'boot:authenticating' },
    { from: BP.AUTHENTICATING, to: BP.PROJECTION_WAITING, event: 'boot:projection_waiting' },
    { from: BP.PROJECTION_WAITING, to: BP.RENDERING, event: 'boot:rendering' },
    { from: BP.RENDERING, to: BP.READY, event: 'boot:ready' },
    // Any state → degraded / failed
    { from: '*', to: BP.DEGRADED, event: 'boot:degraded' },
    { from: '*', to: BP.FAILED, event: 'boot:failed' },
    // Ready can degrade
    { from: BP.READY, to: BP.DEGRADED, event: 'boot:degraded' },
  ];

  return createStateMachine({
    id: 'boot',
    initial: BP.STATIC_SHELL_LOADED,
    states,
    transitions,
  });
}

// ── Intent FSM factory ───────────────────────────────────────────────
// Owned by: IntentFSM. Per-intent lifecycle tracking.
// Terminal: succeeded, refused, failed, cancelled.

function _createIntentFSM(dispatch, evidence) {
  const intentStates = {};

  function _ensure(id) {
    if (id && !intentStates[id]) {
      intentStates[id] = IntentStatus.IDLE;
    }
  }

  const states = {
    [IntentStatus.IDLE]: { entry() {} },
    [IntentStatus.QUEUED]: {
      entry(ctx) {
        _ensure(ctx.intentId);
        intentStates[ctx.intentId] = IntentStatus.QUEUED;
        dispatch(intentQueued(ctx.intentId, ctx.intentName || '', ctx.params || {}));
      },
    },
    [IntentStatus.SENDING]: {
      entry(ctx) {
        _ensure(ctx.intentId);
        intentStates[ctx.intentId] = IntentStatus.SENDING;
        dispatch(intentDispatched(ctx.intentId));
      },
    },
    [IntentStatus.ACKNOWLEDGED]: {
      entry(ctx) {
        _ensure(ctx.intentId);
        intentStates[ctx.intentId] = IntentStatus.ACKNOWLEDGED;
        dispatch(intentAcknowledged(ctx.intentId));
      },
    },
    [IntentStatus.SUCCEEDED]: {
      entry(ctx) {
        _ensure(ctx.intentId);
        intentStates[ctx.intentId] = IntentStatus.SUCCEEDED;
        dispatch(intentResult(ctx.intentId, IntentStatus.SUCCEEDED, ctx.result || null));
      },
    },
    [IntentStatus.REFUSED]: {
      entry(ctx) {
        _ensure(ctx.intentId);
        intentStates[ctx.intentId] = IntentStatus.REFUSED;
        dispatch(intentResult(ctx.intentId, IntentStatus.REFUSED, ctx.result || null, ctx.error));
      },
    },
    [IntentStatus.FAILED]: {
      entry(ctx) {
        _ensure(ctx.intentId);
        intentStates[ctx.intentId] = IntentStatus.FAILED;
        dispatch(intentResult(ctx.intentId, IntentStatus.FAILED, null, ctx.error || 'intent_failed'));
      },
    },
    [IntentStatus.CANCELLED]: {
      entry(ctx) {
        _ensure(ctx.intentId);
        intentStates[ctx.intentId] = IntentStatus.CANCELLED;
        dispatch(intentResult(ctx.intentId, IntentStatus.CANCELLED, null));
      },
    },
  };

  const transitions = [
    { from: IntentStatus.IDLE, to: IntentStatus.QUEUED, event: 'intent:dispatch' },
    { from: IntentStatus.QUEUED, to: IntentStatus.SENDING, event: 'intent:dequeue' },
    { from: IntentStatus.SENDING, to: IntentStatus.ACKNOWLEDGED, event: 'intent:ack' },
    { from: IntentStatus.ACKNOWLEDGED, to: IntentStatus.SUCCEEDED, event: 'intent:resolve' },
    { from: IntentStatus.ACKNOWLEDGED, to: IntentStatus.REFUSED, event: 'intent:refuse' },
    { from: IntentStatus.ACKNOWLEDGED, to: IntentStatus.FAILED, event: 'intent:fail' },
    { from: IntentStatus.IDLE, to: IntentStatus.CANCELLED, event: 'intent:cancel' },
    { from: IntentStatus.QUEUED, to: IntentStatus.CANCELLED, event: 'intent:cancel' },
    { from: IntentStatus.SENDING, to: IntentStatus.CANCELLED, event: 'intent:cancel' },
  ];

  const fsm = createStateMachine({
    id: 'intent',
    initial: IntentStatus.IDLE,
    states,
    transitions,
  });

  return Object.freeze({
    ...fsm,
    getIntentState(id) { return intentStates[id] || IntentStatus.IDLE; },
  });
}

// ── Mode FSM factory ─────────────────────────────────────────────────
// Owned by: ModeFSM. Operator / Review / System / Technical.
// Effect: rebuild widget panel on mode switch.

function _createModeFSM(dispatch, evidence) {
  const values = Object.values(ModeType);
  const states = {};
  for (const m of values) {
    states[m] = {
      entry() {
        dispatch({ type: AT.MODE_CHANGE, payload: { mode: m } });
        evidence.record(EvidenceEventType.MODE_CHANGED, {
          lifecycle_step: m,
          source: 'mode_fsm',
          status: 'ok',
        });
      },
    };
  }

  // Each mode gets its own event; ctx.targetMode selects the destination.
  // Guard: allows transition only when ctx.targetMode matches this transition's target.
  const transitions = values.map((m) => ({
    from: '*',
    to: m,
    event: 'mode:switch',
    guard(ctx) {
      return ctx && ctx.mode === m;
    },
  }));

  return createStateMachine({
    id: 'mode',
    initial: ModeType.OPERATOR,
    states,
    transitions,
  });
}

// ── Loop supervisor ──────────────────────────────────────────────────
// Owned by: LoopSupervisor. Manages loop lifecycle via AbortController.
// Evidence: LOOP_STARTED / LOOP_CANCELLED dispatched on lifecycle changes.

function _createLoopSupervisor(dispatch) {
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

// ── Loop helpers ─────────────────────────────────────────────────────

function _startFreshnessLoop(getState, dispatch, loopSupervisor) {
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

function _startIntentFlushLoop(getState, dispatch, loopSupervisor, intentSendFn) {
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

function _startNotificationDrainLoop(getState, dispatch, loopSupervisor) {
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

function _startEvidenceFlushLoop(getState, evidence, loopSupervisor) {
  loopSupervisor.startLoop(
    LoopType.EVIDENCE_FLUSH,
    () => {
      const st = getState();
      evidence.record(EvidenceEventType.KERNEL_SNAPSHOT, buildStateSummary(st));
    },
    30000,
  );
}

// ── BroadcastChannel setup ────────────────────────────────────────────
// Multi-tab detection. NEVER transmits tokens, secrets, or handshake IDs.
// Only transmits { type: 'cockpit_present', timestamp }.

function _setupBroadcastChannel(dispatch) {
  let channel = null;

  try {
    if (typeof BroadcastChannel !== 'undefined') {
      channel = new BroadcastChannel('rig-relay-cockpit');
      channel.onmessage = () => {
        dispatch({ type: AT.MULTI_TAB_SECONDARY_DETECTED });
      };
      channel.postMessage({ type: 'cockpit_present', timestamp: Date.now() });
    }
  } catch (_) {
    // BroadcastChannel unavailable.
  }

  return {
    channel,
    close() {
      if (channel) {
        try { channel.close(); } catch (_) { /* ignore */ }
        channel = null;
      }
    },
  };
}

// ── Post-reducer effects registration ────────────────────────────────

function _registerEffects(effectRunner, getState, dispatch, loopSupervisor) {
  // On PROJECTION_RECEIVED: mark visible widgets as ready
  effectRunner.register(AT.PROJECTION_RECEIVED, (state) => {
    const visible = getVisibleWidgets(state, getCurrentMode(state));
    for (const widgetId of visible) {
      dispatch(widgetStatusChange(widgetId, WidgetStatus.READY));
    }
  });

  // On MODE_CHANGE: mark visible widgets as waiting
  effectRunner.register(AT.MODE_CHANGE, (state) => {
    const visible = getVisibleWidgets(state, state.mode);
    for (const widgetId of visible) {
      dispatch(widgetStatusChange(widgetId, WidgetStatus.WAITING_FOR_PROJECTION));
    }
  });

  // On TRANSPORT_STATUS_CHANGE: manage freshness loop
  effectRunner.register(AT.TRANSPORT_STATUS_CHANGE, (state) => {
    if (isTransportConnected(state)) {
      _startFreshnessLoop(getState, dispatch, loopSupervisor);
    } else {
      loopSupervisor.cancelLoop(LoopType.PROJECTION_FRESHNESS);
    }
  });
}

// ── Runtime factory ──────────────────────────────────────────────────

export function createRuntime(config) {
  config = config || {};

  let _state = _freshState();
  const _subscribers = new Set();
  let _isDispatching = false;
  const _pendingActions = [];
  let _intentSendFn = null;

  // ── Evidence recorder (from evidence.js — pywebview + HTTP + ring buffer) ─
  const evidence = createEvidenceRecorder({
    handshakeId: config.handshakeId || '',
    ...(config.evidenceConfig || {}),
  });

  // ── Effect runner (from effects.js — DOM/WS/trace effects) ──────────
  const effectRunner = createEffectRunner({
    evidence,
    getState: () => _state,
    dispatch: null, // will be set after _dispatch is created
  });

  // ── Dispatch (created early so FSMs reference it closure-style) ─────
  let _dispatch;

  // ── FSM instances ───────────────────────────────────────────────────
  const bootFSM = _createBootFSM(
    (action) => { if (_dispatch) _dispatch(action); },
    evidence,
    config,
  );

  const intentFSM = _createIntentFSM(
    (action) => { if (_dispatch) _dispatch(action); },
    evidence,
  );

  const modeFSM = _createModeFSM(
    (action) => { if (_dispatch) _dispatch(action); },
    evidence,
  );

  // ── Loop supervisor ──────────────────────────────────────────────────
  const loopSupervisor = _createLoopSupervisor(
    (action) => { if (_dispatch) _dispatch(action); },
  );

  // Update effectRunner's dispatch reference
  effectRunner.dispatch = (action) => { if (_dispatch) _dispatch(action); };

  // ── BroadcastChannel (initialized in init()) ─────────────────────────
  let _bc = { channel: null, close() {} };

  // ── Post-reducer effects ─────────────────────────────────────────────
  _registerEffects(effectRunner, () => _state, _dispatch, loopSupervisor);

  // ── Core dispatch ────────────────────────────────────────────────────
  _dispatch = function dispatch(action) {
    if (!action || !action.type) return;

    // Concurrency guard: queue if already dispatching
    if (_isDispatching) {
      _pendingActions.push(action);
      return;
    }

    _isDispatching = true;

    try {
      const stateBefore = buildStateSummary(_state);
      const oldState = _state;
      const newState = rootReducer(oldState, action);

      // No-op guard
      if (newState === oldState) {
        _isDispatching = false;
        _flushPending();
        return;
      }

      // Commit
      _state = newState;

      // Evidence: emit transition summary — no token data
      evidence.record(EvidenceEventType.STATE_TRANSITION, {
        state_before: stateBefore,
        state_after: buildStateSummary(_state),
        action_type: action.type,
        lifecycle_step: getBootPhase(_state),
        source: 'kernel_dispatch',
        status: 'ok',
      });

      // Post-reducer effects
      effectRunner.run(_state, action, dispatch, {
        evidence,
        loopSupervisor,
        bootFSM,
        intentFSM,
        modeFSM,
        getState: () => _state,
        intentSendFn: _intentSendFn,
      });

      // Notify generic subscribers
      const frozenState = _deepFreeze({ ..._state });
      for (const listener of _subscribers) {
        try {
          listener(frozenState, oldState, action);
        } catch (_) {
          // Swallow — one broken subscriber must not break others.
        }
      }
      // Notify action-type subscribers (compat: notification system bridge)
      var typedSet = _typedSubscribers[action.type];
      if (typedSet) {
        for (const listener of typedSet) {
          try {
            listener(action);
          } catch (_) {
            // Swallow.
          }
        }
      }

      // External state change callback
      if (typeof config.onStateChange === 'function') {
        try { config.onStateChange(frozenState, oldState, action); } catch (_) { /* swallow */ }
      }
    } finally {
      _isDispatching = false;
      _flushPending();
    }
  };

  // Update effectRunner's dispatch (now _dispatch exists)
  effectRunner.dispatch = _dispatch;

  function _flushPending() {
    while (_pendingActions.length > 0) {
      const nextAction = _pendingActions.shift();
      _dispatch(nextAction);
    }
  }

  // ── Subscribe ────────────────────────────────────────────────────────
  function subscribe(listener) {
    if (typeof listener !== 'function') return () => {};
    _subscribers.add(listener);
    return () => { _subscribers.delete(listener); };
  }

  // ── Get frozen state copy ────────────────────────────────────────────
  function getState() {
    return _deepFreeze({ ..._state });
  }

  // ── Init ──────────────────────────────────────────────────────────────
  function init() {
    evidence.record(EvidenceEventType.RUNTIME_INITIALIZED, {
      handshake_id: config.handshakeId || '',
      boot_phase: getBootPhase(_state),
      lifecycle_step: 'init',
      source: 'kernel',
      status: 'ok',
    });

    // BroadcastChannel for multi-tab detection
    _bc = _setupBroadcastChannel(_dispatch);

    // Transition boot FSM to config_loading
    bootFSM.transition('boot:config_loading', {});

    // Start all loop supervisors
    _startFreshnessLoop(() => _state, _dispatch, loopSupervisor);
    _startIntentFlushLoop(() => _state, _dispatch, loopSupervisor, _intentSendFn);
    _startNotificationDrainLoop(() => _state, _dispatch, loopSupervisor);
    _startEvidenceFlushLoop(() => _state, evidence, loopSupervisor);

    return runtime;
  }

  // ── Intent send bridge — set by transport integration ────────────────
  function setIntentSend(fn) {
    _intentSendFn = typeof fn === 'function' ? fn : null;
  }

  // ── Destroy ──────────────────────────────────────────────────────────
  function destroy() {
    loopSupervisor.cancelAllLoops();
    _bc.close();
    effectRunner.clear();
    _subscribers.clear();
    _pendingActions.length = 0;
  }

  // ── Compatibility: notification system bridge ────────────────────────
  // Provides the API expected by notifications.js setup().
  // Uses the kernel's own FSM factory for machine registration.

  const _compatMachines = Object.create(null);
  const _readyCallbacks = [];
  const _notReadyCallbacks = [];

  function registerMachine(id, machineConfig) {
    if (_compatMachines[id]) return _compatMachines[id];
    var sm = createStateMachine({
      id,
      initial: machineConfig.initialState,
      states: Object.fromEntries(
        (machineConfig.states || []).map(function (s) { return [s, {}]; })
      ),
      transitions: Object.entries(machineConfig.transitions || {}).flatMap(
        function ([from, eventMap]) {
          return Object.entries(eventMap).map(function ([event, to]) {
            return { from, to, event };
          });
        }
      ),
    });
    if (typeof machineConfig.onTransition === 'function') {
      sm.subscribe(function (to) {
        machineConfig.onTransition({ nextState: to });
      });
    }
    _compatMachines[id] = sm;
    return sm;
  }

  function onReady(fn) {
    if (typeof fn !== 'function') return;
    _readyCallbacks.push(fn);
    if (isBootReady(_state)) fn();
  }

  function onNotReady(fn) {
    if (typeof fn !== 'function') return;
    _notReadyCallbacks.push(fn);
    if (!isBootReady(_state) && _state.boot.phase !== 'static_shell_loaded') fn();
  }

  // Polymorphic subscribe: supports both generic and action-type filtering.
  // subscribe(fn) → called on every dispatch with (newState, oldState, action)
  // subscribe(actionType, fn) → called only for matching type with (action)
  const _baseSubscribe = subscribe;
  const _typedSubscribers = Object.create(null);
  subscribe = function subscribeCompat() {
    var listener, actionType;
    if (arguments.length === 2) {
      actionType = arguments[0];
      listener = arguments[1];
    } else {
      listener = arguments[0];
    }
    if (typeof listener !== 'function') return function () {};

    if (actionType) {
      if (!_typedSubscribers[actionType]) _typedSubscribers[actionType] = new Set();
      _typedSubscribers[actionType].add(listener);
      return function () {
        if (_typedSubscribers[actionType]) _typedSubscribers[actionType].delete(listener);
      };
    }

    _subscribers.add(listener);
    return function () { _subscribers.delete(listener); };
  };

  // Fire ready/not-ready callbacks after each dispatch
  var _wasReady = false;
  _subscribers.add(function () {
    var nowReady = isBootReady(_state);
    if (nowReady && !_wasReady) {
      _wasReady = true;
      for (var i = 0; i < _readyCallbacks.length; i++) {
        _readyCallbacks[i]();
      }
    } else if (!nowReady && _wasReady) {
      _wasReady = false;
      for (var j = 0; j < _notReadyCallbacks.length; j++) {
        _notReadyCallbacks[j]();
      }
    }
  });

  // ── Runtime API ──────────────────────────────────────────────────────
  const runtime = {
    init,
    dispatch: _dispatch,
    getState,
    subscribe,
    registerMachine,
    onReady,
    onNotReady,
    bootFSM,
    intentFSM,
    modeFSM,
    evidence,
    effects: effectRunner,
    loopSupervisor,
    setIntentSend,
    destroy,
  };

  return runtime;
}

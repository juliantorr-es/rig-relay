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
import { rootReducer, _freshState, _deepFreeze } from './reducer.js';
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
import { createLoopSupervisor, startFreshnessLoop, startIntentFlushLoop, startNotificationDrainLoop, startEvidenceFlushLoop } from './loops.js';
import { setupBroadcastChannel } from './multitab.js';
import { createNotificationBridge } from './notifBridge.js';

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
      startFreshnessLoop(getState, dispatch, loopSupervisor);
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
  var _typedSubscribers = Object.create(null);

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
  const loopSupervisor = createLoopSupervisor(
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
    _bc = setupBroadcastChannel(_dispatch);

    // Transition boot FSM to config_loading
    bootFSM.transition('boot:config_loading', {});

    // Start all loop supervisors
    startFreshnessLoop(() => _state, _dispatch, loopSupervisor);
    startIntentFlushLoop(() => _state, _dispatch, loopSupervisor, _intentSendFn);
    startNotificationDrainLoop(() => _state, _dispatch, loopSupervisor);
    startEvidenceFlushLoop(() => _state, evidence, loopSupervisor);

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
    notifBridge.destroy();
    _subscribers.clear();
    _pendingActions.length = 0;
  }

  // ── Notification system bridge ───────────────────────────────────────
  const notifBridge = createNotificationBridge({
    getState: () => _state,
    get subscribers() { return _subscribers; },
    get typedSubscribers() { return _typedSubscribers; },
  });

  // ── Runtime API ──────────────────────────────────────────────────────
  const runtime = {
    init,
    dispatch: _dispatch,
    getState,
    subscribe: notifBridge.subscribe,
    registerMachine: notifBridge.registerMachine,
    onReady: notifBridge.onReady,
    onNotReady: notifBridge.onNotReady,
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

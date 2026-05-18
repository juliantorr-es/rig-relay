// Rig Relay — Runtime Kernel: Initial State
// Browser-side runtime kernel. No React, Redux, Vue, or new dependencies.
// Plain ES modules. Actions are pure data; the kernel reducer owns all transitions.

import { BootPhase, IntentStatus, WidgetStatus, ModeType, LoopType } from './constants.js';

// ── Initial state ─────────────────────────────────────────────────────
// Frozen snapshot. The kernel reducer must never mutate this object.
// Evidence event: rig.relay.frontend.kernel.state_initialized emitted once.

const INITIAL_STATE = Object.freeze({
  // Boot state machine: orchestrator.js tracks the boot lifecycle
  boot: Object.freeze({
    phase: BootPhase.STATIC_SHELL_LOADED,
    error: null,
    startedAt: null,
    readyAt: null,
    handshakeId: null,
  }),
  // Transport authority: status mirrors transportState.js canonical state
  transport: Object.freeze({
    status: 'idle',
    phase: 'boot',
    lastEvent: null,
    lastError: null,
    handshakeId: '',
    updatedAt: null,
    wsConnected: false,
  }),
  // Projection pipeline: data is the last received projection snapshot
  projection: Object.freeze({
    data: null,
    digest: '',
    lastReceivedAt: null,
    stale: false,
  }),
  // Widget registry: keyed by widgetId, lifecycle owned by widget mount/unmount
  widgets: Object.freeze({}),
  // Intent queue: keyed by intentId, lifecycle owned by intent dispatch/result
  intents: Object.freeze({}),
  // Ordered intent queue: array of intentId strings awaiting dispatch
  intentQueue: Object.freeze([]),
  // Active layout mode
  mode: ModeType.OPERATOR,
  // Notification ring buffer: newest first, drained when locked
  notifications: Object.freeze([]),
  notificationsLocked: false,
  // Loop manager: keyed by loopId
  loops: Object.freeze({}),
  // Multi-tab coordinator: BroadcastChannel-backed primary/secondary detection
  multiTab: Object.freeze({
    isSecondary: false,
    primaryDetected: false,
    channelName: 'rig-relay-cockpit',
  }),
  // User preferences
  animationEnabled: true,
  soundEnabled: false,
  // Degradation state
  degraded: false,
  degradationReasons: Object.freeze([]),
});

export { INITIAL_STATE };

// Rig Relay — Runtime Kernel: Action Types, Creators, State Shape — Barrel Re-Export
// Browser-side runtime kernel. No React, Redux, Vue, or new dependencies.
// Plain ES modules. Actions are pure data; the kernel reducer owns all transitions.

export { ActionTypes, BootPhase, IntentStatus, WidgetStatus, ModeType, LoopType } from './constants.js'
export { INITIAL_STATE } from './initialState.js'
export { bootPhaseTransition, transportStatusChange, projectionReceived, projectionStale, widgetStatusChange, widgetMount, widgetUnmount, intentQueued, intentDispatched, intentAcknowledged, intentResult, intentClear, modeChange, notificationAdd, notificationDrain, notificationLock, notificationUnlock, loopStarted, loopCancelled, loopCompleted, loopFailed, multiTabSecondaryDetected, multiTabPrimaryClaimed, multiTabPrimaryLost, degradationSet, degradationCleared, evidenceFlush, preferenceChange, reset } from './actionCreators.js'

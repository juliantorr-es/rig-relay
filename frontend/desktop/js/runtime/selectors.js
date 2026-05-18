// Rig Relay — Pure State Selectors
// Browser-side runtime kernel. All functions are pure: state in, value out.
// No mutation, no side effects, no framework dependencies.

// Mode-to-widget assignments — single authority, mirrors _renderPanelColumn in main.js
const MODE_WIDGETS = {
  operator: [
    'operatorHeader', 'safetyState', 'nextAction', 'roleModel',
    'missionBoard', 'ralphScout', 'ralphLifecycle', 'validationSummary',
    'releaseGate', 'storageBudget', 'intentResult', 'providerHealth',
    'council', 'providerDock', 'workspaceStatus', 'fleetStatus',
  ],
  review: [
    'progressTimeline', 'receiptTimeline', 'refinementBacklog',
    'reviewValidation', 'reviewStorage', 'reviewSnippets', 'reviewDataset',
  ],
  system: [
    'identity', 'modelProviders', 'telemetryConsent', 'authReceipts',
    'connectionStatus', 'telemetryBundle', 'updateStatus',
    'projectionSources', 'storageDiagnostics',
  ],
  technical: [
    'progressTimeline', 'receiptTimeline', 'projectionSources',
    'storageDiagnostics', 'telemetryBundle', 'updateStatus',
  ],
};

// ── Boot domain ──────────────────────────────────────────────────────

// Selects the current boot phase string
export function getBootPhase(state) {
  return state.boot?.phase ?? '';
}

// True when boot sequence completed successfully
export function isBootReady(state) {
  return getBootPhase(state) === 'ready';
}

// True when boot hit a terminal failure
export function isBootFailed(state) {
  const phase = getBootPhase(state);
  return phase === 'failed' || phase === 'runtime_config_failed';
}

// True when boot completed with degraded capabilities
export function isBootDegraded(state) {
  return state.degraded === true;
}

// ── Transport domain ─────────────────────────────────────────────────

// Selects the transport connection status string
export function getTransportStatus(state) {
  return state.transport?.status ?? '';
}

// True when transport WebSocket is connected
export function isTransportConnected(state) {
  return state.transport?.wsConnected === true;
}

// Selects the transport handshake ID (correlates with boot handshake)
export function getTransportHandshakeId(state) {
  return state.transport?.handshakeId ?? '';
}

// ── Projection domain ────────────────────────────────────────────────

// Selects the projection content digest (SHA256)
export function getProjectionDigest(state) {
  return state.projection?.digest ?? '';
}

// True when projection data exceeds freshness threshold
export function isProjectionStale(state) {
  return state.projection?.stale === true;
}

// Selects the full projection data payload, null-safe
export function getProjectionData(state) {
  return state.projection?.data ?? null;
}

// ── Widget domain ────────────────────────────────────────────────────

// Selects the status of a single widget by ID
export function getWidgetStatus(state, widgetId) {
  return state.widgets?.[widgetId]?.status ?? 'unknown';
}

// Selects IDs of all widgets currently in failed state
export function getFailedWidgets(state) {
  return Object.entries(state.widgets ?? {})
    .filter(([, w]) => w.status === 'failed')
    .map(([id]) => id);
}

// Selects IDs of all widgets currently in ready state
export function getReadyWidgets(state) {
  return Object.entries(state.widgets ?? {})
    .filter(([, w]) => w.status === 'ready')
    .map(([id]) => id);
}

// Selects widget IDs visible in the given layout mode
export function getVisibleWidgets(state, mode) {
  return MODE_WIDGETS[mode] ?? [];
}

// ── Intent domain ────────────────────────────────────────────────────

// Counts intents still waiting to be dispatched (status !== 'resolved')
export function getPendingIntentCount(state) {
  return Object.values(state.intents ?? {})
    .filter((i) => i.status !== 'resolved').length;
}

// Returns the number of queued intents awaiting execution
export function getIntentQueueLength(state) {
  return state.intentQueue?.length ?? 0;
}

// ── Mode domain ──────────────────────────────────────────────────────

// Selects the current layout mode
export function getCurrentMode(state) {
  return state.mode ?? 'operator';
}

// ── Notification domain ──────────────────────────────────────────────

// Counts active notifications in the queue
export function getNotificationCount(state) {
  return state.notifications?.length ?? 0;
}

// ── Multi-tab domain ─────────────────────────────────────────────────

// True when this tab is secondary (another tab is primary)
export function isSecondaryTab(state) {
  return state.multiTab?.isSecondary === true;
}

// ── Degradation domain ───────────────────────────────────────────────

// True when the runtime is operating in degraded mode
export function isDegraded(state) {
  return state.degraded === true;
}

// Selects all active degradation reasons
export function getDegradationReasons(state) {
  return state.degradationReasons ?? [];
}

// ── Loop domain ──────────────────────────────────────────────────────

// Selects IDs of all loops currently executing
export function getActiveLoops(state) {
  return Object.entries(state.loops ?? {})
    .filter(([, loop]) => loop.status === 'running')
    .map(([id]) => id);
}

// Selects the current status of a specific loop by ID
export function getLoopStatus(state, loopId) {
  return state.loops?.[loopId]?.status ?? 'unknown';
}

// ── Evidence summary ─────────────────────────────────────────────────

// Builds a compact summary for evidence/telemetry — no tokens, no secrets.
export function buildStateSummary(state) {
  return {
    bootPhase: getBootPhase(state),
    transportStatus: getTransportStatus(state),
    widgetCount: Object.keys(state.widgets ?? {}).length,
    intentCount: Object.keys(state.intents ?? {}).length,
    mode: getCurrentMode(state),
    degraded: isDegraded(state),
    activeLoops: getActiveLoops(state),
  };
}

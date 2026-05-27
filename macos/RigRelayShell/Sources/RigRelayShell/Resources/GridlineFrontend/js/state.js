// Rig Relay — State
// Shared presentation state. No governance logic here.

export const state = {
  // Current layout mode
  mode: 'operator',

  // Transport connection — canonical authority writes these.
  // wsConnected is derived from the transport authority; do not write directly.
  wsConnected: false,
  transport: {
    status: 'idle',
    phase: 'boot',
    lastEvent: null,
    lastError: null,
    handshakeId: '',
    updatedAt: '',
  },
  _transportStatus: '',

  // Projection data (last received)
  projection: null,

  // Analytics projection (separate path — no collision with main projection)
  analytics: null,

  // Chat
  chat: {
    messages: [],
    backendWired: false,
    pendingResponse: false,
  },

  // Progress events (ring buffer)
  progressEvents: [],

  // Widget disclosure states: widget -> 'compact' | 'standard' | 'expanded'
  disclosures: {},

  // Identity / consent caching
  identity: null,
  consent: null,

  // Ralph: pywebview-visible approval loop
  ralph: {
    panel: null,        // RalphPanel model dump
    runState: null,     // RalphRunState model dump
    lastIntent: null,   // { name, status, summary }
    lifecycle: null,    // RalphLifecycleProjection model dump
    missionBoard: null, // OrchestratorMissionBoard model dump
  },

  // Notifications
  notifications: {
    railOpen: false,
    systemPermission: 'default',
    systemSupported: false,
  },
};

// Per-mode default disclosures
const modeDefaults = {
  operator: {
    operatorHeader: 'compact',
    safetyState: 'compact',
    nextAction: 'compact',
    providerHealth: 'compact',
    roleModel: 'standard',
    missionBoard: 'standard',
    ralphScout: 'standard',
    ralphLifecycle: 'standard',
    profileReadmeLane: 'standard',
    spiderwebTopology: 'standard',
    securityLifecycle: 'standard',
    validationSummary: 'compact',
    storageBudget: 'compact',
    intentResult: 'compact',
    actions: 'compact',
    progressTimeline: 'standard',
    connectionStatus: 'compact',
  },
  review: {
    progressTimeline: 'standard',
    receiptTimeline: 'standard',
    refinementBacklog: 'standard',
    reviewValidation: 'standard',
    reviewStorage: 'standard',
    reviewSnippets: 'standard',
    reviewDataset: 'standard',
  },
  system: {
    identity: 'standard',
    modelProviders: 'standard',
    telemetryConsent: 'standard',
    authReceipts: 'standard',
    connectionStatus: 'standard',
    telemetryBundle: 'standard',
    updateStatus: 'standard',
    projectionSources: 'standard',
    storageDiagnostics: 'standard',
  },
  technical: {
    progressTimeline: 'standard',
    receiptTimeline: 'standard',
    projectionSources: 'standard',
    storageDiagnostics: 'standard',
    telemetryBundle: 'standard',
    updateStatus: 'standard',
  },
  analytics: {
    governanceGateHealth: 'standard',
    sessionHealth: 'standard',
    toolLatency: 'standard',
    releaseBlocker: 'standard',
    dependencyRisk: 'standard',
    findingsWidget: 'standard',
    correlationIntegrity: 'compact',
    localInference: 'standard',
  },
};

export function getDisclosure(widgetId) {
  return state.disclosures[widgetId] || 'compact';
}

export function setDisclosure(widgetId, level) {
  state.disclosures[widgetId] = level;
}

export function applyModeDefaults() {
  const defaults = modeDefaults[state.mode] || {};
  state.disclosures = {};
  for (const [id, level] of Object.entries(defaults)) {
    state.disclosures[id] = level;
  }
}

export function setMode(mode) {
  if (state.mode === mode) return;
  state.mode = mode;
  applyModeDefaults();
}

export function setNotificationRailOpen(open) {
  state.notifications.railOpen = !!open;
}

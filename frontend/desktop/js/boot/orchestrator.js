// Rig Relay — Boot Orchestrator

import { generateHandshakeId } from '../telemetry/correlation.js';
import { recordFrontendEvent, setFrontendHandshakeId } from '../telemetry/frontendTrace.js';
import { fetchRuntimeConfig } from './runtimeConfig.js';
import { createDebugPanel, updateDebugPanel } from './debugPanel.js';
import { createTransportStateAuthority } from '../transportState.js';
import { ProjectionWebSocketClient, setWsClient, onProjectionReceived } from '../transport.js';
import { renderStatusFromState } from '../status.js';
import { handleProjection, handleChatState, handleIntentResult,
         handleProgressEvent, handleProgressEvents } from '../projection.js';
import { wireUI } from '../main.js';
import { state } from '../state.js';
import { createRuntime } from '../runtime/kernel.js';
import { BootPhase } from '../runtime/actions.js';
import { setup as setupNotifications } from '../notifications.js';
import { initNotificationListeners, updateNotificationBadge, toggleNotificationRail } from '../notificationsUI.js';
import { startReactiveLoops, stopReactiveLoops } from '../reactiveLoops.js';
import { isSystemNotificationsSupported, getSystemNotificationPermission } from '../systemNotifications.js';
import { setNotificationRailOpen } from '../state.js';
import { initDelight } from '../delight.js';

const LIFECYCLE = {
  BOOT_STARTED: 'frontend_boot_started',
  MODULE_GRAPH_LOADED: 'frontend_module_graph_loaded',
  RUNTIME_CONFIG_REQUESTED: 'frontend_runtime_config_requested',
  RUNTIME_CONFIG_LOADED: 'frontend_runtime_config_loaded',
  WEBSOCKET_CONSTRUCTED: 'frontend_websocket_constructed',
  SOCKET_OPEN: 'frontend_socket_open',
  AUTH_SENT: 'frontend_auth_sent',
  AUTH_OK: 'frontend_auth_ok',
  PROJECTION_REQUESTED: 'frontend_projection_requested',
  PROJECTION_RECEIVED: 'frontend_projection_received',
  PROJECTION_RENDER_STARTED: 'frontend_projection_render_started',
  PROJECTION_RENDER_OK: 'frontend_projection_render_ok',
  WIDGETS_MOUNT_STARTED: 'frontend_widgets_mount_started',
  WIDGETS_MOUNT_OK: 'frontend_widgets_mount_ok',
  READY: 'frontend_ready',
  NOTIFICATIONS_INITIALIZED: 'frontend_notifications_initialized',
  REACTIVE_LOOPS_STARTED: 'frontend_reactive_loops_started',
  FAILED: 'frontend_failed',
};

let debugPanel = null;
const urlParams = new URLSearchParams(window.location.search);
const isDebug = urlParams.get('boot_debug') === '1';

async function boot() {
  // Canonical handshake_id: prefer the backend-supplied corr_* ID from
  // runtime config. Only generate a frontend hs_* when no backend ID exists.
  const config = await fetchRuntimeConfig();
  const canonicalHandshakeId = config.handshake_id || generateHandshakeId();
  setFrontendHandshakeId(canonicalHandshakeId);

  // ── Frontend Runtime Kernel ────────────────────────────────────────
  // Creates the browser-side runtime that owns lifecycle, state machines,
  // reducer dispatch, loop supervisors, and evidence. Co-exists with
  // existing module graph; does not replace transport/projection/widget code.
  const runtime = createRuntime({
    handshakeId: canonicalHandshakeId,
    onStateChange(_newState, _oldState, action) {
      if (isDebug) {
        updateDebugPanel(debugPanel, {
          kernelPhase: _newState.boot?.phase,
          transportStatus: _newState.transport?.status,
          widgetCount: Object.keys(_newState.widgets || {}).length,
          lastAction: action.type,
        });
      }
    },
  });
  runtime.init();

  // ── Delight: motion + sound system ──────────────────────────────────
  const delight = initDelight(runtime);
  window.RigRelay = window.RigRelay || {};
  window.RigRelay.delight = delight;

  // Wire sound init to first user gesture (one-shot)
  const _initSound = () => {
    delight.sound.init();
    document.removeEventListener('click', _initSound);
    document.removeEventListener('keydown', _initSound);
  };
  document.addEventListener('click', _initSound);
  document.addEventListener('keydown', _initSound);

  // Expose on window for debugging and test introspection
  window.__RIG_RELAY_RUNTIME__ = runtime;

  if (isDebug) {
    debugPanel = createDebugPanel();
  }

  recordFrontendEvent(LIFECYCLE.MODULE_GRAPH_LOADED, {});
  recordFrontendEvent('frontend_boot_started');

  // ── Boot FSM: config loaded ───────────────────────────────────────
  // Precondition: bootFSM is in runtime_config_loading (set by kernel init)
  runtime.bootFSM.transition('boot:config_loaded', { wsUrl: config.ws_url });

  // Create transport authority
  const authority = createTransportStateAuthority({
    onTransition: (stateSnapshot) => {
      state.wsConnected = stateSnapshot.wsConnected;
      state.transport = stateSnapshot.transport;
      renderStatusFromState(stateSnapshot);
      if (isDebug) updateDebugPanel(debugPanel, stateSnapshot);
      recordFrontendEvent('frontend_transport_state', { 
        status: stateSnapshot.transport.status, 
        phase: stateSnapshot.transport.phase 
      });
      // ── Kernel transport dispatch ──────────────────────────────────
      runtime.dispatch({
        type: 'TRANSPORT_STATUS_CHANGE',
        payload: {
          status: stateSnapshot.transport.status,
          detail: {
            handshake_id: stateSnapshot.transport.handshakeId,
            phase: stateSnapshot.transport.phase,
          },
        },
      });
      // Bridge: notification system subscribes to transport-state-changed
      runtime.dispatch({
        type: 'transport-state-changed',
        status: stateSnapshot.transport.status,
        payload: {
          status: stateSnapshot.transport.status,
          detail: {
            handshake_id: stateSnapshot.transport.handshakeId,
            phase: stateSnapshot.transport.phase,
          },
        },
      });
    }
  });

  // Initialize the notification system with kernel wiring
  setupNotifications(runtime);

  const wsUrl = config.ws_url;
  const token = config.auth_token;

  if (wsUrl) {
    recordFrontendEvent('frontend_websocket_connecting');
    // ── Boot FSM: transport connecting ───────────────────────────────
    // Precondition: bootFSM is in runtime_config_loaded
    runtime.bootFSM.transition('boot:transport_connecting', {});
    const wsClient = new ProjectionWebSocketClient({
      wsUrl,
      token,
      handshakeId: canonicalHandshakeId,
      transportMachine: authority,
      onProjection(data) {
        handleProjection(data);
        onProjectionReceived();
        recordFrontendEvent('frontend_projection_received');
        recordFrontendEvent('frontend_projection_rendered');
        // ── Boot FSM: projection received ──────────────────────────
        runtime.bootFSM.transition('boot:projection_waiting', {});
      },
      onStatusChange(status, detail, attempts) {
        switch (status) {
          case 'connected':
            recordFrontendEvent('frontend_auth_ok');
            // ── Boot FSM: auth ok → authenticated ─────────────────
            runtime.bootFSM.transition('boot:authenticating', {});
            break;
          case 'authenticating':
            recordFrontendEvent('frontend_auth_attempt');
            runtime.bootFSM.transition('boot:authenticating', {});
            break;
          case 'auth_failed':
            recordFrontendEvent('frontend_auth_failed', { reason: detail });
            runtime.bootFSM.transition('boot:failed', { reason: detail || 'auth_failed' });
            break;
          case 'disconnected':
          case 'closed':
            recordFrontendEvent('frontend_disconnected');
            recordFrontendEvent('frontend_degraded');
            runtime.bootFSM.transition('boot:degraded', { reason: detail || 'disconnected' });
            break;
        }
        if (isDebug) updateDebugPanel(debugPanel, authority.snapshot());
      },
      onMessage(msg) {
        switch (msg.type) {
          case 'chat_state':
          case 'chat_state_updated':
            handleChatState(msg);
            break;
          case 'desktop_intent_result':
            handleIntentResult(msg);
            break;
          case 'progress_event':
            handleProgressEvent(msg);
            break;
          case 'progress_events':
            handleProgressEvents(msg.events || msg);
            break;
        }
      },
      onError(msg) {
        console.warn('[orchestrator] ws error:', msg);
      },
      onAuthFailed(msg) {
        console.warn('[orchestrator] auth failed:', msg);
      },
    });
    setWsClient(wsClient, authority);
  } else {
    // ── Boot FSM: no transport URL → config_failed ───────────────────
    runtime.bootFSM.transition('boot:config_failed', { reason: 'No WebSocket URL available' });
  }

  // Initialize notification system
  initNotificationListeners();
  updateNotificationBadge();

  // Wire notification bell click
  const bell = document.getElementById('notification-bell');
  if (bell) {
    bell.addEventListener('click', function () {
      toggleNotificationRail();
    });
  }

  // Wire notification rail close button
  const closeRail = document.getElementById('notification-close-rail');
  if (closeRail) {
    closeRail.addEventListener('click', function () {
      toggleNotificationRail();
    });
  }

  // Detect system notification support
  state.notifications.systemSupported = isSystemNotificationsSupported();
  state.notifications.systemPermission = getSystemNotificationPermission();

  // Start reactive loops (projection freshness, connection monitor, etc.)
  startReactiveLoops();

  recordFrontendEvent(LIFECYCLE.WIDGETS_MOUNT_STARTED, {});
  wireUI();
  recordFrontendEvent(LIFECYCLE.WIDGETS_MOUNT_OK, {});
  // ── Boot FSM: widgets rendered → ready ────────────────────────────
  // Precondition: bootFSM is in projection_waiting or authenticating
  runtime.bootFSM.transition('boot:rendering', {});
  runtime.bootFSM.transition('boot:ready', {});
  recordFrontendEvent('frontend_ready');
}

// Start boot flow when DOM is ready
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', boot);
} else {
  boot();
}

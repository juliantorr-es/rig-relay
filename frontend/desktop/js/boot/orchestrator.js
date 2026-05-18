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

  if (isDebug) {
    debugPanel = createDebugPanel();
  }

  recordFrontendEvent(LIFECYCLE.MODULE_GRAPH_LOADED, {});
  recordFrontendEvent('frontend_boot_started');

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
    }
  });

  const wsUrl = config.ws_url;
  const token = config.auth_token;

  if (wsUrl) {
    recordFrontendEvent('frontend_websocket_connecting');
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
      },
      onStatusChange(status, detail, attempts) {
        switch (status) {
          case 'connected':
            recordFrontendEvent('frontend_auth_ok');
            break;
          case 'auth_failed':
            recordFrontendEvent('frontend_auth_failed', { reason: detail });
            break;
          case 'disconnected':
          case 'closed':
            recordFrontendEvent('frontend_disconnected');
            recordFrontendEvent('frontend_degraded');
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
  }

  recordFrontendEvent(LIFECYCLE.WIDGETS_MOUNT_STARTED, {});
  wireUI();
  recordFrontendEvent(LIFECYCLE.WIDGETS_MOUNT_OK, {});
  recordFrontendEvent('frontend_ready');
}

// Start boot flow when DOM is ready
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', boot);
} else {
  boot();
}

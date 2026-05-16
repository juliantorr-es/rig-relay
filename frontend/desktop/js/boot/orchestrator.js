// Rig Relay — Boot Orchestrator

import { generateHandshakeId, setFrontendHandshakeId } from '../telemetry/correlation.js';
import { recordFrontendEvent, setFrontendHandshakeId as traceSetHandshakeId } from '../telemetry/frontendTrace.js';
import { fetchRuntimeConfig } from './runtimeConfig.js';
import { createDebugPanel, updateDebugPanel } from './debugPanel.js';
import { createTransportStateAuthority } from '../transportState.js';
import { ProjectionWebSocketClient } from '../transport.js';
import { renderStatusFromState } from '../status.js';

let debugPanel = null;
const urlParams = new URLSearchParams(window.location.search);
const isDebug = urlParams.get('boot_debug') === '1';

async function boot() {
  const handshakeId = generateHandshakeId();
  setFrontendHandshakeId(handshakeId);
  traceSetHandshakeId(handshakeId);

  if (isDebug) {
    debugPanel = createDebugPanel();
  }

  recordFrontendEvent('frontend_boot_started');

  const config = await fetchRuntimeConfig();
  
  // Create transport authority
  const authority = createTransportStateAuthority({
    onStateChange: (state) => {
      renderStatusFromState(state);
      if (isDebug) updateDebugPanel(debugPanel, state);
      recordFrontendEvent('frontend_transport_state', { 
        status: state.transport.status, 
        phase: state.transport.phase 
      });
    }
  });

  const wsUrl = config.ws_url;
  const token = config.auth_token;

  if (wsUrl) {
    recordFrontendEvent('frontend_websocket_connecting');
    const client = new ProjectionWebSocketClient(
      wsUrl,
      token,
      {
        onOpen: () => {
          authority.handleEvent('TRANSPORT_OPEN');
          recordFrontendEvent('frontend_websocket_open');
        },
        onClose: () => {
          authority.handleEvent('TRANSPORT_CLOSED');
        },
        onError: (e) => {
          authority.handleEvent('TRANSPORT_ERROR', e);
        },
        onMessage: (msg) => {
          // Handled elsewhere
        }
      }
    );
    client.connect();
  }

  recordFrontendEvent('frontend_ready');
}

// Start boot flow when DOM is ready
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', boot);
} else {
  boot();
}

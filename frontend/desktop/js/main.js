// Rig Relay — Main
// Bootstrap, wiring, event loop

import { state, setMode, applyModeDefaults } from './state.js';
import { initTransport, sendMessage, bridgeCall } from './transport.js';
import { renderStatusBar } from './status.js';
import { renderAllWidgets, cycleDisclosure, hideExpanded } from './widgets.js';
import { handleProjection, handleChatState, handleIntentResult,
         handleProgressEvent, handleProgressEvents } from './projection.js';
import { sendChatMessage, clearChat, cancelChat, dispatchIntent,
         updateCharCount } from './chat.js';
import { setText, el } from './utils.js';

// Window API for HTML onclick handlers
window.RigRelay = {
  cycleWidgetDisclosure: cycleDisclosure,
  dispatchIntent: dispatchIntent,
  closeExpanded: hideExpanded,
};

function handleMessage(msg) {
  switch (msg.type) {
    case '_transport':
      renderStatusBar();
      loadFromBridge();
      break;
    case 'auth_error':
    case 'auth_required':
      loadFromBridge();
      break;
    case 'projection':
      handleProjection(msg.data || msg);
      break;
    case 'chat_state':
    case 'chat_state_updated':
      handleChatState(msg.data || msg);
      break;
    case 'chat_message_accepted':
      handleChatState(msg.chat_state || msg);
      break;
    case 'desktop_intent_result':
      handleIntentResult(msg);
      break;
    case 'progress_event':
      handleProgressEvent(msg);
      break;
    case 'progress_events':
      handleProgressEvents(msg.events);
      break;
  }
}

async function loadFromBridge() {
  try {
    const proj = await bridgeCall('get_projection');
    if (proj) handleProjection(proj);
    const chat = await bridgeCall('get_chat_state');
    if (chat) handleChatState(chat);
  } catch (e) {
    console.warn('Bridge fallback:', e);
  }
}

function switchMode(mode) {
  setMode(mode);
  const grid = el('main-grid');
  if (grid) grid.setAttribute('data-mode', mode);

  // Update active button
  document.querySelectorAll('.mode-option').forEach(function(b) {
    b.classList.toggle('active', b.dataset.mode === mode);
  });

  // Clear and rebuild panel column based on mode widgets
  renderPanelColumn();
  renderAllWidgets();
}

function renderPanelColumn() {
  const panel = el('panel-column');
  if (!panel) return;

  // Widget assignments per mode
  const assignments = {
    operator: ['operatorHeader', 'safetyState', 'nextAction',
               'validationSummary', 'storageBudget', 'intentResult',
               'providerHealth'],
    review: ['progressTimeline', 'receiptTimeline', 'refinementBacklog',
             'reviewValidation', 'reviewStorage', 'reviewSnippets', 'reviewDataset'],
    system: ['identity', 'modelProviders', 'telemetryConsent',
             'authReceipts', 'connectionStatus', 'telemetryBundle',
             'updateStatus', 'projectionSources', 'storageDiagnostics'],
    technical: ['progressTimeline', 'receiptTimeline', 'projectionSources',
                'storageDiagnostics', 'telemetryBundle', 'updateStatus'],
  };

  const widgets = assignments[state.mode] || [];

  panel.innerHTML = '';
  widgets.forEach(function(id) {
    const card = document.createElement('div');
    card.id = 'widget-' + id;
    card.className = 'widget-card';
    card.setAttribute('data-disclosure', 'compact');
    panel.appendChild(card);
  });
}

async function init() {
  applyModeDefaults();

  // Register event listeners
  el('send-btn').addEventListener('click', sendChatMessage);
  el('clear-chat-btn').addEventListener('click', clearChat);
  el('chat-input').addEventListener('input', updateCharCount);
  el('chat-input').addEventListener('keydown', function(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendChatMessage();
    }
  });

  // Mode selector
  document.querySelectorAll('.mode-option').forEach(function(btn) {
    btn.addEventListener('click', function() {
      switchMode(btn.dataset.mode);
    });
  });

  // Expanded overlay close
  el('expanded-close-btn').addEventListener('click', hideExpanded);

  // Build initial panel
  renderPanelColumn();

  // Determine transport config — token delivered through pywebview bridge only.
  // URL query parameters are NOT used to carry ws_token as that exposes the
  // token to browser history, referrer headers, and browser extensions.
  let wsConfig = {
    host: '127.0.0.1',
    port: 9876,
    token: '',
  };

  if (window.pywebview && window.pywebview.api) {
    try {
      wsConfig = await bridgeCall('get_ws_config');
    } catch (e) {
      // Use defaults (no token — will fall back to bridge transport)
    }
  }

  const wsUrl = 'ws://' + wsConfig.host + ':' + wsConfig.port;
  initTransport(wsUrl, wsConfig.token, handleMessage);

  // Initial load from bridge if no WS
  if (!state.wsConnected) {
    setTimeout(loadFromBridge, 500);
  }

  // Periodic bridge fallback refresh — only when WebSocket is not connected
  setInterval(function() {
    if (!state.wsConnected && window.pywebview && window.pywebview.api) {
      loadFromBridge();
    }
  }, 15000);
}

document.addEventListener('DOMContentLoaded', init);

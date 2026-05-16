// Rig Relay — Main
// Bootstrap, wiring, event loop

import { state, setMode, applyModeDefaults } from './state.js';
import { initTransport, sendMessage } from './transport.js';
import { renderStatusBar } from './status.js';
import { renderAllWidgets, cycleDisclosure, hideExpanded } from './widgets.js';
import { handleProjection, handleChatState, handleIntentResult,
         handleProgressEvent, handleProgressEvents } from './projection.js';
import { sendChatMessage, clearChat, cancelChat, dispatchIntent,
         updateCharCount } from './chat.js';
import { getAutocompleteMatches } from './commands.js';
import { setText, el } from './utils.js';
import { initToolRuntimeWidget } from './tool_runtime_widget.js';

// Window API for HTML onclick handlers
window.RigRelay = {
  cycleWidgetDisclosure: cycleDisclosure,
  dispatchIntent: dispatchIntent,
  closeExpanded: hideExpanded,

  openProvider: function(provider) {
    if (window.pywebview && window.pywebview.api && window.pywebview.api.open_provider_web) {
      window.pywebview.api.open_provider_web(provider);
    } else {
      window.open({
        'chatgpt': 'https://chatgpt.com',
        'claude': 'https://claude.ai',
        'gemini': 'https://gemini.google.com',
        'deepseek': 'https://chat.deepseek.com',
        'mistral': 'https://chat.mistral.ai',
      }[provider] || 'about:blank', '_blank');
    }
  },

  sendToProvider: function(provider) {
    var input = document.getElementById('chat-input');
    var text = input ? input.value.trim() : '';
    if (!text) return;
    if (window.pywebview && window.pywebview.api && window.pywebview.api.send_to_provider) {
      window.pywebview.api.send_to_provider(provider, text);
    }
  },

  readFromProvider: function(provider) {
    if (window.pywebview && window.pywebview.api && window.pywebview.api.read_from_provider) {
      window.pywebview.api.read_from_provider(provider).then(function(result) {
        if (result && result.text) {
          var transcript = document.getElementById('chat-transcript');
          if (transcript) {
            var div = document.createElement('div');
            div.className = 'chat-message system';
            div.textContent = '[' + provider + '] ' + result.text.substring(0, 800);
            transcript.appendChild(div);
            transcript.scrollTop = transcript.scrollHeight;
          }
        }
      });
    }
  },

  // In-app OAuth: navigate the pywebview window to the auth URL
  // and poll for the callback code.
  openInAppAuth(authUrl, loopbackPort, stateHash, providerName) {
    if (window.pywebview && window.pywebview.api) {
      window.pywebview.api.open_auth_window(authUrl, loopbackPort, stateHash)
        .then(() => {
          // Navigate the webview to the auth URL
          if (window.location && typeof window.location.href !== 'undefined') {
            window.location.href = authUrl;
          }
          // Start polling for the callback
          const pollInterval = setInterval(() => {
            window.pywebview.api.poll_oauth_callback().then((cbResult) => {
              if (cbResult.status === 'completed') {
                clearInterval(pollInterval);
                // Navigate back to the app
                window.location.href = window.location.origin + window.location.pathname;
                // Trigger the exchange intent with the captured code
                const exchangeName = providerName === 'google'
                  ? 'sign_in_google_exchange'
                  : 'sign_in_github_exchange';
                dispatchIntent(exchangeName, {
                  auth_url: authUrl,
                  loopback_port: Number(loopbackPort),
                  state_hash: stateHash,
                  redirect_uri: 'http://127.0.0.1:' + loopbackPort + '/callback',
                });
              } else if (cbResult.status === 'error') {
                clearInterval(pollInterval);
                console.warn('OAuth error:', cbResult.message);
                window.location.href = window.location.origin + window.location.pathname;
              }
            });
          }, 1000);
        });
    } else {
      // Fallback: open system browser
      window.open(authUrl, '_blank');
    }
  },

  submitOAuthCode() {
    const input = document.getElementById('oauth-code-input');
    if (!input || !input.value) return;
    dispatchIntent('manual_code', { code: input.value });
  },
};

function handleMessage(msg) {
  switch (msg.type) {
    case '_transport':
      renderStatusBar();
      break;
    case 'auth_error':
    case 'auth_required':
      break;
    case 'projection':
      handleProjection(msg.data || msg);
      break;
    case 'chat_state':
    case 'chat_state_updated':
      handleChatState(msg.data || msg);
      break;
    case 'chat_message_accepted':
    case 'chat_cleared':
    case 'chat_cancelled':
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

function switchMode(mode) {
  setMode(mode);
  const grid = el('main-grid');
  if (grid) grid.setAttribute('data-mode', mode);

  // Update active button
  document.querySelectorAll('.mode-option').forEach(function(b) {
    const isActive = b.dataset.mode === mode;
    b.classList.toggle('active', isActive);
    b.setAttribute('aria-selected', String(isActive));
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
               'roleModel',
               'missionBoard',
               'ralphScout', 'ralphLifecycle',
               'validationSummary', 'storageBudget', 'intentResult',
               'providerHealth', 'council', 'providerDock',
               'workspaceStatus', 'fleetStatus'],
    review: ['progressTimeline', 'receiptTimeline', 'refinementBacklog',
             'reviewValidation', 'reviewStorage', 'reviewSnippets', 'reviewDataset'],
    system: ['identity', 'modelProviders', 'telemetryConsent',
             'authReceipts', 'connectionStatus', 'telemetryBundle',
             'updateStatus', 'projectionSources', 'storageDiagnostics'],
    technical: ['progressTimeline', 'receiptTimeline', 'projectionSources',
                'storageDiagnostics', 'telemetryBundle', 'updateStatus'],
  };

  const widgets = assignments[state.mode] || [];

  while (panel.firstChild) panel.removeChild(panel.firstChild);
  widgets.forEach(function(id, index) {
    const card = document.createElement('div');
    card.id = 'widget-' + id;
    card.className = 'widget-card';
    card.setAttribute('data-disclosure', 'compact');
    // Staggered entrance
    card.style.animationDelay = index * 50 + 'ms';
    card.classList.add('card-entering');
    panel.appendChild(card);
  });
}

async function init() {
  applyModeDefaults();

  // Register widget renderers (must happen before first projection)
  initToolRuntimeWidget();

  // Register event listeners
  el('send-btn').addEventListener('click', sendChatMessage);
  el('clear-chat-btn').addEventListener('click', clearChat);
  el('chat-input').addEventListener('input', updateCharCount);
  el('chat-input').addEventListener('keydown', function(e) {
    // Tab: autocomplete slash command
    if (e.key === 'Tab' && !e.shiftKey) {
      const input = el('chat-input');
      if (input && input.value.startsWith('/')) {
        e.preventDefault();
        const matches = getAutocompleteMatches(input.value);
        if (matches.length === 1) {
          input.value = matches[0] + ' ';
          updateCharCount();
        }
        return;
      }
    }
    // Enter: send
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

  let config = null;
  if (window.pywebview && window.pywebview.api && window.pywebview.api.get_runtime_config) {
    try {
      config = await window.pywebview.api.get_runtime_config();
    } catch (e) {
      console.warn("Failed to fetch runtime config from bridge:", e);
    }
  }
  if (!config) {
    config = {
      ws_url: 'ws://127.0.0.1:9876',
      ws_protocol: 'ws',
      static_protocol: 'http',
      tls_enabled: false,
      local_mode: true,
      merge_enabled: false,
      push_enabled: false,
    };
  }

  const wsUrl = config.ws_url || 'ws://127.0.0.1:9876';
  const token = config.token || (window.pywebview && window.pywebview.token) || '';
  initTransport(wsUrl, token, handleMessage);
}

document.addEventListener('DOMContentLoaded', init);

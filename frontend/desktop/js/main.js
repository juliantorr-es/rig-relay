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
import { createTransportStateAuthority, STATUS_LABELS } from './transportState.js';

const urlParams = new URLSearchParams(window.location.search);

const transportAuthority = createTransportStateAuthority({
  handshakeId: '',
  onTransition(snap) {
    // Sync canonical state → shared presentation state on every transition
    state.wsConnected = snap.wsConnected;
    state.transport.status = snap.transport.status;
    state.transport.phase = snap.transport.phase;
    state.transport.lastEvent = snap.transport.lastEvent;
    state.transport.lastError = snap.transport.lastError;
    state.transport.handshakeId = snap.transport.handshakeId;
    state.transport.updatedAt = snap.transport.updatedAt;
    // Auto-render status bar
    renderStatusBar();
    // Update debug panel if visible
    _updateDebugPanel(snap);
  },
});

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
      if (msg.status) {
        state._transportStatus = msg.status;
        state._transportDetail = msg.detail || '';
      }
      // Status bar is auto-rendered by onTransition — no manual call needed
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

function _recordFrontendEvent(type, message) {
  if (window.pywebview && window.pywebview.api && window.pywebview.api.record_frontend_event) {
    window.pywebview.api.record_frontend_event({type: type, message: message || ''}).catch(function() {});
  }
}

// ── Boot Debug Panel ──────────────────────────────────────────────────
// Visible with ?boot_debug=1

function _createDebugPanel() {
  if (!urlParams.has('boot_debug') || urlParams.get('boot_debug') !== '1') return;

  const panel = document.createElement('div');
  panel.id = 'boot-debug-panel';
  panel.setAttribute('aria-label', 'Transport Debug Panel');
  panel.style.cssText =
    'position:fixed;bottom:0;right:0;width:340px;max-height:260px;overflow-y:auto;' +
    'background:rgba(0,0,0,0.92);color:#00ff88;font-family:monospace;font-size:11px;' +
    'padding:10px 12px;border-top-left-radius:8px;z-index:9999;line-height:1.6;' +
    'border-top:1px solid #00ff44;border-left:1px solid #00ff44;';

  const title = document.createElement('div');
  title.style.cssText = 'font-weight:bold;margin-bottom:6px;color:#00ff44;font-size:12px;';
  title.textContent = '⚡ Transport Debug';
  panel.appendChild(title);

  const table = document.createElement('table');
  table.id = 'boot-debug-table';
  table.style.cssText = 'width:100%;border-collapse:collapse;';
  panel.appendChild(table);

  document.body.appendChild(panel);
  _updateDebugPanel(transportAuthority.snapshot());
}

function _updateDebugPanel(snap) {
  const table = document.getElementById('boot-debug-table');
  if (!table) return;

  const rows = [
    ['Phase', snap.transport.phase || '—'],
    ['Status', snap.transport.status || '—'],
    ['wsConnected', String(snap.wsConnected)],
    ['Handshake ID', (snap.transport.handshakeId || '—').substring(0, 20)],
    ['Last Event', snap.transport.lastEvent || '—'],
    ['Last Error', snap.transport.lastError || '—'],
    ['Breadcrumb', snap.lastBreadcrumbResult ? snap.lastBreadcrumbResult.path : '—'],
    ['Projection TS', snap.lastProjectionTimestamp || '—'],
    ['Transitions', String(snap.transitionCount || 0)],
    ['Label', snap.label || '—'],
  ];

  let html = '';
  rows.forEach(function(r) {
    html += '<tr><td style="color:#888;padding:1px 6px 1px 0;white-space:nowrap;">' +
      r[0] + '</td><td style="color:#00ff88;padding:1px 0;">' + r[1] + '</td></tr>';
  });
  table.innerHTML = html;
}

// ── Init ──────────────────────────────────────────────────────────────

async function init() {
  console.log("[bridge:frontend] init started");
  transportAuthority.dispatch('runtime_config_loaded', { reason: 'DOMContentLoaded' });
  _recordFrontendEvent("frontend_boot_started", "DOMContentLoaded");
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

  // Create debug panel if ?boot_debug=1
  _createDebugPanel();

  let config = null;
  let configSource = 'fallback';

  // Wait for pywebview API to become available (up to 5s in debug)
  if (window.pywebview === undefined && typeof window.pywebviewready !== 'undefined') {
    console.log("[bridge:frontend] waiting for pywebviewready...");
  }
  let _pywebviewWaitMs = 0;
  const _pywebviewMaxWait = 5000;
  while (
    _pywebviewWaitMs < _pywebviewMaxWait &&
    (!window.pywebview || !window.pywebview.api || !window.pywebview.api.get_runtime_config)
  ) {
    await new Promise(function(r) { setTimeout(r, 100); });
    _pywebviewWaitMs += 100;
  }
  if (_pywebviewWaitMs > 0) {
    console.log("[bridge:frontend] pywebview API wait: " + _pywebviewWaitMs + "ms");
  }

  if (window.pywebview && window.pywebview.api && window.pywebview.api.get_runtime_config) {
    try {
      _recordFrontendEvent("frontend_runtime_config_requested");
      config = await window.pywebview.api.get_runtime_config();
      configSource = 'pywebview_api';
      var tokenPresent = !!(config && config.token);
      transportAuthority.dispatch(
        tokenPresent ? 'runtime_config_loaded' : 'runtime_config_invalid',
        {
          reason: 'runtime config loaded',
          token_present: tokenPresent,
          ws_url: config && config.ws_url ? config.ws_url : '',
        }
      );
      _recordFrontendEvent("frontend_runtime_config_loaded", "source=" + configSource + " token=" + (tokenPresent ? 'present' : 'MISSING'));
      console.log("[bridge:frontend] runtime config loaded from pywebview API, token=" + (tokenPresent ? 'present' : 'MISSING'));
    } catch (e) {
      console.warn("Failed to fetch runtime config from bridge:", e);
      _recordFrontendEvent("frontend_boot_error", "Failed to fetch runtime config: " + (e.message || 'unknown'));
      transportAuthority.dispatch('frontend_fatal', { reason: e.message || 'runtime config fetch failed' });
      configSource = 'error';
    }
  } else {
    console.log("[bridge:frontend] no pywebview API after " + _pywebviewWaitMs + "ms wait — using default config");
  }

  if (!config && window.__RIG_RELAY_RUNTIME_CONFIG__) {
    config = window.__RIG_RELAY_RUNTIME_CONFIG__;
    configSource = 'injected_runtime_config';
    var injectedTokenPresent = !!(config && config.token);
    transportAuthority.dispatch(
      injectedTokenPresent ? 'runtime_config_loaded' : 'runtime_config_invalid',
      {
        reason: 'injected runtime config loaded',
        token_present: injectedTokenPresent,
        ws_url: config && config.ws_url ? config.ws_url : '',
      }
    );
    _recordFrontendEvent("frontend_runtime_config_loaded", "source=" + configSource + " token=" + (injectedTokenPresent ? 'present' : 'MISSING'));
    console.log("[bridge:frontend] runtime config loaded from injected bootstrap, token=" + (injectedTokenPresent ? 'present' : 'MISSING'));
  }

  if (!config) {
    config = {
      ws_url: deriveWebSocketUrl({
        pageProtocol: window.location.protocol,
        host: window.location.hostname || '127.0.0.1',
        port: parseInt(urlParams.get('ws_port')) || 9876,
      }),
      ws_protocol: 'ws',
      static_protocol: 'http',
      tls_enabled: false,
      local_mode: true,
      merge_enabled: false,
      push_enabled: false,
      token: '',
    };
    transportAuthority.dispatch('runtime_config_invalid', { reason: 'fallback config', token_present: false });
  }

  var token = config.token || (window.pywebview && window.pywebview.token) || '';
  var wsUrl = config.ws_url || deriveWebSocketUrl({
    pageProtocol: window.location.protocol,
    host: window.location.hostname || '127.0.0.1',
    port: parseInt(urlParams.get('ws_port')) || 9876,
  });
  var hasToken = !!token;
  console.log("[bridge:frontend] config: source=" + configSource + " token_present=" + hasToken + " ws_url=" + wsUrl);

  if (!hasToken) {
    console.warn("[bridge:frontend] WARNING: No auth token — WebSocket auth will fail");
    _recordFrontendEvent("frontend_boot_error", "No auth token in runtime config (source=" + configSource + ")");
  }

  initTransport(wsUrl, token, handleMessage, transportAuthority, config.handshake_id || config.handshakeId || '');
  console.log("[bridge:frontend] init complete");
}

function deriveWebSocketUrl({ pageProtocol, host, port, explicitUrl } = {}) {
  if (explicitUrl) return explicitUrl;
  const scheme = pageProtocol === 'https:' ? 'wss' : 'ws';
  const resolvedHost = host || '127.0.0.1';
  const resolvedPort = port || 9876;
  return `${scheme}://${resolvedHost}:${resolvedPort}/ws`;
}

document.addEventListener('DOMContentLoaded', init);

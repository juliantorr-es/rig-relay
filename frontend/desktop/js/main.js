// CONTRACT: Compat UI Wiring (Legacy Layer)
// ──────────────────────────────────────────
// Owner: frontend/desktop/js/main.js (compat — migrating to orchestrator.js)
// Safety: wireUI() must be called AFTER transport is established.
//         window.RigRelay API is the single JS bridge surface.
//         No backend policy decisions here — display only.
//
// Rig Relay — Compat UI Wiring (legacy layer)
// Boot ownership has moved to js/boot/orchestrator.js.
// This module provides UI event wiring and the window.RigRelay API.
// Call wireUI() from the orchestrator after transport is established.

import { setMode } from './state.js';
import { sendMessage } from './transport.js';
import { renderAllWidgets, cycleDisclosure, hideExpanded } from './widgets.js';
import { sendChatMessage, clearChat, cancelChat, dispatchIntent,
         updateCharCount } from './chat.js';
import { getAutocompleteMatches } from './commands.js';
import { el } from './utils.js';
import { initToolRuntimeWidget } from './tool_runtime_widget.js';

const cycleWidgetDisclosure = cycleDisclosure;

export function wireUI() {
  // ── Window API for HTML onclick handlers ──────────────────────────
  // ═══ STAGE 5: Operational — RigRelay API exposed ═══
  // Only after wireUI() is called from orchestrator.js.
  window.RigRelay = {
    cycleWidgetDisclosure,
    dispatchIntent,
    closeExpanded: hideExpanded,

    openProvider(provider) {
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

    sendToProvider(provider) {
      var input = document.getElementById('chat-input');
      var text = input ? input.value.trim() : '';
      if (!text) return;
      if (window.pywebview && window.pywebview.api && window.pywebview.api.send_to_provider) {
        window.pywebview.api.send_to_provider(provider, text);
      }
    },

    readFromProvider(provider) {
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

    openInAppAuth(authUrl, loopbackPort, stateHash, providerName, authSessionId) {
      // Convenience wrapper — backend session MUST already be running.
      // If pywebview available, attempt in-app window; otherwise browser tab.
      if (!authUrl) {
        console.warn('openInAppAuth: no auth_url provided');
        return;
      }
      if (window.pywebview && window.pywebview.api && window.pywebview.api.open_auth_window) {
        window.pywebview.api.open_auth_window(authUrl, loopbackPort, stateHash)
          .then(() => {
            if (authSessionId) {
              window.RigRelay._pollAuthSession(authSessionId, providerName);
            }
          });
      } else {
        window.open(authUrl, '_blank');
        if (authSessionId) {
          window.RigRelay._pollAuthSession(authSessionId, providerName);
        }
      }
    },

    signInWithProvider(providerName) {
      const startIntent = 'sign_in_' + providerName + '_start';
      const sendBtn = el('send-btn');
      const savedSendHandler = sendBtn ? sendBtn.onclick : null;

      // Dispatch start intent, then handle the result to show actions
      window.RigRelay._pendingAuthStart = { provider: providerName };
      dispatchIntent(startIntent, {});
    },

    checkAuthStatus(providerName) {
      const sessionId = window.RigRelay._authSessionId;
      if (!sessionId) {
        dispatchIntent('identity_status');
        return;
      }
      const pollIntent = 'sign_in_' + providerName + '_poll';
      dispatchIntent(pollIntent, { auth_session_id: sessionId });
    },

    _pollAuthSession(sessionId, providerName) {
      // Poll the backend session status periodically
      const pollIntent = 'sign_in_' + providerName + '_poll';
      let attempts = 0;
      const maxAttempts = 60;
      window.RigRelay._authPollTimer = setInterval(() => {
        attempts++;
        if (attempts > maxAttempts) {
          clearInterval(window.RigRelay._authPollTimer);
          window.RigRelay._authPollTimer = null;
          console.warn('Auth poll timed out after ' + maxAttempts + ' attempts');
          return;
        }
        dispatchIntent(pollIntent, { auth_session_id: sessionId });
      }, 2000);
    },

    cancelAuth(providerName) {
      const sessionId = window.RigRelay._authSessionId;
      if (!sessionId) return;
      if (window.RigRelay._authPollTimer) {
        clearInterval(window.RigRelay._authPollTimer);
        window.RigRelay._authPollTimer = null;
      }
      const cancelIntent = 'sign_in_' + providerName + '_cancel';
      dispatchIntent(cancelIntent, { auth_session_id: sessionId });
    },

    submitManualCode(providerName, code) {
      const sessionId = window.RigRelay._authSessionId;
      if (!sessionId || !code) return;
      const manualIntent = 'sign_in_' + providerName + '_manual_code';
      dispatchIntent(manualIntent, { auth_session_id: sessionId, manual_code: code });
    },

    submitOAuthCode() {
      const input = document.getElementById('oauth-code-input');
      if (!input || !input.value) return;
      dispatchIntent('manual_code', { code: input.value });
    },
  };

  // ── Chat composer listeners ───────────────────────────────────────
  el('send-btn').addEventListener('click', sendChatMessage);
  el('clear-chat-btn').addEventListener('click', clearChat);
  el('chat-input').addEventListener('input', updateCharCount);
  el('chat-input').addEventListener('keydown', function(e) {
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
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendChatMessage();
    }
  });

  // ── Mode selector ─────────────────────────────────────────────────
  document.querySelectorAll('.mode-option').forEach(function(btn) {
    btn.addEventListener('click', function() {
      _switchMode(btn.dataset.mode);
    });
  });

  // ── Expanded overlay close ────────────────────────────────────────
  el('expanded-close-btn').addEventListener('click', hideExpanded);

  // ── Tool runtime widget ───────────────────────────────────────────
  initToolRuntimeWidget();

  // ── Initial panel render ──────────────────────────────────────────
  _renderPanelColumn();
}

// ── Internal helpers ─────────────────────────────────────────────────

function _switchMode(mode) {
  setMode(mode);
  const grid = el('main-grid');
  if (grid) grid.setAttribute('data-mode', mode);

  document.querySelectorAll('.mode-option').forEach(function(b) {
    const isActive = b.dataset.mode === mode;
    b.classList.toggle('active', isActive);
    b.setAttribute('aria-selected', String(isActive));
  });

  _renderPanelColumn();
  renderAllWidgets();

  // ── Kernel mode FSM: keep runtime state in sync ───────────────────
  // Precondition: runtime kernel initialized (window.__RIG_RELAY_RUNTIME__ exists)
  var rt = window.__RIG_RELAY_RUNTIME__;
  if (rt && rt.modeFSM) {
    rt.modeFSM.transition('mode:switch', { mode: mode });
  }
}

function _renderPanelColumn() {
  const panel = el('panel-column');
  if (!panel) return;

  const mode = document.getElementById('main-grid')?.dataset.mode || 'operator';
  const assignments = {
    operator: ['operatorHeader', 'safetyState', 'nextAction',
               'roleModel',
               'missionBoard',
               'ralphScout', 'ralphLifecycle',
                'profileReadmeLane',
                'spiderwebTopology',
                'validationSummary', 'releaseGate', 'storageBudget', 'intentResult',
               'providerHealth', 'council', 'providerDock',
               'workspaceStatus', 'fleetStatus',
               'bridgeProtocol'],
    review: ['progressTimeline', 'receiptTimeline', 'refinementBacklog',
             'reviewValidation', 'reviewStorage', 'reviewSnippets', 'reviewDataset'],
    system: ['identity', 'modelProviders', 'telemetryConsent',
             'authReceipts', 'connectionStatus', 'bridgeProtocol', 'telemetryBundle',
             'updateStatus', 'projectionSources', 'storageDiagnostics'],
    technical: ['progressTimeline', 'receiptTimeline', 'projectionSources',
                'storageDiagnostics', 'telemetryBundle', 'updateStatus',
                'bridgeProtocol'],
  };

  const widgets = assignments[mode] || [];

  while (panel.firstChild) panel.removeChild(panel.firstChild);
  widgets.forEach(function(id, index) {
    const card = document.createElement('div');
    card.id = 'widget-' + id;
    card.className = 'widget-card';
    card.setAttribute('data-disclosure', 'compact');
    card.style.animationDelay = index * 50 + 'ms';
    card.classList.add('card-entering');
    panel.appendChild(card);
  });
}

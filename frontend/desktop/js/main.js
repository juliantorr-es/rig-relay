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

    openInAppAuth(authUrl, loopbackPort, stateHash, providerName) {
      if (window.pywebview && window.pywebview.api) {
        window.pywebview.api.open_auth_window(authUrl, loopbackPort, stateHash)
          .then(() => {
            if (window.location && typeof window.location.href !== 'undefined') {
              window.location.href = authUrl;
            }
            const pollInterval = setInterval(() => {
              window.pywebview.api.poll_oauth_callback().then((cbResult) => {
                if (cbResult.status === 'completed') {
                  clearInterval(pollInterval);
                  window.location.href = window.location.origin + window.location.pathname;
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
        window.open(authUrl, '_blank');
      }
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
               'validationSummary', 'releaseGate', 'storageBudget', 'intentResult',
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

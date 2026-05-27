// Rig Relay — Chat
// Chat rendering, input handling, intent dispatch

import { state } from './state.js';
import { escapeHtml, el } from './utils.js';
import { sendMessage } from './transport.js';
import { renderAllWidgets } from './widgets.js';
import { isCommand, executeCommand, getAutocompleteMatches } from './commands.js';

let streamingMsgId = null;

export function renderChat(data) {
  if (!data || !data.messages) return;

  state.chat.messages = data.messages;
  state.chat.backendWired = data.backend_wired || false;

  const sendBtn = el('send-btn');
  if (sendBtn) sendBtn.disabled = !state.chat.backendWired;

  const transcript = el('chat-transcript');
  if (!transcript) return;

  while (transcript.firstChild) transcript.removeChild(transcript.firstChild);
  data.messages.forEach(function(msg) {
    appendMessageToDOM(transcript, msg);
  });
  scrollToBottom();
}

function appendMessageToDOM(transcript, msg) {
  const role = msg.role || 'system';
  const div = document.createElement('div');
  div.className = 'chat-message ' + role;
  if (msg.metadata && msg.metadata.is_streaming) {
    div.classList.add('streaming');
  }
  div.textContent = msg.content || '';
  transcript.appendChild(div);
}

function appendMessage(role, content) {
  const transcript = el('chat-transcript');
  if (!transcript) return;
  appendMessageToDOM(transcript, { role, content });
  scrollToBottom();
}

function scrollToBottom() {
  const transcript = el('chat-transcript');
  if (transcript) {
    requestAnimationFrame(() => {
      transcript.scrollTop = transcript.scrollHeight;
    });
  }
}

export function sendChatMessage() {
  const input = el('chat-input');
  if (!input || !input.value.trim()) return;

  const text = input.value.trim();

  // Slash command — execute locally, don't send to backend
  if (isCommand(text)) {
    const result = executeCommand(text);
    if (result) {
      appendMessage('system', result);
    }
    input.value = '';
    updateCharCount();
    return;
  }

  if (!state.chat.backendWired) return;

  input.value = '';
  updateCharCount();

  // Optimistic append
  appendMessage('user', text);

  // Dispatch via available transport
  const sentWS = sendMessage({
    type: 'send_chat_message',
    text: text,
    client_message_id: 'msg_' + Date.now()
  });

  if (!sentWS) {
    appendMessage('error', 'WebSocket not connected. Cannot send message.');
  }
}

export function clearChat() {
  sendMessage({ type: 'clear_chat' });
  const transcript = el('chat-transcript');
  if (transcript) {
    while (transcript.firstChild) transcript.removeChild(transcript.firstChild);
  }
}

export function cancelChat() {
  sendMessage({ type: 'cancel_chat_response' });
}

export function updateCharCount() {
  const input = el('chat-input');
  const count = el('char-count');
  if (!input || !count) return;

  const text = input.value;

  if (isCommand(text)) {
    const matches = getAutocompleteMatches(text);
    if (matches.length === 1 && text === matches[0]) {
      count.textContent = matches[0] + ' ✓';
    } else if (matches.length > 0) {
      count.textContent = matches.slice(0, 3).join('  ') + (matches.length > 3 ? ' ...' : '');
    } else {
      count.textContent = text.length + ' — type /help';
    }
  } else {
    count.textContent = text.length + '/4000';
  }
}

export function dispatchIntent(name, params) {
  // ── Button state: disable all buttons that trigger this intent ──
  if (!state._pendingIntents) state._pendingIntents = {};
  const buttons = document.querySelectorAll('button');
  const matching = [];
  buttons.forEach(function(btn) {
    var onclick = btn.getAttribute('onclick') || '';
    if (onclick.indexOf("dispatchIntent('" + name + "'") !== -1) {
      btn.disabled = true;
      btn._originalText = btn.textContent;
      btn.textContent = intentPendingLabel(name);
      matching.push(btn);
    }
  });
  state._pendingIntents[name] = matching;

  const sentWS = sendMessage({
    type: 'desktop_intent_request',
    intent_name: name,
    parameters: params || {},
    dry_run: true
  });

  if (!sentWS) {
    console.warn('Intent dispatch failed: WebSocket not connected');
    // Re-enable immediately if send failed
    restoreIntentButton(name, 'failed');
  }
}

export function restoreIntentButton(name, status) {
  if (!state._pendingIntents) return;
  var buttons = state._pendingIntents[name];
  if (!buttons || !buttons.length) return;
  buttons.forEach(function(btn) {
    if (status === 'completed') {
      btn.textContent = btn._originalText + ' \u2713';
      btn.disabled = true;
      setTimeout(function() {
        btn.textContent = btn._originalText;
        btn.disabled = false;
      }, 2000);
    } else {
      btn.textContent = btn._originalText;
      btn.disabled = false;
    }
  });
  delete state._pendingIntents[name];
}

function intentPendingLabel(name) {
  var mapping = {
    run_validation_suite: 'Running\u2026',
    run_storage_audit: 'Auditing\u2026',
    ralph_scan: 'Scanning\u2026',
    ralph_approve: 'Approving\u2026',
    ralph_decline: 'Declining\u2026',
    ralph_rescan: 'Rescanning\u2026',
    fleet_queue_snapshot: 'Snapshotting\u2026',
    run_queue_plan_dry_run: 'Planning\u2026',
    run_spawn_plan_dry_run: 'Spawning\u2026',
    fleet_orchestrate: 'Running\u2026',
    workspace_init: 'Bootstrapping\u2026',
    worktree_list: 'Listing\u2026',
    council_consult: 'Consulting\u2026',
    provider_status: 'Refreshing\u2026',
    orchestrator_new_mission: 'Creating\u2026',
    review_with_orchestrator: 'Loading\u2026',
    ralph_background_toggle_on: 'Enabling\u2026',
    ralph_background_toggle_off: 'Disabling\u2026',
    ralph_sign_off: 'Signing off\u2026',
    ralph_adopt: 'Adopting\u2026',
    sign_in_google_exchange: 'Exchanging\u2026',
    sign_in_github_exchange: 'Exchanging\u2026',
  };
  return mapping[name] || 'Pending\u2026';
}

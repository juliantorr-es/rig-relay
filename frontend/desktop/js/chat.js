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
  const sentWS = sendMessage({
    type: 'desktop_intent_request',
    intent_name: name,
    parameters: params || {},
    dry_run: true
  });

  if (!sentWS) {
    console.warn('Intent dispatch failed: WebSocket not connected');
  }
}

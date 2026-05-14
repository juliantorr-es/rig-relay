// Rig Relay — Chat
// Chat rendering, input handling, intent dispatch

import { state } from './state.js';
import { escapeHtml, setHTML, el } from './utils.js';
import { sendMessage, bridgeCall } from './transport.js';
import { renderAllWidgets } from './widgets.js';

let streamingMsgId = null;

export function renderChat(data) {
  if (!data || !data.messages) return;

  state.chat.messages = data.messages;
  state.chat.backendWired = data.backend_wired || false;

  const sendBtn = el('send-btn');
  if (sendBtn) sendBtn.disabled = !state.chat.backendWired;

  const transcript = el('chat-transcript');
  if (!transcript) return;

  transcript.innerHTML = '';
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
  if (!state.chat.backendWired) return;

  const text = input.value.trim();
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
    bridgeCall('send_chat_message', text).catch(function() {
      appendMessage('error', 'Failed to send message. Backend unavailable.');
    });
  }
}

export function clearChat() {
  sendMessage({ type: 'clear_chat' });
  const transcript = el('chat-transcript');
  if (transcript) transcript.innerHTML = '';
}

export function cancelChat() {
  sendMessage({ type: 'cancel_chat_response' });
}

export function updateCharCount() {
  const input = el('chat-input');
  const count = el('char-count');
  if (input && count) {
    count.textContent = input.value.length + '/4000';
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
    bridgeCall('execute_intent', JSON.stringify({
      intent_name: name,
      parameters: params || {},
      dry_run: true
    })).catch(function(e) {
      console.warn('Intent dispatch failed:', e);
    });
  }
}

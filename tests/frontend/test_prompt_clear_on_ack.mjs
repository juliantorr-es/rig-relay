import { readFileSync } from 'fs';
import { Script, createContext } from 'vm';
import { join, dirname } from 'path';
import { fileURLToPath } from 'url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const APP_JS_PATH = join(__dirname, '..', '..', 'frontend', 'rig_console', 'app.js');

const source = `${readFileSync(APP_JS_PATH, 'utf-8')}\n;globalThis.__rigConsoleTest = { connect, handleMessage, submitPrompt };`;
const messages = [];
const input = {
  value: '',
  style: { height: 'auto' },
  disabled: false,
  scrollHeight: 42,
  addEventListener() {},
};
const badges = {
  'connection-badge': { textContent: '', className: '' },
  'status-badge': { textContent: '', className: '' },
  'turn-status': { textContent: '' },
  sid: { textContent: '' },
  dropped: { textContent: '' },
  transcript: { innerHTML: '', scrollTop: 0, scrollHeight: 0 },
  'send-btn': { disabled: false },
  'cancel-btn': { style: { display: 'none' } },
  'prompt-input': input,
};

let wsInstance = null;

class FakeWebSocket {
  static OPEN = 1;

  constructor() {
    this.readyState = FakeWebSocket.OPEN;
    wsInstance = this;
  }

  send(message) {
    messages.push(JSON.parse(message));
  }
}

const sandbox = {
  WS_URL: 'ws://127.0.0.1:0',
  WS_TOKEN: 'token',
  WebSocket: FakeWebSocket,
  requestAnimationFrame: (fn) => fn(),
  document: {
    addEventListener() {},
    getElementById(id) {
      return badges[id] || null;
    },
  },
  JSON,
  setTimeout,
  clearTimeout,
  console,
};

const context = createContext(sandbox);
new Script(source).runInContext(context);

context.__rigConsoleTest.connect();
if (wsInstance && typeof wsInstance.onopen === 'function') {
  wsInstance.onopen();
}
input.value = 'hello rig';
context.__rigConsoleTest.submitPrompt(input);

if (input.value !== 'hello rig') {
  throw new Error('prompt cleared before ack acceptance');
}

context.__rigConsoleTest.handleMessage({
  schema: 'rig.ws.server.ack.v1',
  status: 'refused',
  reason: 'blocked',
});

if (input.value !== 'hello rig') {
  throw new Error('refused ack should preserve prompt text');
}

input.value = 'hello rig';
context.__rigConsoleTest.submitPrompt(input);
context.__rigConsoleTest.handleMessage({
  schema: 'rig.ws.server.ack.v1',
  status: 'accepted',
});

if (input.value !== '') {
  throw new Error('accepted ack should clear prompt text');
}

if (!wsInstance || messages.length < 2) {
  throw new Error('expected websocket traffic to be recorded');
}

console.log('prompt clear on ack: ok');

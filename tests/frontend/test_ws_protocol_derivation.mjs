import { deriveWebSocketUrl } from '../../frontend/desktop/websocket.js';

const httpUrl = deriveWebSocketUrl({
  pageProtocol: 'http:',
  host: '127.0.0.1',
  port: 9876,
});
if (httpUrl !== 'ws://127.0.0.1:9876/ws') {
  throw new Error(`expected ws:// derivation, got ${httpUrl}`);
}

const httpsUrl = deriveWebSocketUrl({
  pageProtocol: 'https:',
  host: '127.0.0.1',
  port: 9876,
});
if (httpsUrl !== 'wss://127.0.0.1:9876/ws') {
  throw new Error(`expected wss:// derivation, got ${httpsUrl}`);
}

const explicitUrl = deriveWebSocketUrl({
  pageProtocol: 'http:',
  host: '127.0.0.1',
  port: 9876,
  explicitUrl: 'ws://example.invalid:1111/ws',
});
if (explicitUrl !== 'ws://example.invalid:1111/ws') {
  throw new Error(`expected explicit websocket_url to win, got ${explicitUrl}`);
}

console.log('ws protocol derivation: ok');

// Rig Relay Desktop WebSocket Client
// Connects to local WebSocket projection stream for live updates.
// Token-gated: sends auth on connect before any protocol messages.
// Falls back to pywebview JS bridge if WebSocket unavailable.

class ProjectionWebSocketClient {
  constructor(options = {}) {
    this.wsUrl = options.wsUrl || deriveWebSocketUrl({
      pageProtocol: window.location && window.location.protocol ? window.location.protocol : 'http:',
      host: window.location && window.location.hostname ? window.location.hostname : '127.0.0.1',
      port: window.location && window.location.port ? Number(window.location.port) : 9876,
    });
    this.token = options.token || null;
    this.reconnectDelay = options.reconnectDelay || 2000;
    this.maxReconnectDelay = options.maxReconnectDelay || 30000;
    this.onProjection = options.onProjection || (() => {});
    this.onStatusChange = options.onStatusChange || (() => {});
    this.onError = options.onError || (() => {});
    this.onAuthFailed = options.onAuthFailed || (() => {});
    this.onMessage = options.onMessage || (() => {});
    this.transportMachine = options.transportMachine || null;
    this.handshakeId = options.handshakeId || null;

    this.ws = null;
    this.connected = false;
    this.authenticated = false;
    this.reconnectAttempts = 0;
    this.currentDelay = this.reconnectDelay;
    this._intentionalClose = false;
    this._subscriptionActive = false;
    this._firstProjectionReceived = false;
    this._connectTimeout = null;
    this._connectTimeoutMs = options.connectTimeout || 15000;
    this.closeCode = null;
    this.closeReason = '';
    this.wasClean = false;
    this.lastBridgeStatusAt = null;
    this.backendState = '';
    this.backendSessionId = '';
    this._bridgeStatusStaleMs = options.bridgeStatusStaleMs || 30000;
    this.onBridgeStale = options.onBridgeStale || (() => {});

    if (this.token) {
      this.connect();
    } else {
      this.onStatusChange('offline', 'No token available');
    }
  }

  connect() {
    if (this._intentionalClose) return;
    if (!this.token) {
      this.onStatusChange('offline', 'No token available');
      return;
    }

    try {
      this.transportMachine && this.transportMachine.transition('websocket_connecting', {
        ws_url: this.wsUrl,
      });
      this.ws = new WebSocket(this.wsUrl);
      this._startConnectTimeout();
    } catch (e) {
      this._handleError('WebSocket construction failed: ' + e.message);
      this._scheduleReconnect();
      return;
    }

    this.ws.onopen = () => {
      this._clearConnectTimeout();
      this.connected = true;
      this.authenticated = false;
      console.log("[bridge:frontend] WebSocket opened");
      if (window.pywebview && window.pywebview.api && window.pywebview.api.record_frontend_event) {
        window.pywebview.api.record_frontend_event({
          type: "frontend_ws_open"
          }).catch(function() {});
      }
      this.transportMachine && this.transportMachine.transition('websocket_open', {
        ws_url: this.wsUrl,
      });
      this.onStatusChange('authenticating');

      // Send auth as first message
      this.send({
        type: 'auth',
        token: this.token,
        handshake_id: this.handshakeId || undefined,
      });
      this.transportMachine && this.transportMachine.transition('auth_sent', {
        ws_url: this.wsUrl,
      });
    };

    this.ws.onmessage = (event) => {
      let message;
      try {
        message = JSON.parse(event.data);
      } catch (e) {
        this._handleError('Failed to parse message: ' + e.message);
        return;
      }

      // ── Bridge Protocol: route v1 envelope messages ──────────────────
      if (message.schema_version === 'rig.relay.bridge_message.v1' && message.message_id) {
        // Transition transport authority for projection envelopes
        if (message.kind === 'projection' && this.transportMachine) {
          this.transportMachine.transition('projection_received', {
            ws_url: this.wsUrl,
          });
        }
        // Track bridge_status lifecycle events for backend liveness
        if (message.kind === 'lifecycle_event' && message.payload && message.payload.bridge_runtime_state) {
          this.lastBridgeStatusAt = Date.now();
          this.backendState = message.payload.bridge_runtime_state || '';
          this.backendSessionId = message.payload.backend_session_id || '';
          if (this.transportMachine) {
            this.transportMachine.setBackendState({
              state: this.backendState,
              last_at: this.lastBridgeStatusAt,
              session_id: this.backendSessionId,
              idle_sequence: message.payload.idle_sequence,
              active_work_count: message.payload.active_work_count,
            });
          }
        }
        this.onMessage(message);
        if (message.kind === 'projection' && this.transportMachine) {
          this.transportMachine.transition('projection_rendered', {
            ws_url: this.wsUrl,
            projection_digest: (message.payload && message.payload.digest) || '',
          });
        }
        return;
      }

      switch (message.type) {
        case 'auth_ok':
          this.authenticated = true;
          this.reconnectAttempts = 0;
          this.currentDelay = this.reconnectDelay;
          if (window.pywebview && window.pywebview.api && window.pywebview.api.record_frontend_event) {
            window.pywebview.api.record_frontend_event({
              type: "frontend_handshake_succeeded",
              token_present: true,
              message: "WebSocket auth_ok",
            }).catch(function() {});
          }
          this.transportMachine && this.transportMachine.transition('auth_ok', {
            ws_url: this.wsUrl,
          });
          this.onStatusChange('connected');

          // Request initial data
          this.send({ type: 'get_projection' });
          this.send({ type: 'get_available_actions' });
          break;

        case 'auth_error':
          this.authenticated = false;
          this.transportMachine && this.transportMachine.transition('auth_failed', {
            reason: message.message || 'Invalid token',
            ws_url: this.wsUrl,
          });
          this.onAuthFailed('Server rejected token: ' + (message.message || 'unknown'));
          this.onStatusChange('auth_failed', message.message || 'Invalid token');
          this._intentionalClose = true;
          this.ws.close();
          break;

        case 'auth_required':
          this.authenticated = false;
          this.transportMachine && this.transportMachine.transition('auth_failed', {
            reason: 'Authentication required',
            ws_url: this.wsUrl,
          });
          this.onAuthFailed('Server requires authentication');
          this.onStatusChange('auth_failed', 'Authentication required');
          this._intentionalClose = true;
          this.ws.close();
          break;

        case 'auth_timeout':
          this.authenticated = false;
          this.transportMachine && this.transportMachine.transition('auth_failed', {
            reason: message.message || 'Authentication timeout',
            ws_url: this.wsUrl,
          });
          this.onAuthFailed('Authentication timed out: ' + (message.message || ''));
          this.onStatusChange('auth_failed', message.message || 'Authentication timeout');
          this._intentionalClose = true;
          this.ws.close();
          break;

        case 'rate_limited':
          this._handleError('Rate limited by server: ' + (message.message || ''));
          this.transportMachine && this.transportMachine.transition('boot_error', {
            reason: message.message || 'Rate limited',
            ws_url: this.wsUrl,
          });
          this.onStatusChange('auth_failed', message.message || 'Rate limited');
          this._intentionalClose = true;
          this.ws.close();
          break;

        case 'message_too_large':
          this._handleError('Message too large: ' + (message.message || ''));
          this.transportMachine && this.transportMachine.transition('boot_error', {
            reason: message.message || 'Message too large',
            ws_url: this.wsUrl,
          });
          this.onStatusChange('auth_failed', message.message || 'Message too large');
          this._intentionalClose = true;
          this.ws.close();
          break;

        case 'projection':
          if (!this._firstProjectionReceived) {
            this._firstProjectionReceived = true;
            console.log("[bridge:frontend] first projection received from server");
            if (window.pywebview && window.pywebview.api && window.pywebview.api.record_frontend_event) {
              window.pywebview.api.record_frontend_event({type: "frontend_first_projection_received"}).catch(function() {});
            }
          }
          this.transportMachine && this.transportMachine.transition('projection_received', {
            ws_url: this.wsUrl,
          });
          this.onProjection(message.data);
          this.transportMachine && this.transportMachine.transition('projection_rendered', {
            ws_url: this.wsUrl,
            projection_digest: message.data && message.data.digest,
          });
          break;

        case 'available_actions':
          this._availableActions = message.actions || [];
          break;

        case 'error':
          this._handleError('Server error: ' + (message.message || 'unknown'));
          break;

        case 'desktop_intent_result':
          this.onMessage(message);
          break;

        case 'chat_state':
        case 'chat_state_updated':
          this.onMessage(message);
          break;

        case 'progress_event':
          this.onMessage(message);
          break;

        case 'progress_events':
          this.onMessage(message);
          break;

        case 'analytics_projection':
          this.onMessage(message);
          break;

        case 'pong':
          // Keepalive acknowledged
          break;

        default:
          this._handleError('Unknown message type: ' + message.type);
      }
    };

    this.ws.onclose = (event) => {
      this._clearConnectTimeout();
      this.connected = false;
      this.authenticated = false;
      this.closeCode = event ? event.code : null;
      this.closeReason = event ? (event.reason || '') : '';
      this.wasClean = event ? !!event.wasClean : false;
      this.transportMachine && this.transportMachine.transition('websocket_closed', {
        reason: 'socket closed',
        ws_url: this.wsUrl,
        close_code: this.closeCode,
        close_reason: this.closeReason,
        was_clean: this.wasClean,
      });
      this.onStatusChange('disconnected', {
        close_code: this.closeCode,
        close_reason: this.closeReason,
        was_clean: this.wasClean,
      });
      if (!this._intentionalClose) {
        this._scheduleReconnect();
      }
    };

    this.ws.onerror = () => {
      this._handleError('WebSocket connection error');
    };
  }

  send(data) {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
      this._handleError('Cannot send: not connected');
      return false;
    }
    try {
      this.ws.send(JSON.stringify(data));
      return true;
    } catch (e) {
      this._handleError('Send failed: ' + e.message);
      return false;
    }
  }

  subscribe(interval) {
    this._subscriptionActive = true;
    return this.send({ type: 'subscribe', interval: interval || 30 });
  }

  sendMessage(data) {
    return this.send(data);
  }

  unsubscribe() {
    this._subscriptionActive = false;
    return this.send({ type: 'unsubscribe' });
  }

  requestProjection() {
    return this.send({ type: 'get_projection' });
  }

  close() {
    this._intentionalClose = true;
    this._subscriptionActive = false;
    this.authenticated = false;
    if (this.ws) {
      this.ws.close(1000, 'Client closing');
      this.ws = null;
    }
    this.connected = false;
    this.onStatusChange('closed');
  }

  isBackendStale() {
    if (!this.lastBridgeStatusAt) return false;
    return Date.now() - this.lastBridgeStatusAt > this._bridgeStatusStaleMs;
  }

  getBackendStatus() {
    return {
      state: this.backendState,
      last_status_at: this.lastBridgeStatusAt,
      session_id: this.backendSessionId,
      is_stale: this.isBackendStale(),
    };
  }

  _startConnectTimeout() {
    this._clearConnectTimeout();
    this._connectTimeout = setTimeout(() => {
      if (!this.connected && !this._intentionalClose) {
        this._handleError('WebSocket connection timed out after ' + this._connectTimeoutMs + 'ms');
        if (this.ws) {
          this.ws.close();
          this.ws = null;
        }
        this._scheduleReconnect();
      }
    }, this._connectTimeoutMs);
  }

  _clearConnectTimeout() {
    if (this._connectTimeout) {
      clearTimeout(this._connectTimeout);
      this._connectTimeout = null;
    }
  }

  _scheduleReconnect() {
    if (this._intentionalClose) return;
    this.reconnectAttempts++;
    const delay = Math.min(
      this.currentDelay * Math.pow(1.5, this.reconnectAttempts - 1),
      this.maxReconnectDelay
    );
    this.onStatusChange('reconnecting', delay, this.reconnectAttempts);
    setTimeout(() => this.connect(), delay);
  }

  _handleError(message) {
    this.onError(message);
  }
}

function deriveWebSocketUrl({ pageProtocol, host, port, explicitUrl } = {}) {
  if (explicitUrl) return explicitUrl;
  const scheme = pageProtocol === 'https:' ? 'wss' : 'ws';
  const resolvedHost = host || '127.0.0.1';
  const resolvedPort = port || 9876;
  return `${scheme}://${resolvedHost}:${resolvedPort}/ws`;
}

export { ProjectionWebSocketClient, deriveWebSocketUrl };

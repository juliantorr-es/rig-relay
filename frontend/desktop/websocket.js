// Rig Relay Desktop WebSocket Client
// Connects to local WebSocket projection stream for live updates.
// Token-gated: sends auth on connect before any protocol messages.
// Falls back to pywebview JS bridge if WebSocket unavailable.

class ProjectionWebSocketClient {
  constructor(options = {}) {
    this.wsUrl = options.wsUrl || 'wss://127.0.0.1:9876';
    this.token = options.token || null;
    this.reconnectDelay = options.reconnectDelay || 2000;
    this.maxReconnectDelay = options.maxReconnectDelay || 30000;
    this.onProjection = options.onProjection || (() => {});
    this.onStatusChange = options.onStatusChange || (() => {});
    this.onError = options.onError || (() => {});
    this.onAuthFailed = options.onAuthFailed || (() => {});
    this.onMessage = options.onMessage || (() => {});

    this.ws = null;
    this.connected = false;
    this.authenticated = false;
    this.reconnectAttempts = 0;
    this.currentDelay = this.reconnectDelay;
    this._intentionalClose = false;
    this._subscriptionActive = false;

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
      this.ws = new WebSocket(this.wsUrl);
    } catch (e) {
      this._handleError('WebSocket construction failed: ' + e.message);
      this._scheduleReconnect();
      return;
    }

    this.ws.onopen = () => {
      this.connected = true;
      this.authenticated = false;
      this.onStatusChange('authenticating');

      // Send auth as first message
      this.send({ type: 'auth', token: this.token });
    };

    this.ws.onmessage = (event) => {
      let message;
      try {
        message = JSON.parse(event.data);
      } catch (e) {
        this._handleError('Failed to parse message: ' + e.message);
        return;
      }

      switch (message.type) {
        case 'auth_ok':
          this.authenticated = true;
          this.reconnectAttempts = 0;
          this.currentDelay = this.reconnectDelay;
          this.onStatusChange('connected');

          // Request initial data
          this.send({ type: 'get_projection' });
          this.send({ type: 'get_available_actions' });
          break;

        case 'auth_error':
          this.authenticated = false;
          this.onAuthFailed('Server rejected token: ' + (message.message || 'unknown'));
          this.onStatusChange('auth_failed', message.message || 'Invalid token');
          this._intentionalClose = true;
          this.ws.close();
          break;

        case 'auth_required':
          this.authenticated = false;
          this.onAuthFailed('Server requires authentication');
          this.onStatusChange('auth_failed', 'Authentication required');
          this._intentionalClose = true;
          this.ws.close();
          break;

        case 'auth_timeout':
          this.authenticated = false;
          this.onAuthFailed('Authentication timed out: ' + (message.message || ''));
          this.onStatusChange('auth_failed', message.message || 'Authentication timeout');
          this._intentionalClose = true;
          this.ws.close();
          break;

        case 'rate_limited':
          this._handleError('Rate limited by server: ' + (message.message || ''));
          this.onStatusChange('auth_failed', message.message || 'Rate limited');
          this._intentionalClose = true;
          this.ws.close();
          break;

        case 'message_too_large':
          this._handleError('Message too large: ' + (message.message || ''));
          this.onStatusChange('auth_failed', message.message || 'Message too large');
          this._intentionalClose = true;
          this.ws.close();
          break;

        case 'projection':
          this.onProjection(message.data);
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

        case 'pong':
          // Keepalive acknowledged
          break;

        default:
          this._handleError('Unknown message type: ' + message.type);
      }
    };

    this.ws.onclose = () => {
      this.connected = false;
      this.authenticated = false;
      this.onStatusChange('disconnected');
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
      this.ws.close();
      this.ws = null;
    }
    this.connected = false;
    this.onStatusChange('closed');
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

export { ProjectionWebSocketClient };

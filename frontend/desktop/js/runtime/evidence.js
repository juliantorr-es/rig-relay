// Rig Relay — Frontend Runtime Evidence Emission
// Browser-side runtime kernel evidence module.
// Emits structured events through pywebview bridge (primary) or HTTP fallback.
// Maintains an in-memory ring buffer.
// CONTRACT: Never log tokens or secrets to console.
//           No full chat message content, raw file contents, or prompt content
//           in evidence payloads. Callers are responsible for this invariant.

// Evidence event type constants — single frozen authority for all event kinds.
const EvidenceEventType = Object.freeze({
  RUNTIME_INITIALIZED: 'RUNTIME_INITIALIZED',
  STATE_TRANSITION: 'STATE_TRANSITION',
  BOOT_PHASE_CHANGE: 'BOOT_PHASE_CHANGE',
  TRANSPORT_CHANGE: 'TRANSPORT_CHANGE',
  PROJECTION_RECEIVED: 'PROJECTION_RECEIVED',
  PROJECTION_STALE: 'PROJECTION_STALE',
  WIDGET_MOUNTED: 'WIDGET_MOUNTED',
  WIDGET_FAILED: 'WIDGET_FAILED',
  INTENT_DISPATCHED: 'INTENT_DISPATCHED',
  INTENT_RESOLVED: 'INTENT_RESOLVED',
  MODE_CHANGED: 'MODE_CHANGED',
  LOOP_STARTED: 'LOOP_STARTED',
  LOOP_CANCELLED: 'LOOP_CANCELLED',
  MULTI_TAB_DETECTED: 'MULTI_TAB_DETECTED',
  DEGRADATION_SET: 'DEGRADATION_SET',
  EFFECT_RUN: 'EFFECT_RUN',
  EFFECT_FAILED: 'EFFECT_FAILED',
  EVIDENCE_FLUSHED: 'EVIDENCE_FLUSHED',
  KERNEL_SNAPSHOT: 'KERNEL_SNAPSHOT',
});

// Keys whose name (case-insensitive) contains any of these substrings are
// redacted. A match replaces the entire value with '[REDACTED]'.
var _SECRET_KEY_RE = /token|secret|key|password|credential|api_key|auth|bearer/i;

// JWT header prefix and PEM boundary marker — redacted at the value level
// independent of key name, because they are token-shaped payloads.
var _JWT_PREFIX = 'eyJ';
var _PEM_BOUNDARY = '-----BEGIN';

var _MAX_SANITIZE_DEPTH = 10;
var _DEFAULT_MAX_BUFFER_SIZE = 500;

// ── action_id generation ───────────────────────────────────────────────
// Prefer crypto.randomUUID(); fall back to timestamp + random for older
// browsers or restricted contexts (e.g. file:// origins).

function _generateActionId() {
  if (globalThis.crypto && typeof globalThis.crypto.randomUUID === 'function') {
    return globalThis.crypto.randomUUID();
  }
  return Date.now().toString(36) + '_' + Math.random().toString(36).slice(2, 8);
}

// ── value-level heuristics ─────────────────────────────────────────────

function _isHexLike(str) {
  // Hex string longer than 32 chars is likely a content hash (SHA-256, etc.).
  // These are safe — they are derived fingerprints, not secrets.
  if (str.length <= 32) return false;
  return /^[0-9a-fA-F]+$/.test(str);
}

function _isTokenLike(str) {
  if (typeof str !== 'string') return false;
  // JWT: starts with base64url-encoded header {"alg":...
  if (str.indexOf(_JWT_PREFIX) === 0) return true;
  // PEM-encoded key material or certificate
  if (str.indexOf(_PEM_BOUNDARY) !== -1) return true;
  return false;
}

// ── recursive sanitizer ────────────────────────────────────────────────
// Recursively walks objects and arrays up to _MAX_SANITIZE_DEPTH levels.
// - Secret-key matches → value replaced with '[REDACTED]'
// - JWT / PEM string values → '[REDACTED]' (hex hashes > 32 chars kept)
// - Non-string primitives pass through unchanged
// - Exceeding max depth returns the sentinel '[MAX_DEPTH]'

function _sanitize(value, depth) {
  if (depth > _MAX_SANITIZE_DEPTH) return '[MAX_DEPTH]';
  if (value === null || value === undefined) return value;

  if (Array.isArray(value)) {
    var arr = [];
    for (var i = 0; i < value.length; i++) {
      arr.push(_sanitize(value[i], depth + 1));
    }
    return arr;
  }

  if (typeof value === 'object') {
    var out = {};
    for (var k in value) {
      if (!Object.prototype.hasOwnProperty.call(value, k)) continue;
      if (_SECRET_KEY_RE.test(k)) {
        out[k] = '[REDACTED]';
        // Do not recurse — the value is already replaced.
        continue;
      }
      out[k] = _sanitize(value[k], depth + 1);
    }
    return out;
  }

  if (typeof value === 'string') {
    // Content hashes (hex > 32 chars) are safe — pass through.
    if (_isHexLike(value)) return value;
    // Token-shaped strings are redacted regardless of key name.
    if (_isTokenLike(value)) return '[REDACTED]';
    return value;
  }

  // number, boolean — pass through
  return value;
}

// ── bridge emission ────────────────────────────────────────────────────
// Primary: window.pywebview.api.record_frontend_event(payload)
// Fallback: fetch('GET', '/frontend-event?...') with query-param encoding.
// Both paths are fire-and-forget; failures are silent.
// The full event object is sent, not just type + detail, because the
// backend evidence schema accepts all fields.

function _emit(event, eventType, sanitizedDetails, handshakeId) {
  // pywebview bridge (primary)
  if (window.pywebview && window.pywebview.api && window.pywebview.api.record_frontend_event) {
    try {
      window.pywebview.api.record_frontend_event(event).catch(function () {});
    } catch (_ignored) {
      // Bridge unavailable during early boot; fall through to HTTP.
    }
    return;
  }

  // HTTP GET fallback
  var detailParam = encodeURIComponent(JSON.stringify(sanitizedDetails));
  var url =
    '/frontend-event?type=' +
    encodeURIComponent(eventType) +
    '&handshake_id=' +
    encodeURIComponent(handshakeId) +
    '&detail=' +
    detailParam;
  if (typeof fetch === 'function') {
    fetch(url, {
      method: 'GET',
      credentials: 'same-origin',
      cache: 'no-store',
      keepalive: true,
    }).catch(function () {});
  }
}

// ── public factory ─────────────────────────────────────────────────────

export function createEvidenceRecorder(config) {
  var handshakeId = config.handshakeId || '';
  var frontendSessionId = config.frontendSessionId || '';
  var maxBufferSize = config.maxBufferSize || _DEFAULT_MAX_BUFFER_SIZE;
  var _seq = 0;
  var _buffer = [];

  // ---- record ----------------------------------------------------------
  // Evidence boundary — every call produces one structured event.
  // - Sanitizes details recursively (secret keys, JWT/PEM tokens).
  // - Auto-populates action_id, timestamp, handshake_id, frontend_session_id, sequence.
  // - Lifts state_before, state_after, lifecycle_step, source, status to top-level
  //   fields when present in details.
  // - Pushes to ring buffer; emits through bridge or HTTP fallback.
  // Must NOT include: raw file contents, full chat messages, prompt text,
  // unredacted tokens or secrets.

  function record(eventType, details) {
    _seq++;
    var raw = details || {};

    // Recursive sanitization removes secret-keyed values and token-shaped strings.
    var sanitized = _sanitize(raw, 0);

    var event = {
      action_id: _generateActionId(),
      timestamp: new Date().toISOString(),
      handshake_id: handshakeId,
      frontend_session_id: frontendSessionId,
      sequence: _seq,
      event_type: eventType,
      details: sanitized,
    };

    // Lift snapshot / lifecycle annotations if provided.
    if (sanitized.state_before !== undefined) {
      event.state_before = sanitized.state_before;
    }
    if (sanitized.state_after !== undefined) {
      event.state_after = sanitized.state_after;
    }
    if (sanitized.lifecycle_step !== undefined) {
      event.lifecycle_step = sanitized.lifecycle_step;
    }
    if (sanitized.source !== undefined) {
      event.source = sanitized.source;
    }
    if (sanitized.status !== undefined) {
      event.status = sanitized.status;
    }

    // Ring buffer — evict oldest when over capacity.
    _buffer.push(event);
    while (_buffer.length > maxBufferSize) {
      _buffer.shift();
    }

    // Emit to backend.
    _emit(event, eventType, sanitized, handshakeId);
  }

  // ---- getEvents -------------------------------------------------------
  // Returns a shallow copy of all buffered events (newest last).

  function getEvents() {
    return _buffer.slice();
  }

  // ---- getEventsJsonl --------------------------------------------------
  // Serializes buffered events as JSONL (one JSON object per line, trailing
  // newline when non-empty).

  function getEventsJsonl() {
    var lines = [];
    for (var i = 0; i < _buffer.length; i++) {
      lines.push(JSON.stringify(_buffer[i]));
    }
    return lines.join('\n') + (lines.length > 0 ? '\n' : '');
  }

  // ---- getSnapshot -----------------------------------------------------
  // Compact kernel snapshot — evidence count + time bounds + session identity.
  // No event payloads are included.

  function getSnapshot() {
    var first = _buffer.length > 0 ? _buffer[0].timestamp : null;
    var last = _buffer.length > 0 ? _buffer[_buffer.length - 1].timestamp : null;
    return {
      evidence_count: _buffer.length,
      first_event_at: first,
      last_event_at: last,
      handshake_id: handshakeId,
      frontend_session_id: frontendSessionId,
    };
  }

  // ---- clear -----------------------------------------------------------
  // Empties the ring buffer. Does not emit an event (callers should emit
  // EVIDENCE_FLUSHED before clearing when traceability matters).

  function clear() {
    _buffer.length = 0;
  }

  return {
    record: record,
    getEvents: getEvents,
    getEventsJsonl: getEventsJsonl,
    getSnapshot: getSnapshot,
    clear: clear,
  };
}

export { EvidenceEventType };

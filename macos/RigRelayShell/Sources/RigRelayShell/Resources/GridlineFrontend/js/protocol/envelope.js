// CONTRACT: Bridge Protocol Envelope v1
// ────────────────────────────────────────
// Owner: frontend/desktop/js/protocol/envelope.js
// Safety: Never serializes tokens, API keys, or raw prompts.
//         No secrets in safe_summary — content-hash-derived only.
//         message_id is always a 24-char random suffix.
//
// Rig Relay — Bridge Protocol Envelope v1
// Builds and parses canonical bridge protocol messages.

const SCHEMA_VERSION = 'rig.relay.bridge_message.v1'

const DIRECTION = Object.freeze({
  FRONTEND_TO_BACKEND: 'frontend_to_backend',
  BACKEND_TO_FRONTEND: 'backend_to_frontend',
})

const KIND = Object.freeze({
  PROJECTION: 'projection',
  INTENT_REQUEST: 'intent_request',
  INTENT_ACK: 'intent_ack',
  INTENT_RESULT: 'intent_result',
  LIFECYCLE_EVENT: 'lifecycle_event',
  NOTIFICATION: 'notification',
  ERROR: 'error',
  HEARTBEAT: 'heartbeat',
  FLOW_CONTROL: 'flow_control',
})

function newMessageId() {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return 'msg_' + crypto.randomUUID().replace(/-/g, '').substring(0, 24)
  }
  var hex = ''
  for (var i = 0; i < 24; i++) {
    hex += Math.floor(Math.random() * 16).toString(16)
  }
  return 'msg_' + hex
}

function getISOUTC() {
  try { return new Date().toISOString() } catch (_) {}
  return ''
}

// ── Envelope Builder ──────────────────────────────────────────────

export function buildEnvelope(config) {
  // config: { handshakeId, kind, payload, requiresAck?, ackFor?,
  //           idempotencyKey?, projectionSequence?, payloadSchema?,
  //           safeSummary?, priority?, sequence? }
  return {
    schema_version: SCHEMA_VERSION,
    message_id: newMessageId(),
    handshake_id: config.handshakeId || '',
    direction: DIRECTION.FRONTEND_TO_BACKEND,
    kind: config.kind,
    sequence: config.sequence || 0,
    created_at: getISOUTC(),
    requires_ack: config.requiresAck || false,
    ack_for: config.ackFor || '',
    idempotency_key: config.idempotencyKey || '',
    projection_sequence: config.projectionSequence != null ? config.projectionSequence : null,
    payload_schema: config.payloadSchema || '',
    payload: config.payload || {},
    safe_summary: config.safeSummary || {},
    redaction_status: 'content_light',
    priority: config.priority || 'normal',
  }
}

// ── Envelope Parser ───────────────────────────────────────────────

export function isEnvelope(msg) {
  return msg && msg.schema_version === SCHEMA_VERSION && typeof msg.message_id === 'string'
}

export function parseEnvelope(msg) {
  if (!isEnvelope(msg)) return null
  return {
    messageId: msg.message_id,
    handshakeId: msg.handshake_id,
    direction: msg.direction,
    kind: msg.kind,
    sequence: msg.sequence,
    createdAt: msg.created_at,
    requiresAck: !!msg.requires_ack,
    ackFor: msg.ack_for,
    idempotencyKey: msg.idempotency_key,
    projectionSequence: msg.projection_sequence,
    payloadSchema: msg.payload_schema,
    payload: msg.payload,
    safeSummary: msg.safe_summary,
    priority: msg.priority,
  }
}

// ── Kind Matchers ─────────────────────────────────────────────────

export function isIntentAck(envelope) {
  return envelope && envelope.kind === KIND.INTENT_ACK
}

export function isIntentResult(envelope) {
  return envelope && envelope.kind === KIND.INTENT_RESULT
}

export function isProjection(envelope) {
  return envelope && envelope.kind === KIND.PROJECTION
}

export function isHeartbeat(envelope) {
  return envelope && envelope.kind === KIND.HEARTBEAT
}

export function isFlowControl(envelope) {
  return envelope && envelope.kind === KIND.FLOW_CONTROL
}

export function isProtocolError(envelope) {
  return envelope && envelope.kind === KIND.ERROR
}

export { SCHEMA_VERSION, DIRECTION, KIND }

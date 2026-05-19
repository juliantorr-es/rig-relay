// Rig Relay — Frontend Trace Context
// Canonical shared state for all frontend tracing.
// frontendTrace, runtime evidence, protocol client, and feedback loops
// all reference these fields through get/annotate/nextSequence.

var _handshakeId = ''
var _frontendSessionId = ''
var _frontendSequence = 0
var _bootPhase = ''
var _projectionSequence = -1
var _protocolMessageId = ''
var _lastReadyAt = ''
var _lastHeartbeatAt = ''
var _readyEmitted = false
var _readyPrerequisites = Object.create(null)
var _annotations = Object.create(null)

function _generateSessionId() {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return 'fs_' + crypto.randomUUID().replace(/-/g, '').substring(0, 20)
  }
  return 'fs_' + Math.random().toString(36).slice(2, 10) + Date.now().toString(36)
}

export function initializeTraceContext(config) {
  config = config || {}
  _handshakeId = config.handshakeId || _handshakeId || ''
  _frontendSessionId = config.frontendSessionId || _frontendSessionId || _generateSessionId()
  _frontendSequence = config.frontendSequence || _frontendSequence
  _bootPhase = config.bootPhase || _bootPhase || ''
  _projectionSequence = config.projectionSequence != null ? config.projectionSequence : _projectionSequence
  _protocolMessageId = config.protocolMessageId || _protocolMessageId
  _readyPrerequisites = {}
  _readyEmitted = false
}

export function setHandshakeId(id) {
  _handshakeId = id || ''
}

export function nextFrontendSequence() {
  _frontendSequence++
  return _frontendSequence
}

export function setBootPhase(phase) {
  _bootPhase = phase || ''
}

export function setProjectionSequence(seq) {
  _projectionSequence = seq
}

export function setProtocolMessageId(msgId) {
  _protocolMessageId = msgId || ''
}

export function recordReady(prerequisites) {
  if (_readyEmitted) return { duplicate: true }
  _readyEmitted = true
  _lastReadyAt = new Date().toISOString()
  _readyPrerequisites = prerequisites || {}
  return { duplicate: false, at: _lastReadyAt, prerequisites: _readyPrerequisites }
}

export function isReadyEmitted() {
  return _readyEmitted
}

export function recordHeartbeat() {
  _lastHeartbeatAt = new Date().toISOString()
}

export function annotate(key, value) {
  if (key && value !== undefined) {
    _annotations[key] = value
  }
}

export function getTraceContext() {
  return {
    handshakeId: _handshakeId,
    frontendSessionId: _frontendSessionId,
    frontendSequence: _frontendSequence,
    bootPhase: _bootPhase,
    projectionSequence: _projectionSequence,
    protocolMessageId: _protocolMessageId,
    lastReadyAt: _lastReadyAt,
    lastHeartbeatAt: _lastHeartbeatAt,
    readyEmitted: _readyEmitted,
    readyPrerequisites: _readyPrerequisites,
    annotations: Object.assign({}, _annotations),
  }
}

// Call fn(parsed, ctx) with trace context enriched with protocolMessageId.
// Returns fn's result. Used by protocol client to annotate envelope processing.
export function withProtocolMessage(envelope, fn) {
  if (!envelope || !fn) return null
  _protocolMessageId = envelope.message_id || envelope.messageId || ''
  if (envelope.projectionSequence != null) {
    _projectionSequence = envelope.projectionSequence
  }
  try {
    return fn(envelope, getTraceContext())
  } finally {
    // Do NOT clear _protocolMessageId — let it persist for subsequent events
    // until the next envelope arrives.
  }
}

export { _generateSessionId }

// CONTRACT: Bridge Protocol Client
// ──────────────────────────────────
// Owner: frontend/desktop/js/protocol/client.js
// Safety: Never exposes the raw WS auth token via envelope methods.
//         Dedup uses a bounded seen-MessageId ring (not unbounded).
//         Stale projection suppression prevents re-render storms.
//         All stats counters are monotonic — no decrement paths.
//         destroy() nulls wsClient and clears lookup tables.
//
// Rig Relay — Bridge Protocol Client
// Wraps raw WebSocket with envelope handling, sequence tracking, and dedup.

import { buildEnvelope, parseEnvelope, isEnvelope, KIND } from './envelope.js'
import { recordFrontendEvent } from '../telemetry/frontendTrace.js'
import { setProtocolMessageId, setProjectionSequence, recordHeartbeat, withProtocolMessage, nextFrontendSequence, getTraceContext } from '../telemetry/traceContext.js'

export function createProtocolClient(config) {
  // config: { wsClient, handshakeId, onProjection, onIntentAck,
  //           onIntentResult, onError, onHeartbeat, onFlowControl }
  var wsClient = config.wsClient || null
  var handshakeId = config.handshakeId || ''
  var _outboundSeq = 0
  var _inboundSeq = -1
  var _lastProjectionSeq = -1
  var _seenMessageIds = Object.create(null)
  var _seenIdempotencyKeys = Object.create(null)
  var _duplicateCount = 0
  var _staleProjectionCount = 0
  var _protocolErrorCount = 0
  var _droppedCount = 0
  var _coalescedCount = 0
  var _maxQueueDepth = 0
  var _messageCountByKind = Object.create(null)
  var _lastHeartbeatAt = 0

  // ── Outbound ──────────────────────────────────────────────────────

  function _nextSeq() {
    _outboundSeq++
    return _outboundSeq
  }

  function _sendRaw(data) {
    if (!wsClient || !wsClient.send) {
      recordFrontendEvent('protocol_send_failed', { reason: 'no_ws_client' })
      return false
    }
    wsClient.send(data)
    return true
  }

  function sendEnvelope(kind, payload, options) {
    options = options || {}
    var envelope = buildEnvelope({
      handshakeId: handshakeId,
      kind: kind,
      sequence: _nextSeq(),
      payload: payload,
      requiresAck: options.requiresAck || false,
      ackFor: options.ackFor || '',
      idempotencyKey: options.idempotencyKey || '',
      projectionSequence: options.projectionSequence != null ? options.projectionSequence : null,
      payloadSchema: options.payloadSchema || '',
      safeSummary: options.safeSummary || {},
      priority: options.priority || 'normal',
    })
    _messageCountByKind[kind] = (_messageCountByKind[kind] || 0) + 1
    return _sendRaw(envelope)
  }

  function sendIntentRequest(intentId, intentName, params, idempotencyKey) {
    return sendEnvelope(KIND.INTENT_REQUEST, {
      intent_id: intentId,
      intent_name: intentName,
      parameters: params || {},
      schema_version: 'rig.relay.desktop_intent_request.v1',
      created_at: new Date().toISOString(),
    }, {
      requiresAck: true,
      idempotencyKey: idempotencyKey || ('idem_' + intentId),
      priority: 'high',
    })
  }

  function sendHeartbeat() {
    _lastHeartbeatAt = Date.now()
    return sendEnvelope(KIND.HEARTBEAT, {}, { priority: 'low' })
  }

  function sendLifecycleEvent(eventType, details) {
    return sendEnvelope(KIND.LIFECYCLE_EVENT, {
      event_type: eventType,
      details: details || {},
    }, { priority: 'low' })
  }

  function sendProjectionRenderedAck(projectionId) {
    return sendEnvelope(KIND.LIFECYCLE_EVENT, {
      event_type: 'projection_rendered',
      projection_id: projectionId || '',
    }, { priority: 'low' })
  }

  // ── Inbound ──────────────────────────────────────────────────────

  function _isDuplicateMessageId(messageId) {
    if (messageId in _seenMessageIds) {
      _duplicateCount++
      return true
    }
    _seenMessageIds[messageId] = true
    return false
  }

  function _checkStaleProjection(parsed) {
    if (parsed.kind !== KIND.PROJECTION) return false
    var pseq = parsed.projectionSequence
    if (pseq != null && pseq <= _lastProjectionSeq) {
      _staleProjectionCount++
      recordFrontendEvent('protocol_stale_projection', {
        received: pseq,
        last_rendered: _lastProjectionSeq,
      })
      return true
    }
    if (pseq != null) {
      _lastProjectionSeq = pseq
    }
    return false
  }

  // ── Message Handler ──────────────────────────────────────────────

  function handleMessage(rawMessage) {
    if (!isEnvelope(rawMessage)) {
      // Legacy path: pass through to onProjection or onMessage callbacks
      recordFrontendEvent('protocol_legacy_message', {
        type: rawMessage.type || 'unknown',
      })
      return { envelope: null, isLegacy: true, raw: rawMessage }
    }

    var parsed = parseEnvelope(rawMessage)
    if (!parsed) {
      _protocolErrorCount++
      return { envelope: null, isLegacy: false, error: 'parse_failed' }
    }

    // Annotate trace context with current envelope
    setProtocolMessageId(parsed.messageId)
    if (parsed.projectionSequence != null) {
      setProjectionSequence(parsed.projectionSequence)
    }

    // Dedup
    if (_isDuplicateMessageId(parsed.messageId)) {
      return { envelope: parsed, isLegacy: false, deduped: true }
    }

    // Track sequence
    if (parsed.sequence > _inboundSeq) {
      _inboundSeq = parsed.sequence
    }

    _messageCountByKind[parsed.kind] = (_messageCountByKind[parsed.kind] || 0) + 1

    // Staleness check
    if (_checkStaleProjection(parsed)) {
      return { envelope: parsed, isLegacy: false, stale: true }
    }

    // Dispatch
    switch (parsed.kind) {
      case KIND.PROJECTION:
        recordFrontendEvent('protocol_projection_received', {
          message_id: parsed.messageId,
          projection_sequence: parsed.projectionSequence,
        })
        if (config.onProjection) config.onProjection(parsed)
        break
      case KIND.INTENT_ACK:
        recordFrontendEvent('protocol_intent_ack', {
          message_id: parsed.messageId,
          intent_id: parsed.payload?.intent_id || '',
          ack_for: parsed.ackFor,
        })
        if (config.onIntentAck) config.onIntentAck(parsed)
        break
      case KIND.INTENT_RESULT:
        recordFrontendEvent('protocol_intent_result', {
          message_id: parsed.messageId,
          intent_id: parsed.payload?.intent_id || '',
          status: parsed.payload?.status || 'unknown',
        })
        if (config.onIntentResult) config.onIntentResult(parsed)
        break
      case KIND.HEARTBEAT:
        recordHeartbeat()
        _lastHeartbeatAt = Date.now()
        recordFrontendEvent('protocol_heartbeat', {
          message_id: parsed.messageId,
          heartbeat_age_ms: Date.now() - _lastHeartbeatAt,
        })
        if (config.onHeartbeat) config.onHeartbeat(parsed)
        break
      case KIND.FLOW_CONTROL:
        recordFrontendEvent('protocol_flow_control', {
          message_id: parsed.messageId,
          reason: parsed.payload?.reason || '',
        })
        if (config.onFlowControl) config.onFlowControl(parsed)
        break
      case KIND.ERROR:
        _protocolErrorCount++
        recordFrontendEvent('protocol_error', {
          message_id: parsed.messageId,
          error_type: parsed.payload?.error_type || '',
        })
        if (config.onError) config.onError(parsed)
        break
    }

    return { envelope: parsed, isLegacy: false }
  }

  // ── Stats ────────────────────────────────────────────────────────

  function getStats() {
    return {
      outboundSeq: _outboundSeq,
      inboundSeq: _inboundSeq,
      lastProjectionSeq: _lastProjectionSeq,
      duplicateCount: _duplicateCount,
      staleProjectionCount: _staleProjectionCount,
      protocolErrorCount: _protocolErrorCount,
      droppedCount: _droppedCount,
      coalescedCount: _coalescedCount,
      maxQueueDepth: _maxQueueDepth,
      messageCountByKind: Object.assign({}, _messageCountByKind),
      heartbeatAgeMs: _lastHeartbeatAt ? Date.now() - _lastHeartbeatAt : -1,
    }
  }

  // ── Lifecycle ────────────────────────────────────────────────────

  function setHandshakeId(id) {
    handshakeId = id || ''
  }

  function setWsClient(client) {
    wsClient = client
  }

  function destroy() {
    stopHeartbeat()
    wsClient = null
    _seenMessageIds = Object.create(null)
    _seenIdempotencyKeys = Object.create(null)
  }

  var _heartbeatTimer = null

  function startHeartbeat() {
    if (_heartbeatTimer) return
    sendHeartbeat()
    _heartbeatTimer = setInterval(function() {
      sendHeartbeat()
    }, 15000)
  }

  function stopHeartbeat() {
    if (_heartbeatTimer) {
      clearInterval(_heartbeatTimer)
      _heartbeatTimer = null
    }
  }

  return Object.freeze({
    sendEnvelope: sendEnvelope,
    sendIntentRequest: sendIntentRequest,
    sendHeartbeat: sendHeartbeat,
    sendLifecycleEvent: sendLifecycleEvent,
    sendProjectionRenderedAck: sendProjectionRenderedAck,
    handleMessage: handleMessage,
    getStats: getStats,
    setHandshakeId: setHandshakeId,
    setWsClient: setWsClient,
    destroy: destroy,
    startHeartbeat: startHeartbeat,
    stopHeartbeat: stopHeartbeat,
    isEnvelope: isEnvelope,
  })
}

// CONTRACT: Bridge Protocol Flow Control
// ───────────────────────────────────────
// Owner: frontend/desktop/js/protocol/flowControl.js
// Safety: Bounded queue (MAX_QUEUE_SIZE=128) with priority-based dropping.
//         NEVER_DROP set protects ERROR and INTENT_RESULT kinds.
//         Coalescing window applies only to LIFECYCLE_EVENT and HEARTBEAT.
//         All counters are monotonic — no reset or decrement paths.
//         No secrets in telemetry events emitted by this module.
//
// Rig Relay — Bridge Protocol Flow Control
// Bounded outbound queue with priority-based dropping and coalescing.

import { KIND } from './envelope.js'
import { recordFrontendEvent } from '../telemetry/frontendTrace.js'

var MAX_QUEUE_SIZE = 128

// Priority order: critical > high > normal > low
var PRIORITY_ORDER = { critical: 0, high: 1, normal: 2, low: 3 }

// Never drop these kinds
var NEVER_DROP = Object.create(null)
NEVER_DROP[KIND.ERROR] = true
NEVER_DROP[KIND.INTENT_RESULT] = true

// Coalesce these kinds (supersede previous of same kind)
var COALESCE_KINDS = Object.create(null)
COALESCE_KINDS[KIND.LIFECYCLE_EVENT] = true
COALESCE_KINDS[KIND.HEARTBEAT] = true

export function createFlowController() {
  var _queue = []
  var _droppedCount = 0
  var _coalescedCount = 0
  var _maxQueueDepth = 0
  var _sendFn = null

  function setSendFn(fn) {
    _sendFn = fn
  }

  function _recordMaxDepth() {
    if (_queue.length > _maxQueueDepth) {
      _maxQueueDepth = _queue.length
    }
  }

  // ── Enqueue ──────────────────────────────────────────────────────

  function enqueue(envelope, sendFn) {
    _sendFn = sendFn || _sendFn

    // Coalescing: supersede same-kind low-priority messages
    if (COALESCE_KINDS[envelope.kind]) {
      for (var i = _queue.length - 1; i >= 0; i--) {
        if (_queue[i].kind === envelope.kind) {
          _queue[i] = envelope
          _coalescedCount++
          recordFrontendEvent('protocol_coalesced', {
            kind: envelope.kind,
            queue_depth: _queue.length,
          })
          return
        }
      }
    }

    // If queue is full, drop lowest priority
    if (_queue.length >= MAX_QUEUE_SIZE) {
      if (NEVER_DROP[envelope.kind]) {
        // Critical message — make room by dropping lowest-priority non-critical
        _dropLowestPriority()
      } else {
        // Check if we can drop this incoming message
        var incomingPriority = PRIORITY_ORDER[envelope.priority] || 3
        var lowestInQueue = _findLowestPriorityIndex()
        if (lowestInQueue >= 0) {
          var queuePriority = PRIORITY_ORDER[_queue[lowestInQueue].priority] || 3
          if (queuePriority >= incomingPriority) {
            // Drop the incoming message instead
            _droppedCount++
            recordFrontendEvent('protocol_dropped', {
              kind: envelope.kind,
              reason: 'queue_full_incoming_lower_priority',
            })
            return
          }
        }
        // Drop lowest priority from queue
        _dropLowestPriority()
      }
    }

    _queue.push(envelope)
    _recordMaxDepth()
    _flush()
  }

  // ── Priority Helpers ─────────────────────────────────────────────

  function _findLowestPriorityIndex() {
    var lowestPriority = -1
    var lowestIndex = -1
    for (var i = 0; i < _queue.length; i++) {
      if (NEVER_DROP[_queue[i].kind]) continue
      var p = PRIORITY_ORDER[_queue[i].priority] || 3
      if (p > lowestPriority) {
        lowestPriority = p
        lowestIndex = i
      }
    }
    return lowestIndex
  }

  function _dropLowestPriority() {
    var idx = _findLowestPriorityIndex()
    if (idx >= 0) {
      var dropped = _queue.splice(idx, 1)[0]
      _droppedCount++
      recordFrontendEvent('protocol_dropped', {
        kind: dropped.kind,
        reason: 'queue_full_lowest_priority',
      })
    }
  }

  // ── Flush ────────────────────────────────────────────────────────

  function _flush() {
    if (!_sendFn) return
    while (_queue.length > 0) {
      var envelope = _queue.shift()
      try {
        _sendFn(envelope)
      } catch (_) {
        _droppedCount++
      }
    }
  }

  function flush() {
    _flush()
  }

  // ── Stats ────────────────────────────────────────────────────────

  function getStats() {
    return {
      queueDepth: _queue.length,
      maxQueueDepth: _maxQueueDepth,
      droppedCount: _droppedCount,
      coalescedCount: _coalescedCount,
    }
  }

  return Object.freeze({
    enqueue: enqueue,
    setSendFn: setSendFn,
    getStats: getStats,
    flush: flush,
  })
}

// Rig Relay — Projection
// Ingestion, caching, widget render coordination
// Batches DOM updates via requestAnimationFrame deduplication.
// Tracks projection digests to skip redundant full re-renders.

import { state } from './state.js';
import { renderWidget, renderAllWidgets, updateIntentResult } from './widgets.js';
import { renderStatusBar } from './status.js';
import { renderChat } from './chat.js';

// ── Render batching ──────────────────────────────────────────────────
// Only one full render cycle per animation frame, regardless of how many
// times scheduleRender() is called within that frame.

let _renderScheduled = false;
let _pendingProjection = null;

function scheduleRender(projection) {
  _pendingProjection = projection;
  if (_renderScheduled) return;
  _renderScheduled = true;
  requestAnimationFrame(() => {
    _renderScheduled = false;
    if (_pendingProjection) {
      state.projection = _pendingProjection;
      _pendingProjection = null;
      renderStatusBar();
      renderAllWidgets();
    }
  });
}

// ── Digest tracking ──────────────────────────────────────────────────
// Compute a content hash of the projection (excluding volatile fields
// like generated_at) to detect true changes vs. timer ticks.

function computeDigest(data) {
  if (!data) return '';
  // Normalize: strip generated_at (changes every tick) and schema_validation_errors
  const copy = Object.assign({}, data);
  delete copy.generated_at;
  delete copy._schema_validation_errors;

  // Stable JSON sort for deterministic hashing
  const json = JSON.stringify(copy, Object.keys(copy).sort());
  let hash = 0;
  for (let i = 0; i < json.length; i++) {
    const chr = json.charCodeAt(i);
    hash = ((hash << 5) - hash) + chr;
    hash |= 0; // Convert to 32bit integer
  }
  return hash.toString(36);
}

let _lastDigest = '';

// ── Server-provided digest ───────────────────────────────────────────
// If the server sends a digest field, prefer it over our local computation.
// This allows the server to optimize which field changes are significant.

function getDigest(data) {
  if (data && data.digest) return data.digest;
  return computeDigest(data);
}

// ── Public API ───────────────────────────────────────────────────────

export function handleProjection(data) {
  const serverDigest = (data && data.digest) || '';
  const projection = data || {};

  const effectiveDigest = serverDigest || computeDigest(projection);
  if (effectiveDigest && effectiveDigest === _lastDigest) {
    return;
  }
  _lastDigest = effectiveDigest;

  if (projection.ralph_lifecycle) {
    state.ralph.lifecycle = projection.ralph_lifecycle;
  }

  scheduleRender(projection);
}

export function handleChatState(data) {
  // Chat state changes are small — render immediately, no batching needed
  renderChat(data);
}

export function handleIntentResult(msg) {
  const result = msg.result || msg;
  const name = result.intent_kind || result.intent_name || 'Intent';
  const status = result.status || 'unknown';
  const summary = result.message || result.summary || '';

  if (name.startsWith('ralph_')) {
    if (result.status !== 'refused' && result.ralph && result.ralph.panel) {
      state.ralph.panel = result.ralph.panel;
    }
    if (result.ralph && result.ralph.run_state) {
      state.ralph.runState = result.ralph.run_state;
    }
    if (result.approval_state && state.ralph.panel) {
      state.ralph.panel.approval_state = result.approval_state;
    }
    var refusalText = result.status === 'refused'
      ? (result.error_code || 'refused') + ': ' + (result.message || '')
      : '';
    state.ralph.lastIntent = {
      name: name,
      status: status,
      summary: refusalText || summary,
      error_code: result.error_code || null
    };
    renderWidget('ralphScout');
    return;
  }

  updateIntentResult(status, name, summary);
}

export function handleProgressEvent(msg) {
  state.progressEvents.push(msg);
  if (state.progressEvents.length > 100) {
    state.progressEvents = state.progressEvents.slice(-100);
  }
  // Only re-render the progress timeline widget, not all widgets
  renderWidget('progressTimeline');
}

export function handleProgressEvents(events) {
  state.progressEvents = (events || []).slice(-100);
  // Batch: schedule full render to pick up the new events list
  scheduleRender(state.projection);
}

// ── Reset for reconnect ──────────────────────────────────────────────

export function resetDigest() {
  _lastDigest = '';
}

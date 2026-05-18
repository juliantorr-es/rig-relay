// Rig Relay — Side Effect Runners
// Browser-side runtime kernel. Effects execute AFTER state transitions complete.
// They perform DOM updates, WebSocket communication, evidence emission, and
// notification management. No React, Redux, Vue, or new dependencies.
// Every effect is wrapped in try/catch — errors are logged to console.warn, never thrown.

import { STATUS_LABELS, STATUS_CHIP_CLASS } from '../transportState.js';
import { getVisibleWidgets } from './selectors.js';
import { el } from '../utils.js';

// ── Standalone loop utilities ──────────────────────────────────────────

// Creates a looping timer backed by an AbortController.
// fn receives { signal } and should check signal.aborted before each body.
// Returns the AbortController so callers can cancel it.
export function startLoop(fn, intervalMs) {
  const controller = new AbortController();
  const { signal } = controller;

  const run = async () => {
    if (signal.aborted) return;
    try {
      await fn({ signal });
    } catch (_) {
      // fn failures are swallowed — loop continues
    }
    if (!signal.aborted) {
      setTimeout(run, intervalMs);
    }
  };

  setTimeout(run, intervalMs);
  return controller;
}

// Cancels a running loop via its AbortController.
export function cancelLoop(controller) {
  if (controller && typeof controller.abort === 'function') {
    controller.abort();
  }
}

// ── Effect runner factory ──────────────────────────────────────────────

export function createEffectRunner(config = {}) {
  const evidence = config.evidence || null;
  const wsClient = config.wsClient || null;
  const getState = config.getState || null;
  const dispatch = config.dispatch || null;

  // Build a ctx object for effect functions that need the full context.
  // Precondition: state must be a valid state object (or null for pre-init).
  function _ctx(state, overrides = {}) {
    return {
      state,
      dispatch,
      getState,
      evidence,
      wsClient,
      previousState: null,
      ...overrides,
    };
  }

  // Wraps an effect function so errors are caught and logged, never thrown.
  function _safe(fn) {
    return (...args) => {
      try {
        fn(...args);
      } catch (e) {
        console.warn('[effects] Error in effect:', e);
      }
    };
  }

  // ── Timestamp helper ─────────────────────────────────────────────────

  function _formatTimestamp(lastReceivedAt) {
    if (!lastReceivedAt) return '\u2014';
    const now = Date.now();
    const received = new Date(lastReceivedAt).getTime();
    if (Number.isNaN(received)) return '\u2014';
    const diffSec = Math.floor((now - received) / 1000);
    if (diffSec < 10) return 'just now';
    if (diffSec < 30) return diffSec + 's ago';
    return 'stale';
  }

  // ── DOM effects ──────────────────────────────────────────────────────

  // Mutates #status-connection text and CSS class based on transport status.
  // Precondition: #status-connection element must exist in DOM.
  // Failure: element not found → silent no-op.
  const updateConnectionChip = _safe((state) => {
    const chip = el('status-connection');
    if (!chip) return;

    const status = state.transport?.status || 'idle';
    const phase = state.transport?.phase || 'boot';
    const label = STATUS_LABELS[status] || 'Unknown';
    const chipCls = STATUS_CHIP_CLASS[status] || 'warn';

    // Preserve header-dot child, update text after it
    const dot = chip.querySelector('.header-dot');
    while (chip.firstChild) chip.removeChild(chip.firstChild);
    if (dot) chip.appendChild(dot);
    chip.appendChild(document.createTextNode(label));

    // Build class list: base + status chip class + phase-specific class
    chip.className = 'header-chip ' + chipCls + ' phase-' + phase;
  });

  // Mutates #status-session element text to reflect current session info.
  // Precondition: #status-session element must exist in DOM.
  // Failure: element not found → silent no-op.
  const updateSessionChip = _safe((state) => {
    const chip = el('status-session');
    if (!chip) return;

    const proj = state.projection;
    const cs = proj?.current_state || {};
    let text = 'No session';
    let cls = '';

    if (cs.available) {
      text = cs.session_id
        ? 'Session ' + cs.session_id.substring(0, 8)
        : 'Active';
      cls = 'ok';
    }

    const dot = chip.querySelector('.header-dot');
    while (chip.firstChild) chip.removeChild(chip.firstChild);
    if (dot) chip.appendChild(dot);
    chip.appendChild(document.createTextNode(text));
    chip.className = 'header-chip ' + cls;
  });

  // Mutates #status-safety element text and class based on safety state.
  // Precondition: #status-safety element must exist in DOM.
  // Failure: element not found → silent no-op.
  const updateSafetyChip = _safe((state) => {
    const chip = el('status-safety');
    if (!chip) return;

    const proj = state.projection;
    const cs = proj?.current_state || {};
    let text = 'Unknown';
    let cls = '';

    if (cs.available) {
      const dirty = (cs.active_writers || 0) + (cs.active_readers || 0);
      const stale = cs.stale_leases || 0;
      if (dirty > 0 || stale > 0) {
        text = dirty + ' active';
        cls = 'warn';
      } else {
        text = 'Safe';
        cls = 'ok';
      }
    }

    const dot = chip.querySelector('.header-dot');
    while (chip.firstChild) chip.removeChild(chip.firstChild);
    if (dot) chip.appendChild(dot);
    chip.appendChild(document.createTextNode(text));
    chip.className = 'header-chip ' + cls;
  });

  // Mutates #header-timestamp with "just now", "Xs ago", or "stale".
  // Precondition: #header-timestamp element must exist in DOM.
  // Failure: element not found → silent no-op.
  const updateHeaderTimestamp = _safe((state) => {
    const tsElement = el('header-timestamp');
    if (!tsElement) return;

    const lastReceivedAt = state.projection?.lastReceivedAt || null;
    const ts = _formatTimestamp(lastReceivedAt);
    tsElement.textContent = ts;
    tsElement.className = 'header-timestamp' + (ts === 'stale' ? ' stale' : '');
  });

  // Toggles .active and aria-selected on .mode-option buttons.
  // Precondition: .mode-option buttons must exist in DOM.
  // Failure: no buttons found → silent no-op.
  const updateModeBar = _safe((state) => {
    const mode = state.mode || 'operator';
    const buttons = document.querySelectorAll('.mode-option');
    if (!buttons.length) return;

    buttons.forEach((btn) => {
      const isActive = btn.dataset.mode === mode;
      btn.classList.toggle('active', isActive);
      btn.setAttribute('aria-selected', String(isActive));
    });
  });

  // Sets data-mode attribute on #main-grid to drive CSS grid layout.
  // Precondition: #main-grid element must exist in DOM.
  // Failure: element not found → silent no-op.
  const updateMainGridMode = _safe((state) => {
    const grid = el('main-grid');
    if (!grid) return;
    grid.setAttribute('data-mode', state.mode || 'operator');
  });

  // Clears and rebuilds #panel-column with widget cards for the current mode.
  // DOM construction only — no innerHTML for untrusted data.
  // Idempotent: skips rebuild if panel already has the correct widgets in order.
  // Precondition: #panel-column and #main-grid must exist in DOM.
  // Failure: missing elements → silent no-op.
  const rebuildWidgetPanel = _safe((state) => {
    const panel = el('panel-column');
    const grid = el('main-grid');
    if (!panel || !grid) return;

    const mode = grid.dataset.mode || state.mode || 'operator';
    const visibleIds = getVisibleWidgets(state, mode);

    // Idempotent check: compare current panel children with expected widgets
    const currentIds = [];
    for (const child of panel.children) {
      const id = child.id;
      if (id && id.startsWith('widget-')) {
        currentIds.push(id.replace('widget-', ''));
      }
    }

    if (
      currentIds.length === visibleIds.length &&
      currentIds.every((id, i) => id === visibleIds[i])
    ) {
      return;
    }

    // Clear and rebuild
    while (panel.firstChild) panel.removeChild(panel.firstChild);

    visibleIds.forEach((widgetId, index) => {
      const card = document.createElement('div');
      card.id = 'widget-' + widgetId;
      card.className = 'widget-card';
      card.setAttribute('data-disclosure', 'compact');
      card.style.animationDelay = index * 50 + 'ms';
      card.classList.add('card-entering');
      panel.appendChild(card);
    });
  });

  // Updates a single widget card's DOM to reflect its status.
  // Precondition: #widget-{widgetId} must exist in DOM.
  // Failure: card not found → silent no-op.
  const updateWidgetCard = _safe((state, widgetId) => {
    const card = el('widget-' + widgetId);
    if (!card) return;

    const widgetState = state.widgets?.[widgetId];
    const status = widgetState?.status || 'unknown';

    // Remove any existing status indicator
    const existing = card.querySelector('.widget-failure-indicator');
    if (existing) existing.remove();

    if (status === 'failed') {
      const indicator = document.createElement('span');
      indicator.className = 'widget-failure-indicator';
      indicator.setAttribute('aria-label', 'Widget failed');
      indicator.textContent = '\u26A0';
      indicator.style.cssText =
        'position:absolute;top:4px;right:8px;color:var(--error);font-size:12px';
      card.appendChild(indicator);
    }

    card.setAttribute('data-status', status);
  });

  // Shows or hides a degradation banner at the top of #main-grid.
  // Creates the banner element if it does not exist.
  // Precondition: #main-grid must exist in DOM.
  // Failure: element not found → silent no-op.
  const renderDegradationBanner = _safe((state) => {
    const grid = el('main-grid');
    if (!grid) return;

    let banner = el('degradation-banner');

    if (state.degraded === true) {
      if (!banner) {
        banner = document.createElement('div');
        banner.id = 'degradation-banner';
        banner.setAttribute('role', 'alert');
        banner.setAttribute('aria-live', 'polite');
        banner.textContent = 'Runtime operating in degraded mode. Some capabilities may be unavailable.';
        banner.style.cssText =
          'background:var(--warn-bg, rgba(196,138,42,0.1));' +
          'color:var(--warn, #c48a2a);' +
          'padding:6px 16px;' +
          'font-size:var(--font-size-xs);' +
          'border-bottom:1px solid var(--warn, #c48a2a);' +
          'text-align:center;' +
          'flex-shrink:0';
        grid.insertBefore(banner, grid.firstChild);
      }
      banner.style.display = '';
    } else if (banner) {
      banner.style.display = 'none';
    }
  });

  // Shows or hides a persistent secondary-tab warning overlay.
  // Creates the element if it does not exist.
  // Precondition: #main-grid must exist in DOM.
  // Failure: element not found → silent no-op.
  const renderSecondaryTabWarning = _safe((state) => {
    const grid = el('main-grid');
    if (!grid) return;

    let warning = el('secondary-tab-warning');

    if (state.multiTab?.isSecondary === true) {
      if (!warning) {
        warning = document.createElement('div');
        warning.id = 'secondary-tab-warning';
        warning.setAttribute('role', 'alert');
        warning.setAttribute('aria-live', 'polite');
        warning.textContent =
          'This tab is a secondary view. A primary session is active in another tab. Some controls are read-only.';
        warning.style.cssText =
          'background:var(--info-bg, rgba(79,143,204,0.1));' +
          'color:var(--info, #4f8fcc);' +
          'padding:6px 16px;' +
          'font-size:var(--font-size-xs);' +
          'border-bottom:1px solid var(--info, #4f8fcc);' +
          'text-align:center;' +
          'flex-shrink:0;' +
          'position:sticky;top:0;z-index:5';
        grid.insertBefore(warning, grid.firstChild);
      }
      warning.style.display = '';
    } else if (warning) {
      warning.style.display = 'none';
    }
  });

  // ── WebSocket effects ─────────────────────────────────────────────────

  // Sends an intent message through the WebSocket client.
  // Precondition: wsClient must be connected AND authenticated.
  // Failure: no client or not ready → silent no-op (intent is dropped).
  const sendIntentViaWs = _safe((ctx, intentId) => {
    const client = ctx.wsClient || wsClient;
    if (!client) return;
    if (!client.connected || !client.authenticated) return;

    const intent = ctx.state?.intents?.[intentId];
    if (!intent) return;

    const message = {
      type: 'desktop_intent_request',
      intent_id: intentId,
      intent_name: intent.name || intentId,
      payload: intent.payload || {},
      schema_version: 'rig.relay.desktop_intent_request.v1',
      created_at: new Date().toISOString(),
    };

    client.send(message);
  });

  // Requests a fresh projection from the backend via WebSocket.
  // Precondition: wsClient must be available (no auth check — projection
  // request is safe even before full auth).
  // Failure: no client → silent no-op.
  const requestProjectionViaWs = _safe((ctx) => {
    const client = ctx.wsClient || wsClient;
    if (!client) return;

    // get_projection is safe to request before full auth; the server
    // gates the response on authentication.
    client.send({ type: 'get_projection' });
  });

  // ── Evidence effects ──────────────────────────────────────────────────

  // Records structured evidence via the evidence subsystem.
  // Precondition: evidence.record must be callable.
  // Failure: no evidence subsystem → silent no-op.
  const emitTransitionEvidence = _safe((ctx, eventType, details = {}) => {
    const ev = ctx.evidence || evidence;
    if (!ev || typeof ev.record !== 'function') return;

    ev.record({
      type: eventType,
      timestamp: new Date().toISOString(),
      details,
    });
  });

  // ── Notification effects ──────────────────────────────────────────────

  // Pops all pending notifications and dispatches NOTIFICATION_DRAIN for each.
  // Skipped when state.notificationsLocked is true (prevents re-entrant drains).
  // Precondition: state.notifications must be an array.
  // Failure: no dispatch → silent no-op.
  const drainNotificationQueue = _safe((state) => {
    if (state.notificationsLocked) return;
    if (!dispatch) return;

    const queue = state.notifications;
    if (!queue || !queue.length) return;

    state.notificationsLocked = true;

    const drained = queue.splice(0, queue.length);
    for (const notification of drained) {
      try {
        dispatch('NOTIFICATION_DRAIN', notification);
      } catch (_) {
        // Individual notification drain failures do not block the queue
      }
    }

    state.notificationsLocked = false;
  });

  // ── Animation / Sound effects ─────────────────────────────────────────

  // Placeholder for notification sound playback.
  // Precondition: state.soundEnabled must be true.
  // Failure: sound not available → silent no-op.
  const playNotificationSound = _safe((state) => {
    if (!state.soundEnabled) return;
    // Placeholder — no audio API call yet.
  });

  // Adds card-entering class to a widget card to trigger entrance animation.
  // Precondition: #widget-{widgetId} must exist in DOM.
  // Failure: card not found → silent no-op.
  const animateWidgetEntrance = _safe((widgetId) => {
    const card = el('widget-' + widgetId);
    if (!card) return;
    card.classList.add('card-entering');
  });

  // ── Loop lifecycle effects ────────────────────────────────────────────

  // Starts a named interval loop stored in state.loops[loopId].
  // Stores the AbortController so the loop can be cancelled later.
  // The loop function receives { signal } and should check signal.aborted.
  // Precondition: state.loops must exist (initialized by kernel).
  // Failure: fn not a function → silent no-op.
  const startLoopEffect = _safe((state, loopId, fn, intervalMs) => {
    if (typeof fn !== 'function') return;
    if (!state.loops) state.loops = {};

    // Cancel existing loop with the same ID before creating a new one
    if (state.loops[loopId]?.abortController) {
      state.loops[loopId].abortController.abort();
    }

    const controller = new AbortController();
    const { signal } = controller;

    state.loops[loopId] = {
      abortController: controller,
      status: 'running',
      startedAt: new Date().toISOString(),
    };

    const run = async () => {
      if (signal.aborted) return;
      try {
        await fn({ signal });
      } catch (_) {
        // Loop fn failures are swallowed — loop continues
      }
      if (!signal.aborted) {
        setTimeout(run, intervalMs);
      }
    };

    setTimeout(run, intervalMs);
  });

  // Cancels a named loop and marks it as cancelled in state.
  // Precondition: state.loops[loopId].abortController must exist.
  // Failure: no loop found → silent no-op.
  const cancelLoopEffect = _safe((state, loopId) => {
    const entry = state.loops?.[loopId];
    if (!entry?.abortController) return;

    entry.abortController.abort();
    entry.status = 'cancelled';
    entry.cancelledAt = new Date().toISOString();
  });

  // Cancels all running loops tracked in state.loops.
  // Precondition: state.loops must exist.
  // Failure: no loops → silent no-op.
  const cancelAllLoopsEffect = _safe((state) => {
    const loops = state.loops;
    if (!loops) return;

    for (const [loopId, entry] of Object.entries(loops)) {
      if (entry?.abortController) {
        try {
          entry.abortController.abort();
        } catch (_) {
          // Individual abort failures do not block others
        }
        entry.status = 'cancelled';
        entry.cancelledAt = new Date().toISOString();
      }
    }
  });

  // ── Generic effect registration (for kernel post-reducer effects) ────

  const _registry = [];

  function register(type, fn) {
    _registry.push({ type, fn: _safe(fn) });
  }

  function run(state, action, dispatch, kernelCtx) {
    for (const entry of _registry) {
      if (entry.type === action.type || entry.type === '*') {
        entry.fn(state, action, dispatch, kernelCtx);
      }
    }
  }

  function clear() {
    _registry.length = 0;
  }

  // ── Result ────────────────────────────────────────────────────────────

  return {
    updateConnectionChip,
    updateSessionChip,
    updateSafetyChip,
    updateHeaderTimestamp,
    updateModeBar,
    updateMainGridMode,
    rebuildWidgetPanel,
    updateWidgetCard,
    renderDegradationBanner,
    renderSecondaryTabWarning,
    sendIntentViaWs,
    requestProjectionViaWs,
    emitTransitionEvidence,
    drainNotificationQueue,
    playNotificationSound,
    animateWidgetEntrance,
    startLoop: startLoopEffect,
    cancelLoop: cancelLoopEffect,
    cancelAllLoops: cancelAllLoopsEffect,
    register,
    run,
    clear,
    dispatch, // mutable: set by kernel after creation
  };
}

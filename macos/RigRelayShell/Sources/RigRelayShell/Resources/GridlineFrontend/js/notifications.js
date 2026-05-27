// Rig Relay — Notifications
// Frontend notification queue and lifecycle system.

// ═══ Constants ═══════════════════════════════════════════════════════

const NOTIFICATION_KINDS = Object.freeze([
  'info',
  'success',
  'warning',
  'error',
  'security',
  'telemetry',
  'lifecycle',
]);

const PRIORITY_WEIGHT = Object.freeze({
  critical: 4,
  high: 3,
  normal: 2,
  low: 1,
});

const NOTIFICATION_SOURCES = Object.freeze([
  'transport',
  'projection',
  'intent',
  'release_gate',
  'telemetry',
  'provider',
  'security',
]);

const MAX_NOTIFICATIONS = 500;
const MAX_HISTORY = 1000;
const HISTORY_RESULT_LIMIT = 200;
const RESOLVED_MOVE_DELAY_MS = 5000;

const SECRET_PATTERNS = [
  /\bsk-[A-Za-z0-9-_]{20,}\b/g,
  /\bAIza[SY][A-Za-z0-9\-_]{35,}\b/g,
  /\bghp_[A-Za-z0-9]{36,}\b/g,
  /\bgho_[A-Za-z0-9]{36,}\b/g,
  /\bghu_[A-Za-z0-9]{36,}\b/g,
  /\bghs_[A-Za-z0-9]{36,}\b/g,
  /\bghr_[A-Za-z0-9]{36,}\b/g,
  /\bxox[bpras]-[A-Za-z0-9\-]{10,}\b/g,
  /\b[0-9a-fA-F]{40,}\b/g,
  /\b[A-Za-z0-9+/=]{40,}\b/g,
  /\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b/g,
  /\bAKIA[0-9A-Z]{16,}\b/g,
  /\brk_live_[A-Za-z0-9]{24,}\b/g,
  /\bSK[A-Za-z0-9]{30,}\b/g,
  /\bLA_DEPLOY_CACHE_\S+\b/g,
  /\bSG\.[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}\b/g,
  /\bdckr_pat_[A-Za-z0-9_-]{30,}\b/g,
  /\bpypi-[A-Za-z]{6}-[A-Za-z]{6}-[A-Za-z]{6}-[A-Za-z]{6}\b/g,
];

// ═══ Internal state ══════════════════════════════════════════════════

let _notifications = [];
let _history = [];

// ═══ Helpers ═════════════════════════════════════════════════════════

function _fallbackUUID() {
  if (typeof crypto !== 'undefined' && typeof crypto.getRandomValues === 'function') {
    const array = new Uint8Array(16)
    crypto.getRandomValues(array)
    array[6] = (array[6] & 0x0f) | 0x40
    array[8] = (array[8] & 0x3f) | 0x80
    const hex = Array.from(array, function (b) { return b.toString(16).padStart(2, '0') }).join('')
    return hex.substring(0, 8) + '-' + hex.substring(8, 12) + '-' + hex.substring(12, 16) + '-' + hex.substring(16, 20) + '-' + hex.substring(20, 32)
  }
  
  // Very weak fallback if no crypto is available
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function (c) {
    const r = (Math.random() * 16) | 0;
    const v = c === 'x' ? r : (r & 0x3) | 0x8;
    return v.toString(16);
  });
}

function _generateId() {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return 'notif_' + crypto.randomUUID();
  }
  return 'notif_' + _fallbackUUID();
}

function _deriveDedupeKey(source, kind, title) {
  const slug = (title || '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '_')
    .replace(/^_+|_+$/g, '')
    .substring(0, 80);
  return source + ':' + kind + ':' + slug;
}

function _isExpired(notif) {
  if (!notif.expires_at) return false;
  return new Date(notif.expires_at).getTime() <= Date.now();
}

function _truncateArray(arr, max) {
  if (arr.length > max) {
    arr.splice(0, arr.length - max);
  }
}

function _nowISO() {
  return new Date().toISOString();
}

function _emit(name, detail) {
  if (typeof document !== 'undefined' && typeof document.dispatchEvent === 'function') {
    document.dispatchEvent(new CustomEvent(name, { detail }));
  }
}

function _sanitizeNotificationBody(text) {
  if (typeof text !== 'string') return String(text ?? '');
  let result = text;
  for (const pattern of SECRET_PATTERNS) {
    result = result.replace(pattern, '[REDACTED]');
  }
  return result;
}

async function _sha256(text) {
  const normalized = String(text ?? '');
  if (
    typeof crypto !== 'undefined' &&
    typeof crypto.subtle !== 'undefined' &&
    typeof crypto.subtle.digest === 'function'
  ) {
    const encoder = new TextEncoder();
    const data = encoder.encode(normalized);
    const hashBuffer = await crypto.subtle.digest('SHA-256', data);
    const hashArray = Array.from(new Uint8Array(hashBuffer));
    return hashArray.map(function (b) {
      return b.toString(16).padStart(2, '0');
    }).join('');
  }
  let hash = 0;
  for (let i = 0; i < normalized.length; i++) {
    const char = normalized.charCodeAt(i);
    hash = ((hash << 5) - hash) + char;
    hash |= 0;
  }
  return (hash >>> 0).toString(16).padStart(8, '0');
}

// ═══ Public API ══════════════════════════════════════════════════════

function createNotification(opts) {
  const source = NOTIFICATION_SOURCES.includes(opts.source) ? opts.source : 'transport';
  const kind = NOTIFICATION_KINDS.includes(opts.kind) ? opts.kind : 'info';
  const title = _sanitizeNotificationBody(opts.title || '');
  const body = _sanitizeNotificationBody(opts.body || '');
  const dedupeKey = _deriveDedupeKey(source, kind, title);

  const activeDuplicate = _notifications.find(function (n) {
    return n.dedupe_key === dedupeKey && !n.resolved && !_isExpired(n);
  });
  if (activeDuplicate) return activeDuplicate.notification_id;

  const historyDuplicate = _history.find(function (n) {
    return n.dedupe_key === dedupeKey && !n.resolved;
  });
  if (historyDuplicate) return historyDuplicate.notification_id;

  const priority = PRIORITY_WEIGHT[opts.priority] ? opts.priority : 'normal';
  const now = _nowISO();

  const notif = {
    notification_id: _generateId(),
    kind: kind,
    priority: priority,
    source: source,
    title: title,
    body: body,
    action_buttons: Array.isArray(opts.action_buttons) ? opts.action_buttons : [],
    created_at: now,
    expires_at: opts.expires_at || null,
    requires_ack: Boolean(opts.requires_ack),
    acked: false,
    evidence_event_id: opts.evidence_event_id || null,
    dedupe_key: dedupeKey,
    resolved: false,
    resolved_at: null,
  };

  _notifications.push(notif);
  _truncateArray(_notifications, MAX_NOTIFICATIONS);

  _history.push(notif);
  _truncateArray(_history, MAX_HISTORY);

  _emit('notification:created', notif);

  return notif.notification_id;
}

function resolveNotification(dedupeKey) {
  const idx = _notifications.findIndex(function (n) {
    return n.dedupe_key === dedupeKey && !n.resolved;
  });
  if (idx === -1) return false;

  const notif = _notifications[idx];
  notif.resolved = true;
  notif.resolved_at = _nowISO();

  _emit('notification:resolved', notif);

  setTimeout(function () {
    const rIdx = _notifications.indexOf(notif);
    if (rIdx !== -1) {
      _notifications.splice(rIdx, 1);
    }
  }, RESOLVED_MOVE_DELAY_MS);

  return true;
}

function acknowledgeNotification(notificationId) {
  const notif = _notifications.find(function (n) {
    return n.notification_id === notificationId;
  });
  if (!notif) return false;

  notif.acked = true;
  _emit('notification:acked', notif);

  return true;
}

function getActiveNotifications() {
  return _notifications
    .filter(function (n) {
      return !n.resolved && !_isExpired(n);
    })
    .sort(function (a, b) {
      const pa = PRIORITY_WEIGHT[a.priority] || 0;
      const pb = PRIORITY_WEIGHT[b.priority] || 0;
      if (pb !== pa) return pb - pa;
      return new Date(b.created_at).getTime() - new Date(a.created_at).getTime();
    });
}

function getNotificationHistory() {
  return _history
    .slice()
    .sort(function (a, b) {
      return new Date(b.created_at).getTime() - new Date(a.created_at).getTime();
    })
    .slice(0, HISTORY_RESULT_LIMIT);
}

function getUnackedCount() {
  return _notifications.filter(function (n) {
    return !n.resolved && !_isExpired(n) && n.requires_ack && !n.acked;
  }).length;
}

function getUnreadCount() {
  return getUnackedCount();
}

function clearResolvedNotifications() {
  _notifications = _notifications.filter(function (n) {
    return !n.resolved;
  });

  const keepIds = new Set(
    _history
      .filter(function (n) {
        return !n.resolved;
      })
      .concat(
        _history
          .filter(function (n) {
            return n.resolved;
          })
          .slice(-MAX_HISTORY / 2)
      )
      .map(function (n) {
        return n.notification_id;
      })
  );

  _history = _history.filter(function (n) {
    return keepIds.has(n.notification_id);
  });
}

function getNotificationsBySource(source) {
  return getActiveNotifications().filter(function (n) {
    return n.source === source;
  });
}

async function toEvidenceEvent(notification) {
  if (!notification) return null;

  const bodySha256 = await _sha256(notification.body || '');

  return {
    notification_id: notification.notification_id,
    kind: notification.kind,
    priority: notification.priority,
    source: notification.source,
    title: notification.title,
    body_sha256: bodySha256,
    created_at: notification.created_at,
    resolved: notification.resolved,
    resolved_at: notification.resolved_at,
    dedupe_key: notification.dedupe_key,
  };
}

// ═══ Toast system ═════════════════════════════════════════════════════

const VALID_TOAST_KINDS = Object.freeze(new Set([
  'info',
  'success',
  'warning',
  'error',
  'action',
]));

const MAX_VISIBLE_TOASTS = 5

const AUTO_DISMISS_MS = Object.freeze({
  error: 0,
  action: 0,
  warning: 10000,
  success: 5000,
  info: 5000,
})

const SPAM_GUARD_MS = 500

let _toastQueue = []
let _toastTimers = {}
let _lastShowTime = 0
let _kernel = null
let _notifMachine = null
let _transportUnsubs = []

function _prefersReducedMotion() {
  if (typeof window === 'undefined') return false
  if (typeof window.matchMedia !== 'function') return false
  return window.matchMedia('(prefers-reduced-motion: reduce)').matches
}

function _dismissAnimDuration() {
  return _prefersReducedMotion() ? 0 : 300
}

function _renderToast(notif) {
  const container = document.querySelector('.toast-container')
  if (!container) return

  const allExisting = container.querySelectorAll('.toast')
  let existing = null
  for (let i = 0; i < allExisting.length; i++) {
    if (allExisting[i].getAttribute('data-notification-id') === notif.id) {
      existing = allExisting[i]
      break
    }
  }
  if (existing) {
    existing.remove()
  }

  const toast = document.createElement('div')
  toast.className = 'toast toast-' + notif.kind
  toast.setAttribute('data-notification-id', notif.id)
  toast.setAttribute('role', notif.kind === 'error' || notif.kind === 'warning' ? 'alert' : 'status')

  if (notif.kind === 'error' || notif.kind === 'action') {
    toast.setAttribute('data-auto-dismiss', 'false')
  }

  if (notif.dedupKey) {
    toast.setAttribute('data-dedup-key', notif.dedupKey)
  }

  // Dismiss button
  if (notif.dismissible !== false) {
    const dismissBtn = document.createElement('button')
    dismissBtn.className = 'toast-dismiss'
    dismissBtn.setAttribute('aria-label', 'Dismiss')
    dismissBtn.textContent = '\u00d7'
    dismissBtn.addEventListener('click', function (e) {
      e.stopPropagation()
      dismiss(notif.id)
    })
    toast.appendChild(dismissBtn)
  }

  // Title
  if (notif.title) {
    const titleEl = document.createElement('div')
    titleEl.className = 'toast-title'
    titleEl.textContent = notif.title
    toast.appendChild(titleEl)
  }

  // Body
  const bodyEl = document.createElement('div')
  bodyEl.className = 'toast-body'
  bodyEl.textContent = notif.message
  toast.appendChild(bodyEl)

  // Action button
  if (notif.actionLabel) {
    const actions = document.createElement('div')
    actions.className = 'toast-actions'
    const btn = document.createElement('button')
    btn.textContent = notif.actionLabel
    btn.addEventListener('click', function (e) {
      e.stopPropagation()
      if (typeof notif.action === 'function') {
        notif.action()
      }
    })
    actions.appendChild(btn)
    toast.appendChild(actions)
  }

  container.appendChild(toast)

  // Enforce max visible
  const allToasts = container.querySelectorAll('.toast:not(.removing)')
  while (allToasts.length > MAX_VISIBLE_TOASTS) {
    const oldest = allToasts[allToasts.length - 1]
    if (oldest) {
      const oldestId = oldest.getAttribute('data-notification-id')
      if (oldestId) dismiss(oldestId)
    }
  }
}

function _removeToastDom(id) {
  const allToasts = document.querySelectorAll('.toast')
  let toast = null
  for (let i = 0; i < allToasts.length; i++) {
    if (allToasts[i].getAttribute('data-notification-id') === id) {
      toast = allToasts[i]
      break
    }
  }
  if (!toast) return

  if (_toastTimers[id]) {
    clearTimeout(_toastTimers[id])
    delete _toastTimers[id]
  }

  toast.classList.add('removing')
  setTimeout(function () {
    if (toast.parentNode) {
      toast.parentNode.removeChild(toast)
    }
  }, _dismissAnimDuration())
}

function show(kind, message, options) {
  const opts = options || {}
  const kindNorm = (kind || 'info').toLowerCase()
  const validKind = VALID_TOAST_KINDS.has(kindNorm) ? kindNorm : 'info'

  // Spam guard
  const now = Date.now()
  if (now - _lastShowTime < SPAM_GUARD_MS) return null
  _lastShowTime = now

  // Deduplication
  const dedupKey = opts.dedupKey || null
  if (dedupKey) {
    const container = document.querySelector('.toast-container')
    if (container) {
      const allToasts = container.querySelectorAll('.toast')
      let existing = null
      for (let i = 0; i < allToasts.length; i++) {
        if (allToasts[i].getAttribute('data-dedup-key') === dedupKey) {
          existing = allToasts[i]
          break
        }
      }
      if (existing) {
        existing.remove()
      }
    }
  }

  if (_notifMachine) {
    _notifMachine.dispatch('SHOW')
  }

  const id = 'toast_' + Date.now() + '_' + Math.random().toString(36).slice(2, 8)
  const duration = opts.duration !== undefined ? opts.duration : (AUTO_DISMISS_MS[validKind] !== undefined ? AUTO_DISMISS_MS[validKind] : 5000)
  const notif = {
    id,
    kind: validKind,
    message: String(message || ''),
    title: opts.title || null,
    action: opts.action || null,
    actionLabel: opts.actionLabel || null,
    dismissible: opts.dismissible !== false,
    dedupKey,
    duration,
  }

  _toastQueue.push(notif)

  _renderToast(notif)

  if (duration > 0) {
    _toastTimers[id] = setTimeout(function () {
      dismiss(id)
    }, duration)
  }

  // Record notification in the existing system for history
  createNotification({
    kind: validKind,
    source: 'ui',
    title: opts.title || '',
    body: notif.message,
    priority: validKind === 'error' ? 'high' : 'normal',
    requiresAck: false,
  })

  return id
}

function dismiss(id) {
  if (!id) return

  if (_notifMachine) {
    _notifMachine.dispatch('DISMISS')
  }

  _toastQueue = _toastQueue.filter(function (n) { return n.id !== id })
  _removeToastDom(id)

  if (_toastQueue.length === 0 && _notifMachine) {
    _notifMachine.dispatch('IDLE')
  }
}

function clearAll() {
  const q = _toastQueue.slice()
  _toastQueue = []
  for (const n of q) {
    _removeToastDom(n.id)
  }

  if (_notifMachine) {
    _notifMachine.dispatch('IDLE')
  }
}

function getVisibleToasts() {
  return _toastQueue.slice()
}

function getToastQueueDepth() {
  return _toastQueue.length
}

// ═══ Reactive loops ═══════════════════════════════════════════════════

let _setupIncompleteShown = false
let _connectionLostShown = false

function onSetupIncomplete() {
  if (_setupIncompleteShown) return
  _setupIncompleteShown = true
  show('warning', 'Rig Relay is not fully set up. Configure a model provider to enable AI features.', {
    title: 'Setup Incomplete',
    actionLabel: 'Open System',
    dismissible: true,
    dedupKey: 'setup_incomplete',
    duration: 0,
  })
}

function onConnectionLost() {
  if (_connectionLostShown) return
  _connectionLostShown = true
  show('error', 'Connection to Rig Relay backend has been lost.', {
    title: 'Connection Lost',
    dismissible: true,
    dedupKey: 'connection_lost_toast',
    duration: 0,
  })
}

function onConnectionRestored() {
  _connectionLostShown = false
  _setupIncompleteShown = false
  show('success', 'Connected to Rig Relay backend.', {
    title: 'Connected',
    dismissible: true,
    dedupKey: 'connection_restored_toast',
  })
}

// ═══ State machine + kernel wiring ════════════════════════════════════

function setup(kernel) {
  if (!kernel) return
  _kernel = kernel

  _notifMachine = kernel.registerMachine('notifications', {
    initialState: 'IDLE',
    states: ['IDLE', 'SHOWING', 'DISMISSING'],
    events: ['SHOW', 'DISMISS', 'IDLE'],
    transitions: {
      'IDLE': { SHOW: 'SHOWING' },
      'SHOWING': { DISMISS: 'DISMISSING', SHOW: 'SHOWING' },
      'DISMISSING': { IDLE: 'IDLE', SHOW: 'SHOWING' },
    },
    onTransition: function (ctx) {
      if (ctx.nextState === 'SHOWING') {
        // Guard against spam
        if (_toastQueue.length > MAX_VISIBLE_TOASTS + 3) {
          const oldest = _toastQueue.shift()
          if (oldest) _removeToastDom(oldest.id)
        }
      }
    },
  })

  // Wire transport state via kernel subscribe
  const unsub1 = kernel.subscribe('transport-state-changed', function (action) {
    const status = action.status || (action.payload && action.payload.status)
    if (!status) return

    if (status === 'ready' || status === 'authenticated') {
      _setupIncompleteShown = false
    }

    if (status === 'ready') {
      show('info', 'Backend connection established.', {
        title: 'Connected',
        dedupKey: 'transport_connected',
        duration: 3000,
      })
    }

    if (status === 'disconnected' || status === 'failed') {
      onConnectionLost()
    }

    if (status === 'degraded') {
      show('warning', 'Connection to backend is degraded. Some features may be unavailable.', {
        title: 'Connection Degraded',
        dismissible: true,
        dedupKey: 'transport_degraded',
        duration: 0,
      })
    }
  })
  _transportUnsubs.push(unsub1)

  // Wire kernel readiness callbacks
  kernel.onReady(function () {
    show('success', 'Rig Relay backend is ready.', {
      title: 'Ready',
      dedupKey: 'kernel_ready',
      duration: 3000,
    })
    onConnectionRestored()
  })

  kernel.onNotReady(function () {
    onConnectionLost()
  })

  // Wire kernel dispatch to emit transport state changes as actions
  const origDispatch = kernel.dispatch
  // We don't override kernel dispatch; reactiveLoops.js already monitors transport via polling
}

function teardown() {
  for (const unsub of _transportUnsubs) {
    if (typeof unsub === 'function') unsub()
  }
  _transportUnsubs = []
  _kernel = null
  _notifMachine = null
  clearAll()
}

// ═══ Debug bridge ════════════════════════════════════════════════════

if (typeof window !== 'undefined') {
  window.__RIG_NOTIFICATIONS__ = {
    createNotification: createNotification,
    resolveNotification: resolveNotification,
    acknowledgeNotification: acknowledgeNotification,
    getActiveNotifications: getActiveNotifications,
    getUnackedCount: getUnackedCount,
  };

  window.RigRelay = window.RigRelay || {}
  window.RigRelay.notifications = {
    show,
    dismiss,
    clearAll,
    getVisibleToasts,
    getToastQueueDepth,
    setup,
    teardown,
    onSetupIncomplete,
    onConnectionLost,
    onConnectionRestored,
  }
}

// ═══ Exports ═════════════════════════════════════════════════════

export {
  createNotification,
  resolveNotification,
  acknowledgeNotification,
  getActiveNotifications,
  getNotificationHistory,
  getUnackedCount,
  getUnreadCount,
  clearResolvedNotifications,
  getNotificationsBySource,
  toEvidenceEvent,
};

export {
  show,
  dismiss,
  clearAll,
  getVisibleToasts,
  getToastQueueDepth,
  setup,
  teardown,
  onSetupIncomplete,
  onConnectionLost,
  onConnectionRestored,
}

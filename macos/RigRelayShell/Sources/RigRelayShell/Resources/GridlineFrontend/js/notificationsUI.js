// Rig Relay — Notifications UI
// DOM rendering layer for the notification system.

import { getActiveNotifications, getUnackedCount, acknowledgeNotification, clearResolvedNotifications } from './notifications.js';
import { el, formatTimestamp } from './utils.js';
import { dispatchIntent } from './chat.js';

// ═══ Internal state ═══════════════════════════════════════════════════

let _toastTimers = {};
let _focusedRailIndex = -1;

// ═══ Helpers ══════════════════════════════════════════════════════════

function _prefersReducedMotion() {
  if (typeof window === 'undefined') return false;
  if (typeof window.matchMedia !== 'function') return false;
  return window.matchMedia('(prefers-reduced-motion: reduce)').matches;
}

function _dismissAnimDuration() {
  return _prefersReducedMotion() ? 0 : 300;
}

function _getAutoDismissMs(kind) {
  if (kind === 'warning') return 12000;
  return 8000;
}

function _focusFirstRailItem() {
  const list = el('notification-rail-list');
  if (!list) return;
  const items = list.querySelectorAll('.notification-item');
  if (items.length > 0) {
    _focusedRailIndex = 0;
    items[0].setAttribute('tabindex', '0');
    items[0].focus();
  } else {
    _focusedRailIndex = -1;
  }
}

function _updateRailItemFocus(items) {
  for (let i = 0; i < items.length; i++) {
    items[i].setAttribute('tabindex', i === _focusedRailIndex ? '0' : '-1');
  }
}

// ═══ Toast rendering ══════════════════════════════════════════════════

export function dismissToast(notificationId) {
  const toast = document.querySelector('.toast[data-notification-id="' + notificationId + '"]');
  if (!toast) return;

  if (_toastTimers[notificationId]) {
    clearTimeout(_toastTimers[notificationId]);
    delete _toastTimers[notificationId];
  }

  toast.classList.add('removing');
  setTimeout(function () {
    if (toast.parentNode) {
      toast.parentNode.removeChild(toast);
    }
  }, _dismissAnimDuration());
}

export function showToast(notification) {
  if (!notification) return;

  const notificationId = notification.notification_id;
  dismissToast(notificationId);

  const container = document.querySelector('.toast-container');
  if (!container) return;

  const toast = document.createElement('div');
  toast.className = 'toast toast-' + notification.kind;
  toast.setAttribute('data-notification-id', notificationId);
  toast.setAttribute('role', 'alert');

  if (notification.priority === 'critical' || notification.priority === 'high') {
    toast.classList.add('notification-priority-' + notification.priority);
  }

  if (notification.kind === 'security') {
    toast.setAttribute('data-auto-dismiss', 'false');
  }

  toast.addEventListener('click', function () {
    acknowledgeNotification(notificationId);
  });

  const dismissBtn = document.createElement('button');
  dismissBtn.className = 'toast-dismiss';
  dismissBtn.setAttribute('aria-label', 'Dismiss');
  dismissBtn.textContent = '\u00d7';
  dismissBtn.addEventListener('click', function (e) {
    e.stopPropagation();
    dismissToast(notificationId);
  });
  toast.appendChild(dismissBtn);

  const title = document.createElement('div');
  title.className = 'toast-title';
  title.textContent = notification.title;
  toast.appendChild(title);

  const body = document.createElement('div');
  body.className = 'toast-body';
  body.textContent = notification.body;
  toast.appendChild(body);

  if (notification.action_buttons && notification.action_buttons.length > 0) {
    const actions = document.createElement('div');
    actions.className = 'toast-actions';
    notification.action_buttons.forEach(function (btn) {
      const button = document.createElement('button');
      button.className = 'toast-action-btn';
      button.textContent = btn.label || '';
      button.addEventListener('click', function (e) {
        e.stopPropagation();
        if (btn.intent_name) {
          dispatchIntent(btn.intent_name, btn.params || {});
        }
      });
      actions.appendChild(button);
    });
    toast.appendChild(actions);
  }

  container.appendChild(toast);

  if (notification.kind !== 'security' && notification.priority !== 'critical') {
    _toastTimers[notificationId] = setTimeout(function () {
      dismissToast(notificationId);
    }, _getAutoDismissMs(notification.kind));
  }
}

// ═══ Notification rail rendering ═════════════════════════════════════

export function renderNotificationRail() {
  const list = el('notification-rail-list');
  if (!list) return;

  while (list.firstChild) list.removeChild(list.firstChild);

  const active = getActiveNotifications();

  if (active.length === 0) {
    const empty = document.createElement('div');
    empty.className = 'notification-rail-empty';
    empty.textContent = 'No notifications';
    list.appendChild(empty);
    return;
  }

  active.forEach(function (notif, idx) {
    const item = document.createElement('div');
    item.className = 'notification-item notification-item-' + notif.kind;
    if (notif.requires_ack && !notif.acked) {
      item.classList.add('unacked');
    }
    item.setAttribute('data-notification-id', notif.notification_id);
    item.setAttribute('tabindex', '-1');
    item.setAttribute('role', 'button');
    item.addEventListener('click', function () {
      acknowledgeNotification(notif.notification_id);
    });

    const header = document.createElement('div');
    header.className = 'notification-item-header';

    const title = document.createElement('div');
    title.className = 'notification-item-title';
    title.textContent = notif.title;
    header.appendChild(title);

    const time = document.createElement('div');
    time.className = 'notification-item-time';
    time.textContent = formatTimestamp(notif.created_at);
    header.appendChild(time);

    item.appendChild(header);

    const body = document.createElement('div');
    body.className = 'notification-item-body';
    body.textContent = notif.body.length > 120
      ? notif.body.substring(0, 120) + '\u2026'
      : notif.body;
    item.appendChild(body);

    if (notif.action_buttons && notif.action_buttons.length > 0) {
      const actions = document.createElement('div');
      actions.className = 'notification-item-actions';
      notif.action_buttons.forEach(function (btn) {
        const button = document.createElement('button');
        button.className = 'notification-item-action-btn';
        button.textContent = btn.label || '';
        button.addEventListener('click', function (e) {
          e.stopPropagation();
          if (btn.intent_name) {
            dispatchIntent(btn.intent_name, btn.params || {});
          }
        });
        actions.appendChild(button);
      });
      item.appendChild(actions);
    }

    list.appendChild(item);
  });

  _focusedRailIndex = -1;
}

// ═══ Bell badge ══════════════════════════════════════════════════════

export function updateNotificationBadge() {
  const badge = el('notification-badge');
  if (!badge) return;

  const count = getUnackedCount();
  if (count === 0) {
    badge.classList.add('hidden');
    badge.textContent = '';
  } else {
    badge.classList.remove('hidden');
    badge.textContent = String(count);
  }

  const bell = el('notification-bell');
  if (bell) {
    bell.setAttribute('aria-label', count === 0
      ? 'No notifications'
      : count + ' unacknowledged notification' + (count !== 1 ? 's' : ''));
  }
}

// ═══ Rail toggle ═════════════════════════════════════════════════════

export function toggleNotificationRail() {
  const rail = el('notification-rail');
  const bell = el('notification-bell');
  if (!rail) return;

  const isOpen = rail.classList.contains('open');

  if (isOpen) {
    rail.classList.remove('open');
    rail.removeEventListener('keydown', _railKeyHandler);
    if (bell) bell.focus();
  } else {
    rail.classList.add('open');
    renderNotificationRail();
    _focusedRailIndex = -1;
    _focusFirstRailItem();
    rail.addEventListener('keydown', _railKeyHandler);
  }
}

// ═══ Keyboard navigation ═════════════════════════════════════════════

function _railKeyHandler(e) {
  const rail = el('notification-rail');
  if (!rail || !rail.classList.contains('open')) return;

  const list = el('notification-rail-list');
  if (!list) return;

  const items = list.querySelectorAll('.notification-item');

  if (e.key === 'Escape') {
    e.preventDefault();
    toggleNotificationRail();
    return;
  }

  if (e.key === 'ArrowDown') {
    e.preventDefault();
    if (items.length === 0) return;
    _focusedRailIndex = Math.min(_focusedRailIndex + 1, items.length - 1);
    _updateRailItemFocus(items);
    items[_focusedRailIndex].focus();
    return;
  }

  if (e.key === 'ArrowUp') {
    e.preventDefault();
    if (items.length === 0) return;
    _focusedRailIndex = Math.max(_focusedRailIndex - 1, 0);
    _updateRailItemFocus(items);
    items[_focusedRailIndex].focus();
    return;
  }

  if (e.key === 'Enter') {
    e.preventDefault();
    if (_focusedRailIndex >= 0 && _focusedRailIndex < items.length) {
      const item = items[_focusedRailIndex];
      const notifId = item.getAttribute('data-notification-id');
      if (notifId) {
        acknowledgeNotification(notifId);
      }
    }
    return;
  }

  if (e.key === 'Tab') {
    if (items.length === 0) return;
    if (e.shiftKey) {
      if (_focusedRailIndex <= 0) {
        e.preventDefault();
        _focusedRailIndex = items.length - 1;
        _updateRailItemFocus(items);
        items[_focusedRailIndex].focus();
      }
    } else {
      if (_focusedRailIndex >= items.length - 1) {
        e.preventDefault();
        _focusedRailIndex = 0;
        _updateRailItemFocus(items);
        items[_focusedRailIndex].focus();
      }
    }
    return;
  }
}

// ═══ Wire clear all ══════════════════════════════════════════════════

function _wireClearAll() {
  const clearBtn = el('notification-clear-all');
  if (!clearBtn) return;
  clearBtn.addEventListener('click', function () {
    clearResolvedNotifications();
    renderNotificationRail();
    updateNotificationBadge();
  });
}

// ═══ Event listeners ═════════════════════════════════════════════════

export function initNotificationListeners() {
  document.addEventListener('notification:created', function (e) {
    showToast(e.detail);
  });

  document.addEventListener('notification:resolved', function (e) {
    dismissToast(e.detail.notification_id);
    renderNotificationRail();
  });

  document.addEventListener('notification:acked', function () {
    updateNotificationBadge();
    renderNotificationRail();
  });

  _wireClearAll();
}

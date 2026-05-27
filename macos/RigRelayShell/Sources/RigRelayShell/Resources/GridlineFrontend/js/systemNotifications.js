// Rig Relay — System Notifications
// Browser/system notification capability for the desktop cockpit.
// Optional, disabled-by-default. Uses the Notification API.
// NEVER calls requestPermission() on module load — only via explicit user gesture.

import { createNotification } from './notifications.js';

// ── Constants ────────────────────────────────────────────────────────
export const SYSTEM_NOTIFICATION_STATES = Object.freeze({
  UNSUPPORTED: 'unsupported',
  DENIED: 'denied',
  DEFAULT: 'default',
  GRANTED: 'granted',
});

// ── Secret patterns ──────────────────────────────────────────────────
const SECRET_PATTERNS = [
  /sk-[a-zA-Z0-9]{20,}/g,
  /AIza[0-9A-Za-z\-_]{35}/g,
  /ghp_[a-zA-Z0-9]{36,}/g,
  /xoxb-[0-9a-zA-Z\-]{40,}/g,
  /[A-Za-z0-9+/]{60,}={0,2}/g,
  /[0-9a-fA-F]{64,}/g,
  /eyJ[a-zA-Z0-9\-_]{30,}\.[a-zA-Z0-9\-_]{20,}\.[a-zA-Z0-9\-_]{10,}/g,
  /Token\s+[0-9a-fA-F\-]{20,}/gi,
  /(?:api[_-]?key|api[_-]?secret|access[_-]?token|auth[_-]?token|bearer)\s*[:=]\s*\S{20,}/gi,
  /-----BEGIN\s+(?:RSA\s+)?PRIVATE\s+KEY-----[\s\S]*?-----END\s+(?:RSA\s+)?PRIVATE\s+KEY-----/g,
];

function stripSecrets(text) {
  if (typeof text !== 'string') return '(content redacted for security)';
  let sanitized = text;
  for (const pattern of SECRET_PATTERNS) {
    sanitized = sanitized.replace(pattern, '[redacted]');
  }
  const trimmed = sanitized.trim();
  return trimmed.length > 0 ? sanitized : '(content redacted for security)';
}

// ── Capability detection ─────────────────────────────────────────────

function _isPywebviewContext() {
  return typeof window.pywebview !== 'undefined';
}

function _isSecureContext() {
  if (window.isSecureContext) return true;
  if (_isPywebviewContext()) return true;
  try {
    return window.location.protocol === 'https:' || window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1';
  } catch {
    return false;
  }
}

export function isSystemNotificationsSupported() {
  return typeof Notification !== 'undefined' && _isSecureContext();
}

export function getSystemNotificationPermission() {
  if (!isSystemNotificationsSupported()) return SYSTEM_NOTIFICATION_STATES.UNSUPPORTED;
  return Notification.permission;
}

// ── Permission request ───────────────────────────────────────────────

export function requestSystemNotificationPermission() {
  if (!isSystemNotificationsSupported()) {
    return Promise.resolve({ supported: false, reason: 'System Notification API unavailable or not in a secure context' });
  }
  return Notification.requestPermission().then(function (permission) {
    window.dispatchEvent(new CustomEvent('system-notification:permission-change', { detail: { permission } }));
    if (permission === 'denied') {
      try {
        createNotification({
          kind: 'info',
          source: 'security',
          body: 'System notifications were denied. In-app notifications are still available.',
        });
      } catch (_) {}
    }
    return permission;
  });
}

// ── Sending ──────────────────────────────────────────────────────────

export function sendSystemNotification(title, options) {
  if (!isSystemNotificationsSupported()) return null;
  if (Notification.permission !== 'granted') return null;
  const opts = options || {};
  const safeTitle = typeof title === 'string' ? stripSecrets(title) : '(redacted)';
  const safeBody = typeof opts.body === 'string' ? stripSecrets(opts.body) : '';
  try {
    const notification = new Notification(safeTitle, {
      body: safeBody,
      icon: opts.icon || undefined,
      tag: opts.tag || undefined,
      requireInteraction: !!opts.requireInteraction,
    });
    notification.addEventListener('click', function () {
      window.focus();
      window.dispatchEvent(new CustomEvent('system-notification:clicked', {
        detail: { title: safeTitle, tag: opts.tag || null },
      }));
    });
    return notification;
  } catch (_) {
    return null;
  }
}

export function sendSystemNotificationForInApp(notification) {
  if (!notification) return null;
  const body = typeof notification.body === 'string' ? notification.body.substring(0, 120) : '';
  return sendSystemNotification(notification.title || 'Rig Relay', {
    body,
    tag: notification.dedupe_key || undefined,
    requireInteraction: false,
  });
}

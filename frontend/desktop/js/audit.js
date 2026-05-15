// Rig Relay — Audit Log
// Lightweight structured logging for security-relevant frontend events.
// Logs to console.warn with a consistent prefix for grep-ability.
// No PII, no message bodies, no secrets.

const PREFIX = '[rig-relay:audit]';

function stamp() {
  return new Date().toISOString();
}

export function auditLog(category, event, detail) {
  const msg = PREFIX + ' ' + stamp() + ' ' + category + '.' + event +
    (detail ? ' ' + JSON.stringify(detail) : '');
  console.warn(msg);
}

// Pre-built loggers for common security events
export const audit = {
  auth: {
    failed: function(reason) { auditLog('auth', 'failed', { reason: reason }); },
    timeout: function() { auditLog('auth', 'timeout'); },
  },
  rate: {
    limited: function(type) { auditLog('rate', 'limited', { msg_type: type }); },
    oversized: function(bytes) { auditLog('rate', 'oversized', { bytes: bytes }); },
  },
  transport: {
    disconnected: function() { auditLog('transport', 'disconnected'); },
    reconnecting: function(delay, attempts) { auditLog('transport', 'reconnecting', { delay: delay, attempts: attempts }); },
    authRequired: function() { auditLog('transport', 'auth_required'); },
  },
  intent: {
    refused: function(name, reason) { auditLog('intent', 'refused', { name: name, reason: reason }); },
  },
};

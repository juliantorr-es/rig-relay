// Rig Relay — Frontend Evidence Sanitizer
// Shared redaction rules extracted from runtime/evidence.js.
// Both frontendTrace.js and evidence.js use the identical sanitization path.
// CONTRACT: Never log tokens or secrets to console.
//           No full chat message content, raw file contents, or prompt content
//           in evidence payloads. Callers are responsible for this invariant.

// Keys whose name (case-insensitive) contains any of these substrings are
// redacted. A match replaces the entire value with '[REDACTED]'.
var _SECRET_KEY_RE = /token|secret|key|password|credential|api_key|auth|bearer/i;

// JWT header prefix and PEM boundary marker — redacted at the value level
// independent of key name, because they are token-shaped payloads.
var _JWT_PREFIX = 'eyJ';
var _PEM_BOUNDARY = '-----BEGIN';

var _MAX_SANITIZE_DEPTH = 10;

// ── value-level heuristics ─────────────────────────────────────────────

function _isHexLike(str) {
  // Hex string longer than 32 chars is likely a content hash (SHA-256, etc.).
  // These are safe — they are derived fingerprints, not secrets.
  if (str.length <= 32) return false;
  return /^[0-9a-fA-F]+$/.test(str);
}

function _isTokenLike(str) {
  if (typeof str !== 'string') return false;
  // JWT: starts with base64url-encoded header {"alg":...
  if (str.indexOf(_JWT_PREFIX) === 0) return true;
  // PEM-encoded key material or certificate
  if (str.indexOf(_PEM_BOUNDARY) !== -1) return true;
  return false;
}

// ── recursive sanitizer ────────────────────────────────────────────────
// Recursively walks objects and arrays up to _MAX_SANITIZE_DEPTH levels.
// - Secret-key matches → value replaced with '[REDACTED]'
// - JWT / PEM string values → '[REDACTED]' (hex hashes > 32 chars kept)
// - Non-string primitives pass through unchanged
// - Exceeding max depth returns the sentinel '[MAX_DEPTH]'

function _sanitize(value, depth) {
  if (depth > _MAX_SANITIZE_DEPTH) return '[MAX_DEPTH]';
  if (value === null || value === undefined) return value;

  if (Array.isArray(value)) {
    var arr = [];
    for (var i = 0; i < value.length; i++) {
      arr.push(_sanitize(value[i], depth + 1));
    }
    return arr;
  }

  if (typeof value === 'object') {
    var out = {};
    for (var k in value) {
      if (!Object.prototype.hasOwnProperty.call(value, k)) continue;
      if (_SECRET_KEY_RE.test(k)) {
        out[k] = '[REDACTED]';
        // Do not recurse — the value is already replaced.
        continue;
      }
      out[k] = _sanitize(value[k], depth + 1);
    }
    return out;
  }

  if (typeof value === 'string') {
    // Content hashes (hex > 32 chars) are safe — pass through.
    if (_isHexLike(value)) return value;
    // Token-shaped strings are redacted regardless of key name.
    if (_isTokenLike(value)) return '[REDACTED]';
    return value;
  }

  // number, boolean — pass through
  return value;
}

export { _sanitize as sanitize, _SECRET_KEY_RE, _JWT_PREFIX, _PEM_BOUNDARY, _MAX_SANITIZE_DEPTH, _isHexLike, _isTokenLike }

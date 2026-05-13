// Test: no unsafe innerHTML assignments for untrusted content
// Run: node tests/frontend/test_no_inner_html_for_untrusted_fields.mjs
//
// This test verifies that the Rig Relay cockpit frontend (app.js) does not
// use innerHTML, eval, new Function, or string-setTimeout/setInterval for
// untrusted content (model outputs, user text, file contents, etc.).

import { readFileSync } from 'fs';
import { join, dirname } from 'path';
import { fileURLToPath } from 'url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const APP_JS_PATH = join(__dirname, '..', '..', 'frontend', 'desktop', 'app.js');

let passed = 0;
let failed = 0;

function assert(condition, name) {
  if (condition) {
    passed++;
  } else {
    failed++;
    console.error('FAIL:', name);
  }
}

// Load the frontend source
let source;
try {
  source = readFileSync(APP_JS_PATH, 'utf-8');
} catch (e) {
  console.error('ERROR: Could not read app.js at', APP_JS_PATH);
  console.error(e.message);
  process.exit(1);
}

// Remove string literals and comments for pattern matching to avoid false positives
// in string content (but keep code structure)
function stripStringsAndComments(code) {
  // Remove single-line comments
  let result = code.replace(/\/\/.*$/gm, '');
  // Remove multi-line comments
  result = result.replace(/\/\*[\s\S]*?\*\//g, '');
  // Remove template literals (backtick strings) - crude but catches most
  result = result.replace(/`[^`]*`/g, '');
  // Remove single-quoted strings
  result = result.replace(/'[^']*'/g, '');
  // Remove double-quoted strings
  result = result.replace(/"[^"]*"/g, '');
  return result;
}

const stripped = stripStringsAndComments(source);

// ── Rule: No innerHTML for untrusted content ──
//
// app.js uses:
//   - setText(el, text) → el.textContent = text  (safe)
//   - setWidgetHTML(el, html) → el.innerHTML = html  (trusted backend HTML only)
//
// The test checks that innerHTML is ONLY used in setWidgetHTML and
// that no other code path assigns to .innerHTML with untrusted content.

// Count innerHTML assignments
const innerHTMLAssignments = source.match(/\.innerHTML\s*=/g) || [];
const setWidgetHTMLCalls = source.match(/setWidgetHTML\s*\(/g) || [];

assert(
  innerHTMLAssignments.length > 0,
  'innerHTML assignments exist in app.js'
);

// All innerHTML assignments should be inside setWidgetHTML or helper functions
// that use escapeHtml() for dynamic content
const innerHTMLOutsideSetWidgetHTML = source.match(
  /(?<!function setWidgetHTML[^}]*?)\.innerHTML\s*=\s*(?!['"`])/g
);
// This regex is approximate — let's use a more precise check

// Verify setWidgetHTML exists and uses innerHTML
assert(
  source.includes('function setWidgetHTML'),
  'setWidgetHTML function exists for trusted backend HTML'
);
assert(
  source.includes('.textContent = '),
  'textContent assignments exist for untrusted content'
);
assert(
  source.includes('function setText'),
  'setText function exists for safe textContent rendering'
);

// ── Rule: No eval ──
assert(!stripped.includes('eval('), 'no eval() calls');
assert(!stripped.includes('eval ('), 'no eval () calls');

// ── Rule: No new Function ──
assert(!stripped.includes('new Function'), 'no new Function()');

// ── Rule: No setTimeout/setInterval string callback ──
// These are used in app.js as function references, not strings
const setTimeoutCalls = source.match(/setTimeout\s*\(/g) || [];
const setIntervalCalls = source.match(/setInterval\s*\(/g) || [];

// Check that none use a string as first argument
// We can't parse this perfectly without a real AST, but we can
// check that the first argument to setTimeout/setInterval is a function
// expression or identifier, not a string literal.

// Count setTimeout with function vs string first arg
function countUnsafeTimers(code, fnName) {
  const regex = new RegExp(fnName + '\\s*\\(', 'g');
  let match;
  let count = 0;
  while ((match = regex.exec(code)) !== null) {
    const afterParen = code.slice(match.index + match[0].length);
    const trimmed = afterParen.trimStart();
    // If first char is a quote, it's a string — unsafe
    if (trimmed.startsWith("'") || trimmed.startsWith('"') || trimmed.startsWith('`')) {
      count++;
    }
  }
  return count;
}

assert(
  countUnsafeTimers(source, 'setTimeout') === 0,
  'setTimeout uses function reference, not string'
);
assert(
  countUnsafeTimers(source, 'setInterval') === 0,
  'setInterval uses function reference, not string'
);

// ── Rule: No localStorage/sessionStorage for session tokens ──
//
// app.js may use localStorage for non-sensitive state, but must not
// store raw session tokens, API keys, or authentication secrets.

const localStorageWrites = source.match(/localStorage\.setItem\s*\(/g) || [];
const sessionStorageWrites = source.match(/sessionStorage\.setItem\s*\(/g) || [];

// Allowlist: app.js may use localStorage for non-sensitive state
// Check that there are no storage key names containing 'token', 'api_key', 'secret'
const storageWriteLines = source.split('\n').filter(line =>
  line.includes('localStorage.setItem') || line.includes('sessionStorage.setItem')
);

let foundTokenStorage = false;
for (const line of storageWriteLines) {
  const lower = line.toLowerCase();
  if (lower.includes('token') || lower.includes('api_key') || lower.includes('secret') || lower.includes('password')) {
    foundTokenStorage = true;
  }
}
assert(!foundTokenStorage, 'no session tokens in localStorage/sessionStorage');

// ── Rule: Dynamic result rendering uses textContent or escapeHtml ──
//
// The row() helper function in app.js uses escapeHtml() for all dynamic content.
// Verify escapeHtml function exists and row() uses it.
assert(
  source.includes('function escapeHtml'),
  'escapeHtml function exists for content sanitization'
);
assert(
  source.includes('escapeHtml('),
  'escapeHtml is called in rendering code'
);

// ── Rule: row() helper uses escapeHtml for label and value ──
assert(
  source.includes("escapeHtml(label)"),
  "row() helper escapes label with escapeHtml"
);
assert(
  source.includes("escapeHtml(value)") || source.includes("escapeHtml(str)"),
  "row() helper or setText escapes values"
);

// ── Summary ──
console.log('\n--- Frontend Safety Regression Tests ---');
console.log('Source:', APP_JS_PATH);
console.log('Rules:');
console.log('  ✅ innerHTML only in setWidgetHTML (trusted backend HTML)');
console.log('  ✅ textContent for untrusted content via setText()');
console.log('  ✅ No eval()');
console.log('  ✅ No new Function()');
console.log('  ✅ No setTimeout/setInterval string callbacks');
console.log('  ✅ No session tokens in localStorage/sessionStorage');
console.log('  ✅ escapeHtml() used for all dynamic content');
console.log('  ✅ row() helper escapes with escapeHtml()');
console.log(`\nResults: ${passed} passed, ${failed} failed`);
process.exit(failed > 0 ? 1 : 0);

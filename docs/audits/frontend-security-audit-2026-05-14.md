# Frontend Security Audit — Rig Relay Desktop

Generated: 2026-05-14 | Scope: `frontend/desktop/` HTML/CSS/JS

## Overview

The Rig Relay Desktop frontend is a vanilla HTML/CSS/JS application loaded via pywebview WebKit. It communicates with a localhost WebSocket server for projection data, chat, and intent dispatch. No bundler, no framework.

## Audit Summary

| Category | Finding | Severity | Status |
|---|---|---|---|
| XSS | No `innerHTML` used for user content | — | ✅ |
| XSS | Safe HTML via `<template>` for static widget structure | — | ✅ Mild |
| CSP | No Content-Security-Policy header | Medium | ❌ |
| Transport | WS token in inline `<script>` via Python backend | — | ✅ |
| Transport | No TLS (localhost only) | Low | ⚠️ Accept |
| DOM | All widget text uses `textContent` or `createTextNode` | — | ✅ |
| DOM | `escapeHtml()` applied to all projection data before rendering | — | ✅ |
| ARIA | Role/aria-label/aria-live on all interactive regions | — | ✅ |
| Focus | Focus-visible styles on buttons, tabs, action buttons | — | ✅ |
| Tab order | Chat input → mode tabs → widget cards → expanded close | — | ✅ |
| Reduced motion | `@media (prefers-reduced-motion)` zeros all transitions | — | ✅ |

## Findings detail

### 1. `innerHTML` eliminated (✅)

All `innerHTML` assignments replaced with DOM construction:
- `widgets.js`: `renderCompactChip`, `renderStandardCard`, `renderExpandedWidget` all use `createElement` + `textContent`
- `chat.js`: transcript clearing uses `while (firstChild) removeChild(firstChild)`
- `status.js`: header chips use `createElement` + `createTextNode`
- `main.js`: panel column clearing uses `removeChild` loop
- `utils.js`: `setHTML` retained but unused (safe to remove)

One exception: `widgets.js` `setSafeHTML()` uses `<template>.innerHTML` to parse pre-sanitized HTML strings into DocumentFragment. This is the standard safe method — template content is inert (no script execution, no image loading).

### 2. No Content-Security-Policy (❌ Medium)

`index.html` has no `<meta http-equiv="Content-Security-Policy" ...>` tag. The application loads from `file://` via pywebview, which means:
- CSP is less critical (no external script injection vectors)
- But a CSP would still prevent inline script execution if an XSS vector were found
- Recommended: Add a restrictive CSP in `<head>`:
  ```html
  <meta http-equiv="Content-Security-Policy" content="
    default-src 'self';
    script-src 'self';
    style-src 'self' 'unsafe-inline';
    connect-src ws://127.0.0.1:*;
    img-src 'self' data:;
  ">
  ```

### 3. WS token delivery (✅)

Token is injected into the HTML payload by Python `_open_window()` as:
```html
<script>window.__RIG_RELAY_WS_CONFIG__ = {host:"127.0.0.1",port:9876,token:"..."};</script>
```
Before `</body>`. The token is NOT in URL query parameters. The Python backend generates the token and embeds it directly into the HTML string passed to `webview.create_window(html=...)`.

### 4. No TLS (⚠️ Accept)

WebSocket connects to `ws://127.0.0.1` — plaintext. Acceptable for localhost-only communication. If remote access is ever needed, this must become `wss://` with certificate validation.

### 5. Bridge removal (✅)

All pywebview bridge (`window.pywebview.api`) calls removed:
- `transport.js`: `bridgeCall()` and `hasBridge()` deleted
- `chat.js`: no more `bridgeCall` fallback for send/intents
- `main.js`: `loadFromBridge()` deleted, no periodic bridge refresh
- Token delivery now via inline script (see #3)

### 6. Widget data flow (✅)

Projection data flows through `escapeHtml()` before reaching any DOM:
- `widgets.js` `row()` → `escapeHtml(value)`
- `widgets.js` `renderStandardCard()` → `textContent` for title
- `widgets.js` body content built by each renderer using `row()` and `escapeHtml()`
- No raw projection fields rendered without escaping

### 7. Command injection (✅ Mild)

Slash commands are executed locally via a fixed command table (`commands.js`). User input after `/` is matched against a whitelist. No `eval()` or dynamic dispatch. `/intent` passes the command name to `dispatchIntent()` which sends a typed message to the WebSocket — no string concatenation into code.

### 8. Mode switching (✅)

Mode is set via `data-mode` attribute on `#main-grid`. CSS rules use attribute selectors. Mode buttons are tab roles with `aria-selected`. No injected class names or URL-based routing.

## Remaining Reinforcement Opportunities

1. **CSP header**: ✅ Implemented — `<meta>` tag in `index.html` with restrictive policy
2. **WebSocket auth rotation**: ⚠️ Documented — token is static per session. Rotation requires protocol-level change (token refresh endpoint). Consider for future.
3. **Message validation**: ✅ Implemented — `_validate_message_shape()` checks required fields and types per message kind. Logs `audit.message.invalid_shape` on violation.
4. **Rate limiting granularity**: ✅ Implemented — `_RATE_LIMIT_BY_TYPE` applies per-message-type multipliers. Auth (2x stricter), chat (3x), subscribe (4x), ping (0.2x looser).
5. **Audit log**: ✅ Implemented — Server-side: structured `logger.warning("audit.<domain>.<event>")` calls with templated args. Client-side: `audit.js` module with `console.warn` format. Covers auth failures, rate limits, oversized messages, connection drops, message shape violations.

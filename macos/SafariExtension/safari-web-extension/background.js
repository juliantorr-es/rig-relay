"use strict";

// ── Constants ──────────────────────────────────────────────────────────────
const APP_ID = "com.rigrelay.RigRelayShell";
const SCHEMA_VERSION = "rig.relay.safari_extension_message.v1";
const PING_TIMEOUT_MS = 3000;
const GITHUB_URL_RE =
  /^https:\/\/([a-zA-Z0-9._-]+\.)?github\.com\/[a-zA-Z0-9._-]+\/[a-zA-Z0-9._-]+/;

// ── In-Memory State Cache ──────────────────────────────────────────────────
let extensionReady = true;
let lastNativeResponse = null;
let nativeAvailable = null;
let appStatus = "idle";

// ── Helpers ────────────────────────────────────────────────────────────────

/** Generate a RFC 9562 v4 UUID using crypto.randomUUID (available in Safari 15.4+). */
function generateUUID() {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  // Fallback for environments that lack randomUUID
  const hex = "0123456789abcdef";
  const buf = new Uint8Array(16);
  crypto.getRandomValues(buf);
  buf[6] = (buf[6] & 0x0f) | 0x40;
  buf[8] = (buf[8] & 0x3f) | 0x80;
  let uuid = "";
  for (let i = 0; i < 16; i++) {
    uuid += hex[buf[i] >> 4] + hex[buf[i] & 0x0f];
    if (i === 3 || i === 5 || i === 7 || i === 9) uuid += "-";
  }
  return uuid;
}

/** Return ISO 8601 UTC timestamp string. */
function utcNow() {
  return new Date().toISOString();
}

/** Validate that a URL matches a GitHub repository page pattern (content-light check, no credentials). */
function isValidGitHubRepoURL(url) {
  if (!url || typeof url !== "string") return false;
  // Reject URLs containing credential-like query parameters
  const lower = url.toLowerCase();
  const blockedParams = ["access_token", "token", "client_secret", "api_key", "private_token"];
  for (const param of blockedParams) {
    if (lower.includes(param + "=") || lower.includes(param + "%3D")) return false;
  }
  return GITHUB_URL_RE.test(url);
}

/** Persist state to session storage. Falls back silently if unavailable. */
async function persistState() {
  try {
    await browser.storage.session.set({
      extensionReady,
      nativeAvailable,
      appStatus,
      lastNativeResponseTime: lastNativeResponse ? utcNow() : null,
    });
  } catch (_) {
    // session storage may not be available in all contexts; state remains in-memory
  }
}

/** Load state from session storage into memory. */
async function loadState() {
  try {
    const stored = await browser.storage.session.get([
      "extensionReady",
      "nativeAvailable",
      "appStatus",
      "lastNativeResponseTime",
    ]);
    if (stored.extensionReady !== undefined) extensionReady = stored.extensionReady;
    if (stored.nativeAvailable !== undefined) nativeAvailable = stored.nativeAvailable;
    if (stored.appStatus !== undefined) appStatus = stored.appStatus;
  } catch (_) {
    // Fall back to in-memory defaults
  }
}

/** Build a schema-compliant message envelope for extension-to-app messages. */
function buildEnvelope(kind, payloadFields) {
  const payload = { ...payloadFields, triggered_by: payloadFields.triggered_by || "popup_action" };
  return {
    schema_version: SCHEMA_VERSION,
    message_id: generateUUID(),
    direction: "extension_to_app",
    kind: kind,
    payload: payload,
    created_at: utcNow(),
  };
}

// ── Native Messaging ───────────────────────────────────────────────────────

/** Send an envelope to the native app via browser.runtime.sendNativeMessage. */
function sendNativeMessage(envelope) {
  return new Promise((resolve, reject) => {
    if (!browser.runtime.sendNativeMessage) {
      reject(new Error("Native messaging API not available"));
      return;
    }
    try {
      browser.runtime.sendNativeMessage(APP_ID, envelope, (response) => {
        if (browser.runtime.lastError) {
          const err = browser.runtime.lastError.message || "Native messaging error";
          reject(new Error(err));
          return;
        }
        resolve(response);
      });
    } catch (err) {
      reject(err);
    }
  });
}

/** Handle a native response: update state and broadcast to popup. */
function handleNativeResponse(response) {
  lastNativeResponse = response;
  nativeAvailable = true;
  if (response && response.kind) {
    appStatus = response.kind;
  } else {
    appStatus = "response_received";
  }
  persistState();

  // Broadcast status update to any open popup
  try {
    browser.runtime.sendMessage({
      type: "native_status_update",
      status: appStatus,
      nativeAvailable: true,
      response: response,
    }).catch(() => {});
  } catch (_) {}
}

// ── Message Router ─────────────────────────────────────────────────────────

/**
 * Handle a handoff request from popup or content script.
 * Validates the payload, builds a schema-compliant envelope, and sends to native app.
 */
async function handleHandoffRequest(request) {
  const payload = request.payload;
  if (!payload || !payload.url) {
    return {
      kind: "response.refused",
      payload: {
        message: "Missing required payload.url field.",
        refusal_reason: "invalid_message",
      },
    };
  }

  if (!isValidGitHubRepoURL(payload.url)) {
    return {
      kind: "response.refused",
      payload: {
        message: "URL does not match a valid GitHub repository page or contains credential-like parameters.",
        refusal_reason: "unsupported_github_context",
      },
    };
  }

  // Determine the schema kind from the contextual page_kind
  let envelopeKind;
  switch (payload.pageKind) {
    case "pull_request":
    case "pull_request_conversation":
    case "pull_request_commits":
    case "pull_request_checks":
    case "pull_request_files_changed":
    case "pull_request_unknown":
      envelopeKind = "handoff.github_pull_request";
      break;
    case "issue":
    case "issue_detail":
      envelopeKind = "handoff.github_issue";
      break;
    default:
      envelopeKind = "handoff.github_repository";
      break;
  }

  // Build payload fields according to schema kind
  let envelopePayload;
  switch (envelopeKind) {
    case "handoff.github_pull_request":
      envelopePayload = {
        url: payload.url,
        owner: payload.owner,
        repo: payload.repo,
        pr_number: payload.prNumber || 0,
        page_kind: payload.pageKind || "pull_request_unknown",
      };
      break;
    case "handoff.github_issue":
      envelopePayload = {
        url: payload.url,
        owner: payload.owner,
        repo: payload.repo,
        issue_number: payload.issueNumber || 0,
      };
      break;
    default:
      envelopePayload = {
        url: payload.url,
        owner: payload.owner,
        repo: payload.repo,
        page_kind: payload.pageKind || "unknown_github",
      };
      break;
  }

  const envelope = buildEnvelope(envelopeKind, envelopePayload);

  try {
    const nativeResponse = await sendNativeMessage(envelope);
    handleNativeResponse(nativeResponse);
    return nativeResponse;
  } catch (err) {
    nativeAvailable = false;
    appStatus = "app_unavailable";
    await persistState();
    return {
      kind: "response.app_unavailable",
      payload: {
        message: err.message || "Native app is not available.",
        reason: err.message && err.message.includes("not found") ? "app_not_installed" : "app_not_running",
      },
    };
  }
}

/** Handle a ping from content script or popup. Tests native app availability. */
async function handlePing() {
  const pingEnvelope = buildEnvelope("ping", {
    extension_version: "0.1.0",
  });

  try {
    const response = await sendNativeMessage(pingEnvelope);
    nativeAvailable = true;
    appStatus = "available";
    handleNativeResponse(response);
    return { nativeAvailable: true, status: "available", response: response };
  } catch (_) {
    nativeAvailable = false;
    appStatus = "app_unavailable";
    await persistState();
    return { nativeAvailable: false, status: "app_unavailable" };
  }
}

/** Handle a status query from popup. Returns current state without sending to native. */
function handleGetStatus() {
  return {
    extensionReady: extensionReady,
    nativeAvailable: nativeAvailable,
    appStatus: appStatus,
    lastNativeResponse: lastNativeResponse,
  };
}

// ── Extension Lifecycle ────────────────────────────────────────────────────

browser.runtime.onInstalled.addListener(async () => {
  console.log("[Rig Relay Companion] Extension installed/updated.");
  extensionReady = true;
  nativeAvailable = null;
  appStatus = "idle";
  await persistState();
});

// ── Message Listener ───────────────────────────────────────────────────────

browser.runtime.onMessage.addListener((request, sender, sendResponse) => {
  // Validate: all messages must have a type field
  if (!request || typeof request !== "object" || !request.type) {
    sendResponse({ error: "invalid_message", message: "Message must contain a 'type' field." });
    return false;
  }

  (async () => {
    switch (request.type) {
      case "handoff_request": {
        const result = await handleHandoffRequest(request);
        sendResponse(result);
        break;
      }
      case "ping": {
        const result = await handlePing();
        sendResponse(result);
        break;
      }
      case "get_status": {
        const result = handleGetStatus();
        sendResponse(result);
        break;
      }
      default: {
        sendResponse({
          kind: "response.refused",
          payload: {
            message: "Unknown message type: " + request.type,
            refusal_reason: "invalid_message",
          },
        });
        break;
      }
    }
  })();

  // Return true to indicate async sendResponse
  return true;
});

// ── Native Message Listener ────────────────────────────────────────────────
// Safari delivers native app responses via browser.runtime.onMessageExternal
// for the extension's own native messaging host. When the native app sends a
// message back asynchronously, it arrives here.

browser.runtime.onMessageExternal?.addListener?.((message, sender) => {
  if (!message) return;
  handleNativeResponse(message);
});

// ── Startup ────────────────────────────────────────────────────────────────

loadState();
console.log("[Rig Relay Companion] Background service worker started.");

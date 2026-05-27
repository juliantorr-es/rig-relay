"use strict";

// ── Constants ──────────────────────────────────────────────────────────────

/** Query parameter names that indicate credential leakage. */
const CREDENTIAL_PARAMS = [
  "access_token", "token", "client_secret", "api_key", "private_token",
  "client_id", "code", "state", "id_token", "refresh_token",
];

/** Page kind classification based on URL pathname segments. */
const PAGE_KIND_RULES = [
  { segments: ["pull"], kind: "pull_request" },
  { segments: ["issues"], kind: "issue" },
  { segments: ["actions"], kind: "repository_actions" },
  { segments: ["settings", "pages"], kind: "repository_pages" },
  { segments: ["settings"], kind: "repository_settings" },
  { segments: ["projects"], kind: "repository_projects" },
  { segments: ["wiki"], kind: "repository_wiki" },
  { segments: ["security"], kind: "repository_security" },
  { segments: ["insights"], kind: "repository_insights" },
  { segments: ["code"], kind: "repository_code" },
];

// ── URL Safety & Extraction ────────────────────────────────────────────────

/**
 * Check whether a URL contains credential-like query parameters.
 * True means the URL is unsafe and should be rejected.
 */
function urlContainsCredentials(urlObj) {
  const params = urlObj.searchParams;
  for (const param of CREDENTIAL_PARAMS) {
    if (params.has(param)) return true;
  }
  // Also check for base64-encoded tokens in hash fragments
  const hash = urlObj.hash.toLowerCase();
  if (hash.includes("access_token") || hash.includes("id_token")) return true;
  return false;
}

/**
 * Extract the canonical repository URL: origin + pathname, no query, no hash.
 * Example: https://github.com/owner/repo/pull/42 becomes https://github.com/owner/repo
 */
function canonicalRepoURL(urlObj) {
  // Walk pathname to find owner/repo root segment
  const parts = urlObj.pathname.split("/").filter(Boolean);
  let canonical = urlObj.origin;
  if (parts.length >= 2) {
    canonical += "/" + parts[0] + "/" + parts[1];
  } else if (parts.length === 1) {
    canonical += "/" + parts[0];
  }
  return canonical;
}

/**
 * Return the minimal URL used in the handoff: origin + pathname.
 * Strips query strings and hash fragments entirely.
 */
function strippedPageURL(urlObj) {
  return urlObj.origin + urlObj.pathname;
}

// ── Page Kind Classification ───────────────────────────────────────────────

/**
 * Classify a GitHub page from its pathname segments.
 * Never inspects DOM, page text, or HTML.
 */
function classifyPageKind(parts) {
  // Organization profile: /orgname with no repo
  if (parts.length === 1) return "organization_profile";

  // Repository root: /owner/repo or /owner/repo/
  if (parts.length === 2) return "repository_main";

  // Sub-page classification
  for (const rule of PAGE_KIND_RULES) {
    const targetSegments = parts.slice(2, 2 + rule.segments.length);
    if (targetSegments.length === rule.segments.length) {
      let match = true;
      for (let i = 0; i < rule.segments.length; i++) {
        if (targetSegments[i] !== rule.segments[i]) {
          match = false;
          break;
        }
      }
      if (match) return rule.kind;
    }
  }

  // If path has more segments after owner/repo but no match, it's unknown
  if (parts.length > 2) return "unknown_github";

  return "repository_main";
}

/**
 * Extract an optional numeric ID from a path segment (PR number, issue number).
 * Returns null if segment is not a positive integer.
 */
function extractNumericID(segment) {
  if (!segment) return null;
  const num = parseInt(segment, 10);
  if (Number.isNaN(num) || num < 1) return null;
  return num;
}

// ── GitHub Page Context Builder ────────────────────────────────────────────

/**
 * Build a GitHubPageContext from window.location.
 * Never scrapes DOM, page text, file contents, or any HTML.
 * Returns null if the URL is unsafe or not a GitHub repository page.
 */
function buildGitHubPageContext() {
  try {
    const urlObj = new URL(window.location.href);

    // Defense-in-depth: reject URLs with credential-like parameters
    if (urlContainsCredentials(urlObj)) {
      console.warn("[Rig Relay Companion] URL contains credential-like parameters. Refusing to parse.");
      return null;
    }

    // Verify we are on github.com (defense-in-depth)
    if (!urlObj.hostname.endsWith("github.com") && urlObj.hostname !== "github.com") {
      return null;
    }

    const parts = urlObj.pathname.split("/").filter(Boolean);

    // Need at least an owner to classify
    if (parts.length === 0) return null;

    const owner = parts[0] || null;
    const repo = parts[1] || null;
    const pageKind = classifyPageKind(parts);

    // Extract PR or issue number from URL segments when applicable
    let prNumber = null;
    let issueNumber = null;

    if (pageKind === "pull_request" && parts.length >= 4) {
      prNumber = extractNumericID(parts[3]);
    }
    if (pageKind === "issue" && parts.length >= 4) {
      issueNumber = extractNumericID(parts[3]);
    }

    return {
      url: strippedPageURL(urlObj),
      canonicalRepoURL: canonicalRepoURL(urlObj),
      owner: owner,
      repo: repo,
      pageKind: pageKind,
      prNumber: prNumber,
      issueNumber: issueNumber,
    };
  } catch (err) {
    console.error("[Rig Relay Companion] Error building page context:", err);
    return null;
  }
}

// ── Page Context Cache ─────────────────────────────────────────────────────

let cachedPageContext = null;

/** Build and cache the page context once. */
function ensurePageContext() {
  if (cachedPageContext === null) {
    cachedPageContext = buildGitHubPageContext();
  }
  return cachedPageContext;
}

// ── Message Listener ───────────────────────────────────────────────────────

browser.runtime.onMessage.addListener((request, sender, sendResponse) => {
  if (!request || typeof request !== "object") {
    sendResponse(null);
    return false;
  }

  switch (request.type) {
    case "get_page_context": {
      const ctx = ensurePageContext();
      sendResponse(ctx);
      break;
    }
    case "refresh_page_context": {
      cachedPageContext = buildGitHubPageContext();
      sendResponse(cachedPageContext);
      break;
    }
    default: {
      sendResponse(null);
      break;
    }
  }

  // Synchronous responses only for content script
  return false;
});

// ── Initialization ─────────────────────────────────────────────────────────

(function init() {
  // Build context immediately on load
  ensurePageContext();

  // Ping background to check native app availability (fire-and-forget)
  browser.runtime.sendMessage({ type: "ping" }).catch(() => {
    // Silently ignore — native app may not be running
  });
})();

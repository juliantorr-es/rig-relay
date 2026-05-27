"use strict";

// ── DOM References ──────────────────────────────────────────────────────────

const repoStatusDot = document.getElementById("repo-status-dot");
const repoStatusText = document.getElementById("repo-status-text");
const repoStatusDetail = document.getElementById("repo-status-detail");

const appStatusDot = document.getElementById("app-status-dot");
const appStatusText = document.getElementById("app-status-text");
const appStatusDetail = document.getElementById("app-status-detail");

const actionsSection = document.getElementById("actions-section");
const btnOpen = document.getElementById("btn-open");
const btnStudy = document.getElementById("btn-study");
const btnStatus = document.getElementById("btn-status");

const responseSection = document.getElementById("response-section");
const responseText = document.getElementById("response-text");

// ── State ──────────────────────────────────────────────────────────────────

let currentPageContext = null;
let appAvailable = null; // null = not checked, true = available, false = unavailable

// ── Status Helpers ─────────────────────────────────────────────────────────

function setRepoStatus(state, detail) {
  repoStatusDot.className = "status-indicator";
  switch (state) {
    case "loading":
      repoStatusText.textContent = "Loading\u2026";
      repoStatusDot.classList.add("dot-orange");
      break;
    case "detected":
      repoStatusText.textContent = "Repository detected";
      repoStatusDot.classList.add("dot-green");
      break;
    case "no_context":
      repoStatusText.textContent = "No GitHub context";
      repoStatusDot.classList.add("dot-gray");
      break;
    case "unsafe_url":
      repoStatusText.textContent = "URL blocked";
      repoStatusDot.classList.add("dot-red");
      break;
    case "error":
      repoStatusText.textContent = "Detection error";
      repoStatusDot.classList.add("dot-red");
      break;
    default:
      repoStatusText.textContent = "Unknown";
      repoStatusDot.classList.add("dot-gray");
      break;
  }
  if (detail) {
    repoStatusDetail.textContent = detail;
    repoStatusDetail.hidden = false;
  } else {
    repoStatusDetail.hidden = true;
  }
}

function setAppStatus(state, detail) {
  appStatusDot.className = "status-indicator";
  switch (state) {
    case "connected":
      appStatusText.textContent = "Rig Relay connected";
      appStatusDot.classList.add("dot-green");
      break;
    case "connecting":
      appStatusText.textContent = "App connecting\u2026";
      appStatusDot.classList.add("dot-orange");
      break;
    case "unavailable":
      appStatusText.textContent = "App unavailable";
      appStatusDot.classList.add("dot-red");
      break;
    case "not_checked":
      appStatusText.textContent = "Not checked";
      appStatusDot.classList.add("dot-gray");
      break;
    case "app_not_running":
      appStatusText.textContent = "App not running";
      appStatusDot.classList.add("dot-red");
      break;
    default:
      appStatusText.textContent = "Unknown";
      appStatusDot.classList.add("dot-gray");
      break;
  }
  if (detail) {
    appStatusDetail.textContent = detail;
    appStatusDetail.hidden = false;
  } else {
    appStatusDetail.hidden = true;
  }
}

function setActionsEnabled(enabled) {
  btnOpen.disabled = !enabled;
  btnStudy.disabled = !enabled;
  btnStatus.disabled = !enabled;
}

function showResponse(text, isError) {
  responseText.textContent = text;
  responseText.className = isError ? "response-text response-error" : "response-text response-info";
  responseSection.hidden = false;
}

function hideResponse() {
  responseSection.hidden = true;
  responseText.textContent = "";
  responseText.className = "response-text";
}

// ── Content Script Query ───────────────────────────────────────────────────

async function queryPageContext() {
  try {
    const tabs = await browser.tabs.query({ active: true, currentWindow: true });
    if (!tabs || tabs.length === 0) {
      setRepoStatus("no_context", "Could not query active tab.");
      setActionsEnabled(false);
      return;
    }

    const tab = tabs[0];
    if (!tab.url || (!tab.url.includes("github.com"))) {
      setRepoStatus("no_context", "Not a GitHub page.");
      setActionsEnabled(false);
      return;
    }

    const response = await browser.tabs.sendMessage(tab.id, { type: "get_page_context" });

    if (!response || !response.url || !response.owner) {
      setRepoStatus("no_context", "Could not extract repository information.");
      setActionsEnabled(false);
      return;
    }

    currentPageContext = response;
    setRepoStatus("detected", response.owner + "/" + response.repo);
    setActionsEnabled(true);
  } catch (err) {
    console.error("[Rig Relay Companion] Error querying page context:", err);
    setRepoStatus("error", err.message || "Unknown error");
    setActionsEnabled(false);
  }
}

// ── App Status Query ───────────────────────────────────────────────────────

async function queryAppStatus() {
  setAppStatus("connecting");
  try {
    const response = await browser.runtime.sendMessage({ type: "get_status" });
    if (response && response.nativeAvailable === true) {
      appAvailable = true;
      setAppStatus("connected", response.appStatus || "Connected");
    } else if (response && response.nativeAvailable === false) {
      appAvailable = false;
      setAppStatus("unavailable", response.appStatus || "Not available");
    } else {
      appAvailable = null;
      setAppStatus("not_checked");
    }
  } catch (err) {
    console.error("[Rig Relay Companion] Error querying app status:", err);
    appAvailable = false;
    setAppStatus("unavailable", "Could not reach background script.");
  }
}

// ── Handoff Actions ────────────────────────────────────────────────────────

/**
 * Send a handoff request to the background script.
 * @param {string} intent - "open", "study", or "status"
 */
async function sendHandoff(intent) {
  if (!currentPageContext) {
    showResponse("No repository context available.", true);
    return;
  }

  hideResponse();
  const buttonMap = {
    open: btnOpen,
    study: btnStudy,
    status: btnStatus,
  };
  const button = buttonMap[intent];
  const originalText = button ? button.textContent : intent;

  if (button) {
    button.textContent = "Sending\u2026";
    button.disabled = true;
  }

  // Update the page context to include the user's intent trigger
  const handoffPayload = {
    url: currentPageContext.canonicalRepoURL || currentPageContext.url,
    owner: currentPageContext.owner,
    repo: currentPageContext.repo,
    pageKind: currentPageContext.pageKind,
    prNumber: currentPageContext.prNumber,
    issueNumber: currentPageContext.issueNumber,
    triggered_by: "popup_action",
  };

  try {
    const response = await browser.runtime.sendMessage({
      type: "handoff_request",
      payload: handoffPayload,
    });

    // Classify the native app response
    if (response && response.kind === "response.accepted") {
      showResponse(
        response.payload?.message || "Handoff accepted. Rig Relay is opening the repository.",
        false
      );
      appAvailable = true;
      setAppStatus("connected", response.payload?.repository_status || "Connected");
    } else if (response && response.kind === "response.deferred") {
      showResponse(
        response.payload?.message || "Handoff deferred: " + (response.payload?.deferral_reason || "unknown reason"),
        false
      );
      setAppStatus("connected", "Deferred: " + (response.payload?.deferral_reason || "unknown"));
    } else if (response && response.kind === "response.refused") {
      showResponse(
        response.payload?.message || "Handoff refused: " + (response.payload?.refusal_reason || "unknown reason"),
        true
      );
      setAppStatus("connected", "Refused: " + (response.payload?.refusal_reason || "unknown"));
    } else if (response && response.kind === "response.app_unavailable") {
      showResponse(
        response.payload?.message || "Rig Relay app is not running. Launch it first.",
        true
      );
      appAvailable = false;
      setAppStatus("app_not_running", response.payload?.reason || "App not running");
    } else {
      // Fallback: parse unstructured response
      if (response && response.nativeAvailable === false) {
        showResponse("Rig Relay app is not running.", true);
        appAvailable = false;
        setAppStatus("unavailable");
      } else if (response) {
        showResponse(JSON.stringify(response), false);
      } else {
        showResponse("No response from Rig Relay.", true);
      }
    }
  } catch (err) {
    console.error("[Rig Relay Companion] Handoff error:", err);
    showResponse("Error: " + (err.message || "Could not reach Rig Relay."), true);
    appAvailable = false;
    setAppStatus("unavailable", err.message || "Communication error");
  } finally {
    if (button) {
      button.textContent = originalText;
      button.disabled = !appAvailable;
    }
  }
}

// ── Event Listeners ────────────────────────────────────────────────────────

btnOpen.addEventListener("click", () => sendHandoff("open"));
btnStudy.addEventListener("click", () => sendHandoff("study"));
btnStatus.addEventListener("click", () => sendHandoff("status"));

// Listen for background script status updates while popup is open
browser.runtime.onMessage.addListener((message) => {
  if (message && message.type === "native_status_update") {
    if (message.nativeAvailable === true) {
      appAvailable = true;
      setAppStatus("connected", message.status || "Connected");
      setActionsEnabled(!!currentPageContext);
    } else {
      appAvailable = false;
      setAppStatus("unavailable", message.status || "Not available");
      setActionsEnabled(false);
    }
  }
});

// ── Initialization ─────────────────────────────────────────────────────────

(async function init() {
  setRepoStatus("loading");
  setActionsEnabled(false);

  // Query page context and app status in parallel
  await Promise.all([queryPageContext(), queryAppStatus()]);

  // After both queries resolve, update action button availability
  if (currentPageContext && appAvailable !== false) {
    setActionsEnabled(true);
  } else if (currentPageContext && appAvailable === false) {
    setActionsEnabled(false);
    showResponse("Rig Relay app is not running. Launch it and try again.", true);
  } else if (currentPageContext && appAvailable === null) {
    // Not checked yet — enable buttons so user can try
    setActionsEnabled(true);
  }
})();

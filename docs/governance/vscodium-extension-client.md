# Governance: VSCodium Extension Client

This document defines the governance boundaries and security invariants for the Rig Relay VSCodium extension.

## 1. Daemon Authority Boundary
The VSCodium extension is a **Content-Light Projector**. It does not possess authority to:
*   Perform direct file I/O on the project codebase.
*   Execute shell commands or scripts.
*   Authorize tool permissions or bypass tool gates.
*   Compile context or assemble LLM prompts.

All of the above responsibilities reside strictly within the **Rig Relay Daemon**.

## 2. Token Storage & Security
*   **SecretStorage**: Authentication tokens for the daemon are stored in VS Code's `SecretStorage` API, which leverages the OS keyring (macOS Keychain, Windows Credential Manager).
*   **Isolation**: Tokens are never stored in `settings.json`, environment variables, or extension-local storage.
*   **Discovery**: The `.rig/daemon/console.json` file is used for configuration discovery but **must never contain raw tokens**. It should only contain the connection metadata (host/port/session_id).

## 3. Protocol Versioning & Invariants
*   **Handshake**: Every connection requires a protocol version check. The client and server must agree on `rig.ws.v1`.
*   **Sequence Tracking**: The client maintains a `last_seen_seq` to ignore stale or out-of-order messages during reconnects.
*   **Idempotency**: All `delta` events carry a unique `event_id`. The client must deduplicate incoming events to ensure deterministic rendering.

## 4. Content-Light Invariant
To prevent sensitive data leakage into the editor's renderer process, the following data types are **strictly prohibited** from being sent to or rendered by the extension:
*   Raw `stdout` / `stderr` from tool executions.
*   Full file contents (unless explicitly requested for a Patch Review).
*   Unformatted `diff` or `patch` blobs.
*   Environment variables or secrets.

In the event of a protocol violation, the extension must render a `rig.ws.server.warning.v1` and refuse further interaction until corrected.

## 5. Webview Security
*   **CSP**: A strict Content Security Policy is applied to the Mission Control webview.
*   **Nonce**: All scripts are gated by a one-time nonce.
*   **Isolation**: The webview has no access to the local filesystem except through authorized `localResourceRoots` pointing to the extension's `media` directory.

## 6. Open VSX & Distribution
*   **Neutrality**: The extension targets VSCodium and is compatible with the Open VSX registry.
*   **Packaging**: The extension is bundled as a standalone `.vsix` that can be sideloaded without Microsoft Marketplace access.

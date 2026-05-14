# Audit: VSCodium Extension Feasibility Spike Results

## 1. Executive Summary: GO
The spike confirms that a standard VSCodium extension can serve as a high-fidelity, governed shell for Rig Relay. Connectivity is robust, the protocol is stable for remote projections, and the development model avoids the risks of an IDE fork.

## 2. Connectivity & Protocol
*   **WebSocket Bridge**: Successfully implemented a `ws` client in the extension host.
*   **Authentication**: Token-gated handshake works as expected.
*   **Idempotency**: Sequence tracking (`seq`) successfully filters stale messages during reconnects.
*   **Event Handling**: The `rig.ws.server.delta.v1` schema correctly updates the frontend without requiring a full re-snapshot.

## 3. Protocol Gaps Found
*   **Token Discovery**: The token currently must be manually copied. Future iterations should use a local discovery file (e.g. `~/.rig/relay/ws_discovery.json`) with restricted permissions.
*   **Binary Content**: The current protocol is JSON-only. While content-light projections avoid large payloads, very long reasoning streams may benefit from compression or chunking.

## 4. Packaging & Distribution
*   **Open VSX**: The extension uses standard VS Code APIs (v1.90) and is compatible with Open VSX.
*   **Sideloading**: Sideloading via VSIX is confirmed as a viable path for VSCodium users.
*   **Dependencies**: The `ws` library must be bundled. Recommend using `esbuild` or `webpack` for final packaging to minimize the VSIX size.

## 5. ChatGPT macOS "Work with Apps" Compatibility
*   **Standard Binary**: By using a standard VSCodium extension rather than a fork, we remain compatible with OpenAI's macOS accessibility hooks.
*   **Context Visibility**: ChatGPT can "see" the Rig side-panel because it is a standard Webview. This is a product advantage (collaborative agents) rather than a risk, provided governance remains in the daemon.

## 6. Security Posture
*   **Safe-by-Design**: The extension never performs file I/O or shell execution. It acts strictly as a display for the daemon's projections.
*   **Raw Data Isolation**: The spike successfully maintained the content-light boundary. Raw stdout/stderr never left the daemon.

## 7. MVP Hardening Results (Current Status)
The feasibility spike has been hardened into a product-ready MVP architecture:
*   **Secure Token Storage**: Switched from standard settings to `SecretStorage` to prevent token leakage in `settings.json`.
*   **Theme Integration**: The UI now dynamically adapts to VS Code's Light, Dark, and High Contrast themes using native CSS variables.
*   **Protocol Negotiation**: Handshake now includes `client_protocol_version` and compatibility checks.
*   **Webview Security**: Implemented strict CSP and nonces; Webview is restricted to the extension's local resource roots.
*   **Daemon Discovery**: Support for `.rig/daemon/console.json` enables zero-config connection for project-specific daemons.

## 8. Remaining Risks
*   **Worktree Lane Sync**: Ensuring the editor accurately reflects the agent's worktree lane without confusing the developer.
*   **Marketplace Friction**: Managing sideloading/distribution for VSCodium users who lack access to the Microsoft Marketplace.

## 9. Final Verdict: PROCEED TO GOVERNANCE HARDENING
The MVP client is stable. The next phase should focus on the **Evidence Rail** (Tree View for receipts) and **Governed Patch Review**.

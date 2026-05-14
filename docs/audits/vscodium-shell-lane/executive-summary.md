# Executive Summary: VSCodium Shell Lane for Rig Relay

## 1. Verdict: GO (Extension-First)
The audit recommends proceeding with the **VSCodium Shell Lane** using an **Extension-First** strategy. VSCodium is a viable, governed editor shell that aligns with Rig's "governance-first" posture while offloading the heavy editor maintenance burden.

## 2. Recommendation: Extension-First
Do not start with a custom branded distribution. Build a high-quality VSCodium extension that connects to a local Rig Relay daemon. This maximizes compatibility with the existing VS Code ecosystem (Open VSX) and ensures immediate compatibility with the ChatGPT macOS "Work with Apps" feature.

## 3. Estimated Effort
*   **Phase 1-3 (MVP):** 3-5 weeks (Skeleton, Daemon bridge, Prompt turns).
*   **Phase 4-6 (Governed Workbench):** 4-6 weeks (Receipts, Patches, Worktrees).
*   **Total for Dogfood:** ~2 months.

## 4. Primary Risks
| Risk Type | Description |
| :--- | :--- |
| **Technical** | Maintaining local WebSocket/IPC security between the extension and the daemon. |
| **Product** | "Clutter-rot": The VS Code UI is dense; Rig must remain content-light and distinct from generic "AI chat" sidebars. |
| **Security** | Extension supply chain: Rig's governance must protect the user even if other extensions are malicious. |

## 5. Minimum Viable Dogfood (MVD)
A VSCodium environment where an operator can:
1.  Open a workspace.
2.  Type a prompt in a Rig side-panel.
3.  Observe agent tool calls (Bash, Read, etc.) in a content-light stream.
4.  Approve/Reject changes via a Patch Review surface.
5.  Inspect Evidence Receipts for all actions within the editor.

## 6. Key Conclusions
1.  **VSCodium is the correct shell**: It removes Microsoft telemetry/marketplace constraints while keeping the extension API.
2.  **Daemon is the source of truth**: Governance, tools, and execution *must* stay in the Python daemon. The extension is purely a projection/input surface.
3.  **Governance as the Wedge**: Unlike Cursor or Aider, Rig wins on verifiable evidence and worktree safety, not on IDE features.

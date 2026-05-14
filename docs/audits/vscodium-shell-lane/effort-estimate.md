# Effort Estimate: VSCodium Shell Lane

This phase plan outlines the path to a testable, governed agent workbench.

| Phase | Goal | Files Touched/Created | Complexity | Exit Criteria |
| :--- | :--- | :--- | :--- | :--- |
| **0: Audit** | Closure / decision gate. | `docs/audits/vscodium-shell-lane/` | S | Audit approved by stakeholders. |
| **1: Skeleton** | Extension boilerplate. | `extension/`, `package.json` | S | Extension installs and shows sidebar. |
| **2: Bridge** | Daemon connection. | `vibe/cli/extension_daemon.py`, `extension/src/daemon_client.ts` | M | Handshake complete; token auth working. |
| **3: Turn** | Prompt turn bridge. | `vibe/cli/webview_console/backend.py` (updates) | M | "Hello World" prompt returns agent text. |
| **4: Evidence** | Receipts + Validation. | `rig_relay/evidence/`, `extension/src/views/receipts.ts` | L | Receipt tree view populated from daemon. |
| **5: Patch** | Patch governance. | `rig_relay/coordination/patch_proposal.py`, `extension/src/patch_review.ts` | L | Native diff view opens on proposed changes. |
| **6: Lanes** | Worktree management. | `rig_relay/coordination/worktree_manager.py` | XL | Agents operate in isolated worktree "lanes". |
| **7: Bundle** | Branded VSCodium app. | `scripts/build_vscodium_bundle.sh` | XL | (Optional) Signed macOS binary available. |

## Dependencies
1.  **VSCodium**: Extension host API (v1.90+ recommended).
2.  **Node.js**: For extension development.
3.  **Python 3.12+**: For the Rig Relay daemon.

## Key Risks to Schedule
*   **Worktree Complexity**: Managing git state across multiple lanes without corrupting the user's main working copy is the highest technical risk.
*   **VS Code API Stability**: Relying on proposed APIs (if needed) can break the extension on minor updates.
*   **Mac OS Notarization**: If we pivot to Option B (Bundled App), signing will add weeks of friction.

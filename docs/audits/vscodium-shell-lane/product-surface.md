# Product Surface: Rig MVP for VSCodium

This document defines the user experience and visual components of the Rig Relay extension.

## 1. Primary Surfaces

### A. The "Mission Control" Sidebar (Webview View)
*   **Chat Interface**: Minimalist prompt input and response stream.
*   **Turn Status**: Visual indicator of the current agent turn (Thinking, Running Tool, Waiting for Approval).
*   **Context Indicator**: Compact list of files currently being used as context (with "remove" buttons).

### B. The "Evidence Rail" (Tree View)
*   List of recent sessions and their associated receipts.
*   Clicking a receipt opens a custom "Receipt Viewer" (read-only document) showing the rationale and verifiable evidence.

### C. The "Governance Bar" (Status Bar)
*   Current Rig status (Ready, Active, Blocked).
*   Workspace lane indicator (e.g., "Lane: main" or "Lane: rig-patch-001").

### D. The "Patch Review" Surface (Native Diff View)
*   When an agent proposes a change, Rig triggers a native VSCodium Diff view.
*   Floating "Approve" / "Reject" buttons inside the diff surface or as a notification toast.

## 2. Competitive Positioning

| Feature | Like Antigravity / Cursor | Unlike Antigravity (The Rig Wedge) |
| :--- | :--- | :--- |
| **Inline Edit** | Yes, via diff view. | Always governed; requires approval by default. |
| **Context** | Yes, auto-detects files. | Verifiable: Every byte of context is recorded in a receipt. |
| **Tools** | Yes, runs bash/ls. | Deterministic: Tools are hardened and permissioned. |
| **Workspace** | Yes, uses project root. | Lane-based: Heavy use of worktrees to isolate agent noise. |

## 3. Minimum Visibility Rules
*   **Default Visible**: Mission Control Sidebar, Governance Bar.
*   **Hidden behind commands**: Full Receipt Browser, Debug logs, Configuration.
*   **Do Not Build Yet**: AI-driven file tree manipulation, generic multi-agent chat, auto-commit.

## 4. Design Aesthetics
*   **Phosphor Monochrome**: Use the green-phosphor palette for the Webview components to maintain the Rig brand identity.
*   **Bauhaus Functional**: Avoid "glass" or "glow" effects in the editor; stick to sharp, functional, high-contrast layouts that match VSCodium's native feel.

# VSCodium Extension API Study

This document identifies the specific VS Code / VSCodium APIs required to implement the Rig Relay shell lane.

## 1. Required for MVP

| API Area | Purpose | Rig Use Case | Host/Daemon | Security Concern |
| :--- | :--- | :--- | :--- | :--- |
| **Webview View** | Custom UI panels. | Side-panel for agent chat, turn status, and receipts. | Extension Host | XSS within the webview. |
| **Status Bar API** | Global status indicators. | Displaying "Agent Running", "Blocked", or "Validation Pending". | Extension Host | None. |
| **Workspace API** | File/Folder discovery. | Detecting open files for context compilation. | Extension Host | Potential leakage of file names. |
| **Commands API** | User actions. | Keybindings for "Start Turn", "Approve Patch", "Clear Input". | Extension Host | Command injection if not sanitized. |
| **SecretStorage API** | Safe credential storage. | Storing daemon tokens and API keys. | Extension Host | Leakage to other extensions. |
| **Terminal API** | Embedded terminal. | Optional view of the raw Rig Relay daemon logs. | Extension Host | Arbitrary shell execution. |

## 2. Useful after MVP

| API Area | Purpose | Rig Use Case | Host/Daemon | Security Concern |
| :--- | :--- | :--- | :--- | :--- |
| **Tree View API** | Hierarchical lists. | Detailed evidence receipt browser and fleet status. | Extension Host | Low. |
| **Custom Editor API** | Custom file views. | Governed "Receipt Files" or "Mission Journals". | Extension Host | None. |
| **FileSystemProvider** | Virtual file system. | Projecting "Mission Worktrees" without actual git checkouts. | Extension Host | High complexity; safety. |
| **Diagnostics API** | Editor linting/errors. | Showing "Validation Errors" directly on the code lines. | Extension Host | False positives from agents. |

## 3. Dangerous / Defer

| API Area | Purpose | Rig Use Case | Rationale for Deferral |
| :--- | :--- | :--- | :--- |
| **Task API** | Running build/test tasks. | Executing validations. | Defer to daemon tools for governance. |
| **Authentication API** | Third-party auth. | GitHub/Mistral login. | Keep in daemon for token isolation. |
| **Integrated Terminal Write** | Injecting text into shell. | Auto-running commands. | Too risky; bypasses tool permissions. |

## 4. Test Strategy
*   **Extension Host Unit Tests**: Use `vscode-test` to mock workspace and commands.
*   **Integration Tests**: Scripted VSCodium instances connecting to a real `rig-relay` daemon.
*   **Shadow Projections**: Compare the extension's view of a turn with the daemon's internal `CodingSessionSnapshot` to ensure no data leakage.

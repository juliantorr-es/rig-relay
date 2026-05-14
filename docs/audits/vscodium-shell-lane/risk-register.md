# Risk Register: VSCodium Shell Lane

This register tracks the critical risks identified during the VSCodium shell lane audit.

| Risk ID | Risk Name | Severity | Likelihood | Mitigation | Owner |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **R-001** | Open VSX Availability | Medium | High | Support sideloading from VSIX; maintain an official Rig VSIX download. | Product |
| **R-002** | Extension Supply-Chain | High | Low | Rig daemon treats all editor-provided data as untrusted; strict validation of patches. | Governance |
| **R-003** | Local WebSocket Hijacking | High | Medium | Use random ports; token-based authentication; 127.0.0.1 binding only. | Security |
| **R-004** | Confused Deputy (Editor) | High | Medium | Do not expose "Run in Terminal" commands to the extension without human-in-the-loop. | Tooling |
| **R-005** | Prompt Injection (Files) | Medium | High | Use the Rig `ContextCompiler` to scrub/filter context before LLM submission. | Context |
| **R-006** | Worktree Corruption | High | Low | Use isolated `git worktree` lanes; enforce `DirtyGuard` on all project paths. | Coordination |
| **R-007** | Custom Shell Maintenance | High | Medium | Avoid Option B (Custom Bundle) unless absolutely necessary. Stick to Extension-First. | Engineering |
| **R-008** | "Spyware" Perception | Medium | Medium | Local-only processing; clear visual receipts; no cloud-sync of code by default. | Brand |
| **R-009** | ChatGPT Compatibility Drift | Medium | Low | Use standard VSCodium paths; avoid renaming the binary or altering the macOS bundle ID. | Product |

## MVP Blockers
*   **R-003 (WebSocket Security)**: Must be solved before the first dogfood.
*   **R-006 (Worktree Safety)**: Basic worktree isolation is required to prevent accidental data loss.
*   **R-002 (Supply-Chain)**: Basic patch review governance must be in place.

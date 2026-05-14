# Final Recommendation: VSCodium Shell Lane

## 1. Recommendation: BUILD NOW
The VSCodium Shell Lane is the most logical evolution for Rig Relay as it transforms into a "workbench". It leverages a world-class editor shell while keeping the governance logic isolated in the Rig daemon.

## 2. Strategy: Extension-First
*   **Architecture**: Option A (Extension-only control plane).
*   **Platform**: Target VSCodium on macOS/Linux/Windows.
*   **Marketplace**: Publish to Open VSX; provide direct VSIX downloads.

## 3. First 3 Agent Missions
1.  **Mission: Skeleton Bridge**: Implement the WebSocket handshake and sidebar activation.
2.  **Mission: Prompt Sync**: Connect the sidebar chat to the `AgentLoop` turns.
3.  **Mission: Patch Review**: Implement the transition from a tool-generated `PatchProposal` to a native VSCodium Diff View.

## 4. Exit Criteria for abandoning pywebview/Textual
Do not kill the Textual or pywebview consoles until the VSCodium extension can:
1.  Successfully execute a "Bash" turn with human approval.
2.  Correctly project a multi-item evidence receipt in a side panel.
3.  Maintain a stable daemon connection for 4+ hours of active coding.

## 5. What must be proven before a Branded Bundle
Only graduate to a branded VSCodium bundle (Option B) if:
1.  Users report extreme friction with manual VSIX installation in VSCodium.
2.  The product requires deep integration that the Extension API cannot provide (e.g., custom UI in the editor gutter or tab bar).
3.  We have the engineering capacity to maintain a fork of a major IDE.

## 6. Closing Thought
Rig's strength is **verifiable governance**. VSCodium provides the **surface area** to make that governance comfortable. By building the extension first, we deliver the most value with the least risk.

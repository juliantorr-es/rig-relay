# ChatGPT macOS Compatibility Audit

This document assesses the interaction between the Rig Relay VSCodium lane and the ChatGPT macOS "Work with Apps" feature.

## 1. Interaction Model
ChatGPT's "Work with Apps" on macOS works via:
1.  **Accessibility API**: Reading the active window's UI hierarchy.
2.  **VS Code Extension**: A proprietary `.vsix` that OpenAI provides to deeper editor state.

## 2. Rig Extension Interaction
*   **Context Visibility**: ChatGPT will likely see the code in the active editor tab. It will **not** see the internal state of the Rig daemon or hidden worktree lanes unless they are opened as tabs.
*   **Conflict of Interest**: If both Rig and ChatGPT are active, the user has two "agents" in one editor. Rig should position itself as the **Governed Authority**, while ChatGPT is the **Creative Assistant**.

## 3. Risks of Branded Bundle (Option B)
*   **Accessibility White-listing**: If we rename the binary (e.g., from `VSCodium` to `Rig Studio`), we may lose the pre-configured "Work with Apps" support in the ChatGPT app until OpenAI adds our new bundle ID.
*   **Recommendation**: Stick to standard VSCodium binary to maintain maximum compatibility with OpenAI's macOS ecosystem.

## 4. Manual Test Checklist (macOS)
- [ ] Install VSCodium.
- [ ] Install `openai-chatgpt.vsix` manually.
- [ ] Verify ChatGPT "Work with Apps" shows VSCodium in the list.
- [ ] Open a file in VSCodium.
- [ ] Ask ChatGPT: "What is the content of my open file?" (Verify accessibility read).
- [ ] Install Rig Relay extension (prototype).
- [ ] Open a Rig Mission Worktree.
- [ ] Verify ChatGPT can see the worktree file.
- [ ] Verify ChatGPT **cannot** see raw Rig tool logs in the terminal unless the terminal is visible.

## 5. Conclusion: Safer in the Stream
Ordinary VSCodium + the Rig Extension is the **safest** path for maintaining ecosystem compatibility. Branded bundles introduce high friction for cross-app AI features.

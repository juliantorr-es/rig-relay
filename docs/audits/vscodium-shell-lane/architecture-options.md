# Architecture Options: VSCodium Shell Lane

We evaluated three architectural approaches for integrating Rig Relay with VSCodium.

## Option A: Extension-only Control Plane (Recommended)
**Model:** User installs the standard VSCodium and adds the Rig Relay extension.
*   **Pros:**
    *   Fastest path to dogfooding.
    *   Zero maintenance of the editor binary.
    *   Immediate compatibility with ChatGPT macOS "Work with Apps".
    *   Least resistance for users who already have a preferred editor setup.
*   **Cons:**
    *   Harder to "WOW" with a completely bespoke branded experience.
    *   User must manually install the extension (VSIX on VSCodium).
*   **Security:** Extension host isolation; standard local WebSocket security.

## Option B: Branded VSCodium Distribution
**Model:** A custom-built VSCodium binary (e.g., "Rig Studio") with the extension pre-bundled and branding applied.
*   **Pros:**
    *   Maximum product polish and "premium" feel.
    *   Can customize `product.json` to include proprietary APIs or marketplaces.
*   **Cons:**
    *   Extremely high maintenance (upstream merges, CI/CD for binaries).
    *   Signing and notarization on macOS is a significant hurdle.
    *   Might be flagged as "another AI IDE" clone.
*   **Security:** Harder to audit the base binary for telemetry/branding changes.

## Option C: Hybrid pywebview + VSCodium
**Model:** Use the existing `pywebview` cockpit for mission control/chat, but communicate with a thin VSCodium extension purely for "Go to File" or "Apply Patch" actions.
*   **Pros:**
    *   Reuses all current frontend investment.
    *   Keeps "Control" and "Code" strictly separated visually.
*   **Cons:**
    *   Fragmented UX (switching windows constantly).
    *   Double the surface area for connections.
*   **Security:** Most complex auth model (app <-> daemon <-> extension).

## Recommendation: Option A (Start with Extension)
Start with **Option A**. It allows us to prove the governance value of Rig Relay without getting bogged down in editor distribution mechanics. If the extension becomes indispensable, we can graduate to **Option B** (Branded Bundle) later for specific high-trust corporate environments.

### Why not Option C?
Rig should feel like a "workbench", not a satellite. Integrating the prompt and evidence rails directly into the side-panel of the editor (Option A) provides a much tighter iteration loop for the developer.

# Textual TUI Retirement Policy

## Status

**Established.** The Textual TUI is a legacy/deprecated product UI, but it
remains an active development compatibility surface until Relay CLI and the
pywebview cockpit reach operational parity.

### Lifecycle States

| State | Meaning |
|---|---|
| `active-dev-compatibility` | Used by developers today; compatible fixes allowed; not the future product UI |
| `deprecated-product-ui` | Explicitly not the future product UI; new product-only features do not target it |
| `delete-candidate` | Potential removal target once parity is proven and no users need it for development |
| `removed` | No longer present |

Current state:

- Textual TUI: `active-dev-compatibility`
- Textual TUI: `deprecated-product-ui`

## Core Policy

### Textual TUI Is Legacy

The `vibe/cli/` Textual TUI (legacy_tui mode) is retained as a compatibility
surface for SSH, headless diagnostics, and development environments where the
Relay cockpit or Relay CLI are not sufficient yet. It is **not** the primary
product UI.

- **No new product features should target the Textual TUI.**
- Compatibility fixes are allowed when they preserve current development
  workflow.
- No new widget, intent, or visual component should be developed for Textual.
- Bug fixes and critical security patches for existing Textual code are
  acceptable during the alpha period to maintain compatibility.

### Primary Desktop Surface

The **pywebview desktop cockpit** (`frontend/desktop/`) is the future primary
local human UX. All new cockpit features, widgets, and visual refinements
target the HTML/CSS/JS frontend rendered by pywebview.

### Relay CLI Is Canonical For Scriptable Workflows

Relay CLI is the canonical scriptable surface for status, validation,
refinement, provider, consent, telemetry bundle, and storage workflows.
Textual is not the long-term product surface, but it stays available while the
Relay CLI and cockpit finish reaching operational parity.

### CLI Remains for Automation

The CLI interface (`bash`, scripting, CI, automation workers) remains
supported for headless/automation use cases. The CLI is not a replacement
for the desktop cockpit; it is a separate interface for non-interactive
workflows.

### Textual Deletion Criteria

The Textual TUI may be removed when all of the following are true:

1. Relay CLI can run status, validation, refinement report, refinement
   packets, storage audit, provider status, consent status, telemetry bundle
   create/validate.
2. The pywebview cockpit can run safe intents reliably.
3. Progress timeline works in the cockpit.
4. Provider, consent, and identity setup are visible in the product surface.
5. Tests cover the replacement surfaces.
6. The user confirms the Textual workflow is no longer needed for development.
7. Removing Textual would not break packaging or compatibility entry points.

Until these criteria are met, the Textual TUI remains as a compat shim.

## Migration Status

| Area | Status |
|---|---|
| pywebview cockpit IA | ✅ Three-mode (Operate/Review/System) |
| Safe intents (read-only) | ✅ Implemented |
| Protected intents | ✅ Receipt-gated |
| Provider onboarding | ✅ Desktop-only (pywebview) |
| Progress timeline | ✅ Desktop-only (WebSocket) |
| Consent management | ✅ Desktop-only |
| Model observation dataset | ✅ Desktop-only (schemas/models) |
| Textual-equivalent validation view | ✅ Review mode |
| Textual-equivalent system view | ✅ System mode |
| Textual shell commands | ⏳ CLI/scripting workaround |
| Textual development compatibility | ✅ Active until parity |

## Cross-References

- [Rig + Intake Cannibalization Plan](../audits/rig-intake-cannibalization-plan.md)
- [Desktop Cockpit UI](desktop-cockpit-ui.md)
- [Vibe Legacy Deprecation](vibe-legacy-deprecation.md)
- [Relay Surface Matrix](relay-surface-matrix.md)
- [Desktop Projection Contract](relay-desktop-projection-contract.md)

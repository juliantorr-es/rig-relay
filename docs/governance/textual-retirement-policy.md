# Textual TUI Retirement Policy

## Status

**Established.** The Textual TUI is a legacy/deprecated interface. The
pywebview desktop cockpit is the primary desktop surface for Rig Relay.

## Core Policy

### Textual TUI Is Legacy

The `vibe/cli/` Textual TUI (legacy_tui mode) is retained as a compatibility
fallback for SSH, headless diagnostics, and development environments where
pywebview is unavailable. It is **not** the primary product UI.

- **No new product features should target the Textual TUI.**
- No new widget, intent, or visual component should be developed for Textual.
- Bug fixes and critical security patches for existing Textual code are
  acceptable during the alpha period to maintain compatibility.

### Primary Desktop Surface

The **pywebview desktop cockpit** (`frontend/desktop/`) is the primary local
human UX. All new cockpit features, widgets, and visual refinements target
the HTML/CSS/JS frontend rendered by pywebview.

### CLI Remains for Automation

The CLI interface (`bash`, scripting, CI, automation workers) remains
supported for headless/automation use cases. The CLI is not a replacement
for the desktop cockpit; it is a separate interface for non-interactive
workflows.

### Textual Deletion Criteria

The Textual TUI may be removed when all of the following are true:

1. The pywebview desktop cockpit supports all workflows that Textual
   currently supports for local interactive use.
2. A headless fallback (e.g., CLI output, static projection dump) covers
   the SSH/diagnostics use case.
3. No alpha user reports Textual-dependent workflows.
4. Textual dependency (`vibe/cli/`) can be removed without breaking the
   packaging or CLI entry points.

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

## Cross-References

- [Rig + Intake Cannibalization Plan](../audits/rig-intake-cannibalization-plan.md)
- [Desktop Cockpit UI](desktop-cockpit-ui.md)
- [Vibe Legacy Deprecation](vibe-legacy-deprecation.md)
- [Desktop Projection Contract](relay-desktop-projection-contract.md)

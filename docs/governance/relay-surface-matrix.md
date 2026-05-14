# Relay Surface Matrix

## Status

**Draft.** Defines which user-facing surfaces are primary, transitional, or
legacy-compatible during the alpha period.

## Surface Matrix

| Surface | Intended Audience | Current Status | Allowed Changes | Forbidden Changes | Retirement Criteria |
|---|---|---|---|---|---|
| Textual TUI | Developers, SSH sessions, compatibility workflows | `active-dev-compatibility` + `deprecated-product-ui` | Compatibility fixes, diagnostics, deprecation messaging | New product-only features, product repositioning, deletion before parity | Delete only after Relay CLI + pywebview parity and explicit user confirmation |
| Relay CLI | Scriptable users, automation, reviewers, operators | Canonical scriptable surface | Status, validation, refinement, provider, consent, telemetry, storage workflows | Protected execution buttons, raw-content export, silent regressions to Vibe branding | Remains canonical while product matures; retire only if superseded by a new canonical automation surface |
| pywebview cockpit | Interactive operators, demo flows, product UX | Primary visual alpha/product surface | Safe intents, progress timeline, provider/identity/consent views, read-only projections | Protected execution buttons, noisy motion, raw evidence exposure | Remains primary until a later product surface replaces it deliberately |
| scripts | Maintainers, debug, release engineering | Low-level/dev escape hatches | Validation, bundle creation, projection generation, storage audits, release helpers | User-facing rebranding as primary UI, protected execution controls | Keep as developer tools; retire only if fully absorbed by higher-level Relay surfaces |
| vibe/core | Legacy substrate and adapters | Compatibility substrate | Adapter maintenance, quarantine, focused migration, test support | New product identity, new user-facing flows, opportunistic rewrites | Retire only after all dependent surfaces are moved and compatibility is no longer needed |

## Policy Notes

- Textual is retained because it still supports current development workflows.
- Relay CLI is the canonical scriptable surface, not Textual.
- pywebview is the future product UI, but it must remain safe and operational
  before any Textual deletion is considered.
- `vibe/core` may remain as a compatibility substrate while Relay-native seams finish maturing.

## Cross-References

- [Textual TUI Retirement Policy](textual-retirement-policy.md)
- [Vibe Legacy Deprecation Doctrine](vibe-legacy-deprecation.md)
- [Vibe Legacy Boundary Inventory](../audits/vibe-legacy-boundary-inventory.md)

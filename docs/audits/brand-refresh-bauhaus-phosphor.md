# Rig Relay Brand Refresh Audit

## Scope

This audit covers the current provider-branded identity surfaces in Rig Relay and recommends a provider-neutral brand direction built around Bauhaus structure, green phosphor terminal nostalgia, and restrained motion.

## Current Branding References

- `README.md` still describes Rig Relay as a standalone fork of Mistral Vibe and repeats legacy upstream references in the install, update, and license sections.
- `vibe/setup/onboarding/screens/welcome.py` uses a colorful animated welcome line and still reads as an onboarding splash rather than a product identity.
- `vibe/setup/onboarding/screens/api_key.py` refers to Vibe in the configuration docs label and still names provider-specific help in a way that puts the provider ahead of the product.
- `vibe/setup/onboarding/__init__.py` prints legacy `vibe` instructions after successful setup.
- `vibe/cli/textual_ui/widgets/banner/banner.py` shows the product name correctly, but the left-side mascot animation is still a legacy visual identity and reads as upstream carryover.
- `vibe/cli/textual_ui/app.tcss` still carries a legacy orange accent token and uses a generic terminal palette rather than a Rig Relay-specific visual system.
- `docs/dogfood/rig-relay-self-dogfood.md` is product-neutral in intent, but the wording still assumes a plain harness rather than a branded local control plane.
- `action.yml`, `flake.nix`, and several docs headers still mention upstream provenance and should be reviewed for any product-facing wording that implies the old brand is still the identity.

## User-Facing Surfaces

- First-run welcome screen.
- Provider key setup screen.
- Main CLI banner.
- Setup completion and error messages.
- README install/configuration copy.
- E2E and onboarding tests that assert exact text.

## UI Surfaces Eligible For Polish

- Banner header and mascot area.
- Welcome screen title treatment.
- Onboarding API-key screen copy.
- Shared Textual color tokens.
- Small motion surfaces such as boot pulse, scanline, or status shimmer.

## Risk List

- Copy changes can break snapshot tests and e2e assertions.
- README changes can drift from packaging or install-script expectations if command names are not updated together.
- Provider-specific help labels can regress if the provider key flow is generalized too aggressively.
- Animation changes can destabilize snapshots if timestamps or frame-dependent rendering leak into tests.
- CSS token changes can reduce contrast if phosphor greens are used as body text instead of accents.

## Recommended Direction

- Make Rig Relay the primary identity everywhere user-facing.
- Treat providers as interchangeable backends, not as product brands.
- Use a Bauhaus-style hierarchy: compact grid, strong alignment, functional labels, geometric restraint.
- Use phosphor green as signal, not floodlight: dark background, green highlights, amber warnings, cream support text, sparing red failure accents.
- Keep animation tiny and decorative: pulse, scanline, or seal effects only where already supported.
- Keep evidence-first language visible: manifest, receipt, session, tool, doctor, and determinism should remain legible in the UI.

## Backlog

- Replace any remaining legacy Vibe text in docs that is still shown to users.
- Review the startup ASCII/banner treatment for a compact Rig Relay mark that does not depend on provider mascots.
- Audit screenshots and snapshots for upstream carryover after copy updates.

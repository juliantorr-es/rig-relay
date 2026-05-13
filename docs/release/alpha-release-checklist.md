# Alpha Release Checklist

## Status

**Draft.** Release-like alpha readiness checklist for Rig Relay.

## Foundation Checks

- `uv sync --all-extras` completes on a clean checkout
- `uv run python scripts/rig_relay_validate_schemas.py` passes
- `uv run python scripts/rig_relay_desktop_cockpit.py --dry-run` passes
- `uv run pytest -n0 tests/frontend/test_no_inner_html_for_untrusted_fields.mjs` passes when present
- `uv run pytest -n0 tests/test_model_observations.py tests/evidence/test_redaction.py` passes if observation flow changed
- `uv run pytest -n0 tests/providers/test_providers.py tests/scripts/test_desktop_projection.py` passes if provider flow changed
- `uv run pytest -n0 tests/test_telemetry_consent.py tests/scripts/test_identity_providers.py` passes if identity or consent changed
- `uv run pytest -n0 tests/scripts/test_desktop_intents.py tests/scripts/test_progress_events.py tests/scripts/test_websocket_server.py` passes if desktop intent or progress flow changed

## Launch Checks

- Cockpit opens in `Operate`, `Review`, and `System` modes
- No protected execution buttons are present
- Provider onboarding is local-only and content-light
- Consent toggles remain separate from identity
- Progress timeline and review mode render without raw prompts, raw outputs, diffs, secrets, or stdout/stderr bodies
- Demo fixtures validate
- Dry-run mode works without network or key material

## Security Checks

- No `innerHTML` path renders untrusted content
- No raw secrets appear in telemetry, audit, or frontend storage
- No upload path is enabled by default
- No protected actions are exposed to the frontend
- Remote-facing data remains content-light and redacted

## Artifact Policy

- Keep `.build/` out of tracked source unless a file is an explicit doc fixture
- Keep generated bundles, session state, coordination state, and projections out of release commits
- Track only durable source, docs, schemas, and test fixtures

## Demo Readiness

- Exact demo commands are documented
- Fallback path exists if the cockpit UI cannot open
- The demo narrative stays alpha-safe and does not claim production readiness
- MCP Night fixtures are current and content-light


# 2026-05-13 — Phase 1: Receipt-Gated Protected Intents

## Objective
Enable a fast "quick-suite" default for validation and establish the first phase of receipt-gated protected intents in the Desktop Cockpit.

## Accomplishments

### 1. Validation Suite Reconciliation
- Updated `run_validation_suite` default steps to remove `pytest` (reserved for explicit heavy validation).
- New "Quick Suite": `ruff_check`, `ruff_format_check`, `pyright`, `schema_validation`, `storage_audit`, `desktop_cockpit_dry_run`.
- Reconciled documentation in `docs/governance/desktop-cockpit-ui.md`, `docs/dogfood/rig-relay-self-dogfood.md`, and `docs/audits/current-built-in-tools.md`.
- Fixed duplicate entry in `docs/governance/desktop-cockpit-ui.md`.

### 2. Phase 1 Protected Intents
- Updated `rig.relay.desktop_intent_request.v1` schema to include `authorization_receipt`.
- Enabled `checkpoint.commit` and `lease_cleanup.archive` in the Desktop Intent API.
- Implemented `validate_protected_intent_authorization` gate in `rig_relay/desktop/intents.py`.
- Verified that protected intents are refused without a valid receipt and execute correctly with one.
- Maintained strict refusal for high-risk intents: `bash`, `shell`, `write_file`, `search_replace`, `remote_upload.confirm`, `lease_cleanup.remove`, `spawn.execute`, `fleet.execute`, `delegate.execute`.

### 3. Verification
- All existing tests pass.
- Added 6 new tests in `tests/scripts/test_protected_intents_phase1.py` covering the receipt-gated intent lifecycle.

## Next Steps
- Implement "Step-up Authorization" UI in the pywebview cockpit to allow users to generate receipts.
- Enable Phase 2 protected intents (`remote_upload.confirm`, `spawn.execute`) once the receipt-gated flow is battle-tested.

# Rig Relay — Conversation Summary

## Session

- **Date**: 2026-05-14
- **Phase**: Phase N — Telemetry Optional Dependency and Stale Lease Cleanup Hardening
- **Topic**: Drive dep isolation, stale lease cleanup script, docs updates
- **Kind**: handoff

## Summary

Completed the agreed next slice: **Telemetry Optional Dependency and Stale Lease Cleanup Hardening**.

### Google Drive Import Isolation

- Moved `HAS_DRIVE_DEPS` from module-level constant to lazy `_has_drive_deps()` function in `scripts/rig_relay_upload_google_drive.py`
- Google imports (`google.auth`, `google_auth_oauthlib`, `googleapiclient`) now only evaluated when the function is called, not at import time
- `_upload_dry_run()` is pyright-clean without Drive deps installed — no module-level import errors
- Added `drive` optional extra to `pyproject.toml` with `google-api-python-client>=2.0.0`, `google-auth-oauthlib>=1.0.0`, `google-auth-httplib2>=0.2.0`

### Stale Lease Cleanup Script

- Created `scripts/rig_relay_cleanup_coordination_leases.py`
- Scans `leases/paths/` and `tasks/` directories under coordination root
- Categorizes leases/tasks as: `active`, `stale`, `released`, `expired` (expired = status=active but past expires_at)
- Never touches active, unexpired leases
- CLI flags: `--coordination-root`, `--max-age-seconds`, `--dry-run` (default), `--archive`, `--confirm`
- Archive mode moves files to `<root>/archived/leases/paths/` and `<root>/archived/tasks/`
- Dry-run is default; `--confirm` required for any destructive action

### Tests

- `tests/scripts/test_google_drive_upload.py`: 8 tests covering `_has_drive_deps()`, dry-run receipts, folder ID warnings, no-confirm dry-run, missing dep warnings, ImportError for real upload without deps, valid JSON output
- `tests/scripts/test_coordination_lease_cleanup.py`: 12 tests covering ISO datetime parsing, empty directory, stale lease detection, expired active lease detection, active unexpired lease preservation, file deletion, missing file handling, scan categorization, archive mode, missing root error

### Validation

- ruff check: pass (all files)
- ruff format: pass (all files)
- pyright: 0 errors, 0 warnings (both test files)
- pytest (upload + cleanup tests): 20 passed, 1 skipped (skipped = ImportError test when Drive deps absent)
- pytest (all script tests): 189 passed, 1 skipped, 3 deselected (3 pre-existing duckdb failures, unrelated)
- Schema validation: 40/40 passed

### Files Changed

**New files:**
- `scripts/rig_relay_cleanup_coordination_leases.py` — stale lease cleanup script
- `tests/scripts/test_google_drive_upload.py` — upload dep isolation tests
- `tests/scripts/test_coordination_lease_cleanup.py` — cleanup script tests

**Modified files (dirty at start — protected):**
- `docs/dogfood/rig-relay-self-dogfood.md` — added entries 21 (Semantic Snippet Hardening) and 22 (Telemetry Optional Dep & Stale Lease Cleanup)

**Modified files (clean at start):**
- `scripts/rig_relay_upload_google_drive.py` — Drive import isolation
- `pyproject.toml` — added `drive` optional extra

### Pending Next Slices

1. Real Google Drive upload (requires Drive deps installed + credentials)
2. External alpha telemetry onboarding
3. Drive optional deps install + pyright-clean path verification

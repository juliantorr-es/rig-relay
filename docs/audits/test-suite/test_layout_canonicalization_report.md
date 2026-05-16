# Test Layout Canonicalization Report

**Generated**: 2026-05-16
**Branch**: main
**HEAD**: 8d0b13c
**Doctrine**: docs/governance/test-suite-doctrine.md

## Baseline Metrics

| Metric | Before | After |
|---|---|---|
| Collected tests | 6085 | 6085 |
| Collection errors | 0 | 0 |
| Total test files | 325 | 325 |
| Root-level warnings | 23 | 15 |
| tests/scripts mis-scope warnings | 11 | 3 |
| Known duplicate pairs | 2 | 2 |
| Relocation manifest: pending | 51 | 33 |
| Relocation manifest: moved | 0 | 18 |
| Relocation manifest: resolved | 2 | 2 |
| Relocation manifest: allowlisted | 1 | 1 |

## Markers

All 13 markers registered in pyproject.toml:
`smoke`, `contract`, `integration`, `e2e`, `packaging`, `slow`, `legacy`, `flaky`, `network`, `provider`, `destructive`, `migration`, `quarantine`

## Moves Performed (18 files)

### Identity → tests/identity/ (2)
| From | To |
|---|---|
| `tests/test_telemetry_consent.py` | `tests/identity/test_telemetry_consent.py` |
| `tests/scripts/test_identity_providers.py` | `tests/identity/test_identity_providers.py` |

### Evidence → tests/evidence/ (3)
| From | To |
|---|---|
| `tests/test_model_observations.py` | `tests/evidence/test_model_observations.py` |
| `tests/test_observation_consent_integration.py` | `tests/evidence/test_observation_consent_integration.py` |
| `tests/scripts/test_google_drive_upload.py` | `tests/evidence/test_google_drive_upload.py` |

### CLI / Core → tests/cli/ and tests/core/ (6)
| From | To |
|---|---|
| `tests/test_cli_programmatic_preload.py` | `tests/cli/test_programmatic_preload.py` |
| `tests/test_rig_relay.py` | `tests/cli/test_rig_relay.py` |
| `tests/test_agents.py` | `tests/core/agents/test_agents.py` |
| `tests/test_message_id.py` | `tests/core/test_message_id.py` |
| `tests/test_message_merging.py` | `tests/core/test_message_merging.py` |
| `tests/test_tagged_text.py` | `tests/core/utils/test_tagged_text.py` |

### Desktop → tests/desktop/ (7)
| From | To |
|---|---|
| `tests/scripts/test_desktop_projection.py` | `tests/desktop/test_projection.py` |
| `tests/scripts/test_desktop_projection_contract.py` | `tests/desktop/test_projection_contract.py` |
| `tests/scripts/test_websocket_server.py` | `tests/desktop/test_websocket_server.py` |
| `tests/scripts/test_progress_events.py` | `tests/desktop/test_progress_events.py` |
| `tests/scripts/test_desktop_authorization_receipts.py` | `tests/desktop/test_authorization_receipts.py` |
| `tests/scripts/test_protected_intents_phase1.py` | `tests/desktop/test_protected_intents.py` |
| `tests/scripts/test_desktop_intents.py` | `tests/desktop/test_intents.py` |

## Trivial Path Fixes

- `tests/identity/test_telemetry_consent.py`: fixed `SCHEMA_PATH` from `.parent.parent` to `.parent.parent.parent` (depth change from root-level to identity/)
- `tests/evidence/test_model_observations.py`: fixed `SCHEMA_DIR` same issue

## Pre-existing Failures (not caused by moves)

- `tests/evidence/test_observation_consent_integration.py` (10 errors): `HarnessFilesManager already initialized` — global state, pre-existing
- `tests/cli/test_programmatic_preload.py` (3 failures): monkeypatches `vibe.core.programmatic` (stale vibe-era reference)
- `tests/core/agents/test_agents.py` (5 failures): Agent list changed (ORCHESTRATOR added), test expects old set
- `tests/desktop/test_intents.py` (1 failure): Frontend button mismatch — pre-existing
- `tests/desktop/test_projection.py` (1 failure): References deleted `scripts/rig_relay_desktop_cockpit.py`

## Remaining Debt

### Root-level warnings (15)
`test_agent_auto_compact`, `test_agent_backend`, `test_agent_observer_streaming`, `test_agent_override_resolve_permission`, `test_agent_stats`, `test_agent_tool_call`, `test_approve_always_permanent`, `test_config_paths`, `test_conftest_hygiene`, `test_deferred_init`, `test_install_script`, `test_middleware`, `test_reasoning_content`, `test_system_prompt`, `test_tracing`

### Mis-scoped scripts (3)
`tests/scripts/test_rig_relay_authorization_policy.py`, `tests/scripts/test_rig_relay_drive_and_cleanup.py`, `tests/scripts/test_rig_relay_telemetry_bundle.py`

### Duplicates Consolidated

### Observability
- **Deferred**: `test_observability.py` and `test_observability_e2e.py` test different tiers (contract vs. integration/e2e). Consolidation blocked by pre-existing `vibe` module references in `real_telemetry_client` fixture. Both files have 12/20 broken tests due to stale `import vibe.core.*` calls that need `rig_relay` migration.
- **Surviving canonical coverage**: Both files retained. Mark with `@pytest.mark.integration` after `vibe` → `rig_relay` fix.

### Bash
- **Deferred**: `test_bash.py` is dirty (modified by parallel lane). Do not touch until RuntimeSupervisor Bash work stabilizes.

## Recommended Next Batch

1. Move remaining root-level agent tests → `tests/core/` (8 files)
2. Move remaining root-level core tests → `tests/core/` (5 files: config_paths, middleware, reasoning_content, system_prompt, tracing)
3. Move remaining 3 mis-scoped scripts to governance/evidence/telemetry
4. Consolidate observability duplicate pair
5. Consolidate Bash duplicate pair (after RuntimeSupervisor stabilizes)

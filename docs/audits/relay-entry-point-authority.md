# Relay Entry Point Authority Audit

## Status

**Established.** Audit of the current CLI/product entry point boundary after the
Vibe CLI purge. Determines which commands are Relay-owned, which are legacy
compatibility aliases, and which runtime paths still depend on `vibe/*`.

## Session State

| Field | Value |
|---|---|
| **Branch** | `main` |
| **HEAD** | `384e486 checkpoint(vibe-cli-purge-surface-cleanup): Vibe CLI Purge and Relay Product Surface Cleanup` |
| **Origin** | `origin/main` [ahead 2] |
| **Dirty files** | 12 modified, 15 untracked (see below) |

### Dirty files at start

**Modified (12):**
- `docs/governance/model-observation-dataset.md`
- `docs/governance/storage-retention-policy.md`
- `docs/governance/telemetry-contribution-policy.md`
- `docs/governance/textual-retirement-policy.md`
- `docs/governance/usage-data-doctrine.md`
- `docs/governance/vibe-legacy-deprecation.md`
- `rig_relay/evidence/model_observations.py`
- `scripts/rig_relay_contribute_telemetry_bundle.py`
- `tests/scripts/test_google_drive_upload.py`
- `tests/test_model_observations.py`
- `vibe/cli/textual_ui/app.py`
- `vibe/core/agent_loop.py`

**Untracked (15):**
- `docs/governance/relay-surface-matrix.md`
- `docs/governance/session-storage-lifecycle.md`
- `docs/schemas/rig.relay.contribution_receipt.v1.schema.json`
- `docs/schemas/rig.relay.contribution_result.v1.schema.json`
- `rig_relay/evidence/session_lifecycle.py`
- `scripts/rig_relay_sessions_audit.py`
- `scripts/rig_relay_sessions_compact.py`
- `scripts/rig_relay_sessions_gc.py`
- `test_out.txt`
- `tests/docs/test_textual_retirement_policy.py`
- `tests/evidence/test_session_lifecycle.py`
- `tests/scripts/test_session_lifecycle_scripts.py`
- `tests/scripts/test_telemetry_contribution_schemas.py`
- `tests/tools/test_session_lifecycle_finalize.py`
- `vibe/core/tools/builtins/session_lifecycle.py`

**Note:** Dirty files are pre-existing and user-owned. This audit neither reads
nor writes them.

## Governance Note: Checkpoint to `main`

The previous mission (`vibe-cli-purge-surface-cleanup`) created a local
checkpoint commit on `main` (HEAD `384e486`). This is **technically permitted**
by AGENTS.md:

> "Agent checkpoint commits: Agents may create local checkpoint commits for
> session-owned files using the `checkpoint` tool."

AGENTS.md does not restrict which branch checkpoints land on. However, this
creates **release-surface ambiguity**: `main` is now 2 commits ahead of
`origin/main` with un-pushed checkpoint content. If a release is cut from
`origin/main`, the checkpoint changes are missing. If cut from `main`, the
checkpoint content (which may be partial or session-scoped) is included.

**Recommendation:** Future checkpoints should land on a dedicated feature
branch (e.g., `agent/wip/*`) rather than `main`. Alternatively, AGENTS.md
should add an explicit rule: "Checkpoint onto `main` only with user
permission; prefer feature branches for session-owned work."

This is a **governance exception** — not a violation, but a practice gap that
should be closed before the next release.

## Command Inventory

### `pyproject.toml` Entry Points (`[project.scripts]`)

| Entry Point | Target Module:Function | Classification | Deployment |
|---|---|---|---|
| `rig-relay` | `rig_relay.cli.entrypoint:main` | **primary** | `pyproject.toml` |
| `rig-relay-acp` | `rig_relay.cli.acp_entrypoint:main` | **primary** | `pyproject.toml` |
| `vibe` | `vibe.cli.entrypoint:main` | **deprecated alias** | `pyproject.toml` |
| `vibe-acp` | `vibe.acp.entrypoint:main` | **deprecated alias** | `pyproject.toml` |
| `vibe-legacy` | `vibe.cli.entrypoint:main` | **explicit legacy** | `pyproject.toml` |
| `vibe-acp-legacy` | `vibe.acp.entrypoint:main` | **explicit legacy** | `pyproject.toml` |

### Entry Points Referenced But Not Registered

| Entry Point | Referenced In | Registration | Issue |
|---|---|---|---|
| `rig-relay-cockpit` | `AGENTS.md`, `docs/audits/vibe-cli-purge-inventory.md` | **NOT registered** in `pyproject.toml` | Advertising without existence; users following AGENTS.md get `Error: No such command` |

The cockpit is runnable via `uv run python scripts/rig_relay_desktop_cockpit.py`
but there is no `rig-relay-cockpit` console_scripts entry point. AGENTS.md
recommends a command that does not exist.

## Entry Point Target Table

| Command | Module | Function | Called Into |
|---|---|---|---|
| `rig-relay` | `vibe/cli/entrypoint.py` | `main()` → `run_cli()` | `vibe/cli/cli.py` |
| `rig-relay-acp` | `vibe/acp/entrypoint.py` | `main()` → `run_acp_server()` | `vibe/acp/acp_agent_loop.py` |
| `vibe` | `vibe/cli/entrypoint.py` | `main()` → `run_cli()` | `vibe/cli/cli.py` |
| `vibe-acp` | `vibe/acp/entrypoint.py` | `main()` → `run_acp_server()` | `vibe/acp/acp_agent_loop.py` |
| `vibe-legacy` | `vibe/cli/entrypoint.py` | `main()` → `run_cli()` | `vibe/cli/cli.py` |
| `vibe-acp-legacy` | `vibe/acp/entrypoint.py` | `main()` → `run_acp_server()` | `vibe/acp/acp_agent_loop.py` |

**Key finding:** Every single entry point — including `rig-relay` and
`rig-relay-acp` — delegates to `vibe.*` modules. There is zero Relay-owned
entry point code.

## Current Dependency Map

```
rig-relay ──→ rig_relay.cli.entrypoint ──→ vibe.cli.entrypoint ──→ vibe.cli.cli ──→ vibe.core.*
                                                         ├── agent_loop
                                                         ├── config
                                                         ├── programmatic
                                                         ├── session.*
                                                         ├── telemetry.*
                                                         ├── tracing
                                                         ├── hooks
                                                         ├── agents
                                                         └── ...

rig-relay-acp ──→ rig_relay.cli.acp_entrypoint ──→ vibe.acp.entrypoint ──→ vibe.acp.acp_agent_loop ──→ vibe.core.*
                                                                       ├── config
                                                                       ├── logger
                                                                       ├── tracing
                                                                       └── ...

vibe ──→ vibe.cli.entrypoint (warning printed) ──→ same as rig-relay
vibe-acp ──→ vibe.acp.entrypoint (warning printed) ──→ same as rig-relay-acp
vibe-legacy ──→ vibe.cli.entrypoint (warning printed) ──→ same as rig-relay
vibe-acp-legacy ──→ vibe.acp.entrypoint (warning printed) ──→ same as rig-relay-acp

rig_relay.* (product namespace, doesn't own any entry point):
  ├── rig_relay/cli/          (target: empty)
  ├── rig_relay/runtime/      (target: has update_status.py only)
  ├── rig_relay/governance/   (seam: dirty_guard, auth_receipts)
  ├── rig_relay/coordination/ (seam: store, models, tool)
  ├── rig_relay/evidence/     (seam: model_observations, session_lifecycle)
  ├── rig_relay/identity/     (seam: OAuth, token store)
  ├── rig_relay/desktop/      (seam: cockpit projection, WS server)
  └── rig_relay/providers/    (seam: registry, health_check)
```

## Relay-Owned vs Vibe-Owned Boundary Assessment

### Relay-Owned (Product Namespace: `rig_relay.*`)

| Module | Owner | Notes |
|---|---|---|
| `rig_relay/cli/` | **empty target package** | Slated for CLI commands but currently vacant |
| `rig_relay/runtime/` | **1 file only** (`update_status.py`) | Target for agent loop migration; mostly empty |
| `rig_relay/governance/` | ✅ owned | Dirty guard, auth receipts, local action envelope |
| `rig_relay/coordination/` | ✅ owned | Store, models, tool, current state |
| `rig_relay/evidence/` | ✅ owned | Model observations, session lifecycle, storage lifecycle |
| `rig_relay/identity/` | ✅ owned | OAuth, providers, consent store |
| `rig_relay/desktop/` | ✅ owned | Cockpit, WebSocket, chat state |
| `rig_relay/providers/` | ✅ owned | Registry, key store, health check |

### Vibe-Owned (Legacy: `vibe.*`)

| Module | Owner | Critical To |
|---|---|---|
| `vibe/cli/entrypoint.py` | **entry point** | All CLI commands |
| `vibe/acp/entrypoint.py` | **entry point** | All ACP commands |
| `vibe/cli/cli.py` | **runtime orchestrator** | `rig-relay` interactive + programmatic modes |
| `vibe/core/agent_loop.py` | **agent loop** | Tool execution, LLM streaming |
| `vibe/core/config/` | **configuration** | Settings, providers, models |
| `vibe/core/llm/` | **LLM backends** | Provider adapters |
| `vibe/core/tools/` | **tool registry** | Built-in tools |
| `vibe/core/telemetry/` | **telemetry** | Events, artifacts, schemas |
| `vibe/core/session/` | **session lifecycle** | Save/load/resume |
| `vibe/core/programmatic.py` | **headless mode** | `-p`/`--prompt` flag |
| `vibe/core/tracing.py` | **tracing** | OpenTelemetry setup |
| `vibe/core/hooks/` | **hooks** | Pre/post execution hooks |
| `vibe/core/agents/` | **agent profiles** | Agent models and dispatch |
| `vibe/acp/acp_agent_loop.py` | **ACP server** | ACP protocol agent |
| `vibe/setup/` | **onboarding** | First-run wizard |
| `vibe/legacy/` | **quarantine** | Reserved for legacy quarantine |

### Boundary Classifications

| Dependency | Classification | Notes |
|---|---|---|
| `rig-relay` → `rig_relay.cli.entrypoint` (→ `vibe.cli.entrypoint`) | **acceptable temp compat** | Entry point facade created; delegates to `vibe.cli.entrypoint` when `vibe/cli/cli.py` is migrated |
| `rig-relay` → `vibe.cli.cli` | **needs wrapper extraction** | This is the CLI orchestrator — highest priority for facade creation |
| `rig-relay` → `vibe.core.agent_loop` | **needs runtime migration** | Core loop; Phase 4 target |
| `rig-relay` → `vibe.core.config` | **acceptable temp compat** | Config loading is stable; migrate when entry point moves |
| `rig-relay` → `vibe.core.programmatic` | **needs wrapper extraction** | Tightly coupled to agent_loop; migrate together |
| `rig-relay-acp` → `rig_relay.cli.acp_entrypoint` (→ `vibe.acp.entrypoint`) | **acceptable temp compat** | Entry point facade created; delegates to `vibe.acp.entrypoint` |
| `rig-relay-acp` → `vibe.acp.acp_agent_loop` | **needs runtime migration** | ACP server is standalone; candidate for migration |
| `vibe-legacy` → `vibe.cli.entrypoint` | **safe to leave internal** | Legacy alias; same path as primary |
| `vibe-acp-legacy` → `vibe.acp.entrypoint` | **safe to leave internal** | Legacy alias; same path as primary |
| Desktop cockpit → `vibe.core.agent_loop` | **needs runtime migration** | Cockpit imports AgentLoop directly |
| Desktop cockpit → `vibe.core.config` | **acceptable temp compat** | Same rationale as CLI |
| Desktop cockpit → `vibe.core.hooks` | **acceptable temp compat** | Hook loading is stable |

## Migration Risk Notes

### Risk 1: All Primary Entry Points Point to `vibe.*`

There is no Relay-owned entry point. `rig-relay` and `rig-relay-acp` are
branded names that delegate entirely to legacy `vibe.*` code. **If `vibe/*`
were deleted, the CLI would stop working.** The `rig_relay/` namespace exists
alongside but does not power any CLI entry point.

### Risk 2: Deprecation Warning Hardcodes Alias Names

Both entry points use a hardcoded check:
```python
if "vibe" in cmd_name.lower():
    rprint("[dim]`vibe` is a legacy compatibility alias...[/]")
```

This means:
- `vibe-lega cy` triggers the warning but says "`vibe`" instead of "`vibe-legacy`"
- The hardcoded backtick name is inaccurate for `vibe-legacy` and `vibe-acp-legacy`

This is a minor cosmetic issue with no functional impact.

### Risk 3: `rig-relay-cockpit` Is Not Registered

AGENTS.md lists `uv run rig-relay-cockpit` as a primary surface entry point.
No such console_scripts entry exists in `pyproject.toml`. Users following
AGENTS.md will get an error. The cockpit is only accessible via:
```
uv run python scripts/rig_relay_desktop_cockpit.py
```

### Risk 4: `vibe-legacy` and `vibe-acp-legacy` Are Functionally Identical

The `vibe-legacy` and `vibe-acp-legacy` entry points point to the same modules
as `vibe` and `vibe-acp`. They are not "explicit legacy" in any meaningful way
— they don't enter a legacy code path or quarantine zone. They are simply
aliases. If the intent is to have an `-legacy` suffix for users who want the
old behavior, those paths will need to be distinct when the Relay facade is
extracted.

### Risk 5: `rig_relay/cli/` and `rig_relay/runtime/` Are Target Packages With No Content

The package structure declares these as target locations for migrating
`vibe/cli/` and `vibe/core/agent_loop.py`, but only `rig_relay/runtime/update_status.py`
exists. The migration doctrine in `vibe-legacy-deprecation.md` and the
`__init__.py` module docstrings advertise these as targets, but no migration
from `vibe.*` to `rig_relay.*` has been done for the entry point or runtime.

## Validation Commands and Results

| Command | Exit Code | Warning? | Notes |
|---|---|---|---|
| `ruff check tests/docs/test_vibe_cli_purge_inventory.py` | 0 | No | All checks passed |
| `pyright tests/docs/test_vibe_cli_purge_inventory.py` | 0 | No | 0 errors, 0 warnings |
| `pytest -n0 tests/docs/test_vibe_cli_purge_inventory.py` | 0 | No | 3 passed |
| `python scripts/rig_relay_validate_schemas.py` | 0 | No | 68/68 passed |
| `rig-relay --help` | 0 | No | Clean output |
| `rig-relay-acp --help` | 0 | No | Clean output |
| `vibe --help` | 0 | **Yes** | "`vibe` is a legacy compatibility alias..." to stdout |
| `vibe-acp --help` | 0 | **Yes** | "`vibe-acp` is a legacy compatibility alias..." to stderr |
| `vibe-legacy --help` | 0 | **Yes** | Says "`vibe`" (misleading; should say `vibe-legacy`) |
| `vibe-acp-legacy --help` | 0 | **Yes** | Says "`vibe-acp`" (misleading; should say `vibe-acp-legacy`) |

**All commands work correctly.** Legacy alias warnings appear for all
`vibe*` commands. The warning text is mildly inaccurate for the `*-legacy`
variants (see Risk 2).

## Recommended Next Slices in Priority Order

### Slice 1: Extract Relay Runtime Facade (IMMEDIATE)

Create a thin `rig_relay.runtime.facade` module that `rig-relay` can own as
its entry point boundary. This is NOT a full migration — just a Relay-owned
surface that delegates to `vibe/core` internals.

**Files to create:**
- `rig_relay/runtime/facade.py` — `def run_cli(args)`, `def run_acp(args)`

**File to modify:**
- `vibe/cli/entrypoint.py` — simplify to delegate to `rig_relay.runtime.facade`
- `vibe/acp/entrypoint.py` — simplify to delegate to `rig_relay.runtime.facade`

**Files to create (entry points):**
- `rig_relay/cli/entrypoint.py` — `main()` calling facade
- `rig_relay/cli/acp_entrypoint.py` — `main()` calling facade

**Then update `pyproject.toml`:**
```
rig-relay = "rig_relay.cli.entrypoint:main"
rig-relay-acp = "rig_relay.cli.acp_entrypoint:main"
```

Keeps `vibe.*` paths unchanged for the legacy aliases.

### Slice 2: Register `rig-relay-cockpit` Console Script (NEXT)

Add a `[project.scripts]` entry and ensure AGENTS.md accuracy:
```
rig-relay-cockpit = "scripts.rig_relay_desktop_cockpit:main"
```
Or, better, move the `main()` wrapper into `rig_relay.desktop.cockpit_cli`.

### Slice 3: Fix Deprecation Warning Accuracy (MINOR)

Update the hardcoded warning in both entry points to use the actual command
name rather than a hardcoded string. This fixes the cosmetic issue with
`vibe-legacy` and `vibe-acp-legacy`.

### Slice 4: Migrate Session Lifecycle Boundary (MEDIUM)

Move session lifecycle (save/load/resume) from `vibe.core.session.*` to
`rig_relay.runtime.session.*`. This is a natural boundary: session lifecycle
is already partly in `rig_relay.evidence.session_lifecycle.py`.

### Slice 5: Migrate CLI Orchestrator (MEDIUM)

Move `vibe/cli/cli.py` (`run_cli`, `_run_standard_cli`, `_run_doctor_command`,
`run_programmatic` wrapper) into `rig_relay.cli.orchestrator`. This makes
`rig-relay` the true Relay-owned command rather than a Vibe delegation.

### Slice 6: Block Checkpoint to Main Governance Gap

Update AGENTS.md or add a policy document to restrict checkpoint commits on
`main`. Preferred approach: feature branches or explicit user permission.

## Out-of-scope Findings

No out-of-scope findings recorded for this audit-only mission.

---

## Facade Implemented

**Date:** Current session.

This section records the result of the Extract Relay Runtime Facade mission.

### What Changed

| Change | Before | After |
|---|---|---|
| `rig-relay` target | `vibe.cli.entrypoint:main` | `rig_relay.cli.entrypoint:main` |
| `rig-relay-acp` target | `vibe.acp.entrypoint:main` | `rig_relay.cli.acp_entrypoint:main` |
| Wheel include | `["vibe/"]` | `["vibe/", "rig_relay/"]` |

### New Facade Modules

- `rig_relay/cli/entrypoint.py` — **Relay-owned CLI entry point.** Imports and re-exports `main` from `vibe.cli.entrypoint`. No additional behavior.
- `rig_relay/cli/acp_entrypoint.py` — **Relay-owned ACP entry point.** Imports and re-exports `main` from `vibe.acp.entrypoint`. No additional behavior.

### What Did Not Change

- `vibe`, `vibe-acp`, `vibe-legacy`, `vibe-acp-legacy` still point to `vibe.*` entry points.
- `vibe/cli/entrypoint.py` and `vibe/acp/entrypoint.py` remain untouched.
- No runtime logic was moved out of `vibe/core`.
- No compatibility aliases were removed.
- No behavior was changed.

### Remaining Architecture

```
rig-relay ──→ rig_relay.cli.entrypoint ──→ vibe.cli.entrypoint ──→ vibe.cli.cli ──→ vibe.core.*
                                              (delegates via import)
rig-relay-acp ──→ rig_relay.cli.acp_entrypoint ──→ vibe.acp.entrypoint ──→ vibe.acp.acp_agent_loop ──→ vibe.core.*
                                                    (delegates via import)
vibe ──→ vibe.cli.entrypoint (unchanged, warning printed)
vibe-acp ──→ vibe.acp.entrypoint (unchanged, warning printed)
vibe-legacy ──→ vibe.cli.entrypoint (unchanged, warning printed)
vibe-acp-legacy ──→ vibe.acp.entrypoint (unchanged, warning printed)
```

### Status

The `rig-relay` and `rig-relay-acp` commands now enter through Relay-owned modules. The facade delegates to the existing `vibe.*` implementation. Runtime migration remains deferred (Phase 2+ in the Strangler Fig plan). Compatibility aliases remain intact.

### Cockpit Registration

`rig-relay-cockpit` was **not registered** in this mission. The cockpit script (`scripts/rig_relay_desktop_cockpit.py`) has a `main(argv)` function, but `scripts/` is not a Python package and is not included in the wheel build. Registration requires either:
- Making `scripts/` a package and adding it to the wheel include list, or
- Moving the `main()` wrapper into `rig_relay.desktop.cockpit_cli`

This is documented as **deferred** (Slice 2 in the recommended slices above).

### Verification

All validation commands pass (see validation section of the mission report).

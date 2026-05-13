# Rig Relay Storage Retention Policy

## Purpose

Defines the storage lifecycle for Rig Relay's local `.build/rig-relay/` artifact tree.
Three storage tiers with explicit retention defaults, sampling policies, and budget
enforcement. Storage lifecycle must exist **before** delegate/fleet execution.

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                     .build/rig-relay/                           │
│                                                                 │
│  ┌─────────────────────┐  ┌──────────────────┐  ┌───────────┐  │
│  │  HOT (raw/logs)     │  │  WARM (derived)  │  │  COLD     │  │
│  │                     │  │                  │  │ (rollups) │  │
│  │ coordination/       │  │ derived/         │  │ *.parquet │  │
│  │ desktop/            │  │ reports/         │  │           │  │
│  │ telemetry-bundles/  │  │ chatgpt-bundles/ │  │ manifests │  │
│  │ drive-uploads/      │  │ cockpit/         │  │           │  │
│  │ coordination/leases │  │                  │  │           │  │
│  └─────────────────────┘  └──────────────────┘  └───────────┘  │
│                                                                 │
│  DuckDB compaction path: JSONL → SELECT/filter/rollup → Parquet │
└─────────────────────────────────────────────────────────────────┘
```

## Storage Tiers

### Hot — Raw Operational Data

Low-latency access for active sessions. High volume. Short retention.

| Category | Default Retention | Path |
|----------|------------------|------|
| Raw observability (`observability.jsonl`) | 3 days | `~/.rig/relay/sessions/*/` |
| Raw tool artifacts | 3 days | `coordination/artifacts/` |
| Coordination events | 14 days | `coordination/events.jsonl` |
| Stale coordination leases | 24 hours | `coordination/leases/` |
| Desktop projection snapshots | 1 day | `desktop/` |
| Telemetry bundle zips | 7 days (keep manifest) | `telemetry-bundles/` |
| Drive upload receipts | 7 days | `drive-uploads/` |

### Warm — Derived Datasets

Reduced volume. Content-light. Weeks-to-months retention.

| Category | Default Retention | Path |
|----------|------------------|------|
| Derived JSONL datasets | 30 days | `derived/*.jsonl` |
| Reports | 30 days | `reports/` |
| ChatGPT dev bundles | 30 days | `chatgpt-bundles/` |
| Cockpit snapshots | 7 days | `cockpit/` |

### Cold — Parquet Rollups

Aggregated, compact, long-lived. Manifests are permanent.

| Category | Default Retention | Path |
|----------|------------------|------|
| Parquet rollups | 365 days | `derived/*.parquet` |
| Rollup manifests | Permanent | `derived/rollup_manifest.json` |
| Export manifests | Permanent | `derived/export_manifest.json` |

## Protected Classes (Never Deleted)

These artifacts are never removed by GC:

- Final mission reports (`docs/` checked-in files)
- Rollup manifests (`derived/rollup_manifest.json`)
- Export manifests (`derived/export_manifest.json`)
- Upload receipts (`drive-uploads/*receipt*.json`)
- Checkpoint receipts (coordinated checkpoint artifacts)
- Parent convergence reports
- Active coordination leases (not stale)

## Sampling Policy

To bound retention volume while preserving failure signal:

| Category | Sampling Rate |
|----------|--------------|
| All failures, refusals, conflicts | 100% (always keep) |
| All checkpoint refusals | 100% (always keep) |
| Successful tool calls | 5% random sample |
| Semantic snippets per session | Max 200 |
| Command events per session | Max 5,000 |

## Storage Budget

Enforced by `scripts/rig_relay_storage_audit.py` against `storage_budget.v1` schema.

| Threshold | Behavior |
|-----------|----------|
| `warn_local_mb` (1 GB) | Print warning, continue |
| `max_local_mb` (2 GB) | Block compaction, warn user |
| `refuse_fleet_over_mb` (4 GB) | Block spawn/delegate/fleet until GC runs |

## Compaction Pipeline

Compaction transforms derived JSONL into Parquet using DuckDB:

```
derived/*.dataset.jsonl ──→ DuckDB SELECT/WHERE/COUNT ──→ derived/*.parquet
                              └─→ derived/rollup_manifest.json
```

- Compaction is **never** destructive. Raw logs stay until GC removes them.
- Compaction reads all available JSONL datasets in `derived/`.
- Output Parquet files use the same stem as the source JSONL with `.parquet` suffix.
- The rollup manifest records source SHA256, row counts, and output SHA256 for audit.
- Dry-run is the default. `--confirm` is required for actual writes.

## Refinement Reports

Built-in tool refinement reports read the warm derived datasets and produce a ranked backlog for tool improvements. They do not touch raw logs, do not compact anything, and should remain small enough to keep in `reports/` with other warm artifacts.

Recommended generated outputs:

- `reports/built-in-tool-refinement.md`
- `derived/builtin_tool_refinement_backlog.jsonl`

These reports are analysis products. They may be regenerated freely from the current derived corpus and should be retained under the same warm retention rules as other derived reports.

## Garbage Collection

GC is a separate step from compaction. It:

1. Uses retention rules to find candidates.
2. Archives (moves to `.../archived/`) or deletes allowed candidates.
3. Never touches protected classes.
4. Never touches active leases.
5. Dry-run is the default. `--confirm` is required for actual deletion.

### Allowed GC Candidates

| Candidate | Action |
|-----------|--------|
| Stale leases (older than `stale_leases_hours`) | Delete |
| Old projection snapshots (older than retention) | Delete |
| Old telemetry zips (keep manifest) | Delete zip only |
| Old raw observability (older than retention) | Archive then delete |
| Old derived JSONL (after Parquet exists + retention expired) | Delete |
| Temp files (`.tmp`, `.temp`) | Delete |
| Old drive upload receipts (older than retention) | Archive then delete |

## Storage Budget Schema

See `docs/schemas/rig.relay.storage_budget.v1.schema.json`.

## Enforcement

- `rig_relay_storage_audit.py` returns budget status: `ok`, `warn`, `over_budget`, `fleet_blocked`
- `rig_relay_compact_artifacts.py` requires `--confirm` to write and checks budget before proceeding
- `rig_relay_gc_artifacts.py` checks budget and refuses if `max_local_mb` exceeded without `--force`
- Fleet/delegate must check `storage_audit.total_size_mb < refuse_fleet_over_mb`

## Budget Status Definitions

| Status | Criteria |
|--------|----------|
| `ok` | Total < `warn_local_mb` |
| `warn` | Total >= `warn_local_mb` and < `max_local_mb` |
| `over_budget` | Total >= `max_local_mb` and < `refuse_fleet_over_mb` |
| `fleet_blocked` | Total >= `refuse_fleet_over_mb` |

## Fleet Preflight Enforcement

Before launching any delegate or fleet, the orchestrator MUST perform a storage
preflight check. The preflight ensures the build artifact tree has sufficient headroom
for planned work and is not in a degraded state that would corrupt derived datasets.

### Preflight Rules

| Rule | Enforced By | Blocking? |
|------|------------|-----------|
| Total storage < `refuse_fleet_over_mb` (4 GB) | `storage_audit.py` budget check | Yes — fleet blocked |
| Storage budget status != `fleet_blocked` | `compute_storage_summary()` | Yes — fleet blocked |
| Stale lease count < 50 | `_count_stale_leases()` | Warning only |
| Rollup candidates < 20 | `_find_rollup_candidates()` | Warning only |
| Prune candidates < 100 | `_find_prune_candidates()` | Warning only |

### Integration Points

1. **`rig_relay/coordination/current_state.py`** — `generate_current_state()` calls
   `compute_storage_summary()` and returns `storage_status` in the pulse. The orchestrator
   reads this field before planning spawn.
2. **`rig_relay/desktop/projection.py`** — `build_projection()` calls
   `compute_storage_summary()` and returns `storage` section. The cockpit displays
   storage preflight status.
3. **`rig_relay/evidence/storage_lifecycle.py`** — `compute_storage_summary()` is the
   canonical importable helper. All preflight queries route through it.
4. **`scripts/rig_relay_storage_audit.py`** — CLI audit tool. Returns budget status
   and warns on stale leases, rollup backlog, and prune backlog.

### Preflight Flow

```
orchestrator reads current_state (includes storage_status)
  ↓
storage_status.budget_status == fleet_blocked?
  YES → block fleet, recommend GC, emit coord.event
  NO → check stale_lease_count > 50?
          YES → warn, continue
          NO → proceed to spawn plan
  ↓
spawn_plan evaluates queue items against storage budget
  ↓
fleet executes (each child receives budget status in mission packet)
  ↓
post-execution: orchestrator reads storage_status again for next loop iteration
```

### Scripts

| Script | Purpose |
|--------|---------|
| `scripts/rig_relay_storage_audit.py` | Storage inspection + budget computation (never deletes) |
| `scripts/rig_relay_compact_artifacts.py` | DuckDB JSONL→Parquet compaction (dry-run by default) |
| `scripts/rig_relay_gc_artifacts.py` | Retention-based GC for build directory (dry-run by default) |

## Cross-References

- [Usage Data Doctrine](usage-data-doctrine.md)
- [Dependency Policy](dependency-policy.md)
- [Cross-Session Coordination](cross-session-coordination.md)
- `docs/schemas/rig.relay.storage_budget.v1.schema.json`

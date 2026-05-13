# Sprint Cockpit: sprint_20260513_154503

*Generated: 2026-05-13T15:45:03.978270+00:00*

## Repository

| Field | Value |
|-------|-------|
| Branch | `main` |
| HEAD | `40a2d0417005` |
| State SHA256 | `sha256:0f62810298837f8514af8906f8310dd7d052ed6f82047c80481814f24275f791` |
| Tracked modified | 11 |
| Untracked | 23 |
| Protected dirty | 11 |

## Coordination

| Field | Value |
|-------|-------|
| Active sessions | 0 |
| Active tasks | 82 |
| Active write leases | 0 |
| Conflicts | 0 |
| Stale leases | 0 |

## Dataset

| Field | Value |
|-------|-------|
| Sessions | 69 |
| Observability events | 6301 |
| Coordination events | 251 |
| Tool calls | 1362 |
| Open findings | 4 |

## Open Findings

| ID | Severity | Title |
|----|----------|-------|
| finding_20260513_dirty_guard_singleton | medium | DirtyFileGuard singleton is shared across forked agents |
| finding_20260513_clear_history_recaptures_guard | medium | clear_history() recaptures guard state instead of preserving conversation-only snapshot |
| finding_20260513_checkpoint_coordination_unknown_metadata | medium | checkpoint and coordination tools have UNKNOWN determinism and mutation metadata |
| finding_20260513_search_replace_plr0914 | low | search_replace.py has recurring PLR0914 (too many locals) and PLR0915 (too many statements) pressure |

## Recent Checkpoints

*No recent checkpoints.*

## Active Sessions

*No active sessions.*

## Sprint Mission

Validate reviewer orchestrator cockpit protocol

## Constraints

- max_parallel_sessions=4
- no_push
- no_direct_git_add_or_commit
- one_writer_per_path

## Available Reviewer Tools

- `rig_relay_read_cockpit`
- `rig_relay_read_coordination_state`
- `rig_relay_read_dataset_report`
- `rig_relay_spawn_session`
- `rig_relay_cancel_session`
- `rig_relay_request_checkpoint`
- `rig_relay_aggregate_reports`

# Rig Relay Dataset Report

*Generated: 2026-05-13T16:00:26.664985+00:00*

## Executive Summary

| Metric | Value |
| --- | --- |
| Sessions observed | 71 |
| Observability events | 7959 |
| Coordination events | 416 |
| Tool calls | 1672 |
| Mutations allowed | 1543 |
| Mutations refused | 0 |
| Guard events | 0 |
| Checkpoints committed | 0 |
| Checkpoints refused | 0 |
| Open findings | 4 |

## Event Volume

| Event Name | Count |
| --- | --- |
| rig.relay.tool.call_completed | 1672 |
| rig.relay.tool.reasoning_trace | 1322 |
| rig.relay.context.request_accounted | 1239 |
| rig.relay.context.assembly_reported | 1239 |
| rig.relay.context.layout_planned | 1239 |
| rig.relay.context.shadow_request_assembled | 1020 |
| coord.task.claimed | 107 |
| coord.path.reserved | 102 |
| coord.path.released | 101 |
| coord.artifact.published | 94 |
| rig.relay.artifact.tool_output_written | 87 |
| rig.relay.session.started | 65 |
| rig.relay.ready | 28 |
| rig.relay.user_copied_text | 23 |
| rig.relay.session.closed | 11 |
| rig.relay.slash_command_used | 9 |
| coord.conflict.reported | 5 |
| coord.path.reservation_refused | 5 |
| rig.relay.context.auto_compact_triggered | 4 |
| rig.relay.user_cancelled_action | 1 |
| coord.projection.read | 1 |
| coord.lease.marked_stale | 1 |

## Tool Behavior

| Tool Name | Total Calls | Success | Refused | Error |
| --- | --- | --- | --- | --- |
| bash | 592 | 503 | 0 | 0 |
| coordination | 4 | 3 | 0 | 0 |
| git_branch | 3 | 3 | 0 | 0 |
| git_diff | 5 | 5 | 0 | 0 |
| git_log | 6 | 6 | 0 | 0 |
| git_ls_files | 1 | 1 | 0 | 0 |
| git_status | 25 | 25 | 0 | 0 |
| grep | 138 | 137 | 0 | 0 |
| read_file | 540 | 532 | 0 | 0 |
| search_replace | 225 | 198 | 0 | 0 |
| task | 6 | 6 | 0 | 0 |
| todo | 49 | 49 | 0 | 0 |
| write_file | 78 | 75 | 0 | 0 |

## Guard and Safety

*No guard events observed.*

## Coordination

| Event Name | Count |
| --- | --- |
| coord.artifact.published | 94 |
| coord.conflict.reported | 5 |
| coord.lease.marked_stale | 1 |
| coord.path.released | 101 |
| coord.path.reservation_refused | 5 |
| coord.path.reserved | 102 |
| coord.projection.read | 1 |
| coord.task.claimed | 107 |

### Breakdown

| Category | Count |
| --- | --- |
| Task claims | 107 |
| Path reservations | 102 |
| Reservation refusals | 5 |
| Conflicts reported | 5 |
| Heartbeats | 0 |

## Checkpoints

*No checkpoint events observed.*

## Provider / Model Use

| Model | Request Count |
| --- | --- |
| deepseek-v4-flash | 709 |
| deepseek-v4-pro | 530 |

## Findings

### Summary by Severity

| Severity | Count |
| --- | --- |
| low | 1 |
| medium | 3 |

### Active Findings

| Finding ID | Title | Severity | Status | Repo Area |
| --- | --- | --- | --- | --- |
| finding_20260513_dirty_guard_singleton | DirtyFileGuard singleton is shared across forked agents | medium | open | vibe/core/guard |
| finding_20260513_clear_history_recaptures_guard | clear_history() recaptures guard state instead of preserving conversation-only snapshot | medium | open | vibe/core/agent_loop |
| finding_20260513_checkpoint_coordination_unknown_metadata | checkpoint and coordination tools have UNKNOWN determinism and mutation metadata | medium | open | vibe/core/tools/builtins |
| finding_20260513_search_replace_plr0914 | search_replace.py has recurring PLR0914 (too many locals) and PLR0915 (too many statements) pressure | low | open | vibe/core/tools/builtins/search_replace |


## Recommended Next Slices

*Derived from current data and findings.*

- **finding_20260513_dirty_guard_singleton**: GuardRegistry for session-scoped dirty snapshots (medium severity, vibe/core/guard)
- **finding_20260513_clear_history_recaptures_guard**: Split clear_history from guard recapture (medium severity, vibe/core/agent_loop)
- **finding_20260513_checkpoint_coordination_unknown_metadata**: Complete checkpoint and coordination tool metadata (medium severity, vibe/core/tools/builtins)
- **finding_20260513_search_replace_plr0914**: Refactor search_replace.py to eliminate PLR0914/PLR0915 (low severity, vibe/core/tools/builtins/search_replace)

## Data Sources Used

| Source | Path / Status |
| --- | --- |
| Coordination events | /Users/user/Developer/GitHub/rig-relay/.build/rig-relay/coordination/events.jsonl |
| Observability logs | 71 file(s) |
|  |   /Users/user/.rig/relay/sessions/02bbef1f-487b-ace3-b7db-f486e05aeacf/observability.jsonl |
|  |   /Users/user/.rig/relay/sessions/033df2c4-7260-2d43-ceaf-dfe90e56084f/observability.jsonl |
|  |   /Users/user/.rig/relay/sessions/09ad7281-6348-ad07-708e-ece4d4b68123/observability.jsonl |
|  |   /Users/user/.rig/relay/sessions/0a2329ac-e4c9-f229-76c3-35a205e05418/observability.jsonl |
|  |   /Users/user/.rig/relay/sessions/0ae49da5-3f26-3dad-2408-7c076dc5c884/observability.jsonl |
|  |   ... and 66 more |
| Findings registry | /Users/user/Developer/GitHub/rig-relay/docs/findings/out-of-scope-findings.jsonl |
| DuckDB available | ✓ |

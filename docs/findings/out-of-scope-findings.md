# Out-of-Scope Findings Registry

> Living index of structured findings discovered during agent missions.
> Each finding is recorded in `out-of-scope-findings.jsonl` with full structured metadata.
> This Markdown index provides a human-readable summary sorted by finding kind.

## Finding Kinds

| Kind | Description |
|------|-------------|
| `architecture_debt` | Structural design debt that constrains future work |
| `lifecycle_semantics` | Session/runtime lifecycle behavior that violates intended semantics |
| `telemetry_schema_gap` | Missing or incomplete observability metadata |
| `lint_refactor` | Recurring lint pressure indicating function-level design issues |
| `safety_guard_gap` | Gaps in dirty-file, mutation, or safety guard coverage |
| `coordination_gap` | Missing or incomplete cross-session coordination primitives |
| `documentation_gap` | Missing or outdated documentation |
| `provider_boundary_gap` | Provider/model boundary leakage or missing abstraction |
| `testing_gap` | Missing test coverage or test infrastructure |

## Severity Levels

| Severity | Description |
|----------|-------------|
| `critical` | Blocks safety or correctness for current features |
| `high` | Blocks a planned feature or creates significant risk |
| `medium` | Material constraint on future work, should be addressed within 2-3 slices |
| `low` | Nuisance or maintenance drag, address opportunistically |

## Status Values

| Status | Description |
|--------|-------------|
| `open` | Reported, not yet triaged |
| `accepted` | Triaged and acknowledged as valid debt |
| `planned` | Scheduled for a specific future slice |
| `in_progress` | Actively being addressed |
| `resolved` | Fixed and validated |
| `superseded` | Replaced by a newer finding or made irrelevant by other changes |
| `wont_fix` | Acknowledged but intentionally not addressed |

## Active Findings

### Architecture Debt

| ID | Title | Severity | Blocked By |
|----|-------|----------|------------|
| `finding_20260513_dirty_guard_singleton` | DirtyFileGuard singleton is shared across forked agents | medium | — |

### Lifecycle Semantics

| ID | Title | Severity | Blocked By |
|----|-------|----------|------------|
| `finding_20260513_clear_history_recaptures_guard` | clear_history() recaptures guard state instead of preserving conversation-only snapshot | medium | `finding_20260513_dirty_guard_singleton` |

### Telemetry Schema Gaps

| ID | Title | Severity | Blocked By |
|----|-------|----------|------------|
| `finding_20260513_checkpoint_coordination_unknown_metadata` | checkpoint and coordination tools have UNKNOWN determinism and mutation metadata | medium | — |

### Lint Refactor

| ID | Title | Severity | Blocked By |
|----|-------|----------|------------|
| `finding_20260513_search_replace_plr0914` | search_replace.py has recurring PLR0914/PLR0915 pressure | low | — |

## Schema

Each JSONL row conforms to `rig.relay.out_of_scope_finding.v1`:

```json
{
  "schema_version": "rig.relay.out_of_scope_finding.v1",
  "finding_id": "finding_<date>_<slug>",
  "created_at": "ISO-8601",
  "source_session_id": "session identifier",
  "source_task_id": "task or mission identifier",
  "repo_area": "module or subsystem path",
  "language": "python | shell | ...",
  "finding_kind": "architecture_debt | lifecycle_semantics | telemetry_schema_gap | lint_refactor | safety_guard_gap | coordination_gap | documentation_gap | provider_boundary_gap | testing_gap",
  "severity": "low | medium | high | critical",
  "status": "open | accepted | planned | in_progress | resolved | superseded | wont_fix",
  "title": "One-line summary",
  "evidence": "Concrete observations from the session",
  "why_it_matters": "Impact if left unresolved",
  "best_practice_anchor": "Reference to external standard or internal convention",
  "recommended_action": "Specific fix approach",
  "suggested_slice": "Human-readable name for the future mission slice",
  "related_files": ["paths"],
  "blocked_by": ["finding_ids"],
  "unblocks": ["capabilities this finding gates"]
}
```

## Language Practice References

Findings reference language-specific best-practice anchors documented in `docs/findings/language-practices/`:

- [Python](language-practices/python.md)

## Governance

- **Do not fix opportunistically.** Findings are recorded, classified, and turned into future work — not patched mid-mission.
- **Append-only JSONL.** Agents append new rows to `out-of-scope-findings.jsonl`. Never edit or remove existing rows.
- **Index is derived.** The Markdown index is regenerated from the JSONL. If the index is stale, regenerate it.
- **Link from final reports.** Every mission final report should include a small "Out-of-scope findings recorded" section linking back to this registry.

### Testing Gaps

| ID | Title | Severity | Blocked By |
|----|-------|----------|------------|
| `finding_20250613_validate_test_duplication` | test_validate.py and test_validate_git_state.py contain 19 duplicate/near-duplicate git-state tests | medium | — |

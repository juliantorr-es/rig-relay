# Ralph — Governed Background Maintenance Loop

Ralph is a governed background maintenance loop for Rig Relay.
Ralph reads evidence-backed state and proposes bounded maintenance
missions. Ralph never silently mutates risky state.

## Purpose

Ralph observes report projections, receipts, validation summaries,
and storage state. It ranks overlooked gaps and proposes one
bounded maintenance mission per scan. Ralph is projection-driven,
not chat-driven.

## Non-goals

Ralph is **not**:
- A daemon or scheduled background worker
- A task manager, feed, or workplace chat system
- A code-review bot or lint-fixing automaton
- A replacement for human judgment on architecture decisions
- A bypass around Relay permissions, reports, receipts, worktree
  isolation, or approval gates

## Relationship to Rig Relay

```
.rig/reports/reports.jsonl       raw report/event ledger
DuckDB query layer (future)      analytical queries over reports
report projectors                deterministic read models
Ralph                            reads projections, proposes missions
Relay                            executes approved Ralph missions
                                 through normal tool governance
rig.report / receipts            record what Ralph observed, proposed,
                                 changed, or declined
```

Ralph uses the same Relay substrate as every other agent path.
It has no special privileges or bypass powers.

## Autonomy tiers

| Tier | Name | Allowed | Forbidden |
|---|---|---|---|
| 0 | Observe | Read projections, receipts, validation summaries, storage state. Emit scan summaries. | Code writes. |
| 1 | Evidence write | Tier 0 + write reports, Ralph scan events, projection diagnostics, receipts. | Code writes. |
| 2 | Safe local maintenance | Tier 1 + rebuild derived indexes, run validators, refresh projections, compact safe local artifacts. | Source-code changes. |
| 3 | Patch proposal | Tier 2 + create isolated worktree and prepare bounded patch proposal. | Merge. Main-workspace mutation. |
| 4 | Main workspace mutation | Tier 3 + apply approved patches to main workspace. | Requires explicit user approval. |
| 5 | External side effects | Tier 4 + network calls, external service writes. | Requires explicit user approval and scoped credentials. |

Ralph v0 operates at **Tier 0 — Observe only**.

## Forbidden actions (all tiers)

Ralph must never:
- Mutate source code without explicit user approval
- Promote reports to canonical findings
- Delete canonical findings
- Bypass worktree isolation
- Make external network calls
- Trigger recursive self-scans
- Write to `docs/findings/out-of-scope-findings.jsonl`

## Stop conditions

Every Ralph scan must stop if:
- No projections found
- Maximum one recommended mission per scan
- Maximum 200 reports inspected
- Maximum 30 seconds elapsed
- Dirty-state ambiguity detected
- Missing projection metadata
- Malformed policy file
- No recursive self-triggering

## Input projections

Ralph may read:
- `docs/findings/out-of-scope-findings.jsonl` (finding registry)
- `.rig/reports/reports.jsonl` (raw report ledger, when present)
- `.rig/reports/indexes/report_summary.json` (projection index, when present)
- `.rig/reports/indexes/candidate_findings.json` (candidate findings, when present)
- `.rig/reports/indexes/open_raw_reports.json` (open reports, when present)

## Output events

Ralph may emit:
- `ralph.scan.started`
- `ralph.scan.completed`
- `ralph.mission_candidate.proposed`
- `ralph.scan.refused`

All output events are content-light: SHA256 hashes, counts,
and structured candidate summaries. No raw file contents or secrets.

## Candidate ranking (v1 policy)

1. projection corruption / malformed ledger diagnostics
2. high severity security_concern or data_race
3. stale canonical findings
4. candidate findings with evidence
5. duplicate clusters above threshold
6. validation gaps
7. architecture seams touching hot files
8. low-risk docs/projection maintenance

Score formula:
```
score = severity_weight + kind_weight + evidence_bonus
```

## v0 behavior

Ralph v0:
- Reads `docs/findings/out-of-scope-findings.jsonl`
- Ranks open findings by score
- Produces one recommended mission
- Writes nothing to disk (output returned in-memory only)
- Operates at Tier 0 — observe only

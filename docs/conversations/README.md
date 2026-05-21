# Conversation Summaries

Historical/reference stream for Rig Relay conversation summaries. These documents capture session-level architecture decisions, progress tracking, and operational context — distinct from audits (analysis), dogfood (self-usage proof), or how-to guides.

## Canonical Filename Pattern

```
YYYY-MM-DD--project--phase-range--topic--kind.md
```
- [2026-05-13--rig-relay--phase-1--receipt-gated-protected-intents--summary.md](2026-05-13--rig-relay--phase-1--receipt-gated-protected-intents--summary.md) — Reconciliation of the validation suite and implementation of Phase 1 receipt-gated intents.

Fields (separated by double hyphens `--`):

| Field | Rules | Examples |
|---|---|---|
| `YYYY-MM-DD` | ISO date of the conversation/session | `2026-05-13` |
| `project` | Lowercase kebab-case project key | `rig-relay`, `rig`, `anigma`, `intake` |
| `phase-range` | Lowercase kebab-case phase/sprint range | `phase-a-j`, `phase-k`, `sprint-001`, `adr-0010`, `no-phase` |
| `topic` | 3–8 lowercase kebab-case words | `orchestration-dataset-control-plane` |
| `kind` | One of: `summary`, `handoff`, `decision-log`, `incident`, `research`, `prompt-pack` | `summary` |

Rules:
- Use lowercase kebab-case throughout.
- Use double hyphens (`--`) between fields.
- Use single hyphens (`-`) inside each field.
- Keep `topic` to 3–8 words.
- Do not use spaces.
- Do not use vague names like `summary.md`, `notes.md`, or `conversation.md`.

## Index

| Date | Project | Phase/Sprint | Topic | Kind | File |
|---|---|---|---|---|---|
| 2026-05-13 | rig-relay | phase-a-j | orchestration dataset control plane | summary | [2026-05-13--rig-relay--phase-a-j--orchestration-dataset-control-plane--summary.md](2026-05-13--rig-relay--phase-a-j--orchestration-dataset-control-plane--summary.md) |
| 2026-05-14 | rig-relay | phase-n | drive-dep-isolation-stale-lease-cleanup | handoff | [2026-05-14--rig-relay--phase-n--drive-dep-isolation-stale-lease-cleanup--handoff.md](2026-05-14--rig-relay--phase-n--drive-dep-isolation-stale-lease-cleanup--handoff.md) |
| 2026-05-13 | rig-relay | phase-3 | desktop-projection-shell-pattern-port | summary | [2026-05-13--rig-relay--phase-3--desktop-projection-shell-pattern-port--summary.md](2026-05-13--rig-relay--phase-3--desktop-projection-shell-pattern-port--summary.md) |
| 2026-05-13 | rig-relay | phase-o-q | commercial license observations demo | summary | [2026-05-13--rig-relay--phase-o-q--commercial-license-observations-demo--summary.md](2026-05-13--rig-relay--phase-o-q--commercial-license-observations-demo--summary.md) |
| 2026-05-13 | rig-relay | phase-3 | facade extraction tool hardening search replace | summary | [2026-05-13--rig-relay--phase-3--facade-extraction-tool-hardening-search-replace--summary.md](2026-05-13--rig-relay--phase-3--facade-extraction-tool-hardening-search-replace--summary.md) |
| 2025-06-13 | rig-relay | no-phase | test suite quality audit | summary | [2025-06-13--rig-relay--no-phase--test-suite-quality-audit--summary.md](2025-06-13--rig-relay--no-phase--test-suite-quality-audit--summary.md) |
| 2026-05-13 | rig-relay | phase-p3 | audit trail adapter coordination | summary | [2026-05-13--rig-relay--phase-p3--audit-trail-adapter-coordination--summary.md](2026-05-13--rig-relay--phase-p3--audit-trail-adapter-coordination--summary.md) |
| 2026-05-14 | rig-relay | phase-3-to-5 | fleet coordination completion | summary | [2026-05-14--rig-relay--phase-3-to-5--fleet-coordination-completion--summary.md](2026-05-14--rig-relay--phase-3-to-5--fleet-coordination-completion--summary.md) |
| 2026-05-14 | rig-relay | phase-k | context compiler phase 3 repo index | summary | [2026-05-14--rig-relay--phase-k--context-compiler-phase-3-repo-index--summary.md](2026-05-14--rig-relay--phase-k--context-compiler-phase-3-repo-index--summary.md) |
| 2026-05-18 | rig-relay | no-phase | frontend boot stabilization fsm effects | summary | [2026-05-18--rig-relay--no-phase--frontend-boot-stabilization-fsm-effects--summary.md](2026-05-18--rig-relay--no-phase--frontend-boot-stabilization-fsm-effects--summary.md) |
| 2026-05-20 | rig-relay | no-phase | analytics data lake hardening lane | summary | [2026-05-20--rig-relay--no-phase--analytics-data-lake-hardening-lane--summary.md](2026-05-20--rig-relay--no-phase--analytics-data-lake-hardening-lane--summary.md) |

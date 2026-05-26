# Orchestrator, Subagent, Model, and Ralph Roles

Rig Relay uses an explicit role model to separate management, execution,
capability configuration, and autonomous background work.

## Roles

```
User → Orchestrator → Subagent Assignments (specialist workers)
                     → Ralph (autonomous background convergence)
Ralph → RalphReport → Orchestrator Review → Adoption Decision
```

### Orchestrator
The manager/supervisor. Creates sprints, assigns missions to configured
subagent profiles, monitors lane projections, receives autonomous Ralph
reports, and coordinates review/adoption decisions.

Not a generic worker. The orchestrator profile has `profile_kind=orchestrator`
(defined separately) and should not be represented as a normal worker lane.

### Subagent Profiles
Configured specialist roles with specific capabilities, trust tiers,
and lane behavior. Profiles define:
- `profile_kind`: `standard_subagent` (assignable) or
  `autonomous_background_worker` (Ralph)
- `assignable`: whether the orchestrator can assign missions
- `reports_to_orchestrator`: whether the worker reports autonomously
- `allowed_capabilities` / `forbidden_capabilities`
- `trust_tier`: observe_only → safe_local → patch_proposal → main_mutation

Demo profiles: runtime_agent, frontend_agent, docs_agent, tests_agent,
analytics_agent, ralph_background_worker.

### Model/Provider Bindings
Runtime capability configuration attached to profiles. Model/provider
selection is NOT role identity — it is capability config.

Each profile has a `default_binding_id`. Mission assignments may override
the binding via `AssignmentBindingOverride`.

Local/demo mode uses `binding-local-demo` which requires no network and
no API key.

### Ralph
Autonomous background convergence worker. Profile has:
- `profile_kind=autonomous_background_worker`
- `assignable=false` — not a normal assignable subagent
- `reports_to_orchestrator=true` — delivers RalphReports
- `requires_worktree=true` — works in isolated lanes
- `merge_enabled=false`, `push_enabled=false`

Ralph observes projections across all lanes, identifies convergence
threats, works inside Ralph-owned worktrees, commits to Ralph branches,
seals review bundles, and delivers RalphReports to the orchestrator.

### RalphReport
Durable report from Ralph to orchestrator after lane completion, blockage,
or risk detection. Contains:
- `report_kind`: completed_lane, blocked_lane, convergence_seam, etc.
- `review_bundle_sha256`, `adoption_proposal_id`
- `target_assignment_id` if relevant to an active assignment
- `status`: created → delivered_to_orchestrator → reviewed → accepted/rejected/deferred

### Review Session
Orchestrator consumes Ralph reports, review bundles, and adoption
proposals. The review session is explain-only by default — no merge,
no push, no mutation.

### Adoption/Merge/Push Gates
All remain separately gated. Review acceptance does not execute merge.
Merge requires adoption approval. Publishing checkpointed review slices requires named milestone authorization and preproduction approval. Push remains separate from merge.

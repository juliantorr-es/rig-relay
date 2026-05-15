# Context Observability Doctrine

**Status:** Phase 1 — observation-first, policy-later.

## Core Rule

**Rig observes first, nudges second, blocks last.**

Context observations are telemetry, not permissions. They correlate tool
calls with the context snapshot that was active at the time. They never
block tool execution.

## Why Observation Before Policy

1. **We do not yet know which signals predict failures.** Collision
   warnings may be harmless 90% of the time. Dirty-file edits may be
   the intent. Hard-blocking based on hunches creates frustration, not
   safety.

2. **Agent autonomy generates training data.** If the harness prevents
   all interesting mistakes, the telemetry becomes sterile. Let agents
   operate, watch them closely, and turn recurring failure modes into
   small, targeted affordances later.

3. **Separation of concerns.** Correlation is not enforcement.
   Observation is not permission. Risk score is not refusal. These are
   independent outputs:

```
Tool policy result:      allow / refuse / require approval
Context observation:     risky / clean / unknown / collision / ignored_context
```

4. **Policy should be evidence-driven.** Future policy changes must be
   justified by observed telemetry, not vibes. The observation layer
   provides the data to answer: "Did touching claimed files actually
   cause regressions?" before adding a block.

## What Observations Record

Each observation records whether the tool's target paths:

- Matched a recommended context file
- Overlapped an active work lane
- Touched a dirty path
- Touched a soft-warning / coordination-risk path
- Touched a hard-denied / do-not-touch path
- Were blocked by policy (separate from observation, for cross-reference)

All observations are `observation_only: true` — the system never uses
observations to make decisions.

## Where Observations Go

Currently: emitted as structured log lines (JSON). Future: stored in
the telemetry pipeline alongside tool receipts and session records.

Observations are content-light: no raw file contents, diffs, secrets,
or prompts.

## Relation to get_context

`rig.get_context` returns the battlefield map. The observation layer
correlates tool calls against the last known map. Together they form:

```
get_context         = map of the battlefield
context observation = record of where the agent stepped
validators/outcomes = whether stepping there caused damage
analysis later      = discover which warnings matter
policy later        = only add leashes where telemetry proves they help
```

## Policy Separation

This file documents observation-only behavior. Any future policy change
(automatic refusal, approval requirement, nudge) must be documented in
a separate policy file and justified by observation data.

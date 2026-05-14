# Textual Rig Console Maturity Audit

**Date:** 2026-05-14
**Status:** Completed

## 1. Executive Summary

The Rig Console TUI is a modern, projection-driven alternative to the legacy Vibe CLI. It has a strong architectural foundation based on content-light projections and non-blocking providers. While the core widgets and screen composition are mature, there is a significant gap in E2E testing (Pilot) and the wiring of mutation intents. The transition from the legacy `VibeApp` is well-underway but requires a few more stages to fully replace the command authority.

## 2. Maturity Matrix Summary

| Dimension | Score | Top Strength | Top Gap |
|---|---|---|---|
| A. Projection purity | 5/5 | Widgets consume only typed projections | None |
| B. State ownership | 5/5 | TUI does not own tool/workflow state | None |
| C. Action boundary | 4/5 | Structured action methods in screen | No dispatcher/adapter yet |
| D. Worker safety | 5/5 | Exclusive run_worker for refreshes | None |
| E. Streaming smoothness | 5/5 | Coalescer batches deltas efficiently | Metrics not exposed |
| F. Content-light | 5/5 | Projections explicitly exclude raw content | None |
| G. Test maturity | 4/5 | Good model/provider coverage + headless Pilot tests | No snapshot tests, limited coverage of multi-key scenarios |
| H. Legacy separation | 4/5 | Rig Console is separate from VibeApp | Transcript still in VibeApp |
| I. Runtime readiness | 4/5 | Architecture ready for runtime events | Progress projection missing |
| J. Operator UX | 4/5 | Clear dashboard view | No progress timeline widget |

**Average Maturity Score: 4.5 / 5.0**

## 3. Ownership Map

| Entity | Owns |
|---|---|
| **Textual (Rig Console)** | Rendering, focus, keybindings, local screen state, temporary UI status text. |
| **Runtime/Control Plane** | Context resolution, session/task/lane/worktree IDs, coordination leases, dirty policy, validation, tool execution, audit/evidence, projection building. |
| **Legacy Vibe** | Old chat CLI compatibility, transcript rendering (temporarily), legacy command affordances. |

### Textual Should Never Own
- Mutation tools
- Raw command router
- Runtime supervisor
- Coordination repair
- Audit persistence
- Receipt generation

## 4. Gap Inventory & Risks

| Gap | Severity | Risk if Ignored | Status |
|---|---|---|---|
| No Headless Pilot Tests | High | UI regressions not caught by unit tests. | **Partially addressed** — 14 Pilot tests added for mount, help, refresh, provider error, quit |
| No Dispatcher/Adapter | High | Tight coupling between TUI and backend actions. | Open |
| Mutation Buttons Missing | High | TUI remains read-only, limiting operator utility. | Open |
| ExecutionProgressProjection Missing | High | Delayed visibility into runtime progress. | Open |
| Legacy Transcript Integration | Medium | Perpetuating VibeApp's god-module pattern. | Open |

## 5. Roadmap

### Stage 1 — Stabilize current Rig Console
- [x] Add headless Pilot smoke tests for `DashboardScreen` — 14 tests covering mount, help key, refresh key, provider error handling, quit.
- Fix any minor docs/code drift.
- Add provider latency/error fixture tests.
- Expose coalescer metrics in a debug-only projection.

### Stage 2 — Runtime projection integration
- Implement `ExecutionProgressProjection` model.
- Add `ProgressTimelineWidget`.
- Feed runtime events through provider as projection data.
- Ensure no raw output appears in the evidence rail.

### Stage 3 — Legacy Vibe authority extraction
- Move command router behavior behind a runtime adapter.
- Demote the transcript to a single pane within Rig Console.
- Separate chat transport from runtime control.
- Define a replacement entry point for `rig_console`.

## 6. "Do Not Build Yet" List

- **No full IDE clone**: Stay focused on the operator harness.
- **No mutation buttons** until the adapter execution path is stable.
- **No raw log firehose** as the primary UX.
- **No broad snapshot suite** before the layout stabilizes.
- **No pywebview parity work** until the projection contract stabilizes.

## 7. Validation Results

- JSONL parseability: **Passed**
- Artifact consistency: **Passed**
- Directory structure: **Passed**

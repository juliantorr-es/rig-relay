# Textual Rig Console

## Status

Deprecated. The Textual Rig Console is retained only as a development
compatibility surface while the pywebview cockpit is the primary product UI.

## Route 3 Compatibility Mode

Rig Console now follows a prompt-first compatibility shell model:

- Ordinary prompt text goes through the coding-session bridge and real
  `AgentLoop.act(...)` runtime path when runtime mode is available.
- Explicit slash commands own governable actions such as validate, queue,
  fleet, router, mission, inspect, and help.
- The UI should feel like a coding-agent terminal, not an admin dashboard.
- Hardened Rig paths are preferred when they exist.
- Base vibe session behavior is only used through the compatibility bridge.
- Widgets must not import raw tools or agent-loop internals directly.

## Launch

Use `rig-relay` for the default product launcher. `rig-console-textual` has
been removed. The legacy Textual app remains only for compatibility and test
coverage.

```bash
uv run rig-relay
```

```bash
uv run rig-console
```

Available flags:

- `--mode fixture|runtime`
- `--session-id <id>`
- `--session-path <path>`
- `--workspace-root <path>`
- `--coordination-root <path>`
- `--audit-root <path>`
- `--refresh-interval <seconds>`

## Modes

### Fixture mode

Fixture mode is the safe default. It renders canned content-light projections
for layout checks and headless smoke tests.

### Runtime mode

Runtime mode reads existing projection artifacts in a read-only way. It
tolerates missing roots and missing files. It does not write to disk, mutate the
workspace, or invoke raw tool execution.

## What The Dashboard Shows

The dashboard is built from content-light projections and is intentionally plain for stable dogfooding. By default, it shows a vertically stacked layout:

- **Top**: Compact header and status bar for session/queue metrics.
- **Main**: Session activity (left) and evidence rail (right) for real-time situational awareness.
- **Bottom**: PromptBar for input, activity log for recent history, and a persistent footer hint.

Experimental or high-density dashboards are hidden by default to reduce visual noise:

- **Fleet Panel (`f`)**: Agent workforce monitoring.
- **Queue Panel (`u`)**: Detailed queue orchestration state.
- **Inspector Drawer (`i`)**: Metadata and summary inspection.
- **Mission Router (`m`)**: Multi-step mission plan previews (Phase 0).
- **Progress Timeline**: Execution event distribution.

## Keybindings

- `Enter` — Focus prompt
- `r` — Refresh projection
- `v` — Run validate (async)
- `x` — Run next queued item
- `f` — Toggle fleet panel
- `u` — Toggle queue panel
- `i` — Toggle inspector drawer
- `?` or `h` — Help overlay
- `Esc` — Cancel active turn / Discard plan / Close overlay
- `q` — Quit

## Design Philosophy: "Stable & Boring"

The legacy TUI was designed to be a transparent, reliable command center. It uses standard Textual theme variables, avoids theatrical visual effects, and enforces a strict content-light boundary. It is optimized for keyboard-only operation during deep coding tasks.

The Prompt Bar (`vibe/cli/textual_ui/rig_console/widgets/prompt_bar.py`) is the
**primary** input surface. It uses Textual `Input` (single line).

Behavior:
- **Enter** submits ordinary text to the session bridge.
- **Slash commands** are explicit escape hatches and do not share the normal
  prompt path.
- **Double-slash escape** (`//hello`) submits a literal `/hello` prompt.
- **Empty/whitespace** input does nothing.
- **Successful submission** clears the input only after the bridge accepts it.
- **Rejected submission** keeps the current input in place.
- **Focus**: Press `f` to focus the prompt bar.

The prompt bar does NOT execute anything directly. It only emits text into the
coding-session bridge or explicit slash-command handlers.

### Live Turn Streaming

When the user submits a normal prompt:

1. PromptBar disables immediately (`disabled=True, "Starting"`).
2. `DashboardScreen._do_turn(text)` worker starts via `run_worker`.
3. `RuntimeSessionAdapter.submit_user_message(text)` returns immediately
   (`accepted=True, status="running"`). A background task iterates
   `AgentLoop.act(...)` events and stores them incrementally.
4. Dashboard polls `provider.events_since(cursor)` every 50ms.
5. Each new event updates the TranscriptWidget (via `append_item`), the
   ActivityLog (via `_set_status`), and the StatusBar.
6. When the bridge emits a `turn_status` event (completed/failed/cancelled),
   the polling loop exits.
7. A final `provider.snapshot()` replaces the transcript projection.
8. PromptBar re-enables (`disabled=False, "Ready"`).

Escape key calls `action_cancel_or_discard()` which invokes
`provider.cancel_turn()`, cancelling the background `asyncio.Task` and
propagating `CancelledError` through `AgentLoop`. Cancel is UI-safe even if
the backend cannot fully interrupt the LLM mid-turn—the subscription stops,
and state reverts to `turn_status="cancelled"`.

## Unified Prompt Input

The **PromptBar** is the single active input surface for the dashboard. It handles:

- Ordinary coding prompts through the session bridge
- Explicit slash commands for governable actions
- Transcript-style rendering of user and assistant text

The bridge normalizes session events into content-light projections. Generic
panels do not render raw stdout, stderr, diffs, file contents, argv arrays,
secrets, or raw model payloads.

## Prompt Bridge

The session bridge owns the prompt-to-session boundary:

- `FixtureSessionAdapter` produces deterministic transcript items for tests.
- `RuntimeSessionAdapter` reuses the base vibe `AgentLoop.act(...)` turn path.
- Dashboard widgets only talk to the bridge/provider boundary.
- Transcript projections stay content-light outside the conversation surface.

## Queue Runner Integration

The queue panel is backed by a **QueueRunnerBridge** — the TUI's sole surface
for triggering queue item execution through governed runtime paths.

### Architecture

```
Queue Panel (read-only projection)
        │
        ▼  (action: queue_run_next)
Dashboard action handler
        │
        ▼  (Textual worker)
QueueRunnerBridge.run_next()
        │
        ▼
QueueRunnerBridge dispatches the selected item once
        │
        ├── VALIDATE  → runtime_exec intent → RuntimeToolExecutionRunner.execute_runtime_exec()
        └── RUNTIME_EXEC → runtime_exec intent → RuntimeToolExecutionRunner.execute_runtime_exec()
```

The TUI never calls raw tools (`BaseTool`, `ToolError`, file I/O tools, bash)
directly. All executable queued actions route through the governed
`FleetQueueRunner` / `RuntimeToolExecutionRunner` path.

### Supported Queue Item Kinds

| Kind | Runtime Method | Notes |
|---|---|---|
| `VALIDATE` | `execute_runtime_exec()` | Lint/type-check the workspace through governed runtime_exec |
| `RUNTIME_EXEC` | `execute_runtime_exec()` | Run a named sub-tool |
| `MESSAGE` | _(none)_ | Completes synchronously, no exec |
| `HANDOFF_NOTE` | _(none)_ | Completes synchronously, no exec |

### Phase 0 Behavior (Current)

- **One item per action**: Each `queue_run_next` call processes exactly one
  queue item. No looping.
- **Content-light results**: `FleetQueueRunnerResult` contains only metadata:
  `decision`, `queue_item_id`, `runtime_result_sha256`, `receipt_sha256`,
  `tool_name`, `error_kind`, `reason`, `changed_paths`. No raw content.
- **Missing-root safety**: When `coordination_root` or `executor` is `None`,
  `run_next()` returns a blocked result (`decision="blocked"`,
  `error_kind="missing_runner_roots"`). Never crashes, never writes to
  `~/.rig/relay`.
- **Empty-queue idle**: When no items are eligible, returns
  `decision="idle"` with `queue_item_id=None`.

### Deferred Actions

The following are explicitly **not** exposed as queue buttons in Phase 0:

- Direct `write_file` / `search_replace` / `bash` tool buttons
- File-system mutation from the TUI
- Any action that bypasses `FleetQueueRunner`

These may be added in future phases as `RUNTIME_EXEC` items with governed
sub-tools.

### Queue Action Keybindings

- `u` — Toggle queue panel
- `j` / `k` — Navigate queue items
- `o` — Inspect selected queue item
- `Ctrl+r` — Run next queued item (via QueueRunnerBridge)
- `Ctrl+v` — Enqueue a validate item
- `Ctrl+Enter` — Request steering for the current task
- `f` — Toggle fleet panel
- `Shift+f` — Inspect selected fleet summary
- `Ctrl+f` — Refresh fleet snapshot

## What It Refuses To Show

The console must not display raw:

- `stdout`
- `stderr`
- `content`
- `file_contents`
- `chunk_text`
- `old_text`
- `new_text`
- `diff`
- `patch`
- `prompt`
- `secret`
- `argv`
- `snippet`

Only metadata, counts, summaries, hashes, and safe display strings belong in
the projection layer.

## Contract Boundaries

- Runtime adapters own execution and govern mutation.
- Audit events provide content-light history and proof.
- Coordination leases and blockers provide read-only state for concurrent work.
- The Textual UI is a consumer of those projections, not a tool executor.
- Mutating actions must continue to route through governed intents and runtime
  adapters.

## Keybindings

- `r` refresh
- `?` or `h` help
- `t` toggle detail hints
- `q` quit

No mutation keybindings are defined here.

## Command Palette

The dashboard also exposes safe actions through the Textual command palette.
Entries are auto-generated from `SAFE_ACTIONS` in `actions.py`:

- Refresh
- Run Validate
- Help
- Toggle Details
- Queue Message
- Steer Current Task
- Clear Input
- Toggle Queue Panel
- Run Next Queued Item
- Queue Validate
- Refresh Queue
- Runtime Status
- Leases
- Audit Timeline
- Copy Receipt Ref

Command execution routes through the dashboard action registry. The palette is
read-only and must not bypass governed runtime execution.

## Queue Actions

Three safe queue actions are exposed through palette/keybindings:

| Action | Key | Behavior |
|---|---|---|
| Run Next Queued Item | `action_queue_run_next` | Runs one eligible queue item through `FleetQueueRunner` via the `QueueRunnerBridge` |
| Queue Validate | `action_queue_validate` | Enqueues a validate item; does NOT execute it |
| Refresh Queue | `action_queue_refresh` | Rebuilds queue projection from stored events |

**One item per action.** Phase 0 — no batch execution. Each call to
`action_queue_run_next` processes exactly one item via `runner.run_once()`.

**Non-blocking.** Queue actions use Textual `run_worker()` to avoid freezing
the UI. Running state is shown in the footer status line.

**State transitions.** After execution, `FleetQueueRunner` transitions items
through event-sourced states: `queued → running → completed / failed / blocked`.
Failures from the runner (e.g. `mark_failed`, `mark_blocked`) are reflected in
queue projection counts.

**Missing roots.** If `QueueRunnerBridge` is unavailable (no coordination root
or runtime executor), actions return `blocked` status with a descriptive
`error_kind`. The UI shows the status in the footer and never crashes.

**No bypass.** Queue actions never call raw tools directly. All executable
items route through `FleetQueueRunner._dispatch_runtime_exec()` which creates
a `RuntimeToolIntent` and resolves through governed `runtime_exec` paths.

## Queue Runner Integration

The `QueueRunnerBridge` in `queue_runner.py` is the TUI's sole surface for
triggering queue item execution. It:

- Locates the `FleetQueue` at `<coordination_root>/queue/events.jsonl`
- Constructs a `FleetQueueRunner` with the coordination root's executor
- Calls `run_once()` for one item per action
- Returns a `FleetQueueRunnerResult` with content-light metadata only
- Never blocks — callers use Textual workers

The bridge is lazily constructed by `RuntimeDashboardProjectionProvider` via
`_queue_bridge()`, which creates a `QueueRunnerBridge` from the provider's
`coordination_root` and `_runner()` when first needed.

## Deferred Actions (Phase 0)

The following are NOT implemented in Phase 0:

- **Steer current task** — steering is a safe-placeholder; no live steering semantics
- **Full prompt persistence** — prompt bodies are stored behind `payload_ref` only; no durable persistence UI
- **Multi-item scheduler** — one item per action; no batch execution
- **write_file/search_replace/bash dedicated controls** — not added to TUI
- **Patch proposal review/apply** — future phase
- **Persistent multi-agent queue orchestration** — future phase

## UI Truthfulness Audit

Adapted from Intake's UI inventory pattern. Every visible surface is categorized:

| Surface | Category | Status |
|---|---|---|
| PromptBar input | REAL | Functional, handles submit/slash/escape |
| TranscriptWidget | REAL | Shows user/assistant/status events incrementally |
| StatusBar (mode/hint/metrics) | REAL | Reads from projection, renders live |
| FooterStatusWidget (hints) | REAL | Reads from projection |
| ActivityLogWidget | REAL | Shows compact action status entries |
| OperatorHeaderWidget | PARTIAL | Title/subtitle rendered, session details partial |
| SessionPaneWidget | PARTIAL | Shows summary, no live turn progress |
| EvidenceRailWidget | PARTIAL | Shows receipt metadata, no live updates |
| QueuePanelWidget | REAL | Toggleable, reads queue projection |
| FleetPanelWidget | REAL | Toggleable, reads fleet projection |
| InspectorDrawerWidget | REAL | Toggleable, navigates items |
| MissionRouterPanelWidget | REAL | Toggleable, reads mission projection |
| ProgressTimelineWidget | PARTIAL | Reads execution_progress, no live update |
| HelpOverlayWidget | REAL | Toggleable help text |
| NotificationPanelWidget | REAL | Shows recovery hints |
| /validate command | REAL | Routes to governed validate |
| /queue, /fleet, /inspect | REAL | Toggle panels |
| /router, /plan, /mission | REAL | Routes mission batch |
| /doctor command | REAL | Runs diagnostics checks |
| /help command | REAL | Shows help overlay |

**Definitions:**
- **REAL**: Backed by functioning code; does what it says.
- **PARTIAL**: Works but surface is incomplete or lacks live updates.
- **PLACEHOLDER**: Exists but is not wired to backend.
- **UNWIRED**: Code present but no UI surface accessible.

There are currently no PLACEHOLDER or UNWIRED surfaces. The two PARTIAL surfaces (SessionPaneWidget, EvidenceRailWidget, ProgressTimelineWidget) show static snapshot data rather than live streaming — acceptable for Phase K dogfood.

## Related Docs

- [Desktop Cockpit UI](desktop-cockpit-ui.md)
- [Runtime Tool Invocation Execution](runtime-tool-invocation-execution.md)
- [Usage Data Doctrine](usage-data-doctrine.md)

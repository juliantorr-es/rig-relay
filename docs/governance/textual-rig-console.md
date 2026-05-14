# Textual Rig Console

## Status

Supported. The Textual Rig Console is the terminal-native coding cockpit for
Rig Relay. The pywebview cockpit remains the desktop cockpit.

## Launch

Use `rig-relay` for the default product launcher. `rig-console` remains an
explicit alias.

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
- `Esc` — Discard plan / Close overlay
- `q` — Quit

## Design Philosophy: "Stable & Boring"

The TUI is designed to be a transparent, reliable command center. It uses standard Textual theme variables, avoids theatrical visual effects, and enforces a strict content-light boundary. It is optimized for keyboard-only operation during deep coding tasks.

The Prompt Bar (`vibe/cli/textual_ui/rig_console/widgets/prompt_bar.py`) is the
**primary** input surface. It uses Textual `Input` (single line).

Behavior:
- **Enter** queues a message. The callback routes through
  `DashboardScreen._handle_queue_input`, creating a `QueueItemProjection` with
  `kind="message"` and `status="queued"`.
- **Empty/whitespace** input does nothing.
- **Successful queue** clears the input and shows "Queued" status.
- **Missing queue root** is safe — the bar shows disabled/refused status.
- **Prompt body** is stored behind a `payload_ref` (`local://queue/<uuid>`).
  The generic queue/fleet projection shows only the sanitized summary, not
  the raw prompt body. Full prompt body persistence is deferred.
- **Focus**: Press `f` to focus the prompt bar.

The prompt bar does NOT execute anything directly. It only creates queue items.
Executable work routes through `FleetQueueRunner` → `runtime_exec`.

## Unified Prompt Input

The **PromptBar** is the single active input surface for the dashboard. It handles:
- Single-line instructions (direct enqueuing)
- Multi-line or `/batch` missions (routed via `MissionRouter`)
- Contextual steering (planned)

The queue input bar is a local-only cockpit surface for staging the next
message or action. It is read-only with respect to the governed runtime:

- `Enter` queues the current message
- `Shift+Enter` inserts a newline when multiline editing is supported
- `Ctrl+Enter` requests steering for the current task

Queue messages are not exposed as raw prompt text in projections. The TUI keeps
the body behind a local-only payload boundary and only surfaces a content-light
summary plus an opaque `payload_ref` in queue projections. Steering is explicit
and visibly labeled, but is safe-placeholder behavior in this mission and does
not invoke live steering semantics.

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

## Related Docs

- [Desktop Cockpit UI](desktop-cockpit-ui.md)
- [Runtime Tool Invocation Execution](runtime-tool-invocation-execution.md)
- [Usage Data Doctrine](usage-data-doctrine.md)

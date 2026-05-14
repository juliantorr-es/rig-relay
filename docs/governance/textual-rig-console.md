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

The dashboard is built from content-light projections. It may show:

- session or mission identity
- runtime adapter status
- recent execution events
- execution progress
- active leases or blockers
- queue state and queue item summaries
- evidence receipts
- validation or test summaries
- git branch and HEAD summary when available
- safe footer hints and keybindings

## Inspector Drawer

The dashboard includes a keyboard-driven inspector drawer for the currently
selected content-light item. It can show summaries for runtime audit events,
recent runtime supervisor invocations, lease/blocker state, and evidence
receipts. The drawer displays only metadata: IDs, status, tool names,
timestamps, durations, hashes, changed path refs, and already-sanitized error
or refusal details.

The inspector is read-only. It does not expose stdout, stderr, content,
file_contents, diffs, patches, prompts, secrets, argv, or snippets. Use `i`
to open or close the drawer, `n`/`p` to move through items, and `c` to copy a
safe hash/reference when available.

## Queue Panel

The queue panel is a read-only projection of the current fleet queue snapshot.
It shows queue counts, the running item when present, blocked items, and recent
completed, failed, or cancelled items. Queue items are content-light summaries:
IDs, kind, status, title or summary, payload refs, timestamps, sanitized
blocked reasons, and safe receipt/runtime hashes when available.

The panel never mutates queue state and never executes queued actions. Use `u`
to toggle the panel, `j`/`k` to navigate queue items, and `o` to send the
selected queue item to the inspector when both views are present.

## Queue Input

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
FleetQueueRunner.run_once()
        │
        ├── VALIDATE  → RuntimeToolExecutionRunner.execute_validate()
        └── RUNTIME_EXEC → RuntimeToolExecutionRunner.execute_runtime_exec()
```

The TUI never calls raw tools (`BaseTool`, `ToolError`, file I/O tools, bash)
directly. All executable queued actions route through the governed
`FleetQueueRunner` / `RuntimeToolExecutionRunner` path.

### Supported Queue Item Kinds

| Kind | Runtime Method | Notes |
|---|---|---|
| `VALIDATE` | `execute_validate()` | Lint/type-check the workspace |
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

The dashboard also exposes the same safe read-only actions through the Textual
command palette:

- Refresh
- Help
- Toggle Details
- Queue Message
- Steer Current Task
- Clear Input
- Toggle Queue Panel
- Runtime Status
- Leases
- Audit Timeline
- Copy Receipt Ref

Command execution routes through the dashboard action registry. The palette is
read-only in this mission and must not bypass governed runtime execution.

## Related Docs

- [Desktop Cockpit UI](desktop-cockpit-ui.md)
- [Runtime Tool Invocation Execution](runtime-tool-invocation-execution.md)
- [Usage Data Doctrine](usage-data-doctrine.md)

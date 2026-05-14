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
IDs, kind, status, title or summary, timestamps, sanitized blocked reasons, and
safe receipt/runtime hashes when available.

The panel never mutates queue state and never executes queued actions. Use `u`
to toggle the panel, `j`/`k` to move through queue items, and `o` to send the
selected queue item to the inspector when both views are present.

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

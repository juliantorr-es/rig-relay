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
- evidence receipts
- validation or test summaries
- git branch and HEAD summary when available
- safe footer hints and keybindings

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

## Related Docs

- [Desktop Cockpit UI](desktop-cockpit-ui.md)
- [Runtime Tool Invocation Execution](runtime-tool-invocation-execution.md)
- [Usage Data Doctrine](usage-data-doctrine.md)

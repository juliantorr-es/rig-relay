# Textual Rig Console — Slice 5.1: Worker-Safe Dashboard Refresh

## Status

**Complete.** Moves `DashboardScreen.action_refresh()` behind a Textual
Worker boundary so provider reads (`build_receipt_index`) cannot block
the UI event loop as receipt/session data grows.

## Motivation

Slice 5 added `RuntimeDashboardProjectionProvider` — a real, read-only
provider that reads session observability JSONL via `build_receipt_index()`.
For small receipts this is fast (<1ms), but as session data accumulates
the read could take tens of milliseconds or more. Textual guidance is
to use workers for any work that may take more than a few milliseconds.

Previously, `action_refresh()` awaited `provider.dashboard_projection()`
directly in the message handler — blocking widget updates and keystroke
processing until the read completed.

## What Changed

### `DashboardScreen` (`screens/dashboard.py`)

1. **`action_refresh()` rewritten** — no longer awaits the provider
   directly. Instead it:
   - Returns immediately with a status message ("Refresh started")
   - Schedules the real work via `self.run_worker(self._do_refresh, exclusive=True, exit_on_error=False)`
   - Without a provider, returns early (no worker, no status)

**Important:** `action_refresh` passes `self._do_refresh` (a bound method
callable) rather than `self._do_refresh()` (a coroutine). Textual's
`run_worker` accepts both — when given a callable it calls it to obtain
the coroutine. When `run_worker` is patched in tests, the mock receives
a bound method (never an orphaned coroutine), avoiding `RuntimeWarning:
coroutine '_do_refresh' was never awaited`.

2. **`_do_refresh()` added** — async method that runs inside a Textual
   Worker:
   - Calls `provider.dashboard_projection()` in the background
   - On success: calls `update_projection()`, sets `_last_refresh_at`,
     clears `_last_refresh_error`, shows "Refresh complete"
   - On `asyncio.CancelledError`: silently exits (worker was replaced
     by a newer refresh via `exclusive=True`)
   - On other exceptions: sanitizes the error (first line, max 100 chars),
     stores it in `_last_refresh_error`, shows "Refresh failed: <msg>"

3. **Refresh state fields added** to `__init__`:
   - `_refresh_in_progress: bool` — True while a worker is active
   - `_last_refresh_error: str | None` — sanitized error message
   - `_last_refresh_at: str | None` — ISO-8601 timestamp of last success

### Worker Behavior

| Aspect | Decision |
|--------|----------|
| Mechanism | `self.run_worker(coro, exclusive=True, exit_on_error=False)` |
| Overlapping refreshes | `exclusive=True` cancels the previous worker before starting a new one |
| Error handling | `exit_on_error=False` prevents unhandled exceptions from crashing the app; exceptions are caught in `_do_refresh` |
| No-provider path | `action_refresh` returns immediately, no worker started, no status change |

### Error Sanitization

Errors from `provider.dashboard_projection()` are sanitized before
display:
- Only the first line is kept (tracebacks are suppressed)
- Truncated to 100 characters max
- Displayed as `Refresh failed: <sanitized>` in the footer

No raw traceback appears in the UI.

### No-Provider Safety

When `DashboardScreen` is instantiated without a provider:
- `action_refresh()` returns immediately (no worker started)
- Footer/status unchanged
- All existing no-provider tests pass unchanged

## Updates to Existing Files

| File | Change |
|------|--------|
| `vibe/cli/textual_ui/rig_console/screens/dashboard.py` | `action_refresh` rewritten, `_do_refresh` added, refresh state fields added |
| `tests/cli/textual_ui/rig_console/test_dashboard_screen.py` | 11 new tests for worker dispatch, worker body, error handling, state tracking |
| `docs/ui/textual-rig-console-slice-5-runtime-provider.md` | "Intentionally does not implement workers" removed; Future Provider Path updated |

## What This Slice Intentionally Does Not Do

- Does not modify legacy VibeApp or its TCSS files
- Does not wire mutation actions
- Does not execute validate or any tool from the TUI
- Does not read coordination state or session lifecycle files
- Does not parse raw observability payloads in widgets/screens
- Does not add real-time/frequent polling
- Does not resolve branch_name (not available from receipt index alone)
- Does not change the provider abstraction — provider remains read-only,
  widget/screen code still never parses logs
- Does not add persistent state — refresh state is local UI only

## Next Slice (6)

Add coordination state reading for branch/lane/heartbeat fields in
the `SessionPaneProjection`.

## Cross-References

- [Slice 5: Runtime Dashboard Provider](textual-rig-console-slice-5-runtime-provider.md)
- [DashboardScreen source](../../vibe/cli/textual_ui/rig_console/screens/dashboard.py)
- [Providers module](../../vibe/cli/textual_ui/rig_console/providers.py)

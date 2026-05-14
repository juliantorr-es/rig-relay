# Vibe / Rig Compatibility Bridge

## Purpose

This document records the temporary Route 3 bridge between the base vibe session
path and the Rig Relay harness.

## Policy

- Ordinary prompt text enters through `CodingSessionBridge`.
- `RuntimeSessionAdapter` uses the base vibe `AgentLoop.act(...)` turn path for
  normal coding prompts when no hardened Rig equivalent exists.
- `FixtureSessionAdapter` provides deterministic transcript events for tests.
- Hardened Rig primitives stay authoritative for validate, queue, fleet,
  mission routing, audit, receipts, and governance.
- Widgets and Textual surfaces must call the bridge or provider boundary, not
  raw agent-loop, tool, or SDK internals.

## Content-Light Rules

- Transcript projections may show user-visible and assistant-visible chat text.
- Tool summaries must be reduced to metadata, hashes, and sanitized status.
- Raw stdout, stderr, diffs, file contents, argv, secrets, and raw payloads are
  forbidden in generic dashboard projections.

## Streaming Turn Model (Phase K)

`RuntimeSessionAdapter.submit_user_message()` no longer blocks until the turn
completes. It starts an `asyncio.Task` that iterates `AgentLoop.act(...)` in
the background, storing `CodingTranscriptItemProjection` records as each event
arrives. The method returns immediately with `accepted=True, status="running"`.

The dashboard worker polls `events_since(cursor)` in a 50ms loop to receive
new events incrementally. Turn lifecycle is signalled via `kind="turn_status"`
records (`completed`/`failed`/`cancelled`).

Cancellation calls `cancel_turn()` on the adapter, which cancels the background
task and sets `turn_status="cancelled"`. The `AgentLoop` yields control at
its next await point, propagating `CancelledError` through the background task.

Three new protocol members were added:
- `cancel_turn()` — cancel the active background turn
- `is_turn_active` — property, True while a turn is processing
- `wait_for_turn()` — await the background task (test support)
- `turn_status` — property, one of `idle`, `running`, `completed`, `failed`, `cancelled`

## Fallback Order

1. Use hardened Rig functionality when available.
2. Fall back to the base vibe session path through the bridge when needed.
3. Refuse safely when neither exists.

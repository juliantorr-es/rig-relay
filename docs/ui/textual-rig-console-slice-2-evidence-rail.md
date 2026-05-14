# Textual Rig Console — Slice 2: EvidenceRailWidget

## Status

**Draft.** Completed alongside Slice 1.1 (structured blocker_summary).
Provides a content-light receipt timeline widget that renders metadata-only
receipt summaries from `EvidenceRailProjection`.

## Why EvidenceRailWidget Exists

The `SessionPaneWidget` only shows aggregate receipt counts and latest kind.
The `EvidenceRailWidget` provides a scrollable list of individual receipt
items — but only metadata (tool name, status, error kind, path, duration).
No raw logs, file contents, diffs, or command transcripts.

This is the second projection type in the Rig Console. Both widgets
consume projections, never raw data.

## EvidenceRailProjection Fields

| Field | Type | Description |
|---|---|---|
| `session_id` | str | Session identifier |
| `receipt_count` | int | Total receipts (capped) |
| `mutation_count` | int | Receipts with `changed=True` |
| `refusal_count` | int | Receipts with `status="refused"` |
| `timeout_count` | int | Receipts with timeout status/error_kind |
| `items` | list[EvidenceRailItemProjection] | Content-light receipt items (capped at 20) |

## EvidenceRailItemProjection Fields

| Field | Type | Description |
|---|---|---|
| `event_id` | str \| None | Source event identifier |
| `captured_at` | str \| None | ISO 8601 timestamp |
| `tool_name` | str | Tool that produced the receipt |
| `status` | str | Receipt status (success, refused, error, etc.) |
| `error_kind` | str \| None | Structured error classification |
| `path` | str \| None | File path (display-only) |
| `changed` | bool \| None | Whether a mutation occurred |
| `duration_ms` | float \| None | Execution duration in ms |

## What the Widget Shows

1. **Header** — "Evidence [session_id]"
2. **Counts row** — receipts, mutations, refusals, timeouts (positive only)
3. **Item list** — one line per receipt:
   - Right-aligned tool name (capped at 16 chars)
   - Status text
   - Error kind in brackets (if present)
   - Shortened file path (if present)
   - Duration in ms (if present)
4. **Empty state** — "No receipts yet."

## Adapter: evidence_rail_from_receipt_index()

A pure function that converts `list[ToolReceiptIndexRecord]` (from
`rig_relay/evidence/receipt_index.py`) into an `EvidenceRailProjection`.

- Extracts only metadata fields — no raw output
- Counts mutations (search_replace with changed=True)
- Counts refusals (status=refused)
- Counts timeouts (status=timed_out or bash error_kind=timeout)
- Orders by `captured_at` descending
- Caps items (default 20)
- Does not read files, parse JSONL, or touch disk

## What It Intentionally Does Not Do

- No raw stdout/stderr rendering
- No file contents or diffs
- No direct JSONL parsing inside the widget
- No mutation actions
- No session lifecycle controls

## Cross-References

- [Slice 1: SessionPaneWidget](textual-rig-console-slice-1.md)
- [Desktop Projection Contract](../governance/relay-desktop-projection-contract.md)
- [Receipt Index](../../rig_relay/evidence/receipt_index.py)
- [Textual Retirement Policy](../governance/textual-retirement-policy.md)

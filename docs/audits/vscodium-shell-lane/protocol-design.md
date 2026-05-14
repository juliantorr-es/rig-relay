# Protocol Design: Extension ↔ Rig Daemon

This document defines the local-only WebSocket protocol for the VSCodium shell lane.

## 1. Transport
*   **Endpoint:** `ws://127.0.0.1:PORT/rig/v1/extension`
*   **Authentication:** Token-gated. The daemon writes a one-time token to a secure local file (or `SecretStorage` after initial handshake) which the extension must provide in the `Authorization` header or initial `auth` message.
*   **Security:** Localhost-only. No unauthenticated commands. No raw shell execution.

## 2. Message Envelopes

### Base Message
```json
{
  "version": "1.0",
  "type": "string",
  "request_id": "uuid",
  "session_id": "string",
  "workspace_id": "string",
  "payload": {},
  "timestamp": "iso8601"
}
```

### Key Messages

| Type | Request/Response | Description | Content-Light Rules |
| :--- | :--- | :--- | :--- |
| `auth` | Request | Initial handshake with token. | N/A |
| `get_snapshot` | Request | Retrieve current session projection. | No raw file contents. |
| `start_turn` | Request | Submit a prompt to the agent. | Only user text and workspace metadata. |
| `cancel_turn` | Request | Stop current agent turn. | N/A |
| `subscribe_events`| Request | Subscribe to real-time agent events. | Projections only (summaries). |
| `list_receipts` | Request | Query evidence receipts. | Metadata + rationale only. |
| `propose_patch` | Response | Daemon proposes a file change. | **Exception**: Must include diff/patch. |
| `apply_patch` | Request | User approves the patch. | Patch ID + workspace ID. |
| `run_validate` | Request | Trigger a validation run. | Argv summary only. |

## 3. Refusal Shape
All requests may result in a refusal if governance rules are violated.
```json
{
  "type": "error",
  "request_id": "uuid",
  "error_kind": "permission_denied | state_conflict | validation_failure",
  "message": "Human-readable reason",
  "refusal_code": "RIG_ERR_001"
}
```

## 4. Content-Light Projections
The protocol strictly enforces **Content-Light Projections** for all non-editor-specific messages.
*   `AssistantEvent`: Contains the text response but **no tool output** (stdout/stderr).
*   `ToolCallEvent`: Contains tool name and arguments summary, but **no raw arguments** if they contain sensitive data (hashes only).
*   `ToolResultEvent`: Contains duration and status, but **no raw output data**.
*   **Diff Surface Exception**: Only messages specifically destined for the VSCodium Diff View may contain raw patch data.

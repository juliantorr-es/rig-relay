# Rig Relay Desktop Cockpit UI

## UI Modes

Rig Relay supports three UI modes for different use cases:

| Mode | Name | Use Case |
|---|---|---|
| `headless` | CLI-only | Automation, CI, worker sessions, scripting |
| `legacy_tui` | Textual TUI | Diagnostics, SSH, dev fallback |
| `desktop` | pywebview cockpit | **Primary local human UX (default)** |

## Design Decision

**Textual is no longer the primary product UI.** The terminal-based Textual TUI
is retained as a legacy/dev fallback for SSH/diagnostics use cases. The
pywebview desktop cockpit is the default local human UX direction.

## Architecture

```
Python runtime (backend)
    ├── tools, guards, coordination, checkpoint
    ├── current_state, queue, spawn, telemetry
    └── pywebview shell
            └── HTML/CSS/JS frontend (dumb renderer)
```

- **Backend** remains the authority for all tool execution, guards,
  coordination, checkpointing, telemetry, queue, and spawn operations.
- **Frontend** is a dumb renderer. It displays projections and sends user
  intents. It does not enforce policy.
- **Intents** flow frontend → backend; backend validates and executes.
  No mutation happens without backend approval.

## Security Boundary

- Use pywebview JS bridge or local static files — no external web server.
- If HTTP/WebSocket is needed, bind `localhost` only.
- Use a session-unique token for API protection.
- Never expose mutation APIs without backend validation.
- Never let the UI bypass dirty guard, path leases, checkpoint policy, or
  telemetry gates.

## Read-Only Cockpit (Current)

The first slice is a read-only cockpit that renders a **content-light projection**
built from available artifacts. The projection builder reads real artifact field
names and never invents data. Missing sources return `"available": false`.

### Artifact Sources

| Source | Path | Schema |
|---|---|---|
| Current State | `.build/rig-relay/current_state.json` | current_state.json summary block |
| Queue Plan | `.build/rig-relay/queue/ready_plan.json` | Queue plan ready/blocked/waiting |
| Dataset Summary | `.build/rig-relay/derived/export_manifest.json` + (optional) `.build/rig-relay/reports/dataset-summary.md` | export_manifest row_counts + Executive Summary table |
| Semantic Snippets | `.build/rig-relay/derived/semantic_change_snippets_manifest.json` | snippet manifest fields |
| Telemetry Bundle | `.build/rig-relay/telemetry-bundles/<latest>/telemetry_bundle_manifest.json` | bundle manifest fields |
| Update Status | `.build/rig-relay/update_status.json` (or fallback to running `rig_relay_update_status.py`) | update status fields |

### Exposed Read-Only API Methods

- `get_projection()` — returns the full projection dict
- `refresh_projection()` — re-reads artifacts and returns fresh projection
- `get_available_actions()` — returns list of read-only action names

No mutation buttons. No write APIs. All APIs return content-light data only.

### Projection Schema

The projection follows `docs/schemas/rig.relay.desktop_projection.v1.schema.json`:
- `schema_version`, `generated_at`, `app_version`, `alpha_label`
- `source_status` — boolean per-source availability map
- `current_state`, `queue`, `dataset`, `semantic_snippets`, `telemetry_bundle`, `update`
- Each category has `available: bool` + typed fields from real artifacts
- Missing sources: `"available": false` only, no invented fields
- `warnings` — user-actionable messages for missing sources
- `read_only_actions` — list of available safe actions
- `_schema_validation_errors` — present only if jsonschema validation fails (debug)

## Future Mutation Intents

After the read-only shell is stable, add safe intents:

- `refresh_current_state`
- `run_dataset_export`
- `run_dataset_report`
- `open_review_packet`
- `create_spawn_plan_dry_run`

Only after backend tools are stable:
- `queue_claim_ready`
- `spawn_execute`
- `checkpoint_session`

## Content Safeguards

The desktop shell must NOT display:
- Raw prompts
- Raw model outputs
- File contents
- stdout/stderr bodies
- Diffs
- Secrets
- Raw private paths (unless already in local-only cockpit docs and never exported)

Prefer: counts, statuses, hashes, titles, warnings.

## Frontend Stack

- **HTML/CSS/JS** — no build step required
- **No framework** in the first slice (vanilla JS)
- CSS provides cards, status pills, tables, simple layout

## Cross-References

- [Install Channels](../install.md)
- [Reviewer Orchestrator Doctrine](reviewer-orchestrator.md)
- [Delegate/Fleet Orchestration](delegate-fleet-orchestration.md)
- [Cross-Session Coordination](cross-session-coordination.md)
- [Rig-to-Relay Porting Doctrine](rig-to-relay-porting-doctrine.md)
- [Rig-to-Relay Pattern Inventory](rig-to-relay-pattern-inventory.md)

### Step-Up Authorization
 
The desktop cockpit may prompt for step-up authorization for high-authority actions (real upload, lease cleanup). See `docs/governance/step-up-authorization.md`.
Dev/local receipt minting exists for Phase 1 protected intents (`checkpoint.commit`, `lease_cleanup.archive`) and is verified. Protected execution buttons remain deferred until a real step-up provider is wired in.
The next step-up path is macOS LocalAuthentication via a Python bridge (implemented and verified), not WebAuthn/passkeys yet.
 
### Authorization Metadata
 
Audit events and result artifacts for protected intents include non-sensitive authorization metadata:
- `authorization_receipt_sha256`: Hash of the receipt used.
- `authorization_action`: The authorized action.
- `authorization_status`: Final verification status (`valid`, `expired`, etc.).
- `authorization_expires_at`: Expiry timestamp from the receipt.
- `authorization_method`: The method used (`none_dev_only`, `local_system_auth`).
 
Raw receipt bodies are strictly stripped from all audit trails.

## Chat Interface (Current)

The third slice adds a chat interface to the pywebview desktop shell. This is
the primary human UX for interacting with Rig Relay.

### Chat Architecture

- **Backend authoritative**: The backend owns the session state, model/provider
  authority, tool execution, and guard logic.
- **AgentLoop Adapter**: The `ChatAgentAdapter` (`rig_relay/desktop/chat_agent_adapter.py`)
  bridges the `AgentLoop` event stream to the persistent `ChatStore`.
- **Thread-safe bridge**: Bridge methods in `scripts/rig_relay_desktop_cockpit.py`
  execute on a separate `pywebview` thread. They use `asyncio.run_coroutine_threadsafe`
  to interact with the `asyncio` event loop.
- **Frontend renderer**: The chat UI is for frontend rendering only. It displays
  the chat transcript and sends user intents to the backend.
- **Intents, not execution**: Chat messages are intents or state updates. Sending
  a message does not directly execute a tool unless the backend agent loop
  processes it through its normal governance and tool execution gates.
- **Safe Rendering**: The frontend **must** render all untrusted text safely
  using `textContent` or similar methods to prevent XSS.

### Lifecycle States

The chat response lifecycle is managed by the `ChatAgentAdapter`:

- `idle`: No active agent response. Ready to accept messages.
- `running`: Agent loop is active and streaming events.
- `cancelling`: Cancellation has been requested but the task has not yet finalized.

State transitions:
- `idle` → `running`: When a message is processed.
- `running` → `cancelling`: When `cancel_chat_response` is called.
- `running`/`cancelling` → `idle`: When the task completes, is cancelled, or fails.

Concurrent sends:
- If `send_chat_message` is called while the state is not `idle`, it is refused
  with an `another_response_active` error.

### Content Constraints

The chat interface follows strict content-light constraints:
- **Assistant content**: Text is streamed to the UI.
- **Tool summaries**: Tool calls/results are summarized (status, name, hashes).
- **Sanitization**: Raw `stdout`, `stderr`, `diffs`, source code, and secrets
  are stripped from tool status messages.
- **Tracebacks**: Internal backend errors are summarized without tracebacks.

### Safe Backend API
 
 The chat interface interacts with the backend through a restricted set of
 safe methods:
 - `get_chat_state()` — returns the current chat session state
 - `send_chat_message(text, client_message_id)` — sends a user message (refused if active)
 - `clear_chat_view()` — clears the local chat transcript
 - `cancel_chat_response()` — requests cancellation of a pending assistant response
 - `run_desktop_intent(request)` — executes a governed, read-only/dry-run intent (e.g., `refresh_projection`, `run_validation_suite`)
 - `mint_authorization_receipt_dev(action, ttl_seconds, reason)` — mints a dev/local receipt for `checkpoint.commit` or `lease_cleanup.archive`
 - `mint_authorization_receipt_local(action, ttl_seconds, reason)` — mints the same receipt shape after macOS local auth succeeds
 - `inspect_authorization_receipt(receipt)` — returns content-light receipt metadata without exposing the raw body in audit logs

### Auth and Receipts

High-authority actions initiated through chat still require authorization
receipts. The chat UI should display these receipts and request approval
when necessary.

## Desktop Chat Persistence and Event Stream (Current)

The fourth slice makes the desktop chat shell persistent and event-backed. This
ensures chat history is preserved across cockpit restarts and provides an
auditable event log.

### Architecture

- **ChatStore**: `rig_relay.desktop.chat_store` manages persistence under
  `.build/rig-relay/desktop/chat/`.
- **Chat State**: `chat_state.json` stores the full message history in a
  versioned format (`rig.relay.desktop_chat_state.v1`).
- **Event Log**: `chat_events.jsonl` is an append-only log of content-light
  chat events (messages created, cleared, etc.).
- **Live Updates**: The WebSocket protocol is extended with `chat_state_updated`
  broadcasts, allowing the frontend to refresh the chat state in real time.

### Content-Light Events

Chat events follow strict content-light safeguards:
- **No full content**: Events store a SHA256 hash of message content and a
  short preview (120 chars max).
- **Metadata**: Stores `message_id`, `client_message_id`, `role`, and `status`.
- **Warnings**: Captures `warning_codes` for validation or policy violations.

### WebSocket Protocol Extension

| Type | Fields | Description |
|---|---|---|
| `get_chat_state` | — | Request current chat session state |
| `chat_state_updated` | `seq` | Server push notification that chat state has changed |

### Event Types

- `chat.message.created`
- `chat.message.refused`
- `chat.message.updated`
- `chat.view.cleared`
- `chat.response.cancelled`
- `chat.backend.stubbed`

### Files

| File | Role |
|---|---|
| `rig_relay/desktop/chat_store.py` | Chat persistence and event logging |
| `docs/schemas/rig.relay.desktop_chat_event.v1.schema.json` | Chat event schema |
| `tests/desktop/test_chat_persistence.py` | Persistence and event tests |

## WebSocket Projection Stream (Current)

The second slice adds a local WebSocket projection stream that serves content-light
projections to the frontend in real time. The frontend connects to the WebSocket
server and receives push updates without polling the pywebview JS bridge.

### Architecture

```
Python runtime
    └── ProjectionWebSocketServer (rig_relay.desktop.websocket_server)
            └── ws://127.0.0.1:9876
                    └── frontend/desktop/websocket.js (ProjectionWebSocketClient)
                            └── frontend/desktop/app.js (renderProjection)
```

- **Server**: `ProjectionWebSocketServer` binds to localhost only. Each connection
  is an independent session. Runs in a daemon thread when started by the cockpit.
- **Client**: `ProjectionWebSocketClient` in `frontend/desktop/websocket.js`
  connects to the server, requests initial projection, and reconnects on disconnect
  with exponential backoff.
- **Fallback**: If WebSocket is unavailable, the frontend falls back to the
  pywebview JS bridge (`window.pywebview.api.get_projection()`).
- **Connection indicator**: A new `#connection-status` element in the header
  shows "WS" (WebSocket), "Bridge" (pywebview), or "Offline" (no connection).

### Authentication

Every WebSocket connection **must** send an `auth` message as its first message.
The server requires a valid session token before any protocol messages are
processed. Authentication failures result in `auth_error` or `auth_required`
responses, and the connection is closed.

**Auth flow:**
1. Client opens WebSocket connection
2. Client sends {"type": "auth", "token": "<session-token>"}
3. Server responds with `auth_ok` on success, or `auth_error` on failure
4. After `auth_ok`, protocol messages are accepted

The session token is generated per desktop server instance via
`secrets.token_hex(32)`. It is exposed to the frontend only through the
pywebview JS bridge (`CockpitAPI.get_ws_config()`). The token is never
printed in normal logs.

### WebSocket Protocol (after authentication)

**Client → Server:**
| Type | Fields | Description |
|---|---|---|
| `auth` | `token` (str) | Authenticate (first message required) |
| `get_projection` | — | Request full projection |
| `get_available_actions` | — | Request available actions list |
| `subscribe` | `interval` (int, 5–300s) | Periodic projection push |
| `unsubscribe` | — | Stop periodic push |
| `ping` | — | Keepalive |

**Server → Client:**
| Type | Fields | Description |
|---|---|---|
| `auth_ok` | — | Authentication succeeded |
| `auth_error` | `message` | Authentication failed |
| `auth_required` | — | First message was not auth |
| `projection` | `data`, `seq` | Content-light projection |
| `available_actions` | `actions`, `seq` | List of read-only actions |
| `error` | `message` | Error description |
| `pong` | — | Keepalive response |

### CLI Entry Points

**Standalone WebSocket server:**
```
uv run python scripts/rig_relay_desktop_websocket.py --port 9876
```

**Cockpit with integrated WebSocket (default):**
```
uv run python scripts/rig_relay_desktop_cockpit.py
```

**Cockpit with JS bridge only (no WebSocket):**
```
uv run python scripts/rig_relay_desktop_cockpit.py --no-ws
```

### Subscription Model

- Minimum interval: 5 seconds (clamped via `MIN_SUBSCRIBE_INTERVAL`)
- Maximum interval: 300 seconds (clamped via `MAX_SUBSCRIBE_INTERVAL`)
- Default interval: 30 seconds
- Each subscribe replaces the prior subscription (only one active per connection)
- Unsubscribe cancels the polling task
- Connection close automatically cancels the subscription

### Files

| File | Role |
|---|---|
| `rig_relay/desktop/websocket_server.py` | Core WebSocket server |
| `scripts/rig_relay_desktop_websocket.py` | CLI entry point |
| `frontend/desktop/websocket.js` | Frontend WebSocket client |
| `frontend/desktop/app.js` | Updated to use WS with fallback |
| `frontend/desktop/index.html` | Added `#connection-status` + `websocket.js` |
| `scripts/rig_relay_desktop_cockpit.py` | Integrated WS server thread |

### Pattern Source

Port of Rig's `runtime_websocket.py` (`WebSocketStreamMessage` pattern), adapted
for Rig Relay's content-light projection model. Key differences:
- Token-gated session (auth message required before protocol)
- Content-light only (no raw prompts, outputs, or file contents)
- Polling-based push (no file-watch-driven push yet; `watchfiles` is available for future)
- Single server per cockpit instance (no UIServer abstraction)

## Desktop Intent API (Current)

The fifth slice adds a governed, schema-validated Intent API to the desktop
WebSocket/pywebview shell. This is the first Intent API slice: all intents
are read-only or dry-run. Protected mutation intents are explicitly refused.

### Architecture

```
Frontend (HTML button / WS message)
    └── desktop_intent message (schema-validated)
            └── rig_relay/desktop/intents.py
                    ├── validate_intent_request() - schema check
                    ├── ALLOWED_INTENTS registry
                    ├── PROTECTED_INTENTS registry
                    ├── execute_desktop_intent() - dispatch
                    └── _build_result() - content-light response
```

### Allowed First-Slice Intents

| Intent | Description | Effect |
|--------|-------------|--------|
| `refresh_projection` | Rebuild projection from artifacts | Updates projection |
| `get_chat_state` | Return current chat session state | None |
| `generate_refinement_report` | Generate tool refinement report | Creates report + JSONL |
| `create_refinement_packets` | Create mission packets from backlog | Dry-run only |
| `run_storage_audit` | Run storage audit, return budget | None |
| `run_validation_suite` | Run validation suite: ruff check, format check, pyright, schema validation, storage audit, desktop cockpit dry run | Writes structured validation evidence |
| `create_chatgpt_dev_bundle_dry_run` | Dry-run dev bundle creation | No zip written |
| `create_telemetry_bundle_dry_run` | Dry-run telemetry bundle creation | No zip written |
| `validate_telemetry_bundle` | Validate bundle content-light compliance | None |
| `run_queue_plan_dry_run` | Dry-run queue planner | No state mutation |
| `run_spawn_plan_dry_run` | Dry-run spawn session planner | No subprocess spawning |

### Phase 1 Protected Intents (Receipt-Gated)

| Intent | Description | Authorization |
|--------|-------------|---------------|
| `checkpoint.commit` | Create a governed local checkpoint commit for session-owned files. | Required (`step-up`) |
| `lease_cleanup.archive` | Archive stale coordination leases and task claims. | Required (`step-up`) |

### Still-Refused Intents (Not Yet Enabled)

`bash`, `shell`, `write_file`, `search_replace`,
`remote_upload.confirm`, `lease_cleanup.remove`,
`spawn.execute`, `fleet.execute`, `delegate.execute`

Refusal returns `status: refused`, `authorization_required: true`, and
error code `protected_intent_not_enabled` even with a valid
receipt. These will be unlocked in future phases.

### Schemas

- `desktop_intent_request.v1` — `intent_name`, `parameters`, `dry_run`, `authorization_receipt` (optional)
- `desktop_intent_result.v1` — `status`, `summary`, `output_refs`, `warnings`, `error_code`

### Files

| File | Role |
|---|---|
| `rig_relay/desktop/intents.py` | Core intent module: registry, validation, execution |
| `docs/schemas/rig.relay.desktop_intent_request.v1.schema.json` | Request schema |
| `docs/schemas/rig.relay.desktop_intent_result.v1.schema.json` | Result schema |
| `rig_relay/desktop/websocket_server.py` | Handles `desktop_intent` WS message type |
| `scripts/rig_relay_desktop_cockpit.py` | Exposes `run_desktop_intent()` via pywebview bridge |
| `frontend/desktop/index.html` | Actions card with safe intent buttons |
| `frontend/desktop/app.js` | `runIntent()` + `displayIntentResult()` with result_kind-based structured card rendering |
| `frontend/desktop/styles.css` | `.intent-result` card styles (ok/warning/error/pending) |
| `tests/frontend/test_intent_result_rendering.mjs` | 21 JS rendering tests (Node.js) |
| `frontend/desktop/websocket.js` | Routes `desktop_intent_result` messages |
| `tests/scripts/test_desktop_intents.py` | 63 tests + 21 JS rendering tests |
| `rig_relay/desktop/intent_audit.py` | Audit trail module: build_event, emit_received, emit_result |
| `docs/schemas/rig.relay.desktop_intent_event.v1.schema.json` | Event schema |

### Security Model

- Intents are validated against the request schema before execution.
- Only intents in ALLOWED_INTENTS are dispatched. Everything else is refused.
- Protected mutation intents have explicit refusal entries with error codes.
- The WebSocket `type` envelope field is stripped before schema validation.
- All results are content-light: counts, statuses, hashes, refs, never raw data.

### Intent Audit Trail (Current)

The sixth slice adds a durable, content-light audit trail for all intents.
Every intent produces at least two audit events and an optional result artifact.

#### Events

| Event Name | Trigger | Fields |
|---|---|---|
| `desktop.intent.received` | Intent received | event_id, intent_id, intent_name, status, dry_run, created_at |
| `desktop.intent.completed` | Successful execution | + result_kind, output_ref_count, result_sha256 |
| `desktop.intent.refused` | Protected/unknown intent | + authorization_required, error_code |
| `desktop.intent.failed` | Execution error | + result_kind, output_ref_count |

All events are content-light: no raw prompts, model outputs, source code,
stdout/stderr bodies, diffs, secrets, or raw private paths.

#### Storage

- **Event log**: `.build/rig-relay/desktop/intents/intent_events.jsonl`
- **Result artifacts**: `.build/rig-relay/desktop/intents/intent_results/<intent_id>.json`
- Writes are atomic (write to `.tmp`, then rename).
- Result artifacts use sorted keys for deterministic SHA256 computation.

#### Files

| File | Role |
|---|---|
| `rig_relay/desktop/intent_audit.py` | Audit module: build_event, emit_received, emit_result |
| `docs/schemas/rig.relay.desktop_intent_event.v1.schema.json` | Event schema |
| `tests/scripts/test_desktop_intents.py::TestAuditTrail` | 15 audit tests |

## Rig Pattern Port

The desktop projection pattern is ported from Rig's domain model, inspected from:

| Rig File | Pattern Ported | Adaptations |
|---|---|---|
| `src/rig/domain/projections.py` | `UIProjection` → content-light projection dict | Removed Rig-specific fields (WorkspaceHeader, ProposalLifecycle, AuditTrail, IntegrityStatusCard, ChatProjection) |
| `src/rig/domain/projection_builder.py` | `build_projection()` reads snapshots, builds typed categories | Adapted for Rig Relay artifact stack; `_load_json` + `_load_markdown_summary` instead of Rig's snapshot reader |
| `src/rig/domain/intent_defs.py` | `Intent` dataclass → `read_only_actions` array | Not yet ported as intent dispatch; documented as future |
| `src/rig/domain/runtime_websocket.py` | `WebSocketStreamMessage`, `RuntimeStreamProjection` | Ported to `rig_relay.desktop.websocket_server` without token auth; uses polling-based push |
| `src/rig/commands_window.py` | pywebview launcher with `UIServer` | Ported to `scripts/rig_relay_desktop_cockpit.py` with integrated WS server thread |
| `src/rig_tools/window_launcher.py` | Session token generation, `--dry-run`, `--browser`, `--allow-lan` | Session token paradigm documented for future WebSocket phase |

### Patterns Intentionally NOT Ported

- **Rig-specific projections**: WorkspaceHeader, ProposalLifecycle, AuditTrail, IntegrityStatusCard — these are specific to Rig's product domain
- **Rig receipt/audit domain** — Rig Relay does not have a receipt store
- **Rig job store or worktree executor** — Rig Relay uses coordination leases, not a job store
- **Intake-specific auth/onboarding** — Rig Relay has its own telemetry consent and update policy
- **Mutable UI-side policy** — backend remains authoritative; frontend is a dumb renderer

### Projection Builder Design

`rig_relay/desktop/projection.py` follows Rig's `projection_builder.py` pattern:

1. Read snapshots from disk (current_state.json, export_manifest.json, etc.)
2. Extract typed fields per category
3. Assemble into a single projection dict
4. Validate against schema (if jsonschema available)
5. Return with field names drawn from actual artifact schemas

Key differences from Rig:
- Content-light only (counts, statuses, hashes — never raw content)
- Missing sources → `"available": false` (never crashes on missing data)
- Schema-validated output (jsonschema Draft 7)
- No Rig-specific domain fields


## Cockpit IA: Operate / Review / System

The desktop cockpit is organized into three progressive-disclosure modes,
adopted from the [Relay Desktop Projection Contract](relay-desktop-projection-contract.md).

| Mode | Purpose | Shows |
|---|---|---|
| **Operate** | Primary human interface (default) | OperatorHeader, SafetyState, NextAction, ValidationSummary, StorageBudget, LatestIntentResult, Action buttons, Operator Feed (chat) |
| **Review** | Evidence and artifacts | ReceiptTimeline, RefinementBacklog, Validation History, Storage Audit, Semantic Snippets, Dataset Summary |
| **System** | Advanced and diagnostics | Authorization Receipts, Connection/WebSocket status, Telemetry Bundle, Update Status, Projection Source Diagnostics, Storage Diagnostics |

### Operate (default)

Answers three questions:
- **What is happening?** — Session info, safety posture, active child sessions
- **Is it safe?** — Dirty file count, active leases, stale leases, validation status
- **What should I do next?** — Backend-recommended next action with rationale

Operate shows these projection widgets:
- **OperatorHeader** — Mode, version, session ID
- **SafetyState** — Dirty files, active leases, stale leases
- **NextAction** — Backend-recommended action, rationale, blockers
- **ValidationSummary** — Last validation run: passed/failed counts, run button
- **StorageBudget** — Build artifact size, budget status, prune candidates
- **LatestIntentResult** — Result of the last intent execution
- **Action buttons** — Refresh Projection, Run Validation Suite, Storage Audit, Refinement Report, Refinement Packets
- **Operator Feed** — Chat transcript for agent communication

### Review

Shows evidence and artifacts for operator inspection:
- **ReceiptTimeline** — Bounded list of durable evidence (checkpoints, authorizations, validations)
- **RefinementBacklog** — Pending and refined built-in tool refinement items
- **Validation History** — Full validation run details
- **Storage Audit** — Detailed storage breakdown with recommendations
- **Semantic Snippets** — Code change snippet manifest
- **Dataset Summary** — Coordination, tool failure, artifact reuse rows

### System

Shows advanced and diagnostic controls:
- **Identity** — Sign in with GitHub / Google, view provider status, sign out. System mode only; not in Operate.
- **Authorization Receipts** — Mint/inspect controls for Phase 1 protected intents (checkpoint.commit, lease_cleanup.archive)
- **Connection** — WebSocket/bridge transport status
- **Telemetry Bundle** — Bundle manifest and dry-run creation buttons
- **Update Status** — Current/latest version, restart requirements
- **Projection Sources** — Per-source availability diagnostics
- **Storage Diagnostics** — Rollup candidates, prune candidates, stale leases, GC button

### Progressive Disclosure Policy

1. **Operate** is the default mode. New sessions always start in Operate.
2. **Review** is one click away for evidence inspection. Receipts and artifacts are never in Operate.
3. **System** is two clicks away for diagnostics. Authorization receipt controls and mutation-adjacent features are deferred to System.
4. Protected execution buttons (checkpoint.commit, lease_cleanup.archive, bash, write_file, search_replace, spawn.execute, fleet.execute, delegate.execute) are **absent from all modes** in this slice.
5. The frontend state machine is mode + mode only. No nested submodes.

### Widget Mapping

The projection builder (`rig_relay/desktop/projection.py`) produces a flat
projection dict. The frontend (`frontend/desktop/app.js`) maps projection fields
to widget cards depending on the active mode:

| Projection field | Operate widget | Review widget | System widget |
|---|---|---|---|
| app_version | OperatorHeader | --- | --- |
| current_state | SafetyState | --- | --- |
| storage | StorageBudget | Storage Audit details | Storage Diagnostics |
| _last_validation | ValidationSummary | Validation History | --- |
| warnings + _receipts | NextAction | ReceiptTimeline | --- |
| _refinement | --- | RefinementBacklog | --- |
| semantic_snippets | --- | Semantic Snippets | --- |
| dataset | --- | Dataset Summary | --- |
| telemetry_bundle | --- | --- | Telemetry Bundle |
| update | --- | --- | Update Status |
| source_status | --- | --- | Projection Sources |
| read_only_actions | Action buttons | --- | --- |
| --- | --- | --- | Identity |
| --- | --- | --- | Authorization Receipts |
| progress_events | --- | Progress Timeline | --- |
| --- | --- | --- | Connection Status |

### Frontend Safety

The cockpit follows the [Frontend Rendering Safety Doctrine](frontend-rendering-safety.md):
- `textContent` for untrusted content (model outputs, user text, file contents)
- `escapeHtml()` for all dynamic content in structured cards
- `innerHTML` only for trusted backend widget HTML via `setWidgetHTML()`
- No eval, no dynamic code execution
- No raw session tokens in storage
- No frontend mutation authority — all mutations go through backend intent API

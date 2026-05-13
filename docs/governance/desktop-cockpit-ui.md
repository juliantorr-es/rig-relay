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

### WebSocket Protocol

**Client → Server:**
| Type | Fields | Description |
|---|---|---|
| `get_projection` | — | Request full projection |
| `get_available_actions` | — | Request available actions list |
| `subscribe` | `interval` (int, 5–300s) | Periodic projection push |
| `unsubscribe` | — | Stop periodic push |
| `ping` | — | Keepalive |

**Server → Client:**
| Type | Fields | Description |
|---|---|---|
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
- No token-gated session yet (documented as future)
- Content-light only (no raw prompts, outputs, or file contents)
- Polling-based push (no file-watch-driven push yet; `watchfiles` is available for future)
- Single server per cockpit instance (no UIServer abstraction)

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
- **Chat UI or composer** — Rig Relay is a CLI harness, not a chat product
- **UIServer or WebSocket streaming** — documented as Phase 2
- **Mutable UI-side policy** — backend remains authoritative; frontend is a dumb renderer
- **Token-gated sessions** — documented as future

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

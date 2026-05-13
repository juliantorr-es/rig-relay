# Rig-to-Relay Pattern Inventory

Canonical inventory of Rig architecture patterns worth porting into Rig Relay,
with porting status, adaptation notes, and recommended slices.

## Porting Statuses

| Status | Meaning |
|---|---|
| `candidate` | Pattern identified but not yet ported |
| `porting` | Active port in progress |
| `ported` | Successfully ported to Relay-native interface |
| `deferred` | Postponed to a later slice |
| `rejected` | Not suitable for porting (document why) |
| `superseded-by-relay-native` | Rig pattern was ported then replaced by a Relay-native solution |

## Inventory

### 1. pywebview Desktop Shell

| Field | Value |
|---|---|
| **Rig source files** | `src/rig_tools/window_launcher.py`, `src/rig/commands_window.py`, `src/rig/commands_ui.py` |
| **Purpose in Rig** | Launch native OS window with pywebview; manage session lifecycle (dry-run, browser fallback, session token) |
| **Relay target interface** | `scripts/rig_relay_desktop_cockpit.py` (JS bridge API), `frontend/desktop/` (HTML/CSS/JS) |
| **Port status** | `ported` |
| **Risks** | pywebview optional dep; window creation requires macOS main thread; no UIServer/WebSocket yet |
| **Recommended slice** | Done. Future: migrate from script to `rig_relay.desktop.pywebview_shell` |

### 2. Backend-Owned Projection

| Field | Value |
|---|---|
| **Rig source files** | `src/rig/domain/projections.py` (UIProjection, WidgetProjection, IntentProjection), `src/rig/domain/projection_builder.py` |
| **Purpose in Rig** | Backend reads snapshots, builds typed projection dict with integrity checks, authored widgets, and action intents |
| **Relay target interface** | `scripts/rig_relay_desktop_projection.py` (content-light projection builder) |
| **Port status** | `ported` |
| **Risks** | Projection is content-light only (counts/hashes/statuses, never raw content). Missing sources return `"available": false` |
| **Recommended slice** | Done. Future: migrate to `rig_relay.desktop.projection` |

### 3. WebSocket Progress Stream

| Field | Value |
|---|---|
| **Rig source files** | `src/rig/domain/runtime_websocket.py`, `src/rig/domain/runtime_streaming/`, `src/rig_tools/ui_server.py` |
| **Purpose in Rig** | Ordered, deterministic, backpressure-aware stream events between backend and frontend; stream recovery and duplicate detection |
| **Relay target interface** | Not yet implemented. Target: `rig_relay.desktop.websocket_stream` with token-gated localhost-only WebSocket |
| **Port status** | `deferred` |
| **Risks** | WebSocket brings security surface (token-gating, localhost-only binding). Need pywebview + aiohttp or equivalent |
| **Recommended slice** | Phase 2 after read-only cockpit is stable. Must keep token-gated, localhost-only, backend-authoritative |

### 4. Intent Dispatcher

| Field | Value |
|---|---|
| **Rig source files** | `src/rig/domain/intent_defs.py` (Intent dataclass, IntentHandler), `src/rig_tools/intent_decoder.py`, `src/rig_tools/static/js/app/intent-dispatch.js` |
| **Purpose in Rig** | Typed intents flow frontend → backend; backend validates and dispatches; idempotency via intent_id; projection revision concurrency guard |
| **Relay target interface** | Not yet implemented. Target: `rig_relay.desktop.intent_api` with typed Intent model, registered handlers, and idempotency |
| **Port status** | `deferred` |
| **Risks** | Intent dispatch requires careful validation to prevent mutation bypass. Must gate behind authorization receipts for protected actions |
| **Recommended slice** | Phase 3 after WebSocket stream. Start with read-only intents (refresh_projection, run_dry_plan) before mutation intents |

### 5. Worktree Execution Isolation

| Field | Value |
|---|---|
| **Rig source files** | `scripts/rig_agent_worktree.py`, `scripts/worktree_normalize.py`, `scripts/work_merge_friendly.py`, `src/rig_tools/worktree_manager.py` |
| **Purpose in Rig** | Git worktree-based isolation for multi-writer child sessions; each child gets a separate working tree with no file conflicts |
| **Relay target interface** | Not yet implemented. Target: `rig_relay.coordination.worktree` with git worktree create/remove lifecycle tied to coordination leases |
| **Port status** | `deferred` |
| **Risks** | Worktree creation can conflict with dirty repo state. Must coordinate with coordination leases and dirty-file guard. Git worktree add/remove is stateful |
| **Recommended slice** | Phase 4 after spawn planner and fleet executor are stable. Worktrees are the execution sandbox for parallel child sessions |

### 6. Receipt / Checkpoint Store

| Field | Value |
|---|---|
| **Rig source files** | `src/rig/domain/receipts.py`, `src/rig/domain/receipt_envelope.py`, `src/rig/domain/progress_receipt_derivation.py`, `src/rig_tools/receipt_writer.py`, `scripts/rig_validate_receipt.py` |
| **Purpose in Rig** | Append-only receipt store for progress, completion, and failure events; receipt derivation for evidence aggregation |
| **Relay target interface** | `vibe/core/coordination/_models.py` (checkpoint_committed/refused payloads), `vibe/core/telemetry/local.py` (checkpoint artifact), `scripts/rig_relay_authorization_policy.py` (authorization receipts) |
| **Port status** | `ported` (adapted as authorization receipts + checkpoint artifacts, not full receipt store) |
| **Risks** | Rig's receipt store is a SQLite/git-backed append log. Rig Relay uses structured events + artifacts instead. Do not duplicate |
| **Recommended slice** | Done for authorization receipts. Future: evaluate if Rig's progress-receipt derivation pattern adds value to Relay's telemetry pipeline |

### 7. Update / Restart Policy

| Field | Value |
|---|---|
| **Rig source files** | N/A — Rig does not have a formal update policy |
| **Purpose in Rig** | N/A |
| **Relay target interface** | `scripts/rig_relay_update_status.py`, `docs/governance/update-policy.md`, `docs/schemas/rig.relay.update_status.v1.schema.json` |
| **Port status** | `superseded-by-relay-native` |
| **Risks** | N/A — Rig Relay developed its own update policy independently |
| **Recommended slice** | Done. No Rig pattern to port |

### 8. Frontend DOM Patch / Render Pattern

| Field | Value |
|---|---|
| **Rig source files** | `src/rig_tools/static/js/app/projection-store.js`, `src/rig_tools/static/js/app/websocket.js`, various HTML/CSS in `src/rig_tools/static/` |
| **Purpose in Rig** | Vanilla JS DOM patching from projection updates; WebSocket-driven live re-render; no framework |
| **Relay target interface** | `frontend/desktop/app.js` (vanilla JS bridge pull-based refresh), `frontend/desktop/styles.css` (dark theme cards) |
| **Port status** | `ported` (pull-based refresh only; no WebSocket live re-render yet) |
| **Risks** | First slice is pull-based (JS bridge `get_projection()`/`refresh_projection()`). WebSocket push is Phase 2 |
| **Recommended slice** | Done. Future: add WebSocket push for live updates |

### 9. Local Token / Security Bridge

| Field | Value |
|---|---|
| **Rig source files** | `src/rig/domain/auth_models.py` (ClientIdentity, SessionToken), `src/rig/domain/runtime_websocket.py` (token validation), `src/rig_tools/window_launcher.py` (session_token generation) |
| **Purpose in Rig** | Session-unique token protects local HTTP/WebSocket API from unauthorized access; token is generated by backend, embedded in URL, validated on every request |
| **Relay target interface** | Documented in `docs/governance/desktop-cockpit-ui.md` (Security Boundary section) but not yet implemented |
| **Port status** | `deferred` |
| **Risks** | Token-based protection is critical for WebSocket phase. Must generate per-session, validate every request, support reconnection with rotation |
| **Recommended slice** | Phase 2 alongside WebSocket stream. Keep tokens opaque and session-scoped |

### 10. Doctor / Diagnostic Aggregation

| Field | Value |
|---|---|
| **Rig source files** | `src/rig_tools/doctor.py`, `src/rig/commands_doctor.py` |
| **Purpose in Rig** | System health check: dependency availability, config validity, repo integrity, auth status |
| **Relay target interface** | Not yet implemented. Target: `rig_relay.cli.doctor` with checks for: pywebview, Google Drive deps, coordination store, update status, dirty files |
| **Port status** | `candidate` |
| **Risks** | Must be content-light; no raw file system traversal exposed. Checks must be fast (< 1s) |
| **Recommended slice** | Phase 2 after desktop shell is stable. Useful for install validation and diagnostics |

### 11. Worktree Execution Executor

| Field | Value |
|---|---|
| **Rig source files** | N/A — Rig does not have a multi-worktree executor |
| **Purpose in Rig** | N/A |
| **Relay target interface** | `docs/governance/delegate-fleet-orchestration.md` (fleet spawn planner) |
| **Port status** | `superseded-by-relay-native` |
| **Risks** | Rig Relay has its own spawn/fleet planner doctrine. Worktree isolation (pattern #5) is a future enabler for safe parallel execution |
| **Recommended slice** | N/A — Rig Relay's spawn planner is independent |

## Patterns Rejected from Porting

| Pattern | Rig source | Reason rejected |
|---|---|---|
| ChatUI / Composer | `src/rig/domain/projection_builder.py` (ChatProjection, ChatMessage) | Rig Relay is a CLI harness, not a chat product |
| WorkspaceHeader / ProposalLifecycle | `src/rig/domain/projections.py` | Rig-specific product domain; Rig Relay has no workspace model |
| AuditTrail / IntegrityStatusCard | `src/rig/domain/projection_builder.py` | Rig-specific governance model; Rig Relay has its own guard/coordination/telemetry gates |
| Job store | `src/rig/domain/` (various) | Rig Relay uses CoordinationStore + coordination leases instead |
| Intake auth/onboarding | `src/rig/domain/auth_models.py` (partial) | Rig Relay has its own telemetry consent and update policy |
| UIServer | `src/rig_tools/ui_server.py` | Too tightly coupled to Rig's auth/receipt model. Will reimplement in WebSocket phase |

## Cross-References

- [Rig-to-Relay Porting Doctrine](rig-to-relay-porting-doctrine.md)
- [Desktop Cockpit UI Doctrine](desktop-cockpit-ui.md)
- [Delegate/Fleet Orchestration](delegate-fleet-orchestration.md)
- [Step-Up Authorization](step-up-authorization.md)

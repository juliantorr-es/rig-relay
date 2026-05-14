# Rig Runtime Port Audit — Rig to Rig Relay

## Audit Metadata

| Field | Value |
|-------|-------|
| **Date** | 2026-05-15 |
| **Source** | `../Rig` (HEAD `da71305`) |
| **Target** | `rig-relay` (HEAD `384e4860`) |
| **Scope** | Runtime/control-plane concepts, execution plane, governance plane |
| **Status** | Draft |

## Method

Systematic comparison of Rig and Rig Relay source trees, docs, schemas, and
test files to identify port candidates, gaps, and already-ported patterns.

### Files Inspected (Rig)

| Domain | Key Files |
|--------|-----------|
| Governance engine | `src/rig/domain/governance/engine.py`, `decisions.py` |
| Runtime domain | `src/rig/domain/runtime.py` (invocation, capability, provider models) |
| Runtime supervisor | `src/rig/domain/runtime_supervisor.py` (asyncio subprocess) |
| Runtime registry | `src/rig/domain/runtime_registry.py` |
| Runtime streaming | `src/rig/domain/runtime_streaming/` (chunk, status, heartbeat, proposals) |
| Workspace runtime | `src/rig/domain/workspace_runtime.py` (lane-scoped context) |
| Execution domain | `src/rig/domain/execution/models.py` (request, lease, result) |
| Receipt envelope | `src/rig/domain/receipt_envelope.py` (canonical receipt model) |
| Workspace audit | `src/rig/domain/workspace_audit.py` (audit primitives) |
| Receipt store | `src/rig/domain/receipts.py` (receipt models + store) |
| Projection builder | `src/rig/domain/projection_builder.py` |
| Projection contracts | `src/rig/domain/projection_contracts.py` |
| Projections | `src/rig/domain/projections.py` |
| Worktree manager | `src/rig_tools/worktree_manager.py` |
| Workspace manager | `src/rig_tools/workspace_manager.py` |
| Work queue | `src/rig_tools/work_queue.py` |
| Execution engine | `src/rig_tools/execution_engine.py` |
| CLI commands | `commands_workspace.py`, `commands_job.py`, `commands_queue.py`, `commands_runtime.py` |

### Files Inspected (Rig Relay)

| Domain | Key Files |
|--------|-----------|
| Coordination | `rig_relay/coordination/models.py`, `store.py`, `tool.py` |
| Evidence | `rig_relay/evidence/receipt_index.py`, `model_observations.py` |
| Desktop projection | `rig_relay/desktop/projection.py`, `projection_widgets.py` |
| Desktop intents | `rig_relay/desktop/intents.py`, `intent_audit.py` |
| Governance | `rig_relay/governance/local_action_envelope.py`, `dirty_guard.py` |
| Runtime | `rig_relay/runtime/update_status.py` |
| Docs | `docs/governance/rig-to-relay-porting-doctrine.md` |
| Docs | `docs/governance/rig-to-relay-pattern-inventory.md` |
| Docs | `docs/governance/relay-desktop-projection-contract.md` |

---

## Decision Matrix

### Direct Port Candidates (close 1:1 pattern match)

| Rig Pattern | Rig Relay Target | Complexity | Priority | Rationale | Status |
|-------------|------------------|------------|----------|-----------|--------|
| Governance Engine (`decisions.py`, `engine.py`) | `rig_relay.governance.governance_engine` | Low | P1 | Pure evaluation of gate legality; no dependencies; 190 lines | ✅ **IMPLEMENTED** (P1a) |
| Runtime Model Types (`runtime.py`) | `rig_relay.runtime.models` | Low | P1 | Provider kinds, trust tiers, capabilities, invocations — all pure enums/models | ✅ **IMPLEMENTED** (P1c) |
| Runtime Streaming Types (`runtime_streaming/_types.py`) | `rig_relay.desktop.stream_types` | Low | P1 | Stream chunk, status, heartbeat, proposal event types | Pending |
| Workspace Runtime (`workspace_runtime.py`) | `rig_relay.coordination.workspace_runtime` | Low | P2 | Lane-scoped execution context with worktree/replay/artifact namespaces | Pending |

### Reimplement Patterns (relay-native adaptation required)

| Rig Pattern | Rig Relay Approach | Complexity | Priority | Rationale |
|-------------|--------------------|------------|----------|-----------|
| Worktree Manager (`worktree_manager.py`) | `rig_relay.coordination.worktree_manager` | Medium | P1 | Git worktree lifecycle with structured models, input sanitization, porcelain parsing, dirty detection; lease integration deferred | ✅ **IMPLEMENTED** (P1b) |
| Execution Request + Execution Lease (`execution/models.py`) | `rig_relay.runtime.execution_request` + `rig_relay.coordination.execution_lease` | Medium | P2 | ✅ **IMPLEMENTED** (P2c) — Pydantic models with extra="forbid", standalone file-backed store, TTL enforcement, path-traversal protection, 54 tests |
| Runtime Supervisor (`runtime_supervisor.py`) | `rig_relay.runtime.supervisor` | High | P2 | asyncio subprocess with bounded buffers, stall detection, cancellation, dry-run path | ✅ **IMPLEMENTED** (P2b) |
| Projection Builder (`projection_builder.py`) | `rig_relay.desktop.projection_builder` → `rig_relay.desktop.projection_integrity` | Medium | P2 | Integrity checks implemented via relay-native `build_projection_integrity_assessment()` — **IMPLEMENTED** (P2a) |
| Receipt Envelope (`receipt_envelope.py`) | `rig_relay.evidence.receipt_envelope` | Medium | P3 | Canonical receipt envelope theme (actor, subject, decision, evidence) — **IMPLEMENTED** (P3a) |
| Workspace Audit Trail (`workspace_audit.py`) | `rig_relay.evidence.audit_trail` | Medium | P3 | Deterministic audit events with auth classification; no side effects |

### Already Exists in Rig Relay (no port needed)

| Rig Pattern | Rig Relay Equivalent | Status | Notes |
|-------------|----------------------|--------|-------|
| Intent definitions | `rig_relay/desktop/intents.py` | **ported** | Read-only + dry-run intent API |
| Projection model | `rig_relay/desktop/projection.py` | **ported** | Content-light, backend-authored |
| Authorization receipts | `rig_relay/desktop/authorization_receipts.py` | **ported** | Local desktop auth receipts |
| Coordination store | `rig_relay/coordination/store.py` | **ported** | Task claims, path leases, artifacts |
| Coordination tool | `rig_relay/coordination/tool.py` | **ported** | Coordination plane tool |
| Dirty-file guard | `rig_relay/governance/dirty_guard.py` | **ported** | Path-level write protection |
| Local action envelope | `rig_relay/governance/local_action_envelope.py` | **ported** | Signed envelope for protected intents |
| Receipt index | `rig_relay/evidence/receipt_index.py` | **ported** | Content-light receipt builder |
| Tool receipt policy | `rig_relay/evidence/tool_receipt_policy.py` | **ported** | Content-light validation |
| Session lifecycle | `rig_relay/evidence/session_lifecycle.py` | **ported** | Session state machine |
| Update status | `rig_relay/runtime/update_status.py` | **ported** | Version check + restart policy |
| Tool receipts | `rig.relay.*_receipt.v1` schemas | **ported** | Bash, search_replace, write_file, validate |
| Desktop telemetry | `rig_relay/evidence/telemetry_bundle.py` | **ported** | Bundle + consent + budget |

### Leave Behind (Rig product domain, not applicable to Relay)

| Rig Pattern | Reason to Leave Behind |
|-------------|----------------------|
| ChatUI / Composer | Rig Relay is a CLI harness, not a chat product |
| WorkspaceHeader / ProposalLifecycle | Rig-specific product domain; Rig Relay has no workspace model |
| AuditTrail / IntegrityStatusCard | Rig-specific governance model; replaced by guard/coordination/telemetry |
| Job store (SQLite) | Rig Relay uses CoordinationStore (file-backed, no SQLite) |
| Intake auth/onboarding | Rig Relay has its own identity module (OAuth, consent store) |
| UIServer | Too tightly coupled to Rig's auth/receipt model |
| Rig's receipt store | Rig Relay uses structured events + artifacts |
| Rig's runtime providers (llama_cpp, mlx) | Rig Relay has its own provider registry/onboarding |
| Rig's agent loop | Rig Relay inherits Vibe agent loop (legacy, being replaced) |
| Rig's projection contract tests | Rig Relay has its own projection contract + widget modes |

---

## Gap Analysis

### Gap 1: No Worktree Manager — ✅ **FILLED** (P1b)
Rig Relay had no git worktree lifecycle. All execution was in-repo (no isolation).

**Impact:** ✅ **RESOLVED** — `WorktreeManager` provides git worktree lifecycle with: create (sanitized inputs, linked worktree), remove (refuses dirty without force), get_head_hash, list_worktrees (porcelain parsing), inspect (dirty detection). 52 tests. Schema at `docs/schemas/rig.relay.worktree.v1.schema.json`. Coordination lease integration deferred (P2 follow-up). Dirty-file guard boundary documented.

### Gap 2: No Subprocess Supervisor — ✅ **FILLED** (P2b)
Rig Relay's tool execution is in-process via asyncio. There is no bounded subprocess supervision with stall detection, output size caps, or dry-run path.

**Impact:** ✅ **RESOLVED** — `RuntimeSupervisor` provides lease-gated subprocess execution with bounded output (64KB configurable caps per stream), timeout (terminate→kill escalation), cancellation, concurrent stream draining with SHA256 hashing past truncation, and content-light completion/failure events. Schema at `docs/schemas/rig.relay.runtime_stream_event.v1.schema.json`. Governance doc at `docs/governance/runtime-supervisor.md`. **Governance gate and active lease conflict detection implemented P2b-follow-up (2026-06)** — GovernanceEngine evaluation wired before subprocess creation; ExecutionLeaseStore refuses concurrent active leases for same worktree_path. **Heartbeat emission and stall detection implemented P2b-follow-up (2026-06)** — RuntimeHeartbeatEvent emitted at configured interval, RuntimeWarningEvent emitted on stalled output. 108 tests (23 stream types + 36 supervisor incl. heartbeat/stall + 8 governance gate + 41 governance engine/lease conflict/existing). Dry-run mode remains deferred.

### Gap 3: No Execution Lease Model — ✅ **FILLED** (P2c)
Rig Relay has coordination leases (path-based), but had no execution leases (time-bounded authorization to run a command in a specific worktree).

**Impact:** ✅ **RESOLVED** — `ExecutionLeaseStore` provides time-bounded authorization with TTL enforcement, state-machine transitions, and path-traversal-safe storage. 54 tests. Schema at `docs/schemas/rig.relay.execution_lease.v1.schema.json`.

### Gap 4: No Runtime Provider Registry
Rig Relay has provider onboarding (rig_relay/providers/) but no runtime provider registry with trust tiers, capability scoping, or status tracking.

**Impact:** No way to declare "provider X can read files but not write" at the runtime level.

### Gap 5: No Projection Builder with Integrity Checks — ✅ **FILLED** (P2a)
Rig Relay's projection builder is content-light (counts/hashes/statuses). Missing integrity contract validation, authority binding verification, and stale receipt detection.

**Impact:** ✅ **RESOLVED** — `projection_integrity.py` provides `build_projection_integrity_assessment()` pure function with stale detection, orphaned receipt flagging, authority binding verification, and unknown widget detection. Schema at `docs/schemas/rig.relay.projection_integrity.v1.schema.json`. Desktop projection schema updated with optional `integrity` field. 33 tests.

---

## Porting Priority (Weighted)

Priority weights: Risk exposure (3), Implementation effort inverse (2), Dependency order (1)

| Slice | Pattern | Weight | Score |
|-------|---------|--------|-------|
| P1a | Governance Engine | High | Direct port, unlocks GateDecision model |
| P1b | Worktree Manager | High | Enables isolated execution |
| P1c | Runtime Model Types | High | Foundation for all runtime work — **IMPLEMENTED** |
| P2a | Projection Builder Upgrade | Medium | State-aware, integrity-verified |
| P2b | Subprocess Supervisor | Medium | Bounded, monitored execution |
| P2c | Execution Lease | Medium | Time-bounded auth |
| P3a | Receipt Envelope | Low | Canonical theme |
| P3b | Workspace Audit Trail | Low | Deterministic audit ✅ **IMPLEMENTED** |

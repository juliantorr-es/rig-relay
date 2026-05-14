# Rig-to-Relay Runtime Concept Map

Maps each Rig runtime/control-plane concept to its Rig Relay equivalent,
porting status, and adaptation notes.

## Legend

| Status | Meaning |
|--------|---------|
| `port_direct` | Close 1:1 match; port with minimal adaptation |
| `reimplement` | Pattern worth reimplementing with relay-native interface |
| `already_ported` | Already exists in Rig Relay |
| `leave_behind` | Not applicable to Rig Relay; document why |
| `deferred` | Postponed to a future slice |

---

## Governance Layer

### GateDecision
- **Rig:** `rig.domain.governance.decisions.GateDecision` — Frozen dataclass with workspace_id, decision, gate, reasons, allowed/blocked intents
- **Relay:** `rig_relay.governance.governance_engine.GateDecision` — **implemented** (P1a)
- **Port:** `port_direct` (P1a)
- **Rig sources:** `src/rig/domain/governance/decisions.py`, `engine.py`
- **Implementation:** `rig_relay/governance/decisions.py` + `governance_engine.py`. Uses Pydantic BaseModel with extra="forbid". Includes `AllowedIntent` model (Rig used plain str list). Adds `GovernanceReasonSeverity.CRITICAL`. Schema at `docs/schemas/rig.relay.governance_decision.v1.schema.json`.

### LocalActionEnvelope
- **Rig:** Not present (Rig has no local envelope pattern)
- **Relay:** `rig_relay.governance.local_action_envelope` — Signed envelope for protected intents
- **Port:** `already_ported` (relay_native)

### DirtyFileGuard
- **Rig:** Not present (Rig uses worktree isolation instead)
- **Relay:** `rig_relay.governance.dirty_guard` — Path-level write protection
- **Port:** `already_ported` (relay_native)

---

## Execution Plane

### WorktreeManager
- **Rig:** `rig_tools.worktree_manager.WorktreeManager` — Git worktree create/remove/get_head
- **Relay:** `rig_relay.coordination.worktree_manager.WorktreeManager` — **implemented** (P1b)
- **Port:** `reimplement` (P1b)
- **Adaptation:** Relay-native reimplementation with Pydantic models, structured results, input sanitization, `git worktree list --porcelain` parsing, dirty detection. Coordination lease integration deferred (P2 follow-up).
- **Rig sources:** `src/rig_tools/worktree_manager.py`
- **Implementation:** `rig_relay/coordination/worktree_manager.py`. Pydantic models: WorktreeStatus, WorktreeRecord, WorktreeOperationResult, WorktreeOperationKind. Methods: create (with sanitization), remove (refuses dirty without force), get_head_hash, list_worktrees (porcelain parsing), inspect (with dirty detection). Schema at `docs/schemas/rig.relay.worktree.v1.schema.json`. Governance doc at `docs/governance/worktree-manager.md`.

### ExecutionLease
- **Rig:** `rig.domain.execution.models.ExecutionLease` — Time-bounded auth to execute
- **Relay:** `rig_relay.coordination.execution_lease.ExecutionLease` — **implemented** (P2c)
- **Port:** `reimplement` (P2c)
- **Adaptation:** Standalone file-backed store (ExecutionLeaseStore) with atomic writes, TTL enforcement, path-traversal protection. Not embedded in CoordinationStore.
- **Rig sources:** `src/rig/domain/execution/models.py`
- **Implementation:** `rig_relay/coordination/execution_lease.py` + `docs/schemas/rig.relay.execution_lease.v1.schema.json`. Uses Pydantic BaseModel with extra="forbid". Adds lease state machine (active→released/expired/cancelled/failed). 32 store/validation tests.

### ExecutionRequest
- **Rig:** `rig.domain.execution.models.ExecutionRequest` — argv, cwd, env, timeout, purpose
- **Relay:** `rig_relay.runtime.execution_request.ExecutionRequest` — **implemented** (P2c)
- **Port:** `reimplement` (P2c)
- **Adaptation:** Use `list[str]` for argv (security), NOT shell strings. No `shell=True`. Adds SHA256 content fingerprint. Adds requested_capabilities for future governance hooks.
- **Rig sources:** `src/rig/domain/execution/models.py`
- **Implementation:** `rig_relay/runtime/execution_request.py`. Pydantic BaseModel with extra="forbid", argv non-empty validation, timeout_ms > 0 validation, SHA256 fingerprint. 22 tests.

### RuntimeSupervisor
- **Rig:** `rig.domain.runtime_supervisor` — asyncio subprocess with bounded buffers, stall detection, cancellation
- **Relay:** `rig_relay.runtime.supervisor.RuntimeSupervisor` — **implemented** (P2b)
- **Port:** `reimplement` (P2b)
- **Adaptation:** Relay-native Pydantic stream events (RuntimeStreamEvent discriminated union). Lease-gated execution (requires active ExecutionLease). Bounded concurrent stream draining with SHA256 hashing past truncation cap. Timeout and cancellation use terminate→kill escalation. Content-light terminal events (hashes, byte counts, truncated flags, no raw output). Governance gate wired via optional GovernanceEngine constructor arg — BLOCKED/REQUIRES_REVIEW blocks subprocess creation (P2b-follow-up, 2026-06). Active lease conflict detection in ExecutionLeaseStore — same worktree_path refused (P2b-follow-up, 2026-06). Heartbeats and stall detection implemented (P2b-follow-up, 2026-06). Dry-run mode remains deferred.
- **Rig sources:** `src/rig/domain/runtime_supervisor.py` (deprecated), `src/rig/domain/runtime_stream.py`
- **Implementation:** `rig_relay/runtime/supervisor.py` + `rig_relay/runtime/stream_types.py`. Stream events: RuntimeStatusEvent, RuntimeOutputChunkEvent, RuntimeHeartbeatEvent (model only), RuntimeWarningEvent (model only), RuntimeCompletionEvent, RuntimeFailureEvent. Schema at `docs/schemas/rig.relay.runtime_stream_event.v1.schema.json`. Governance doc at `docs/governance/runtime-supervisor.md`. 39 tests (23 stream types + 16 supervisor).

### RuntimeProvider
- **Rig:** `rig.domain.runtime.RuntimeProvider` — Provider kind, trust tier, status, capabilities
- **Relay:** `rig_relay.runtime.models.RuntimeProviderDescriptor` — Content-light descriptor (provider_id, kind, trust_tier, status, version)
- **Port:** `port_direct` (P1c) — **implemented**
- **Rig sources:** `src/rig/domain/runtime.py`
- **Implementation:** `RuntimeProviderDescriptor` is content-light (no executable paths, manifests, or capability details). Separate enums: `RuntimeProviderKind`, `RuntimeProviderTrustTier`, `RuntimeProviderStatus`. Schema at `docs/schemas/rig.relay.runtime_types.v1.schema.json`.

### RuntimeCapability
- **Rig:** `rig.domain.runtime.RuntimeCapabilityKind` — FILE_READ, FILE_WRITE_PROPOSAL, SHELL_PROPOSAL, etc.
- **Relay:** `rig_relay.runtime.models.RuntimeCapabilityKind` + `RuntimeCapability` model — **implemented**
- **Port:** `port_direct` (P1c) — **implemented**
- **Adaptation:** Includes 8 Rig-original kinds plus 6 Relay extensions: VALIDATION, RECEIPT_READ, COORDINATION_READ, COORDINATION_WRITE, WORKTREE_READ, WORKTREE_WRITE
- **Rig sources:** `src/rig/domain/runtime.py`
- **Implementation:** `RuntimeCapability` model with `capability_kind: RuntimeCapabilityKind` and `scope: str = "request"` (simplified from Rig's `RuntimeCapabilityScope` enum). Schema at `docs/schemas/rig.relay.runtime_types.v1.schema.json`.

### RuntimeContextResolver
- **Rig:** No direct equivalent; Rig agents typically carried session/task identifiers through the runtime stack.
- **Relay:** `rig_relay.runtime.context_resolver.RuntimeContextResolver` — relay-native control-plane helper
- **Port:** `relay_native`
- **Adaptation:** Derives canonical runtime coordination context from an intent, infers session/task/worktree metadata when available, and refuses unsafe paths or missing required scope. Content-light only; does not acquire reservations or execute tools.

### MissionEnvelope
- **Rig:** Mission-shaped orchestration exists conceptually in docs and workflow direction, but not as a fully executable runtime path.
- **Relay:** `docs/governance/mission-envelope.md` — minimal bridge object for governed runs
- **Port:** `relay_native`
- **Adaptation:** Mission-first envelope that can later carry ADR/sprint metadata as optional references. Keeps executable context packet compilation ahead of full orchestration.

### WorkspaceRuntime
- **Rig:** `rig.domain.workspace_runtime.WorkspaceRuntime` — Lane-scoped execution context (worktree, replay, artifact namespaces)
- **Relay:** `rig_relay.coordination.workspace_runtime.WorkspaceRuntime` — **new**
- **Port:** `reimplement` (P2a)
- **Rig sources:** `src/rig/domain/workspace_runtime.py`

---

## Evidence / Receipts

### ReceiptEnvelope
- **Rig:** `rig.domain.receipt_envelope` — ReceiptActor, ReceiptSubject, ReceiptInput, ReceiptOutput, ReceiptDecision, ReceiptEvidence
- **Relay:** `rig_relay.evidence.receipt_envelope` — **implemented** (P3a)
- **Port:** `reimplement` (P3a)
- **Adaptation:** Pydantic BaseModel with extra="forbid", StrEnum enums, content-light (no raw payloads). `build_receipt_envelope()` hashes payload and discards raw data. Pure function, no side effects. Standalone module (no dependency on tool receipts, receipt index, or governance decisions at import time).
- **Rig sources:** `src/rig/domain/receipt_envelope.py`
- **Implementation:** `rig_relay/evidence/receipt_envelope.py` + `docs/schemas/rig.relay.receipt_envelope.v1.schema.json`. Models: ReceiptActor (5 fields), ReceiptSubject (5 fields), ReceiptInput (4 fields), ReceiptOutput (5 fields), ReceiptEvidence (5 fields), ReceiptDecision (4 fields), ReceiptEnvelope (10 fields). Enums: ReceiptActorKind, ReceiptSubjectKind, ReceiptEvidenceKind. Builder: `build_receipt_envelope()` with payload hashing. 46 tests. Content-light policy enforced: no forbidden raw fields in any model or schema.

### WorkspaceAuditTrail
- **Rig:** `rig.domain.workspace_audit` — AuditAction, AuditActor, AuditSubject, AuditEvent, AuditDecision
- **Relay:** `rig_relay.evidence.audit_trail` — **implemented**
- **Port:** `reimplement` (P3b) ✅
- **Adaptation:** Replace Rig's workspace-specific audit model with relay-native session-centric model. Keep event_id, actor, action, subject, decision pattern.
- **Rig sources:** `src/rig/domain/workspace_audit.py`

### ExecutionReceipt
- **Rig:** `rig.domain.receipts.ExecutionReceipt` — argv, cwd, exit_code, stdout/stderr refs, timing
- **Relay:** `rig.relay.execution_receipt.v1` schema — **new**
- **Port:** `reimplement` (P3a)
- **Adaptation:** Content-light only (SHA256 of stdout/stderr, never full content).
- **Rig sources:** `src/rig/domain/receipts.py`

---

## Projection / UI

### ProjectionContract
- **Rig:** `rig.domain.projection_contracts` — ProjectionField, AuthorityBindingType, ReceiptBackingRequirement, ContractViolationCode
- **Relay:** Already have `docs/governance/relay-desktop-projection-contract.md`
- **Port:** `already_ported` (adapted as relay-native contract)

### ProjectionBuilder
- **Rig:** `rig.domain.projection_builder` — Full projection from receipts, audit, integrity checks
- **Relay:** `rig_relay.desktop.projection` + `rig_relay.desktop.projection_integrity` — Content-light with integrity checks
- **Port:** `reimplement` (P2a) — **implemented** (2026-05)
- **Implementation:** `build_projection_integrity_assessment()` pure function added. `_build_integrity()` helper in projection.py loads receipt index via `build_receipt_index()`. Schema at `docs/schemas/rig.relay.projection_integrity.v1.schema.json`. Desktop projection schema updated with optional `integrity` field. 33 tests.

### WidgetProjection
- **Rig:** `rig.domain.projections.WidgetProjection` — Named widgets with typed fields
- **Relay:** `rig_relay.desktop.projection_widgets` — Canonical widget names + mode mapping
- **Port:** `already_ported` (widget names differ; rig-relay has its own taxonomy: SafetyState, NextAction, etc.)

### IntentDispatch
- **Rig:** `rig.domain.intent_defs.Intent` + `rig_tools.intent_decoder`
- **Relay:** `rig_relay.desktop.intents` — Read-only + dry-run intents
- **Port:** `already_ported` (relay-native, no Rig dependency)

---

## Queue / Jobs

### WorkQueue
- **Rig:** `rig_tools.work_queue` — JSON file-backed queue with checkpoints
- **Relay:** `rig.relay.work_queue.v1.schema.json` (schema only)
- **Port:** `deferred` — rig-relay has the schema but no queue implementation yet

### OrchestrationJob
- **Rig:** `rig_tools.orchestration` — Agent loop orchestration jobs with task/provider/model
- **Relay:** No equivalent; uses Vibe agent loop (legacy)
- **Port:** `leave_behind` — Rig Relay has its own agent loop path

---

## CLI Commands

### `rig workspace status/lanes/projection/receipts/recommend`
- **Rig:** Read-only workspace control-plane status
- **Relay:** No equivalent; use `relay current-state --summary` + desktop projection
- **Port:** `deferred` — UI projection already provides equivalent info

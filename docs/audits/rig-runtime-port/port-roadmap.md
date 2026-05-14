# Rig Runtime Port Roadmap

## Status
**Draft.** Proposed slices for porting Rig runtime/control-plane concepts into
Rig Relay, ordered by dependency and risk priority.

## Dependencies

```
P1a (Governance Engine) ──┐
                           ├──→ P2a (Projection Builder Upgrade)
P1b (Worktree Manager) ────┤
                           │
P1c (Runtime Models) ──────┼──→ P2b (Subprocess Supervisor) ──→ P3a (Receipt Envelope)
                           │
                           └──→ P2c (Execution Lease) ─────────┘
                                                               │
                                                               └──→ P3b (Audit Trail)
```

---

## Phase 1: Foundation (P1a+P1b+P1c)

### P1a: Governance Engine Port
**Status:** ✅ **IMPLEMENTED** (2026-05)
**Effort:** 2–3 days
**Files:** `rig_relay/governance/governance_engine.py`, `rig_relay/governance/decisions.py`
**Tests:** 41 (6 test classes)

**Deliverables:**
- `GateDecision` model (Pydantic, extra="forbid") with workspace_id, decision (allowed/blocked/requires_review/not_applicable), gate, reasons, allowed_intents, blocked_intents
- `DecisionReason` model with code, message, severity
- `BlockedIntent` model with intent_id, reason, code
- `AllowedIntent` model with intent_id, reason
- `GovernanceEngine.evaluate_action_legality()` pure function
- Schema: `docs/schemas/rig.relay.governance_decision.v1.schema.json`
- Exports via `rig_relay/governance/__init__.py`

**Acceptance:**
- `GovernanceEngine` evaluates actions with/without capabilities
- Blocked intents returned for impasse states (blocked provider, dirty policy)
- Requires review returned for mutation/network without explicit allowance
- No side effects (pure evaluation)
- Adapted from Rig's proposal/evidence model to relay-native capability-based checks

**Deviations from Rig source:**
- Pydantic BaseModel with extra="forbid" instead of frozen dataclass
- Added GovernanceReasonSeverity.CRITICAL (Rig only had info/warning/error)
- Added AllowedIntent model (Rig used plain str list)
- Simplified input signature (no proposal/evidence model)
- Relay-native capability-based checks using RuntimeCapabilityKind from rig_relay.runtime.models
- Schema version string on GateDecision

### P1b: Worktree Manager
**Status:** ✅ **IMPLEMENTED** (2026-05)
**Effort:** 3–5 days
**Files:** `rig_relay/coordination/worktree_manager.py`
**Tests:** 52 (13 test classes)

**Deliverables:**
- `WorktreeManager` class with create(workspace_id, branch_name, base_ref), remove(workspace_id, force=False), get_head_hash(workspace_id), list_worktrees(), inspect(workspace_id)
- `WorktreeRecord`, `WorktreeOperationResult`, `WorktreeStatus`, `WorktreeOperationKind` models
- Private `_run_git` helper with timeout, output caps, structured error handling
- Schema: `docs/schemas/rig.relay.worktree.v1.schema.json`
- Go governance doc: `docs/governance/worktree-manager.md`

**Acceptance:**
- Creates isolated git worktree with new branch per workspace/lane ✅
- Removes worktree; refuses dirty worktree removal without force ✅
- Lists active worktrees by parsing `git worktree list --porcelain` ✅
- Inspects individual worktree status (healthy/dirty) ✅
- Does not conflict with dirty-file guard (worktrees are outside main repo) ✅
- Safety: workspace_id and branch_name sanitized; no path traversal; no shell=True ✅

**Deviations from Rig source:**
- Pydantic BaseModel with extra="forbid" instead of raw subprocess calls
- Worktree root under repo (`repo/.rig/relay/worktrees/`) instead of `~/.local/state/rig/worktrees/`
- Structured error/refusal models instead of bare exceptions
- workspace_id and branch_name sanitization (Rig had none)
- `_run_git` helper with timeout, output caps, and structured error return
- `list_worktrees()` uses `--porcelain` parsing (Rig had no list method)
- `inspect()` with dirty detection (Rig had no inspect)
- Coordination lease integration deferred (P2 follow-up)
- Execution integration deferred (P2b follow-up)

### P1c: Runtime Model Types
**Status:** ✅ **IMPLEMENTED** (2025-06)
**Effort:** 1–2 days
**Files:** `rig_relay/runtime/models.py`, `docs/schemas/rig.relay.runtime_types.v1.schema.json`
**Tests:** 32 (12 test classes across RuntimeCapabilityModel, RuntimeProviderDescriptorModel, and all 5 enums)

**Deliverables:**
- `RuntimeProviderKind` enum (local, cli, custom, dry_run, stub)
- `RuntimeProviderTrustTier` enum (blocked, advisory, reviewer, planner, executor_candidate, validator)
- `RuntimeProviderStatus` enum (available, unavailable, degraded, blocked, error)
- `RuntimeCapabilityKind` enum (file_read, file_write_proposal, shell_proposal, patch_proposal, replay_access, network_fetch_proposal, docs_fetch_proposal, telemetry_export_proposal + relay extensions: validation, receipt_read, coordination_read, coordination_write, worktree_read, worktree_write)
- `RuntimeInvocationStatus` enum (pending, starting, running, succeeded, failed, timed_out, cancelled, blocked)
- `RuntimeCapability` Pydantic model (capability_kind, scope="request")
- `RuntimeProviderDescriptor` Pydantic model (provider_id, kind, trust_tier, status, version)
- Schema: `docs/schemas/rig.relay.runtime_types.v1.schema.json`
- Exports via `rig_relay/runtime/__init__.py`

**Acceptance:**
- ✅ All enums match Rig's semantics (adapted for Relay tool set with 6 relay-extended capability kinds)
- ✅ Pydantic BaseModel enums with `model_dump(mode="json")` serialization
- ✅ Combined runtime_types schema with all 5 enums as named definitions + capability and provider_descriptor object schemas
- ✅ `extra="forbid"` on both models
- ✅ 32 tests passing (ruff, pyright, pytest, schema validation all clean)

**Implementation Notes:**
- Rig uses `enum.Enum`; Relay uses `StrEnum` for string-serializable enums
- `RuntimeCapability.scope` is `str` (simplified from Rig's `RuntimeCapabilityScope` enum)
- `RuntimeProviderDescriptor` is content-light (no executable paths, manifests, or capability details)
- Relay extensions to `RuntimeCapabilityKind`: VALIDATION, RECEIPT_READ, COORDINATION_READ, COORDINATION_WRITE, WORKTREE_READ, WORKTREE_WRITE
- Schema file registered with convention `rig.relay.runtime_types.v1.schema.json`

---

## Phase 2: Execution (P2a+P2b+P2c)

### P2a: Projection Builder Upgrade
**Status:** ✅ **IMPLEMENTED** (2026-05)
**Effort:** 3–5 days
**Files:** `rig_relay/desktop/projection_integrity.py` (new), `rig_relay/desktop/projection.py` (upgraded), `docs/schemas/rig.relay.projection_integrity.v1.schema.json` (new)
**Tests:** 33 (3 test classes)

**Deliverables:**
- Integrity assessment in projections: `integrity_status`, `contract_status`, `violation_count`
- Stale receipt detection
- Orphaned receipt detection
- Authority binding verification (list-based and dict-based)
- Unknown widget detection against canonical taxonomy
- Pure function builder: `build_projection_integrity_assessment()`
- Relay-native module: `projection_integrity.py` (not a copy of Rig's 1900-line `projection_contracts.py`)
- Schema: `docs/schemas/rig.relay.projection_integrity.v1.schema.json`
- Desktop projection schema updated with optional `integrity` `$ref`
- `_build_integrity()` helper in `projection.py` loads receipt index and attaches assessment

**Acceptance:**
- Projection includes integrity assessment (content-light: status enums, violation codes, counts)
- Stale/orphaned receipts flagged
- No authority claimed without receipt backing
- Unknown widgets detected against `projection_widgets.ALL_WIDGETS`
- All checks are pure (no side effects, no file reads in model layer)
- 33 tests passing: model validation, builder behavior, schema contract

### P2b: Subprocess Supervisor
**Status:** ✅ **IMPLEMENTED** (2026-06)
**Effort:** 5–8 days
**Files:** `rig_relay/runtime/supervisor.py`, `rig_relay/runtime/stream_types.py`, `docs/schemas/rig.relay.runtime_stream_event.v1.schema.json`, `docs/governance/runtime-supervisor.md`
**Tests:** 39 (23 stream types + 16 supervisor)

**Deliverables:**
- `RuntimeSupervisor` asyncio class with:
  - `execute(ExecutionLease) -> AsyncIterator[RuntimeStreamEvent]`
  - Bounded output buffers (configurable per stream: max_stdout_bytes, max_stderr_bytes)
  - Lease-gated execution (checks ACTIVE status and expiry)
  - Timeout (asyncio.wait_for with terminate→kill escalation)
  - Cancellation (terminate→kill cleanup)
  - Content-light completion/failure events (SHA256 hashes, byte counts, truncated flags)
  - Concurrent bounded stream draining with hash tracking beyond truncation
- `RuntimeStreamEvent` discriminated union: status, stdout_chunk, stderr_chunk, heartbeat (model only), warning (model only), completion, failure
- Schema: `docs/schemas/rig.relay.runtime_stream_event.v1.schema.json` (Draft 7, all 6 event variants)
- Governance doc: `docs/governance/runtime-supervisor.md`

**Acceptance:**
- ✅ Subprocess runs in bounded time; timeouts produce `RuntimeFailureEvent` with status="timed_out"
- ✅ Large output truncated at configurable limit; SHA256 hashing continues past cap
- ✅ Cancellation cleans up subprocess and produces `RuntimeFailureEvent` with status="cancelled"
- ✅ No shell execution — `asyncio.create_subprocess_exec(*argv)`
- ✅ Lease-gated — inactive/expired leases produce BLOCKED failure
- ✅ Content-light terminal events — no raw stdout/stderr in completion/failure
- ✅ 39/39 tests passing (ruff, pyright, pytest, schema validation all clean)
- ✅ CWD resolution from worktree_path or request.cwd

**Deferred (P2b-follow-up):**
- Dry-run mode (documented as not implemented)

### P2b-follow-up: Governance Gate + Active Lease Conflict
**Status:** ✅ **IMPLEMENTED** (2026-06)
**Effort:** 1–2 days
**Files:** `rig_relay/runtime/supervisor.py` (amended), `rig_relay/coordination/execution_lease.py` (amended)
**Tests:** 66 (16 original supervisor + 8 governance gate + 34 original lease + 8 conflict detection)

**Deliverables:**
- GovernanceEngine evaluation wired into RuntimeSupervisor before subprocess creation
- Constructor args: governance_engine, provider_trust_tier, provider_status, allow_mutation, allow_network, dirty_policy_satisfied
- BLOCKED/REQUIRES_REVIEW decisions produce RuntimeFailureEvent(status=blocked) without creating subprocess
- Active lease conflict detection in ExecutionLeaseStore.acquire() — refuses when active lease exists for same worktree_path or workspace_id
- enforce_exclusive_worktree parameter (default True) on acquire()
- Expired/released leases do not block new acquisitions

**Governance gate behavior:**
- No capability execution allowed through
- Mutation require allow_mutation=True → REQUIRES_REVIEW status
- Network require allow_network=True → REQUIRES_REVIEW status
- Blocked provider trust tier/status → BLOCKED decision
- Content-light failure events with governance error_kind
- Lease released on governance refusal

**Active lease conflict behavior:**
- Same worktree_path → refused with active_worktree_lease_exists
- Same workspace_id (no worktree_path) → refused with active_workspace_lease_exists
- Distinct worktree_paths → both granted
- enforce_exclusive_worktree=False → same worktree allowed
- All conflict results produce ExecutionLeaseResult(status="refused") with error_kind and refusal_reason

### P2c: Execution Lease
**Status:** ✅ **IMPLEMENTED** (2026-06)
**Effort:** 2–3 days
**Files:** `rig_relay/coordination/execution_lease.py`, `rig_relay/runtime/execution_request.py`
**Tests:** 54 (22 execution request + 32 execution lease)

**Deliverables:**
- `ExecutionRequest` model (request_id, argv, cwd, env_overlay, timeout_ms, purpose, workspace_id, worktree_path, requested_capabilities, request_sha256) — Pydantic BaseModel with extra="forbid", argv validation (non-empty list of non-empty strings), timeout_ms > 0 validation, SHA256 content fingerprint
- `ExecutionLease` model (lease_id, request, workspace_id, worktree_path, acquired_at, expires_at, released_at, status, refusal_reason, error_kind) — Pydantic BaseModel with extra="forbid"
- `ExecutionLeaseStatus` enum (pending, active, released, expired, cancelled, failed)
- `ExecutionLeaseResult` model (status, lease, error_kind, refusal_reason)
- `ExecutionLeaseStore` — standalone file-backed store with atomic writes (temp-file + replace), path-traversal protection on lease_id, TTL enforcement on acquire, state-machine transitions on release/expire
- Schema: `docs/schemas/rig.relay.execution_lease.v1.schema.json` (combined definitions for ExecutionRequest, ExecutionLeaseStatus, ExecutionLease, ExecutionLeaseResult, RuntimeCapabilityKind)

**Acceptance:**
- ✅ Lease acquired before execution starts — acquire() creates active lease with expires_at = now + ttl_seconds
- ✅ Lease expires after TTL; expired leases block new execution — expire_stale() marks active leases expired when now >= expires_at; release() on expired lease returns already_expired result
- ✅ Lease released on completion — release() transitions active→released, sets released_at
- ✅ Missing/malformed lease files return None/structured not_found result
- ✅ Path-traversal on lease_id rejected (dots prefix, slashes, backslashes)
- ✅ 54 tests passing (ruff, pyright, schema validation all clean)
- ✅ Content-light — no stdout/stderr/output/content/diff/shell fields

**Implementation Notes:**
- Standalone `ExecutionLeaseStore` (not embedded in CoordinationStore) — cleaner separation
- Reuses `dump_canonical_json` from coordination._canonical_json for deterministic writes
- Atomic write via .tmp + .replace() — same pattern as CoordinationStore._write_json
- Timestamps: ISO-8601 strings with UTC timezone via `datetime.now(UTC).isoformat()`
- lease_id doubles as filename — validated with \_validate_lease_id() to prevent path traversal
- request_sha256 computed from canonical JSON of all fields except request_id and request_sha256
- Governance hook placeholder via `requested_capabilities: list[RuntimeCapabilityKind]` — future RuntimeSupervisor can evaluate before acquiring lease

---

## Phase 3: Evidence (P3a+P3b)

### P3a: Receipt Envelope
**Status:** ✅ **IMPLEMENTED** (2026-05)
**Effort:** 3–4 days
**Files:** `rig_relay/evidence/receipt_envelope.py`, `docs/schemas/rig.relay.receipt_envelope.v1.schema.json`
**Tests:** 46 (8 test classes)

**Deliverables:**
- `ReceiptActor` Pydantic model (actor_id, actor_kind, display_name, is_human, is_authoritative) — StrEnum: H#!AN, AGENT, TOOL, RUNTIME, SYSTEM
- `ReceiptSubject` Pydantic model (subject_id, subject_kind, workspace_id, session_id, path) — StrEnum: TOOL_INVOCATION, RUNTIME_INVOCATION, GOVERNANCE_DECISION, WORKTREE, PROJECTION, SESSION, ARTIFACT
- `ReceiptDecision` model (decision, rationale, gate, governance_decision_id)
- `ReceiptInput` model (input_id, input_kind, input_sha256, input_bytes)
- `ReceiptOutput` model (output_id, output_kind, output_sha256, output_bytes, status)
- `ReceiptEvidence` model (evidence_id, evidence_kind, evidence_sha256, schema_version, uri) — StrEnum: SHA256, SCHEMA, RECEIPT_INDEX, GOVERNANCE_DECISION, RUNTIME_EVENT, TOOL_RECEIPT, PROJECTION_INTEGRITY
- `ReceiptEnvelope` model combining actor, subject, input, output, decision, evidence
- `build_receipt_envelope()` pure factory function — hashes payload, discards raw data
- `_compute_payload_sha256()` internal helper using canonical JSON
- Schema: `docs/schemas/rig.relay.receipt_envelope.v1.schema.json`
- Governance doc: `docs/governance/receipt-envelope.md`
- Placeholder constants: `PLACEHOLDER_UNKNOWN`, `PLACEHOLDER_UNAVAILABLE`, `PLACEHOLDER_NO_RECEIPT`

**Acceptance:**
- ✅ All receipt fields are content-light (SHA256, never raw)
- ✅ Placeholder constants for missing/explicit null states
- ✅ Serialization round-trips through JSON
- ✅ No side effects (pure function builder)
- ✅ All models reject unknown fields (extra="forbid")
- ✅ Payload hashed, not stored — raw payload never appears in envelope dump
- ✅ Deterministic for identical inputs
- ✅ 46/46 tests passing (ruff, pyright, pytest, schema validation all clean)

### P3b: Workspace Audit Trail
**Status:** ✅ **IMPLEMENTED** (2026-05)
**Effort:** 2–3 days
**Files:** `rig_relay/evidence/audit_trail.py`, `docs/schemas/rig.relay.audit_event.v1.schema.json`
**Tests:** 27 (3 test classes)

**Deliverables:**
- `AuditEvent` model with event_id, actor, action, subject, decision, timestamp
- `AuditTrailStore` append-only event log (file-backed, JSONL)
- Deterministic event ordering by timestamp + sequence number
- Schema: `docs/schemas/rig.relay.audit_event.v1.schema.json`

**Acceptance:**
- Events are append-only (no mutation/delete)
- Audit trail is replayable from events alone
- Content-light (SHA256 of sensitive data, never raw)
- Governance: `docs/governance/audit-trail.md`

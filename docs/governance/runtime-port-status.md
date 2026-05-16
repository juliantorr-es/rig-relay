# Runtime Port Status Normalization

Generated: 2026-05-15
Vocabulary: not_started | documented | contract_only | implemented | wired | validated | known_blocked | deprecated

## Core runtime

| Component | Status | Notes |
|---|---|---|
| AgentLoop conductor | validated | MRO mixins, ToolRuntime delegate, turn tracking |
| AgentRuntimeState | implemented | Snapshot model, `build_runtime_state()`, debug dict |
| ConversationTurnRuntime | implemented | Phase tracking in `_conversation_loop`, 10 phases |
| ToolRuntime | implemented | `execute_one()` owns cache→permission→approval→patch→invoke |
| RuntimeToolExecutionRunner | wired | Intent/lease/audit adapter over `ToolRuntime.execute_one()` |
| ToolRuntimeResult | implemented | Typed statuses, refusal codes, degradation |
| ToolRuntimeLedger | implemented | `InMemoryToolRuntimeResultLedger`, `ToolRuntimeResultSink` protocol |
| ToolRuntime projection | wired | `rig.ui.tool_runtime_summary.v1` via desktop projection + frontend widget |
| SessionLifecycleMixin | validated | `_reset_session`, `fork`, `compact`, `clear_history` |
| GovernanceMixin | validated | `approve_always`, `set_tool_permission`, session rules |
| TelemetryMixin | validated | Session telemetry + context observation |
| ContextEnvelopeMixin | validated | Context assembly + layout planning |
| MiddlewareMetadataMixin | validated | Pipeline setup, compact/stop/inject handling |

## Receipt pipeline

| Component | Status | Notes |
|---|---|---|
| Receipt model | implemented | `ToolRuntimeReceipt`, `ContextEnvelopeReceipt` |
| `build_receipt()` tool hook | implemented | Tool class method, captured on success |
| `capture_tool_receipt()` | implemented | Writes to `.rig/receipts/` |
| Receipt index | implemented | `build_receipt_index()` reads session receipts |
| Receipt projection integrity | implemented | `ProjectionIntegrityAssessment` |
| Receipt E2E tests | validated | `runtime_audit_event` + runtime invocation receipts are linked through result metadata |
| Policy validation path | documented | `docs/governance/receipt-envelope.md` |
| Write-file receipt validation | documented | Mutation tool receipts governed by patch gate |
| Receipt in desktop projection | wired | `integrity` field in projection |

## Ralph lifecycle

| Component | Status | Notes |
|---|---|---|
| Ralph scanner | implemented | `scan_projections()`, reads report + bash projections |
| Ralph models | implemented | `CandidateKind`, `ScanInput`, `RankedCandidate`, `MissionCandidate` |
| Ralph panel | implemented | `build_ralph_panel()`, action list |
| Ralph intents | implemented | `ralph_scan`, `ralph_approve`, `ralph_decline`, `ralph_rescan` |
| Ralph background lane gates | documented | `docs/governance/ralph-background-loop.md` |
| Ralph worktree lanes | documented | `docs/governance/ralph-worktree-lanes.md` |
| Ralph lifecycle projection | documented | Demo lifecycle visible, needs real runtime integration |

## Mission envelope

| Component | Status | Notes |
|---|---|---|
| Mission envelope design | documented | `docs/governance/mission-envelope.md` |
| Executable bridge | not_started | No code path from mission metadata → context/runtime |
| Mission envelope in receipts | not_started | Not yet bound to execution state |
| Orchestrator mission board | documented | Demo fixtures show synthetic missions |

## Provider registry

| Component | Status | Notes |
|---|---|---|
| Provider registry | implemented | `PROVIDER_REGISTRY` in `rig_relay/providers/registry.py` |
| Provider health check | implemented | `check_provider_status()` with network_allowed flag |
| Provider status in projection | wired | Desktop projection shows provider status |
| Trust tiers | not_started | Documented but not coded |
| Capability scoping | not_started | Context window, streaming, tool_calling not scoped per-provider |
| Background Ralph provider policy | not_started | No restriction on which providers Ralph can use |

## Workspace runtime

| Component | Status | Notes |
|---|---|---|
| Worktree root isolation | implemented | `_workspace_root` on AgentLoop |
| Artifact root | implemented | `.rig/relay/` and `.build/rig-relay/` |
| Receipt root | implemented | `.rig/relay/receipts/` |
| Projection root | implemented | `.build/rig-relay/desktop/projection.json` |
| Event ledger root | implemented | `~/.rig/relay/sessions/<id>/observability.jsonl` |
| Path policy enforcement | documented | `docs/governance/dependency-policy.md` |
| Audit trail parity | documented | Runtime-intent audit events now preserve runtime envelope hashes and source kind |

## Schema contracts

| Component | Status | Notes |
|---|---|---|
| Desktop projection schema | validated | `rig.relay.desktop_projection.v1.schema.json` |
| ToolRuntime summary schema | contract_only | `rig.ui.tool_runtime_summary.v1` (Pydantic, no JSON schema yet) |
| Context observation schema | validated | `rig.context_observation.v1.schema.json` |
| Context packet schema | validated | `rig.context_packet.v1.schema.json` |
| Report schema | validated | `rig.report.v1.schema.json` |
| Ralph scan schema | contract_only | `rig.ralph_scan.v1.schema.json` exists |
| Bash invocation schema | contract_only | `rig.bash_invocation.v1.schema.json` exists |
| IDE capability manifest | validated | `rig.ide.capability_manifest.v1.schema.json` |

## Stubs

| Component | Status | Notes |
|---|---|---|
| `rig_relay/identity/token_store.py` | documented | OAuth token store design exists; local mode works without it |
| `rig_relay/core/tools/builtins/git.py` | documented | Git operations gated behind merge/push policy |
| `RuntimeToolExecutionRunner` direct-invoke seam | documented | Normal runtime-intent path now converges through `ToolRuntime`; helper adapters remain for tool-specific backends |
| Demo seed/doctor | validated | Fresh-clone path works, 10/10 doctor checks |

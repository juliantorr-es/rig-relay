# Rig + Intake Cannibalization Plan for Rig Relay

## Status

**Established.** This plan classifies architecture patterns from
[Rig](https://github.com/juliantorr-es/Rig) and
[Intake](https://github.com/juliantorr-es/Intake) for selective porting into
Rig Relay. All P0 items are implemented and test-backed. P1 items have
deferred stubs with documented reasons. See also the existing
[Rig-to-Relay Porting Doctrine](../governance/rig-to-relay-porting-doctrine.md)
and [Pattern Inventory](../governance/rig-to-relay-pattern-inventory.md) for
prior porting work.

## Verdict

**Cannibalize Rig's cockpit/projection/progress semantics and Intake's
security/local-authority semantics. Keep Rig Relay's own agent runtime.**

| Source | What to take | Priority |
|---|---|---|
| Rig | Workspace/Operation/Lane/Receipt/Projection vocabulary | P0 |
| Rig | UI projection widget contracts | P0 |
| Rig | ProgressEvent stream model | P0 |
| Rig | Textual-retired stance for product copy | P0 |
| Intake | Hosted/local authority boundary | P0 |
| Intake | Signed local action envelope pattern | P0 |
| Intake | No-raw-token/no-innerHTML/no-eval frontend doctrine | P0 |
| Intake | Passkey localhost/RP-ID caveats | P1 |
| Rig | Lane/review/promotion/recommendation card shapes | P1 |
| Rig | Debug bundle idea | P1 |
| Both | Provider/runtime registries (deferred) | P2 |
| Intake | Deployment adapters (deferred) | P2 |

## Source Verification

All sources fetched 2026-05-14 from `main` branches via GitHub raw content.

| Document | Source | Verified |
|---|---|---|
| Rig README | `github.com/juliantorr-es/Rig` | ✅ |
| Rig Workspace Control Plane | `docs/architecture/workspace-control-plane.md` | ✅ |
| Rig UI Projection Contract | `docs/architecture/workspace-ui-projection-contract.md` | ✅ |
| Rig Progress Stream | `docs/architecture/workspace-progress-stream.md` | ✅ |
| Intake README | `github.com/juliantorr-es/Intake` | ✅ |
| Intake Hosted/Local Boundary | `docs/architecture/hosted-local-boundary.md` | ✅ |

## Classification

Status legend:
- **✅ done** — implemented and test-backed
- **✅ done-with-test-gap** — implemented but missing regression tests
- **⏳ intentionally deferred** — deferred with documented reason and stub policy
- **🚫 blocked** — blocked by external dependency
- **↪️ superseded** — replaced by a better solution

### port_now — do in next implementation slice

All P0 items.

#### 1. Workspace / Operation / Lane / Receipt / Projection vocabulary  [✅ done]

| Field | Value |
|---|---|
| **Source repo** | Rig |
| **Source documents** | `docs/architecture/workspace-control-plane.md` |
| **Target in Rig Relay** | `docs/schemas/rig.relay.operation.v1.schema.json`, `docs/schemas/rig.relay.child_session.receipt.v1.schema.json`, update `vibe/core/coordination/_models.py` vocabulary comments |
| **Rationale** | Rig's Workspace→Operation→Receipt→Projection chain is the exact model Rig Relay already approximates with RelaySession/ChildSession/current_state. Giving it the canonical Rig vocabulary aligns docs, schemas, and code. Specifically: RelaySession ≈ Operation, ChildSession/FleetLane ≈ AgentLane, current_state/projection ≈ Workspace Projection, intent_events/result artifacts ≈ Receipts |
| **Risk** | Low. Pure vocabulary alignment and schema additions. No code refactor needed. |
| **Validation** | `uv run pyright`, `uv run pytest -n0 tests/docs/` |

#### 2. Desktop Projection Widget Contract  [✅ done]

| Field | Value |
|---|---|
| **Source repo** | Rig |
| **Source documents** | `docs/architecture/workspace-ui-projection-contract.md` |
| **Target in Rig Relay** | `docs/governance/relay-desktop-projection-contract.md`, `rig_relay/desktop/projection_widgets.py`, `tests/scripts/test_desktop_projection_contract.py` |
| **Rationale** | Rig's UI projection contract explicitly says "frontend is a renderer, not a governor" and defines 8 widget types with fields, allowed intentions, and forbidden inferences. Rig Relay's current projection builder (`scripts/rig_relay_desktop_projection.py`) already produces a content-light projection but does not organize it into Rig's widget hierarchy. Porting the widget contract gives the desktop cockpit a structured render framework. |
| **Risk** | Medium. The Rig widget set (WorkspaceHeader, AgentLaneCard, LaneReviewCard, PromotionPlanCard, LaneRecommendationCard, CommandProgressCard, ReceiptTimeline, WorkspaceGitState, WorkspaceLaneSummary) must be adapted to Relay concepts, not copied verbatim. Relay-specific widgets: OperatorHeader, SafetyState, NextAction, ActiveChildSessions, ValidationSummary, StorageBudget, ReceiptTimeline, LatestIntentResult, RefinementBacklog. |
| **Validation** | `uv run pytest -n0 tests/docs/test_rig_intake_cannibalization_plan.py` + manual review of `scripts/rig_relay_desktop_projection.py` for widget alignment |

#### 3. ProgressEvent Stream Model  [✅ done]

| Field | Value |
|---|---|
| **Source repo** | Rig |
| **Source documents** | `docs/architecture/workspace-progress-stream.md` |
| **Target in Rig Relay** | `docs/schemas/rig.relay.progress_event.v1.schema.json`, `rig_relay/desktop/progress_events.py`, `rig_relay/desktop/websocket_server.py`, `tests/scripts/test_progress_events.py` |
| **Rationale** | Rig defines a clean ProgressEvent model with phases (operation.started, operation.log, operation.progress, operation.completed, workspace.projection.refreshed, etc.), WebSocket envelope shape, and transport guidance (prefer existing WS, no second transport). Rig Relay already has a desktop WebSocket server (`scripts/rig_relay_desktop_websocket.py`) and an intent event schema (`rig.relay.desktop_intent_event.v1`). Rig's progress_event fills the gap between intent dispatch and projection refresh. |
| **Risk** | Medium. Rig's ProgressEvent uses Rig-specific fields (workspace_id, workspace_path, receipt_candidate). Must be adapted to Relay equivalents (session_id, operation_id, child_session_id). Transport is already WebSocket — no new transport needed. |
| **Validation** | `uv run python scripts/rig_relay_validate_schemas.py` (schema validation), `uv run pytest -n0 tests/docs/` |

#### 4. Textual-Retired Product Copy  [✅ done]

| Field | Value |
|---|---|
| **Source repo** | Rig |
| **Source documents** | Rig README: "Textual TUI: Retired. Use `rig ui` for a rich interface or CLI commands for terminal workflows." |
| **Target in Rig Relay** | Update `README.md`, `docs/governance/textual-retirement-policy.md`, update product copy in `vibe/core/skills/builtins/vibe.py` |
| **Rationale** | Rig Relay's README still describes it as "a command-line coding assistant harness" and documents `vibe` as a compatibility alias. The README should say: "Rig Relay is a governed local agent cockpit. CLI agents propose work. Relay routes tools, coordinates child sessions, preserves evidence, validates outputs, and keeps mutation authority local." The Textual TUI should be documented as legacy/diagnostics-only. |
| **Risk** | Low. Copy-only change. Does not modify behavior. |
| **Validation** | `uv run ruff format .` and `uv run ruff check --fix .` |

#### 5. Hosted/Local Authority Boundary  [✅ done]

| Field | Value |
|---|---|
| **Source repo** | Intake |
| **Source documents** | `docs/architecture/hosted-local-boundary.md`, README |
| **Target in Rig Relay** | `docs/governance/relay-local-remote-boundary.md`, `docs/governance/telemetry-redaction-boundary.md` |
| **Rationale** | Intake's split-brain architecture (public backend stores ciphertext/redacted metadata, local console owns decryption/authority) maps directly to Rig Relay's planned remote telemetry model. The alpha telemetry rule should be: cloud/shared data gets redacted projections and content-light rows; local cockpit keeps authority and sensitive evidence. |
| **Risk** | Low. Policy document only. No code changes. |
| **Validation** | `uv run ruff format .`, `uv run pyright` |

#### 6. Signed Local Action Envelope  [✅ done]

| Field | Value |
|---|---|
| **Source repo** | Intake |
| **Source documents** | `docs/architecture/hosted-local-boundary.md` (Signed Local Device Actions section) |
| **Target in Rig Relay** | `docs/schemas/rig.relay.local_action_envelope.v1.schema.json`, `rig_relay/governance/local_action_envelope.py`, `tests/governance/test_local_action_envelope.py` |
| **Rationale** | Intake's signed local action envelope uses Ed25519 signatures, canonicalized payloads, action_id/nonce/issued_at replay prevention, and cryptographic signatures. This is the exact model for Rig Relay's future protected-intent receipt system. The receipt-gated protected intents system already exists in `rig_relay/evidence/receipt_gate.py` — the signed envelope gives it a cryptographic container for intent requests. |
| **Risk** | Low for schema definition. Implementation is future; this slice defines the schema and model only. |
| **Validation** | `uv run python scripts/rig_relay_validate_schemas.py` |

#### 7. Frontend Rendering Safety Doctrine  [✅ done]

| Field | Value |
|---|---|
| **Source repo** | Intake |
| **Source documents** | Intake README (security boundaries section) |
| **Target in Rig Relay** | `docs/governance/frontend-rendering-safety.md`, `tests/frontend/test_no_inner_html_for_untrusted_fields.mjs` |
| **Rationale** | Intake lists explicit security rules: no raw session tokens in storage, no plaintext sensitive data in long-term DB, encryption for readable sensitive data, hashing for lookup/deduplication, no innerHTML for user-controlled frontend content, no eval/dynamic code execution, no public backend subprocess/Git commands. Rig Relay already follows most of these in practice but has no written doctrine. |
| **Risk** | Low. Policy document + test skeleton. |
| **Validation** | `uv run ruff format .`, `uv run pyright` |

### port_next — after UI redesign

All P1 items.

#### 8. Rig Lane/Review/Promotion/Recommendation Card Shapes  [⏳ intentionally deferred]

| Field | Value |
|---|---|
| **Source repo** | Rig |
| **Source documents** | `docs/architecture/workspace-ui-projection-contract.md` (AgentLaneCard, LaneReviewCard, PromotionPlanCard, LaneRecommendationCard) |
| **Target in Rig Relay** | Rig Relay desktop widgets: `ActiveChildSessionCard`, `ReadyWorkPlanCard`, `ParentConvergenceCard`, `NextSafeActionCard` |
| **Rationale** | Rig's lane/review/promotion/recommendation widgets map exactly to Rig Relay's delegate/fleet UI. ActiveChildSession maps to AgentLaneCard, ReadyWorkPlan maps to PromotionPlanCard, ParentConvergence maps to LaneReviewCard, NextSafeAction maps to LaneRecommendationCard. |
| **Risk** | Medium. Requires UI redesign first. Do not implement until the cockpit widget hierarchy is stable. |
| **Validation** | Manual UI review + `uv run pytest -n0 tests/docs/` |

#### 9. Debug Bundle  [⏳ intentionally deferred]

| Field | Value |
|---|---|
| **Source repo** | Rig |
| **Source documents** | Rig README: `rig debug bundle` |
| **Target in Rig Relay** | `rig_relay/evidence/debug_bundle.py` (consolidate existing ChatGPT dev bundles + telemetry bundles under one command) |
| **Rationale** | Rig Relay already has `scripts/rig_relay_create_chatgpt_dev_bundle.py` and `scripts/rig_relay_create_telemetry_bundle.py`. Consolidating under `rig-relay debug bundle` gives a single command for review/debug output. |
| **Risk** | Low. Mostly script consolidation and documentation. |
| **Validation** | `uv run pytest -n0 tests/` |

#### 10. Intake Passkey Localhost Caveats  [⏳ intentionally deferred]

| Field | Value |
|---|---|
| **Source repo** | Intake |
| **Source documents** | Intake README (passkey section, localhost vs 127.0.0.1 note) |
| **Target in Rig Relay** | `docs/governance/future-passkey-plan.md` (deferred reference) |
| **Rationale** | Intake documents that local dev passkeys use localhost not 127.0.0.1 because RP ID cannot be an IP address. Document this for when WebAuthn/passkeys are added to Rig Relay. No implementation now. |
| **Risk** | None. Reference doc only. |
| **Validation** | `uv run ruff format .` |

### defer — later

All P2 items.

#### 11. Rig Provider/Runtime Registries  [⏳ intentionally deferred]

| Field | Value |
|---|---|
| **Source repo** | Rig |
| **Target** | Rig Relay provider layer |
| **Rationale** | Useful once Vibe provider layer becomes painful. Not the immediate bottleneck. Rig's `rig provider list` / `rig runtime list` / `rig model list` commands could inspire a Relay-native provider registry. |
| **Risk** | Low priority. Keep on backlog. |

#### 12. Intake Deployment Adapters  [⏳ intentionally deferred]

| Field | Value |
|---|---|
| **Source repo** | Intake |
| **Target** | Future alpha telemetry deployment |
| **Rationale** | Useful for `rig-relay publish alpha telemetry` or Google Drive/bootstrap flows. Not relevant to cockpit redesign. |
| **Risk** | Low priority. Keep on backlog. |

### reject — not suitable

| Candidate | Source | Reason |
|---|---|---|
| Raw Intake quote domain / service lanes | Intake | Business-domain specific to freelance services. Not relevant to Rig Relay. |
| Intake public-hosted backend implementation | Intake | Specific to Railway/Fly deployment. Rig Relay's alpha telemetry is local-first. |
| Intake production passkey workflow | Intake | Requires WebAuthn RP origin setup. Not yet relevant. |
| Rig Python 3.14-only policy | Rig | Rig Relay is 3.12+ and has no reason to raise the floor. |
| Rig old placeholder UI files | Rig | Rig Relay already has newer cockpit code (`frontend/desktop/`). |
| Anigma-specific migration residue | Rig | Product history, not architecture. |
| Second transport beside WebSocket | Rig/Intake | Rig's progress stream doc explicitly says not to introduce a second transport. |

## Existing Rig Relay Patterns to Keep (not cannibalize)

These are Rig Relay's substrate that should be refined, not replaced:

- Agent loop (`vibe/core/agent/`)
- Provider integration (`vibe/core/providers/`)
- Tool registry (`vibe/core/tools/`)
- Existing CLI compatibility (`vibe/cli/`)
- Config/home migration path (`_config.py`, `_settings.py`)
- Desktop/frontend assets (`frontend/desktop/`)
- Audited intent pipeline (`rig_relay/evidence/`)
- Validation suite (`scripts/rig_relay_validate_*.py`)
- Coordination store/tool (`vibe/core/coordination/`)
- Receipt-gated protected intents (`rig_relay/evidence/receipt_gate.py`)

## Out-of-Scope Findings from Audit

### `.build/rig-relay` is tracked in git

The `.build/rig-relay/` directory contains runtime-generated artifacts
(coordination leases, chatgpt bundles, sprint cockpits, telemetry bundles,
desktop projections) and is **committed to the public git repository**
(`git ls-files .build/ | wc -l` shows thousands of tracked files).

**Impact:** This causes repository bloat, exposes internal coordination state
(session IDs, task claims, path leases) in the public repo, and makes `git clone`
significantly larger than necessary. The `.gitignore` does not list `.build/`.

**Recommendation:** Add `.build/` to `.gitignore` and remove tracked files with
`git rm -r --cached .build/`. If certain sample artifacts should remain tracked
(for dogfood demos), move them to a `docs/samples/` directory.

## Recommended Implementation Sequence

1. **Cockpit IA redesign** — Wire Rig's widget hierarchy into the desktop projection builder
2. **Desktop projection contract** — Port Rig's UI projection contract as `relay-desktop-projection-contract.md`
3. **ProgressEvent model** — Port Rig's progress_event schema into Relay WebSocket stream
4. **Local/remote authority boundary** — Port Intake's boundary as `relay-local-remote-boundary.md`
5. **Signed action envelope** — Define `rig.relay.local_action_envelope.v1` schema
6. **Frontend rendering safety** — Port Intake's security rules as `frontend-rendering-safety.md`

**Rationale for order:** The UI currently feels rough because it does not yet
have Rig's projection/widget hierarchy. Do not add more authority to a rough UI.
Give it the Rig cockpit model first.

## Cross-References

- [Rig-to-Relay Porting Doctrine](../governance/rig-to-relay-porting-doctrine.md)
- [Rig-to-Relay Pattern Inventory](../governance/rig-to-relay-pattern-inventory.md)
- [Desktop Cockpit UI Doctrine](../governance/desktop-cockpit-ui.md)
- [Relay Desktop Projection Contract](../governance/relay-desktop-projection-contract.md)
- [Relay Local/Remote Boundary](../governance/relay-local-remote-boundary.md)
- [Frontend Rendering Safety](../governance/frontend-rendering-safety.md)

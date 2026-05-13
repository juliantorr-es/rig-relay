# Rig-to-Relay Porting Doctrine

## Status

**Established.** This doctrine governs how proven architecture patterns from the
[Rig](https://github.com/user/rig) project may be ported into Rig Relay.

## Canonical Roles

| Role | Identity | Function |
|---|---|---|
| **Rig** | Architecture lab / upstream | Proves orchestration, governance, and product-shell patterns |
| **Rig Relay** | Agent-runtime product | Ports/adapts proven Rig patterns into the Vibe-derived agent runtime |
| **Relay** | Future unified product surface | Becomes the canonical home if the repos diverge too far for the split to pay rent |

## Core Rules

### Rule 1: Port Patterns, Not Product Domain

Rig patterns may be ported into Rig Relay **only through Relay-native interfaces,
tests, and docs**. The goal is to absorb proven architectural shapes, not Rig's
product-domain code.

**Allowed to port:**
- Projection model (backend-owned, typed, content-light)
- pywebview shell architecture (backend authority + dumb renderer)
- WebSocket stream protocol shape (ordered, deterministic, backpressure-aware)
- Intent dispatcher pattern (typed intents, backend authority, idempotency)
- Worktree-backed execution isolation
- Receipt/checkpoint store patterns
- Update/restart policy
- UI polish patterns (CSS layout, dark theme, status cards)

**Not allowed to port blindly:**
- Rig-specific product domain (WorkspaceHeader, ProposalLifecycle, AuditTrail, ChatUI)
- Stale assumptions that no longer hold (e.g. Rig's job store semantics)
- UI-side authority of any kind
- Duplicated job-store semantics that conflict with CoordinationStore
- Anything that bypasses Rig Relay guards, checkpoints, telemetry, or authorization gates

### Rule 2: No Direct Rig Runtime Dependency

Rig Relay MUST NOT import `rig.*` or `rig_tools.*` at runtime. All ported patterns
must be re-implemented or adapted behind Relay-native interfaces.

Exceptions:
- Reading Rig source files during development to understand a pattern
- Copying small code fragments (< 20 lines) with provenance notes
- Referencing Rig docs in design discussions

### Rule 3: No UI-Side Authority

The frontend (pywebview shell) is a **dumb renderer** of backend-authored projections.
It does not enforce policy, does not mutate state without backend validation, and
does not bypass:
- Dirty-file guard
- Coordination leases
- Checkpoint policy
- Telemetry gates
- Authorization receipts

### Rule 4: Backend Remains Authoritative

All tool execution, guard enforcement, coordination, checkpointing, telemetry, queue,
and spawn operations remain on the backend. The backend owns:
- State transitions
- Action legality
- Governance enforcement
- Evidence generation

### Rule 5: Every Port Requires Provenance

Each ported pattern must document:
1. **Rig source files inspected** — which files were read and what patterns were extracted
2. **Adaptation notes** — what changed from the Rig pattern to the Relay-native interface
3. **Tests** — parity tests demonstrating the Relay behavior matches the useful Rig behavior
4. **Docs** — documentation of the Relay-native interface
5. **Deprecation decision** — whether Rig keeps owning the pattern or Relay becomes canonical

### Rule 6: Governed by Strangler Fig, Not Fork

Rig Relay follows a controlled **Strangler Fig migration** away from upstream Vibe.
Vibe-derived modules are legacy substrate being gradually replaced by Relay-native
seams. See [Vibe Legacy Deprecation Doctrine](vibe-legacy-deprecation.md).

## Migration Model

### 1. Pattern Inventory
List Rig systems worth porting in `docs/governance/rig-to-relay-pattern-inventory.md`.

### 2. Adapter Slice
Port one pattern into Rig Relay behind a new Relay-native interface.

### 3. Provenance Note
Document source files inspected and what changed.

### 4. Parity Test
Assert the Relay behavior matches the useful Rig behavior.

### 5. Deprecation Decision
Decide whether Rig keeps owning that pattern or Relay becomes the canonical version.

## Porting Statuses

| Status | Meaning |
|---|---|
| `candidate` | Pattern identified but not yet ported |
| `porting` | Active port in progress |
| `ported` | Successfully ported to Relay-native interface |
| `deferred` | Postponed to a later slice |
| `rejected` | Not suitable for porting (document why) |
| `superseded-by-relay-native` | Rig pattern was ported then replaced by a Relay-native solution |

## Cross-References

- [Rig-to-Relay Pattern Inventory](rig-to-relay-pattern-inventory.md)
- [Desktop Cockpit UI Doctrine](desktop-cockpit-ui.md)
- [Reviewer Orchestrator Doctrine](reviewer-orchestrator.md)
- [Delegate/Fleet Orchestration](delegate-fleet-orchestration.md)
- [Step-Up Authorization](step-up-authorization.md)
- [Vibe Legacy Deprecation Doctrine](vibe-legacy-deprecation.md)
- [Self-Dogfood Workflow](../dogfood/rig-relay-self-dogfood.md)

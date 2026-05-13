# Vibe Legacy Deprecation Doctrine

## Status

**Established.** Rig Relay is an independent product line. Vibe-derived modules
are legacy substrate being gradually replaced by Relay-native seams through a
controlled Strangler Fig migration.

## Core Doctrine

### Rig Relay Is the Product

Rig Relay is not "Vibe with governance bolted on." It is an independent
agent-runtime product that happens to share Vibe CLI provenance. The public
product identity, package metadata, CLI commands, desktop title, telemetry
schemas, and update status all say **Rig Relay**.

### Vibe Modules Are Legacy Substrate

The `vibe.*` package tree is derived from the upstream Mistral Vibe CLI.
It contains the agent loop, LLM backends, tool registry, and CLI framework.
These modules are **legacy bones** being strangulated — not the product
architecture.

### Migration Follows Strangler Fig, Not Fork

Following Fowler's Strangler Fig pattern, the new system (`rig_relay.*`) grows
around the old system (`vibe.*`) until the old system can be replaced. This is
a controlled migration, not a high-risk rewrite.

## Migration Phases

| Phase | Name | Description |
|---|---|---|
| **Phase 1** | Relay-native façade | New entrypoints and package spine (`rig_relay.*`) established. Existing `vibe.*` internals remain behind adapters. |
| **Phase 2** | Relay-owned seams | Tool execution, telemetry, coordination, checkpoint, desktop, queue, current_state move into `rig_relay.*` modules. `vibe.*` may import from `rig_relay.*`. |
| **Phase 3** | Legacy quarantine (active) | Upstream Vibe modules move behind `vibe/legacy/` or equivalent. New product code does not import from `vibe/core` directly. `vibe/legacy/` namespace established. Remaining `scripts/` migrated to `rig_relay.*`. |
| **Phase 4** | Replace agent-loop boundary | Relay owns the session lifecycle and calls provider/tool adapters. |
| **Phase 5** | Delete or vendor remaining legacy | Vibe bones are either deleted, vendored, or kept only as compatibility shims. |

### Current Phase

**Phase 3 (Legacy quarantine)** — The `vibe/legacy/` namespace is established.
Six scripts migrated to `rig_relay.*` modules. Authorization receipt seam
migrated. Dirty-file guard seam migrated: `vibe/core/guard/` is now a
compatibility adapter re-exporting from `rig_relay.governance.dirty_guard`.
Desktop Chat Shell state and WebSocket protocol established as Relay-native
seams in `rig_relay.desktop.chat_state`. Coordination migration is now
explicitly inventory-first: `docs/audits/coordination-migration-inventory.md`
records the current surface, target boundary, and adapter strategy. The
coordination models and store now live in `rig_relay.coordination.*`, while
`vibe.core.coordination` remains a compatibility adapter during alpha. The
built-in coordination tool execution helpers now live in `rig_relay.coordination.tool`,
while `vibe.core.tools.builtins.coordination` remains the registry-facing
compatibility adapter. Full tool registry migration is deferred to a later slice. Remaining
Vibe core modules are being quarantined behind the legacy barrier.

## Compatibility Rules

### Rule 1: Existing `vibe.*` Imports Remain Supported

All existing `vibe.*` imports continue to work during alpha. No code that
imports `from vibe.core.x import ...` will break. This is a **compatibility
guarantee** for the alpha period.

### Rule 2: New Product Code Targets `rig_relay.*`

New product code should prefer `rig_relay.*` as the target architecture.
Existing `vibe.*` modules may later wrap or import Relay-native
implementations.

### Rule 3: No Circular Imports Between `rig_relay` and `vibe`

`rig_relay.*` MUST NOT import from `vibe.*` (that would re-introduce the
legacy dependency). `vibe.*` may import from `rig_relay.*` during Phase 2
and Phase 3 as adapters are built.

### Rule 4: No Broad Deletion or Rename

No file is deleted or renamed until adapters and tests exist. The migration
is additive — new modules appear, old modules are left in place until proven
unused.

### Rule 5: Public Product Identity Is Rig Relay

All public-facing surfaces must use Rig Relay identity:
- **Package name**: `rig-relay` (pyproject.toml)
- **Python version**: `0.1.0a1` (PEP 440)
- **CLI command**: `rig-relay` / `rig-relay-acp`
- **Desktop title**: `Rig Relay Cockpit`
- **Telemetry schemas**: `rig.relay.*`
- **Update status**: `rig-relay` product channel

## Authority Boundaries

All governance authority remains on the backend. The frontend is a dumb
renderer. See [Rig-to-Relay Porting Doctrine](rig-to-relay-porting-doctrine.md)
for full porting rules.

## Cross-References

- [Rig-to-Relay Porting Doctrine](rig-to-relay-porting-doctrine.md)
- [Rig-to-Relay Pattern Inventory](rig-to-relay-pattern-inventory.md)
- [Vibe Legacy Boundary Inventory](../audits/vibe-legacy-boundary-inventory.md)
- [Desktop Cockpit UI Doctrine](desktop-cockpit-ui.md)
- [Versioning Policy](../release/versioning-policy.md)
- [Install Channels](../install.md)
- [Self-Dogfood Workflow](../dogfood/rig-relay-self-dogfood.md)

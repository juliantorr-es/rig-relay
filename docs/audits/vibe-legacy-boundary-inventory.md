# Vibe Legacy Boundary Inventory

Canonical inventory of Vibe-derived modules and their migration status.
This inventory governs which modules are legacy substrate and where they
target in the Relay-native architecture.

## Migration Statuses

| Status | Meaning |
|---|---|
| `legacy` | Vibe-derived; not yet migrated |
| `adapting` | Wrapper or import redirect exists |
| `migrated` | Implementation lives in `rig_relay.*` |
| `retained` | Kept intentionally (no migration planned) |
| `deprecated` | Scheduled for deletion |
| `deleted` | Removed |

## Inventory

### 1. `vibe/core/tools/builtins/`

| Field | Value |
|---|---|
| **Current responsibility** | Built-in tool implementations: bash, read_file, write_file, search_replace, checkpoint, coordination, task, grep, web_fetch, etc. |
| **Product-critical?** | Yes — tools are the executor interface |
| **Relay-native target** | `rig_relay.runtime.tools` |
| **Migration status** | `legacy` |
| **Risk** | Tools are tightly coupled to `BaseTool`, `InvokeContext`, and telemetry types. Migration requires a stable tool interface first |
| **Recommended slice** | Phase 2 after coordinator/current_state migration |

### 2. `vibe/core/llm/`

| Field | Value |
|---|---|
| **Current responsibility** | LLM backends: Anthropic, Mistral, OpenAI, Vertex. Message formatting, types, error handling. |
| **Product-critical?** | Yes — core provider boundary |
| **Relay-native target** | `rig_relay.runtime.providers` |
| **Migration status** | `legacy` |
| **Risk** | Deeply coupled to Vibe message types and streaming semantics. High risk to change during alpha |
| **Recommended slice** | Phase 4 (replace agent-loop boundary) |

### 3. `vibe/core/agent_loop.py`

| Field | Value |
|---|---|
| **Current responsibility** | Main agent orchestration loop: prompt assembly, tool call dispatch, streaming, conversation management |
| **Product-critical?** | Yes — central orchestration |
| **Relay-native target** | `rig_relay.runtime.agent_loop` |
| **Migration status** | `legacy` |
| **Risk** | Highest-risk migration. Deep coupling to LLM backends, tool system, session lifecycle, and event types |
| **Recommended slice** | Phase 4 (replace agent-loop boundary) |

### 4. `vibe/core/telemetry/`

| Field | Value |
|---|---|
| **Current responsibility** | Telemetry event emission, artifact building, bundle creation, duckdb projection, doctor, validation |
| **Product-critical?** | Yes — governance evidence pipeline |
| **Relay-native target** | `rig_relay.governance.telemetry`, `rig_relay.evidence.*` |
| **Migration status** | `legacy` |
| **Risk** | Telemetry events are used throughout the codebase. Migration requires stable event contracts |
| **Recommended slice** | Phase 2 after coordination migration. Start with bundle/dataset scripts |

### 5. `vibe/core/coordination/`

| Field | Value |
|---|---|
| **Current responsibility** | Coordination store, models, path leases, task claims, conflict detection, state projections |
| **Product-critical?** | Yes — multi-session governance |
| **Relay-native target** | `rig_relay.coordination.store`, `rig_relay.coordination.leases` |
| **Migration status** | `legacy` |
| **Risk** | `CoordinationStore` is used by checkpoint tool and guard. Migration requires stable interface |
| **Recommended slice** | Phase 2. Start with `current_state` + queue planner (lowest-risk seams) |

### 6. `vibe/core/guard/`

| Field | Value |
|---|---|
| **Current responsibility** | Dirty file guard: capture, snapshot, report, touch tracking |
| **Product-critical?** | Yes — core governance primitive |
| **Relay-native target** | `rig_relay.governance.guard` |
| **Migration status** | `legacy` |
| **Risk** | Tightly coupled to checkpoint tool. Migration requires coordination lease stability |
| **Recommended slice** | Phase 2 alongside checkpoint tool migration |

### 7. `vibe/core/auth/`

| Field | Value |
|---|---|
| **Current responsibility** | Crypto (encrypt/decrypt), GitHub auth provider, authorization receipts |
| **Product-critical?** | Yes — authorization gates |
| **Relay-native target** | `rig_relay.governance.auth` |
| **Migration status** | `adapting` (receipt.py already a Relay-native seam) |
| **Risk** | GitHub auth is Vibe-specific (keyring). Crypto module has no Relay equivalent yet |
| **Recommended slice** | Phase 2. Receipt module is already Relay-native. Migrate crypto/auth adapters |

### 8. `vibe/cli/`

| Field | Value |
|---|---|
| **Current responsibility** | CLI entrypoint, command definitions, Textual TUI, update notifier, voice manager, narrator, plan offer |
| **Product-critical?** | Yes — user interface |
| **Relay-native target** | `rig_relay.cli.commands`, `rig_relay.cli.tui` (or replace TUI with desktop) |
| **Migration status** | `legacy` |
| **Risk** | CLI depends on agent loop and tool system. Textual TUI is being deprecated in favor of desktop |
| **Recommended slice** | Phase 3 (after seams are migrated). Start with `rig-relay` entrypoint alias, then migrate commands |

### 9. `scripts/`

| Field | Value |
|---|---|
| **Current responsibility** | Standalone product scripts: upload, cleanup, desktop, projection, current_state, spawn, validation, update, export, dataset, telemetry bundle |
| **Product-critical?** | Yes — product features |
| **Relay-native target** | `rig_relay.desktop.*`, `rig_relay.coordination.*`, `rig_relay.evidence.*`, `rig_relay.cli.doctor` |
| **Migration status** | `adapting` (scripts call each other via importlib; no direct `vibe.*` dependency in modern scripts) |
| **Risk** | Scripts are importable but not structured as a package. Migration is additive |
| **Recommended slice** | Phase 2 (lowest-risk migration). Start with `rig_relay.desktop.projection`, `rig_relay.coordination.current_state`, `rig_relay.evidence.telemetry_bundle` |

### 10. `frontend/desktop/`

| Field | Value |
|---|---|
| **Current responsibility** | HTML/CSS/JS frontend assets for pywebview desktop cockpit |
| **Product-critical?** | Yes — desktop UI |
| **Relay-native target** | `rig_relay.desktop.frontend` |
| **Migration status** | `legacy` |
| **Risk** | Static assets with no build step. Low migration risk |
| **Recommended slice** | Phase 2 alongside desktop script migration. Move file paths to `rig_relay.desktop` |

### 11. `docs/schemas/`

| Field | Value |
|---|---|
| **Current responsibility** | JSON Schema drafts for all telemetry, coordination, projection, and governance event types |
| **Product-critical?** | Yes — data contract surface |
| **Relay-native target** | `docs/schemas/` (stays in docs — no module migration needed) |
| **Migration status** | `retained` |
| **Risk** | Schemas are docs, not code. No migration needed |
| **Recommended slice** | N/A — retain in docs/schemas/ |

### 12. `vibe/core/` (other modules)

| Field | Value |
|---|---|
| **Current responsibility** | Types, config, session, logger, loop, middleware, hooks, system_prompt, relay, skills, tracing, teleport, utils, paths |
| **Product-critical?** | Mixed — config, session, types are critical; others are utility |
| **Relay-native target** | Various `rig_relay.*` modules |
| **Migration status** | `legacy` |
| **Risk** | Medium — utilities can migrate individually |
| **Recommended slice** | Phase 3 after governance seams are stable |

## Summary

| Priority | Path | Status | Target | Slice |
|---|---|---|---|---|
| P0 | `vibe/core/agent_loop.py` | `legacy` | `rig_relay.runtime.agent_loop` | Phase 4 |
| P0 | `vibe/core/llm/` | `legacy` | `rig_relay.runtime.providers` | Phase 4 |
| P0 | `vibe/core/tools/builtins/` | `legacy` | `rig_relay.runtime.tools` | Phase 2 |
| P0 | `vibe/core/coordination/` | `legacy` | `rig_relay.coordination.*` | Phase 2 |
| P0 | `vibe/core/guard/` | `legacy` | `rig_relay.governance.guard` | Phase 2 |
| P0 | `vibe/core/telemetry/` | `legacy` | `rig_relay.governance.telemetry` | Phase 2 |
| P0 | `vibe/core/auth/` | `adapting` | `rig_relay.governance.auth` | Phase 2 |
| P0 | `vibe/cli/` | `legacy` | `rig_relay.cli.*` | Phase 3 |
| P1 | `scripts/` | `adapting` | `rig_relay.*` | Phase 2 |
| P1 | `frontend/desktop/` | `legacy` | `rig_relay.desktop.frontend` | Phase 2 |
| P2 | `docs/schemas/` | `retained` | `docs/schemas/` | N/A |

## Cross-References

- [Vibe Legacy Deprecation Doctrine](../governance/vibe-legacy-deprecation.md)
- [Rig-to-Relay Porting Doctrine](../governance/rig-to-relay-porting-doctrine.md)
- [Rig-to-Relay Pattern Inventory](../governance/rig-to-relay-pattern-inventory.md)

# Context Compiler Doctrine

**Status:** Phase 1 — MVP map mode.

## Purpose

The context compiler is the domain logic behind `rig.get_context`, the
governed read-only context front door for Rig Relay agents. It answers:

- What is this repository?
- What subsystems exist?
- What files matter for this mission?
- Who else is touching nearby files?
- What should I avoid touching?
- What context can fit in my model budget?

## Core Rules

1. **`rig.get_context` is read-only.** It must never mutate the repo,
   worktrees, ledgers, receipts, or build outputs.

2. **The manifest is the authority.** Subsystem detection is structural
   (file tree, naming conventions), not semantic (AST). Symbols are
   discovered by convention, not by full index.

3. **Collision warnings are advisory.** The context tool reports
   overlapping claims but does not enforce locks. Enforcement is a
   separate governance concern.

4. **Receipts are content-light.** The receipt contains hashes, counts,
   and timestamps — never raw file contents, diffs, or secrets.

5. **Substituted packets are derived views.** The canonical packet
   (pre-substitution) is the source of truth. The `canonical_packet_sha256`
   and `optimized_packet_sha256` fields prove the correspondence.

## Modes

| Mode | Speed | What it returns |
|---|---|---|
| `map` | Fast | Repo topology, dirty state, subsystem map, active lanes, collision warnings |
| `packet` | Heavy | Everything in `map` + receipt scan, selected file excerpts, symbol table |
| `handoff` | Medium | Agent-specific handoff: do-not-touch list, current blockers, recommended next files |
| `collision` | Fast | Path conflict check only: which lanes claim which paths |
| `symbols` | Fast | Symbol substitution table and definitions only |

## Compression

| Mode | Behavior |
|---|---|
| `none` | Full names, full paths. |
| `light` | Short path aliases. |
| `symbol_substitution` | Replace repeated long names with short aliases (e.g., `⟦S1⟧`). Substitution table included in output. |
| `aggressive` | Aggressive compression with lossy summarization. Not yet implemented. |

## Relation to Other Systems

- **ACP**: The context tool is a built-in Rig tool, not an ACP command.
  ACP sessions can call `get_context` as a tool within a mission.

- **MCP**: `rig.get_context` will be exposed as an MCP tool. MCP resources
  (`rig://context/current`, `rig://repo/map`, `rig://work/active`,
  `rig://receipts/latest`, `rig://symbols/index`) will be added later.

- **IDE Sidecar**: IDE active buffer, selection, and diagnostics can
  become inputs to context requests in future versions. For now the
  tool is file-system-driven.

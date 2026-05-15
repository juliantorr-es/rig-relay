# Rig MCP Server — Capability Map

The first 16 MCP tools exposed by Rig Relay. Designed for consumption by
Antigravity, VS Code, Zed, Cursor, and other MCP hosts.

Tools are organized into 5 tiers. Tiers 0-2 are always available.
Tiers 3+ require authorization receipts.

## Tier 0 — Read-Only Context

Tools that inspect state without any mutation. Safe by default.

### `rig.current_mission`
Get the active mission envelope: scope, sprint, task assignments.

### `rig.search_evidence`
Search the evidence ledger for receipts, findings, and coordination events.

### `rig.read_receipt`
Read a specific receipt by ID. Returns summary + content hashes.

### `rig.list_worktrees`
List all tracked git worktrees: workspace ID, path, status, HEAD SHA.

### `rig.inspect_schema`
Inspect a Rig schema (mission-envelope, receipt, patch-proposal, consultation).

### `rig.summarize_dirty_state`
Summarize dirty files with path hashes only. No file contents exposed.

### `rig.run_readonly_doctor`
Read-only diagnostics: git repo check, worktree health, lease status.

## Tier 1 — Analysis / Packet Generation

Non-mutating tools that produce artifacts.

### `rig.build_context_packet`
Build a content-light mission context packet with configurable redaction.

### `rig.create_consult_packet`
Create a structured consultation packet for adversarial provider review.

### `rig.compare_provider_opinions`
Compare council findings across providers. Returns consensus and disagreements.

## Tier 2 — Validation / Bounded Execution

Run known validators and audits. Read-only outputs.

### `rig.run_validator`
Run an approved validator (pytest, ruff, pyright, work_doctor). Returns receipt.

### `rig.check_merge_friendly`
Check if the working tree is clean and safe to merge.

### `rig.audit_dirty_state`
Audit dirty file state and produce a recommendation.

## Tier 3 — Patch Proposal

Creates artifacts for review. Does NOT apply to the workspace.

### `rig.propose_patch`
Create a patch proposal with rationale, target files, and proposed changes.
Returns `blocked_pending_approval` + receipt ID. User must approve in Rig
before the patch is applied.

## Tier 4 — Mutation

Requires explicit authorization receipt.

### `rig.request_user_approval`
Request user approval for a gated action. Returns an authorization receipt
that can be passed to Tier 3+ tools.

## Tier 5 — Git / Release

Denied by default. Requires promotion flow.

### `rig.promote_to_preproduction`
Promote approved patches to the preproduction branch. Requires authorization
receipt AND explicit user confirmation.

## Usage with Antigravity

Configure Antigravity's MCP settings to connect to Rig:

```json
{
  "mcpServers": {
    "rig-relay": {
      "command": "uv",
      "args": ["run", "rig-relay", "mcp", "serve", "--stdio"]
    }
  }
}
```

Antigravity agents can then call Rig tools through standard MCP tool calls.
Every mutation-tier tool returns `approval_required: true` — Antigravity
should display this to the user as a confirmation gate.

## Usage with VS Code / Zed

Same stdio transport. The Rig MCP server speaks standard JSON-RPC 2.0 MCP
protocol. Any MCP-compatible host can connect.

```json
{
  "mcpServers": {
    "rig-relay": {
      "command": "uv",
      "args": ["run", "rig-relay", "mcp", "serve", "--stdio"]
    }
  }
}
```

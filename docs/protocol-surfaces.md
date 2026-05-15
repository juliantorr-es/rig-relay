# Protocol Surfaces

Rig Relay exposes four protocol surfaces for different integration patterns.
Each surface has a distinct role, transport, and authority model.

## ACP Agent — Editor ↔ Agent

Rig presents itself as a governed coding agent to editors and IDEs (Zed,
JetBrains, VS Code). ACP standardizes session management, progress streaming,
edit proposals, and permission gating.

| Concept | Rig Mapping |
|---|---|
| ACP Session | Rig mission / lane / worktree session |
| ACP Progress | Rig progress events (phase, status, percent) |
| ACP Edit | Rig patch proposal (never direct write) |
| ACP Permission | Rig approval gate / authorization receipt |
| ACP Terminal | Rig deterministic execution stream |

```
Editor/IDE  →  ACP Client  →  Rig ACP Agent
  send session requests
  receive plans, edits, progress
  request permissions
```

Entry point: `rig_relay.protocols.acp.RigACPAgent`

## MCP Client — Rig ↔ External Tools

Rig consumes external MCP servers for additional tools, databases, and
context sources. Rig acts as an MCP host, connecting to servers over
stdio or Streamable HTTP.

This surface is future work. The adapter layer is designed but not yet
wired to the tool manager.

## MCP Server — Host ↔ Rig Tools

Rig exposes governed tools, resources, and prompts to MCP hosts (Antigravity,
Claude Desktop, Cursor, Zed). Tools are tiered: read-only context first,
mutation gated behind authorization receipts.

```
Antigravity / Claude / Cursor / Zed
  →  MCP Client
    →  Rig MCP Server
      →  governed tool execution
      →  receipt-backed result
```

Entry point: `rig_relay.protocols.mcp.RigMCPServer`

Transport: stdio (local) or Streamable HTTP (remote).

### Tool Tiers

| Tier | Access | Examples |
|---|---|---|
| 0 — Read-only | Always available | `rig.current_mission`, `rig.summarize_dirty_state`, `rig.list_worktrees` |
| 1 — Analysis | Always available | `rig.build_context_packet`, `rig.create_consult_packet` |
| 2 — Validation | Always available | `rig.run_validator`, `rig.check_merge_friendly` |
| 3 — Patch proposal | Gated | `rig.propose_patch` — returns approval gate |
| 4 — Mutation | Requires auth receipt | `rig.request_user_approval` |
| 5 — Git/release | Denied by default | `rig.promote_to_preproduction` |

Every Tier 3+ tool returns `blocked_pending_approval` + `receipt_id` + `approval_required: true`.

## WebSocket — Cockpit ↔ Backend

Local projection stream for the desktop cockpit. Token-gated, localhost-only
(`127.0.0.1`), content-light. Clients authenticate with a session token, then
subscribe to projection pushes, request chat state, send messages, and
dispatch desktop intents.

```
Frontend (pywebview)  →  WebSocket  →  ProjectionWebSocketServer
  auth, subscribe, get_projection, send_chat_message, desktop_intent
  ←  projection, chat_state, progress_events, intent_results
```

Port: 9876 (default). Token auto-generated per session, delivered via
inline script injection in the HTML payload.

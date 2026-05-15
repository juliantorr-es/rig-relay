# MCP Context Tools

**Status:** Planning. MCP resource/tool exposure of `rig.get_context`.

## MCP Tool: `rig.get_context`

Exposed as an MCP tool with the same schema as the built-in tool.
Returns a structured JSON context packet.

```json
{
  "name": "rig.get_context",
  "description": "Get governed repository context. Read-only, receipt-backed.",
  "inputSchema": {
    "type": "object",
    "properties": {
      "mode": { "type": "string", "enum": ["map", "packet", "handoff", "collision", "symbols"] },
      "scope_paths": { "type": "array", "items": { "type": "string" } },
      "include_receipts": { "type": "boolean" },
      "include_other_agents": { "type": "boolean" },
      "max_tokens": { "type": "integer" }
    }
  }
}
```

## MCP Resources (future)

| Resource | Description |
|---|---|
| `rig://context/current` | Latest context packet for this session. |
| `rig://repo/map` | Fast repository topology. |
| `rig://work/active` | Active work lanes and collision state. |
| `rig://receipts/latest` | Most recent receipts. |
| `rig://symbols/index` | Symbol substitution table. |

## Policy

- All context MCP surfaces are read-only.
- `requires_workspace_trust: true` — semantic repo inspection requires trust.
- Receipts are emitted but not persisted on the MCP side (persistence is
  the callers's responsibility).

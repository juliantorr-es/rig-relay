# Rig IDE / Sidecar IPC Protocol (v1)

**Status:** Phase 0/1 bootstrap. Contract-hardening phase.

The IDE extension and the Rig Python sidecar communicate over the
extension host's **stdin/stdout** using newline-delimited JSON (JSONL).
Each line is a complete JSON object. The sidecar also runs the Rig ACP
agent on a separate async task within the same process.

## Transport

```
IDE Extension Host (TypeScript)         Rig Python Sidecar
     │                                        │
     │──── JSON object + \n ────────────────→ stdin
     │←─── JSON object + \n ───────────────── stdout
     │                                        │
     │                                        ├─ ACP Agent (asyncio task)
     │                                        └─ IPC handler (asyncio task)
```

- **stdin**: Extension → Sidecar (commands, snapshots, approvals)
- **stdout**: Sidecar → Extension (responses, receipts, approval requests, status)
- **stderr**: Sidecar → Extension (logs, diagnostics — not protocol)
- Line-buffered: `sys.stdout.reconfigure(line_buffering=True)`

## Message Catalog

### Extension → Sidecar

#### `workspace_snapshot`

Sent whenever the active editor changes or selection changes.

```json
{
  "type": "workspace_snapshot",
  "roots": ["/home/user/project"],
  "active_file": "/home/user/project/src/main.py",
  "open_tabs": ["/home/user/project/src/main.py", "/home/user/project/src/utils.py"],
  "selection": {
    "file": "/home/user/project/src/main.py",
    "startLine": 42,
    "startCol": 0,
    "endLine": 42,
    "endCol": 15
  },
  "visible_ranges": [
    { "file": "/home/user/project/src/main.py", "startLine": 30, "endLine": 60 }
  ],
  "editor_state": {
    "language": "python",
    "lineCount": 200,
    "eol": "LF",
    "isUntitled": false,
    "isDirty": false
  }
}
```

#### `capability_request`

Request execution of an IDE capability through the broker.

```json
{
  "type": "capability_request",
  "id": "req_abc123",
  "capability": "ide.diagnostics.file",
  "args": { "file": "/home/user/project/src/main.py" }
}
```

#### `approval_response`

User responded to an approval prompt.

```json
{
  "type": "approval_response",
  "id": "approval_def456",
  "approved": true
}
```

### Sidecar → Extension

#### `ack`

Sent after successful connection and workspace snapshot receipt. Includes the
capability manifest for the extension to reference.

```json
{
  "type": "ack",
  "status": "received",
  "capabilities": {
    "ide.workspace.describe": { "risk": "low", "mutates": false },
    ...
  }
}
```

#### `capability_response`

Result of a capability execution.

```json
{
  "type": "capability_response",
  "id": "req_abc123",
  "capability": "ide.diagnostics.file",
  "status": "ok",
  "result": { "diagnostics": [...] }
}
```

#### `approval_request`

Sidecar needs user approval before proceeding. The extension must show a
modal dialog and respond with `approval_response`.

```json
{
  "type": "approval_request",
  "id": "approval_def456",
  "title": "Allow ide.tests.run_file?",
  "description": "Run all tests in a file. Test execution can run arbitrary project code.",
  "capability": "ide.tests.run_file",
  "risk": "medium",
  "mutates": "possible"
}
```

#### `receipt`

Emitted for every capability execution. Content-light — no raw data.

```json
{
  "type": "receipt",
  "kind": "rig.ide.capability.receipt.v1",
  "capability": "ide.diagnostics.file",
  "input_sha256": "sha256:a1b2c3...",
  "output_sha256": "sha256:d4e5f6...",
  "agent_id": "agent.frontend-reviewer",
  "mission_id": "M123",
  "user_approved": true,
  "mutated_workspace": false
}
```

#### `status`

Connection status update.

```json
{
  "type": "status",
  "status": "ready",
  "message": "ACP agent running"
}
```

## Schema Validation

All messages MUST validate against the corresponding JSON Schema:

- `docs/schemas/rig.ide.sidecar.message.v1.schema.json`
- `docs/schemas/rig.ide.capability_receipt.v1.schema.json`
- `docs/schemas/rig.ide.capability_manifest.v1.schema.json`

The sidecar validates incoming messages. The extension SHOULD validate
outgoing messages before sending.

## Capability Manifest

The canonical capability registry lives at `etc/rig.ide.capability_manifest.v1.json`.
Both the Python sidecar and the TypeScript broker MUST generate their
permission tables from this file. Validation tests MUST fail if the
implemented permission tables drift from the manifest.

## Versioning

- Sidecar protocol: `rig.ide.v1` (header in sidecar-protocol.ts)
- Capability manifest: `rig.ide.capability_manifest.v1`
- Capability receipt: `rig.ide.capability.receipt.v1`

Breaking changes require incrementing the major version. Adding new
capabilities to the manifest is non-breaking. Adding new fields to
the sidecar message schema is non-breaking if `additionalProperties: false`
is not violated.

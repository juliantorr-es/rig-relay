# OpenCode Context Ledger Tools Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the built-in OpenCode file tools with native context-aware tools that keep a bounded JSONL history of file changes, make `read_file` the mechanical context digest surface, and preserve full provenance in git history.

**Architecture:** `read_file` becomes the single inspection surface for current file contents plus deterministic context synthesis. `write_file`, `search_replace`, and `edit` become mutation tools that automatically append rolling change events to an append-only JSONL ledger capped at the last 5 events per target. A small shared core module owns hashing, structural extraction, ledger rotation, and schema-safe artifact writing so the tools stay consistent and deterministic.

**Tech Stack:** OpenCode TS tools, `ast-grep` (`sg`), `rg`, `git`, `jq`, JSON Schema, and the repo-local `.opencode/tools/` and `docs/schemas/` layout.

---

### Task 1: Define the context artifact model and rolling ledger core

**Files:**
- Create: `/.opencode/tools/opencode_context_core.mjs`
- Create: `docs/schemas/opencode.file_context.v1.schema.json`
- Create: `docs/schemas/opencode.file_change_event.v1.schema.json`
- Test: `tests/opencode/test_context_artifacts.py`

- [ ] **Step 1: Write the schema examples first**

```json
{
  "schema_version": "opencode.file_context.v1",
  "artifact_id": "opencode-file-context-20260528T120000Z-acde1234",
  "created_at": "2026-05-28T12:00:00Z",
  "target_path": "src/example.ts",
  "kind": "file",
  "scope_root": "src/example.ts",
  "scope_hash": "sha256:0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
  "target_hash": "sha256:0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
  "language": "typescript",
  "symbols": [],
  "imports": [],
  "exports": [],
  "references_out": [],
  "references_in": [],
  "dependencies": [],
  "dependents": [],
  "entrypoints": [],
  "edit_surfaces": [],
  "recent_events": [],
  "unknowns": [],
  "confidence": 1,
  "content_light": true
}
```

- [ ] **Step 2: Run the schema test to verify it fails before implementation**

Run: `uv run pytest tests/opencode/test_context_artifacts.py -q`
Expected: FAIL because the new schemas and core module do not exist yet.

- [ ] **Step 3: Implement the shared core**

```javascript
export function contextRoot(repoRoot) { return join(repoRoot, "docs", "json", "opencode", "context") }
export function fileContextPath(repoRoot, artifactId) { return join(contextRoot(repoRoot), "files", `${artifactId}.json`) }
export function fileChangeLedgerPath(repoRoot, targetPath) { return join(contextRoot(repoRoot), "ledgers", `${stablePathId(targetPath)}.jsonl`) }
export function rotateLedger(entries) { return entries.slice(-5) }
```

- [ ] **Step 4: Run the schema test again and verify it passes**

Run: `uv run pytest tests/opencode/test_context_artifacts.py -q`
Expected: PASS for the schema fixtures once the core and schemas exist.

- [ ] **Step 5: Commit the core and schemas**

```bash
git add /.opencode/tools/opencode_context_core.mjs docs/schemas/opencode.file_context.v1.schema.json docs/schemas/opencode.file_change_event.v1.schema.json tests/opencode/test_context_artifacts.py
git commit -m "feat: add context ledger core"
```

### Task 2: Replace `read_file` with mechanical context digesting

**Files:**
- Create: `/.opencode/tools/read_file.ts`
- Modify: `/.opencode/tools/smart_read_file.ts` or retire it after the new surface is verified
- Modify: `/.opencode/tools/opencode_context_core.mjs`
- Test: `tests/opencode_read_file.test.mjs`

- [ ] **Step 1: Write a failing integration test for the new `read_file` behavior**

```javascript
const result = await readFile({
  path: "src/example.ts",
  include_history: true,
  include_structure: true,
})
assert.equal(result.artifact.kind, "file")
assert.equal(result.artifact.target_path, "src/example.ts")
assert.equal(result.artifact.recent_events.length, 5)
```

- [ ] **Step 2: Run the test and confirm it fails before the tool exists**

Run: `node --test tests/opencode_read_file.test.mjs`
Expected: FAIL because the custom `read_file` tool is not wired yet.

- [ ] **Step 3: Implement `read_file` as the canonical inspection tool**

```javascript
// Read file contents, extract symbols with ast-grep, collect refs with rg,
// merge the last 5 ledger events, and return a deterministic JSON artifact.
```

- [ ] **Step 4: Run the test and confirm it passes**

Run: `node --test tests/opencode_read_file.test.mjs`
Expected: PASS.

- [ ] **Step 5: Commit the new read surface**

```bash
git add /.opencode/tools/read_file.ts /.opencode/tools/opencode_context_core.mjs tests/opencode_read_file.test.mjs
git commit -m "feat: replace read_file with context digest"
```

### Task 3: Replace `write_file`, `search_replace`, and `edit` with context-seeding mutation tools

**Files:**
- Create: `/.opencode/tools/write_file.ts`
- Create: `/.opencode/tools/search_replace.ts`
- Create: `/.opencode/tools/edit.ts`
- Modify: `/.opencode/tools/opencode_context_core.mjs`
- Test: `tests/opencode_write_tools.test.mjs`

- [ ] **Step 1: Write a failing test that proves each mutation appends a rolling event**

```javascript
assert.equal(eventsAfterWrite.length, 1)
assert.equal(eventsAfterSearchReplace.length, 2)
assert.equal(eventsAfterEdit.length, 3)
assert.equal(ledgerAfterSixthMutation.length, 5)
```

- [ ] **Step 2: Run the test and confirm the mutation tools are missing**

Run: `node --test tests/opencode_write_tools.test.mjs`
Expected: FAIL.

- [ ] **Step 3: Implement each mutation tool so it writes the file and appends a JSONL event**

```javascript
// Each tool computes before/after hashes, records the operation kind,
// stores the structural summary, and rotates the ledger to the most recent 5 events.
```

- [ ] **Step 4: Run the mutation test and verify ledger rotation works**

Run: `node --test tests/opencode_write_tools.test.mjs`
Expected: PASS.

- [ ] **Step 5: Commit the mutation tools**

```bash
git add /.opencode/tools/write_file.ts /.opencode/tools/search_replace.ts /.opencode/tools/edit.ts /.opencode/tools/opencode_context_core.mjs tests/opencode_write_tools.test.mjs
git commit -m "feat: add context-aware mutation tools"
```

### Task 4: Disable the built-in file tools and rebind the familiar names to the custom tools

**Files:**
- Modify: `opencode.json`
- Modify: `/.opencode/opencode.json`
- Modify: `/.opencode/agents/execution.md`
- Modify: `/Users/user/.config/opencode/agents/execution.md`
- Modify: `/.opencode/agents/orchestrator.md` if the agent-facing wording needs a tool inventory refresh
- Modify: `/Users/user/.config/opencode/agents/orchestrator.md`

- [ ] **Step 1: Write a config test that asserts the old built-ins are no longer available and the replacement names are present**

```python
assert "read_file" in config
assert "write_file" in config
assert "search_replace" in config
assert "edit" in config
assert "builtin read_file" not in config
```

- [ ] **Step 2: Run the config test and confirm it fails before the permissions change**

Run: `uv run pytest tests/integrations/test_prompt_parity.py -q`
Expected: FAIL until the replacement tool names are wired and the built-ins are disabled.

- [ ] **Step 3: Update the OpenCode configuration so the custom tools are the only file-edit surface**

```json
{
  "tools": {
    "read_file": "custom",
    "write_file": "custom",
    "search_replace": "custom",
    "edit": "custom"
  }
}
```

- [ ] **Step 4: Re-run the config test and confirm the surface is now the custom one**

Run: `uv run pytest tests/integrations/test_prompt_parity.py -q`
Expected: PASS.

- [ ] **Step 5: Commit the policy binding**

```bash
git add opencode.json /.opencode/opencode.json /.opencode/agents/execution.md /.opencode/agents/orchestrator.md /Users/user/.config/opencode/agents/execution.md /Users/user/.config/opencode/agents/orchestrator.md
git commit -m "feat: bind file tools to context-aware implementations"
```

### Task 5: Validate the whole surface end to end and verify the bounded history behavior

**Files:**
- Test: `tests/opencode_context_tools.test.mjs`
- Test: `tests/opencode/test_context_artifacts.py`
- Test: `tests/integrations/test_prompt_parity.py`

- [ ] **Step 1: Add an end-to-end test that reads, mutates, and rereads the same file**

```javascript
const first = await readFile({ path: "src/example.ts" })
await writeFile({ path: "src/example.ts", content: "..." })
const second = await readFile({ path: "src/example.ts" })
assert.equal(second.artifact.recent_events.length <= 5, true)
```

- [ ] **Step 2: Run the end-to-end test and confirm the ring buffer stays bounded**

Run: `node --test tests/opencode_context_tools.test.mjs`
Expected: PASS.

- [ ] **Step 3: Run the schema and parity suite together**

Run: `uv run pytest tests/opencode/test_context_artifacts.py tests/integrations/test_prompt_parity.py -q`
Expected: PASS.

- [ ] **Step 4: Commit the verification updates**

```bash
git add tests/opencode_context_tools.test.mjs tests/opencode/test_context_artifacts.py tests/integrations/test_prompt_parity.py
git commit -m "test: cover context-aware file tool surface"
```

## Self-Review

This plan covers the new context-aware file tool surface, the rolling five-event history, the replacement of the built-in names, and the test coverage needed to keep the behavior deterministic. The only deliberate scope cut is full service-wide propagation analysis, which should come after the file-level and module-level tools are stable and proven.

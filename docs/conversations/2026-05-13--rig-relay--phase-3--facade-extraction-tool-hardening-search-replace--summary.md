# Rig Relay — Phase 3: Facade Extraction & Tool Hardening (search_replace)

## 1. User's Primary Goals and Intent

Leading a multi-phase migration and hardening of **Rig Relay** — a Python 3.12+ CLI coding-agent harness derived from Mistral Vibe CLI. Primary objectives:

1. **Product-surface purification**: Strip "Vibe" branding from the product surface; establish `rig-relay` as the primary identity.
2. **Namespace ownership migration**: Move from `vibe.*` to `rig_relay.*` through a controlled Strangler Fig pattern (Phases 1–5).
3. **Tool hardening**: Implement deterministic, schema-validated, content-light envelopes for high-friction tools, starting with `bash` then `search_replace`.
4. **Governance over ceremony**: Prefer audit documents, schema validation, content-light receipts, and structured refusal over ad-hoc guards.
5. **No destructive Git operations**: Checkpoints via tool only, no force-push, no amend, no rebase, no merge.
6. **No broad formatters**: Only format specific changed files.
7. **No unsolicited refactoring**: Each mission targets exactly one boundary.

Priorities (user-stated):
- bash deterministic envelope first (highest-pressure tool surface: 5,023 calls, 337 failures, ~6.71% failure rate)
- search_replace next (2,057 calls, 217 failures, ~10.55% failure rate — highest failure rate, mutation accountability)
- Then `rig_relay.runtime` facade around session lifecycle
- Vibe-legacy warning wording and cockpit packaging are "product polish" — defer.

## 2. Conversation Timeline and Progress

### Session 1: Vibe CLI Purge Inventory Audit
- **Request**: Review and classify all user-facing Vibe CLI/Textual product surfaces for the Rig Relay migration.
- **Outcome**: Created `docs/audits/vibe-cli-purge-inventory.md` classifying commands as `retired`, `compatibility`, `deprecated`, or `internal`.
- **Key finding**: `rig-relay` and `rig-relay-acp` still pointed to `vibe.cli.entrypoint:main` — branding-only shells.

### Session 2: Relay Entry Point Authority Audit
- **Request**: Audit the CLI/product entry point boundary to determine exactly which commands are Relay-owned vs legacy compatibility aliases.
- **Outcome**: Created `docs/audits/relay-entry-point-authority.md` (332 lines). Found zero Relay-owned entry point code. All `[project.scripts]` entries delegate to `vibe.*`.
- **Key finding**: `rig_relay.*` namespace is structurally present but not authoritative at the CLI boundary.
- **Governance note**: Previous mission checkpointed to `main` (HEAD ahead 2 of origin/main). Technically permitted by AGENTS.md but creates release-surface ambiguity.
- **Recommendation**: Next slice = Extract Relay Runtime Facade.

### Session 3: Extract Relay Runtime Facade
- **Request**: Create Relay-owned CLI entrypoint modules for `rig-relay` and `rig-relay-acp` as thin facades delegating to `vibe.*`.
- **Files created**:
  - `rig_relay/cli/entrypoint.py` — delegates to `vibe.cli.entrypoint.main`
  - `rig_relay/cli/acp_entrypoint.py` — delegates to `vibe.acp.entrypoint.main`
  - `tests/cli/test_relay_entrypoint_facade.py` — 19 tests
- **Files modified**:
  - `pyproject.toml` — changed targets + added `rig_relay/` to wheel include
  - `docs/install.md` — updated entry point table
  - `docs/audits/vibe-cli-purge-inventory.md` — updated table
  - `docs/audits/relay-entry-point-authority.md` — appended "Facade Implemented" section
- **Key changes**: `rig-relay` → `rig_relay.cli.entrypoint:main`, `rig-relay-acp` → `rig_relay.cli.acp_entrypoint:main`
- **Cockpit command**: Deferred (not registered in `pyproject.toml`; `scripts/` not a Python package).
- **Tests**: 19/19 passed, 58 total across all test files.

### Session 4: Bash Deterministic Envelope Verification
- **Request**: Implement bash deterministic envelope (subprocess execution containment).
- **Finding**: The bash envelope was already fully implemented from prior uncommitted work.
- **Already present**: `BashResult` with status/duration_ms/truncation_flags/error_kind, `BashReceipt` with SHA256 hashes, `build_receipt()`, structured timeout result, per-stream byte caps, explicit cwd, 3 JSON schemas, 23 hardening tests in `tests/tools/test_bash_hardening.py`.
- **Action**: Updated `docs/audits/tool-usage-analysis/tool-hardening-priority.md` to mark bash as ✅ COMPLETED.
- **Validation**: 58/58 tests passed, 71/71 schemas validated.

### Session 5: Deterministic Envelope for search_replace (IN PROGRESS)
- **Request**: Harden search_replace with mutation accountability envelope.
- **Current state**: Implementation changes complete, tests not yet written, existing tests broken (9 failures — `Can't instantiate abstract class SearchReplace without an implementation for abstract method 'run'`).
- **Last action**: Identified that `_classify_status_from_error_kind` was placed at module level between class methods, causing the class to be malformed.

## 3. Technical Context and Decisions

### Architecture
- **Package layout**: `vibe/` (legacy Vibe CLI substrate), `rig_relay/` (Relay-native product spine)
- **Entry points** (after Session 3):
  - `rig-relay` → `rig_relay.cli.entrypoint:main` → `vibe.cli.entrypoint.main` (facade)
  - `rig-relay-acp` → `rig_relay.cli.acp_entrypoint:main` → `vibe.acp.entrypoint.main` (facade)
  - `vibe`/`vibe-acp`/`vibe-legacy`/`vibe-acp-legacy` → `vibe.*` directly (unchanged)
- **Strangler Fig phases**: Phase 3 (Legacy quarantine) active. `vibe/legacy/` namespace established.
- **Tool framework**: `BaseTool[Args, Result, Config, State]` with Pydantic models, async generators for `run()`.

### Patterns Established
1. **Deterministic envelope pattern** (applied to bash, being applied to search_replace):
   - Structured invocation model (Pydantic `Args`)
   - Structured result model with status/duration/error_kind
   - Content-light receipt model (SHA256 hashes, no raw content)
   - `build_receipt(result)` method on tool class
   - JSON schemas under `docs/schemas/`
   - Hardening tests in `tests/tools/`
2. **Content-light receipts**: No raw stdout, stderr, file contents, old/new text, diffs, or secrets. Only metadata: hashes, byte counts, exit codes, status, error classification.
3. **Result statuses** (search_replace): `success`, `no_match`, `ambiguous_match`, `count_mismatch`, `mismatch` (legacy), `refused`, `internal_error`
4. **Error kinds** (search_replace): `old_text_not_found`, `unchanged_replacement`, `multiple_matches_when_single_required`, `replacement_count_mismatch`, `encoding_error`, `expected_hash_mismatch`, `protected_file`, `path_refused`, `binary_file`

### Schema Files (74 total after Session 5 additions)
- `docs/schemas/rig.relay.search_replace_invocation.v1.schema.json`
- `docs/schemas/rig.relay.search_replace_result.v1.schema.json`
- `docs/schemas/rig.relay.search_replace_receipt.v1.schema.json`
- Plus existing bash schemas (invocation, result, receipt) and other schemas.

### Key Files Referenced
- `vibe/core/tools/builtins/bash.py` (envelope-hardened)
- `vibe/core/tools/builtins/search_replace.py` (being hardened now)
- `vibe/cli/entrypoint.py` (legacy CLI entry point, unchanged)
- `vibe/acp/entrypoint.py` (legacy ACP entry point, unchanged)
- `rig_relay/cli/entrypoint.py` (Relay facade)
- `rig_relay/cli/acp_entrypoint.py` (Relay facade)

## 4. Files and Code Changes

### Files Created (Session 3 only)

**`rig_relay/cli/entrypoint.py`**:
```python
"""rig_relay.cli.entrypoint — Relay-owned CLI entry point."""
from __future__ import annotations
from vibe.cli.entrypoint import main
__all__ = ["main"]
```

**`rig_relay/cli/acp_entrypoint.py`**:
```python
"""rig_relay.cli.acp_entrypoint — Relay-owned ACP entry point."""
from __future__ import annotations
from vibe.acp.entrypoint import main
__all__ = ["main"]
```

**`tests/cli/test_relay_entrypoint_facade.py`**: 19 tests covering pyproject.toml mappings, module imports, help command warnings.

**`docs/schemas/rig.relay.search_replace_invocation.v1.schema.json`**: Defines `file_path` (required), `expected_before_sha256`, `expected_replacements`, `allow_multiple`.

**`docs/schemas/rig.relay.search_replace_result.v1.schema.json`**:
```json
{
  "properties": {
    "status": {"enum": ["success", "no_match", "ambiguous_match", "count_mismatch", "mismatch", "refused", "internal_error"]},
    "error_kind": {"enum": ["old_text_not_found", "unchanged_replacement", "multiple_matches_when_single_required", "replacement_count_mismatch", "encoding_error", "expected_hash_mismatch", "protected_file", "path_refused", "binary_file", null]}
  },
  "required": ["file", "status"]
}
```

**`docs/schemas/rig.relay.search_replace_receipt.v1.schema.json`**: Content-light, same status/error_kind enums.

### Files Modified (Session 5 only)

**`vibe/core/tools/builtins/search_replace.py`** — Key changes:
1. Added `expected_replacements: int | None = None` and `allow_multiple: bool = True` to `SearchReplaceArgs`
2. Added `replacements: int = 0`, `before_bytes: int = 0`, `after_bytes: int = 0` to `SearchReplaceResult`
3. Added `replacements: int = 0`, `before_bytes: int = 0`, `after_bytes: int = 0` to `SearchReplaceReceipt`
4. Added `_is_binary_content()` function — checks null bytes in first 8KB
5. Added binary file check in `_prepare_and_validate_args` — raises `ToolError` for binary files
6. Updated `_apply_blocks()` to accept `allow_multiple` and `expected_replacements` params:
   - If `allow_multiple=False` and >1 match → error with `ambiguous_match`
   - If `expected_replacements` set and actual != expected → error with `count_mismatch`
7. Updated `_apply_search_replace()` to pass through new params and use `_classify_status_from_error_kind`
8. Added `_classify_status_from_error_kind()` module-level function mapping `error_kind` → status
9. Updated `_build_search_replace_result()` to populate `replacements`, `before_bytes`, `after_bytes`
10. Updated `run()` to pass `allow_multiple`/`expected_replacements` to `_apply_search_replace`
11. Updated `build_receipt()` to include new fields
12. Added `binary_file` to `_classify_refusal()`

**`docs/audits/tool-usage-analysis/tool-hardening-priority.md`**: Marked bash as ✅ COMPLETED (Session 4).

## 5. Active Work and Last Actions

### Last Completed Action
- All search_replace implementation changes to `vibe/core/tools/builtins/search_replace.py` are complete
- 3 new JSON schemas created and validated (74/74 passed)
- Schema validation passes for all schemas

### Current Bug
All 9 search_replace tests in `tests/tools/test_hardened_tools.py` fail with:
```
TypeError: Can't instantiate abstract class SearchReplace without an implementation for abstract method 'run'
```

### Root Cause Analysis
The `_classify_status_from_error_kind()` module-level function was placed between `_apply_search_replace()` (a class method) and `build_receipt()` (a class method). The issue is likely indentation-related — the module-level function may be accidentally indented inside the class body, or the preceding method may not be properly closed.

### Last Bash Command Run
```bash
uv run pytest -n0 tests/tools/test_hardened_tools.py tests/tools/test_bash.py tests/tools/test_bash_hardening.py -v --timeout=30
```
Results: 70 passed (bash + non-search_replace tests), 9 failed (all search_replace tests).

### What Remains for This Session's Work
1. **Fix the `SearchReplace` class instantiation bug** — the `_classify_status_from_error_kind` function placement is breaking the class definition.
2. **Add hardening tests** for search_replace.
3. **Update `docs/audits/tool-usage-analysis/tool-hardening-priority.md`**.
4. **Create or update tool-hardening audit document** for search_replace.

### Required Test Coverage (not yet written)
1. Successful single replacement returns structured success
2. before_sha256 and after_sha256 differ after mutation
3. Replacement count is exact
4. No match returns structured `no_match`
5. Multiple matches with `allow_multiple=False` returns `ambiguous_match`
6. Expected replacement count mismatch does not mutate the file
7. Receipt omits raw old/new content and file contents
8. Binary file refusal
9. Path/cwd behavior remains deterministic
10. Existing search_replace tests continue passing

## 6. Unresolved Issues and Pending Tasks

### Critical (Blocking)
1. **search_replace class instantiation bug**: `SearchReplace` can't be instantiated because `_classify_status_from_error_kind` placement broke the class definition. Likely indentation issue — the module-level function might be indented inside the class, or the preceding `_apply_search_replace` method has wrong indentation on its closing.

### Unresolved Issues (from prior sessions)
2. **Vibe-legacy warning mislabeling**: `vibe-legacy --help` says "`vibe`" instead of "`vibe-legacy`". Known cosmetic issue, deferred.
3. **ACP import-time side effect**: `vibe/acp/entrypoint.py` calls `sys.stdin.reconfigure()` at import time, breaking pytest. Workaround via AST parsing in tests. Documented as later cleanup.
4. **Cockpit command not registered**: `rig-relay-cockpit` advertised in AGENTS.md but not in `pyproject.toml`. Deferred.
5. **Bash remaining gaps**: No-shell/argv mode, explicit env filtering, receipt not wired into telemetry.
6. **Checkpoint-to-main governance**: Previous missions checkpointed to `main` (ahead 2 of origin/main). Documented as governance exception but not fixed.

### Pending Decisions
- None currently awaiting user input.

## 7. Immediate Next Step

**Fix the `SearchReplace` class instantiation bug.**

1. Read lines 415–450 of `vibe/core/tools/builtins/search_replace.py` to examine indentation of `_classify_status_from_error_kind` and surrounding class methods.
2. The function should be at module level (no indentation). If indented, de-indent it. If the preceding method has wrong indentation on its closing, fix that.
3. After fixing, run the failing tests:
   ```bash
   uv run pytest -n0 tests/tools/test_hardened_tools.py::test_search_replace_successful_records_hashes tests/tools/test_hardened_tools.py::test_search_replace_does_not_write_when_block_fails -x --timeout=30
   ```
4. Once passing, continue writing the hardening tests and update the priority document.

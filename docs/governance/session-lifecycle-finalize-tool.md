# Session Lifecycle Finalize Tool

**File:** `docs/governance/session-lifecycle-finalize-tool.md`

## Status

**Design.** Governed agent-callable tool for end-of-session lifecycle finalization. Wraps the existing `finalize_session_storage()` function in a Pydantic-contract tool.

## Tool Name

`session_lifecycle_finalize`

## Data Flow

```
SessionLifecycleFinalizeRequest
       │
       ▼
  SessionLifecycleFinalizeTool.run()
       │
       ├── 1. Validate request (Pydantic)
       ├── 2. Check dry_run flag → skip mutations
       ├── 3. Call finalize_session_storage()
       │       ├── audit → classify → protect → compact → prune
       │       └── write manifest + receipt
       └── 4. Return SessionLifecycleFinalizeResult
```

## Input Envelope

`SessionLifecycleFinalizeRequest` (Pydantic model)

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `session_id` | string | required | Session identifier |
| `sessions_root` | string\|null | `~/.rig/sessions/{session_id}` | Root path for session storage |
| `older_than_days` | int | 30 | Age threshold for prune candidates |
| `allow_compaction` | bool | `false` | Enable JSONL gzip rollup |
| `allow_prune` | bool | `false` | Enable age-based file removal |
| `write_receipt` | bool | `true` | Write lifecycle receipt to session root |
| `reason` | string | `"session_end"` | Label for the finalization event |
| `dry_run` | bool | `true` | Audit-only mode; no files modified |

## Output Receipt

`SessionLifecycleFinalizeResult` (Pydantic model)

| Field | Type | Description |
|-------|------|-------------|
| `status` | string | `ok`, `partial`, or `refused` |
| `session_id` | string | Session identifier |
| `scanned_files` | int | Number of files inspected |
| `total_bytes_before` | int | Total bytes scanned |
| `total_bytes_after` | int | Total bytes after compaction |
| `compacted_count` | int | Files compacted |
| `refused_count` | int | Files refused (protected or error) |
| `prune_candidate_count` | int | Candidates eligible for pruning |
| `deleted_count` | int | Files deleted (only when `allow_prune=true` and `dry_run=false`) |
| `compacted_details` | list[dict] | Per-file compaction results (source, output, size before/after) |
| `protected_details` | list[dict] | Protected files skipped |
| `refused_details` | list[dict] | Refused files with reasons |
| `manifest_path` | string\|null | Path to written manifest |
| `receipt_path` | string\|null | Path to written receipt |
| `warnings` | list[str] | Non-fatal warnings |

## Dry-Run / Safe Default Behavior

- `dry_run` defaults to `true`
- `allow_compaction` defaults to `false`
- `allow_prune` defaults to `false`
- When `dry_run=true`:
  - Audit runs (classify, scan)
  - No files are compacted, pruned, or deleted
  - Manifest and receipt are **not** written
  - Result contains full candidate lists but zero mutations
- When `dry_run=false` and `allow_compaction=true`:
  - JSONL/progress/intent/validation files are gzip-rolled into `lifecycle/rollups/`
  - Protected files are never touched
- When `dry_run=false` and `allow_prune=true`:
  - Age-based prune candidates are marked for deletion
  - Protected classes are never deleted
  - Active/pinned session markers block deletion

## Refusal Cases

| Condition | Behavior |
|-----------|----------|
| Session directory does not exist | `status: refused`, no files scanned |
| Active session marker present | Files in `active/` or `pinned/` are refused |
| Protected file (receipt, consent, upload, signed envelope) | Classified protected, never compacted/pruned |
| Compaction I/O error | File recorded as refused, warning added |
| `dry_run=true` with `allow_prune=true` | Prune candidates listed but not deleted |
| `dry_run=true` with `allow_compaction=true` | Compaction candidates listed but not rolled up |

## Retention Policy

The tool uses `SessionRetentionPolicy` from `session_lifecycle.py`:

| Parameter | Default | Description |
|-----------|---------|-------------|
| `older_than_days` | 30 | Prune candidates older than this threshold |
| `preserve_receipts` | True | Never delete receipt files |
| `preserve_consent` | True | Never delete consent files |
| `preserve_upload_receipts` | True | Never delete upload receipt files |
| `preserve_signed_envelopes` | True | Never delete signed envelope files |
| `archive_dir` | None | Optional archive directory for pruned files |

## Protected Paths

The following file classes are never compacted or pruned:

- Receipts (`receipt`, `receipts` in filename)
- Consent (`consent` in filename)
- Upload receipts (`upload` + `receipt`)
- Signed envelopes (`signed`, `envelope` in filename)
- Active session markers (`active` in path or filename)
- Pinned session markers (`pinned` in path or filename)

## Content-Light Guarantees

The result model contains:

- **Allowed:** counts, paths, hashes (`line_sha256`), byte totals, statuses, retention decisions, schema versions
- **Forbidden:** raw prompts, raw model outputs, stdout/stderr bodies, secrets, source diffs, file content

Compact rollups use gzip with content-light line hashes (SHA256 of each line, no raw content).

## Cross-References

- [Session Storage Lifecycle](session-storage-lifecycle.md)
- [Storage Retention Policy](storage-retention-policy.md)
- [Usage Data Doctrine](usage-data-doctrine.md)
- `rig_relay/evidence/session_lifecycle.py` — core lifecycle functions
- `rig_relay/evidence/session_lifecycle_tool.py` — Pydantic models + tool class
- `tests/evidence/test_session_lifecycle_tool.py` — tool tests

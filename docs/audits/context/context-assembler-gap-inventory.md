# Context Assembler — Gap Inventory

Inspection date: 2026-05-15. HEAD: c5a31bbe.

## Files inspected

| File | Lines | Role |
|---|---|---|
| `compiler.py` | 340 | `ContextCompiler.build_envelope()`, `execute()`, `build_receipt()`, helpers |
| `models.py` | 207 | `ContextRequest`, `ContextPacket`, `ContextEnvelopeReceipt`, `ContextReceipt`, `SubsystemEntry`, `ActiveLane`, `CollisionWarning`, `SymbolEntry`, `ReceiptEntry`, `PathRecommendation`, `ContextScope`, `ContextBudget`, `ContextFreshness`, `ContextOutput`, `CompressionMode`, `DetailLevel`, `OutputFormat` |
| `repo_map.py` | 150 | `build_repo_info()`, `build_subsystem_map()`, `git_ls_files()`, `git_status_short()` |
| `work_map.py` | 120 | `build_active_work()`, `scan_worktrees()`, `compute_collision_warnings()` |
| `repo_index.py` | 300 | `RepoContextIndex` with DuckDB-backed relation discovery |
| `symbol_codec.py` | 200 | `SymbolCodec` class, `estimate_tokens()`, reversible compression |
| `token_estimator.py` | 30 | `estimate_tokens(text, model_hint)` — simple char/4 heuristic |
| `correlation.py` | 50 | `correlate_tool_call_with_context()` — pure function, no side effects |
| `observation.py` | 40 | `ContextObservation` model — `observation_only=true` |
| `assembler.py` | ? | Placeholder/empty |

## Gap inventory

### 1. Request fields ignored by compiler

| Field | Model | Compiler usage | Gap |
|---|---|---|---|
| `budget.max_tokens` | `ContextBudget` | Not read | Budget never enforced; `estimated_tokens` computed after build |
| `budget.compression` | `CompressionMode` | Not read | Symbol codec exists but never applied to output |
| `budget.detail` | `DetailLevel` | Not read | Always builds full detail regardless of request |
| `freshness.require_git_status` | `ContextFreshness` | Not read | Always runs git status |
| `freshness.require_worktree_scan` | `ContextFreshness` | Not read | Always scans worktrees |
| `freshness.require_receipt_scan` | `ContextFreshness` | Not read | Only gated by `scope.include_receipts` |
| `scope.paths` | `ContextScope` | Partially read | Passed to `build_active_work()` for collision paths, but not used for targeted file selection |
| `scope.symbols` | `ContextScope` | Not read | Symbol aliases/expansion never used |
| `scope.include_tests` | `ContextScope` | Not read | Always returns all subsystems; no test filtering |
| `scope.include_docs` | `ContextScope` | Not read | Always returns all subsystems; no doc filtering |
| `scope.include_other_agents` | `ContextScope` | Not read | No agent-lane filtering |
| `output.format` | `ContextOutput` | Not read | Always returns JSON packet; no markdown or context_packet format |

### 2. Relevance scoring missing

| Gap | Detail |
|---|---|
| `user_text` not analyzed | `build_envelope()` accepts `user_text: str = ""` but only uses it in docstring. No task-specific relevance ranking. |
| No candidate scoring | `_build_recommended_context()` just picks first config/doc per subsystem — no priority based on task, budget, or freshness. |
| No omission tracking | Omitted candidates are silently dropped. No `ContextOmission` list. |
| No relation expansion | `RepoContextIndex` exists but `execute()` does not call it to expand tests/docs/schemas for requested paths. |

### 3. Budget enforcement absent

| Gap | Detail |
|---|---|
| No selection under budget | `_estimate_tokens()` runs AFTER building the full packet. Budget is never checked before inclusion. |
| No incremental token tracking | Each section has no token estimate before rendering. |
| No omission recording | When sections exceed budget, no record of what was dropped. |

### 4. Compression unused

| Gap | Detail |
|---|---|
| Symbol codec not applied | `CompressionMode.SYMBOL_SUBSTITUTION` exists in model but `compiler.py` never imports or uses the codec. |
| No savings check | Codec has `estimate_tokens()`. No caller checks net savings before applying. |
| No substitution table in packet | `packet.substitution_table_sha256` always `None`. |

### 5. Privacy risks

| Risk | Detail |
|---|---|
| Raw messages in envelope | `build_envelope()` appends "## Recent Messages" with truncated content. Still includes first 120 chars of user/assistant messages. |
| Raw paths in receipts | `_scan_receipts()` includes full file paths in `ReceiptEntry.path`. |
| No trust labels | All context is treated equally — no provenance or trust tier. |
| No prompt injection boundary | Files and receipts are rendered into the system prompt without marking them as quoted evidence. |

### 6. Hash determinism

| Gap | Detail |
|---|---|
| `generated_at` in packet | `ContextPacket.generated_at = datetime.now(UTC).isoformat()` — makes every packet hash different even on identical input. |
| `context_id` is random | `uuid4().hex[:12]` — non-deterministic. |
| `request_sha256` includes timestamps | Request model has no timestamps, so this is OK for now. |

### 7. Failure silence

| Gap | Detail |
|---|---|
| Broad `except Exception: pass` | `build_envelope()` wraps everything in `try/except: pass`. Suppresses all structural failures. |
| No structured warnings | `ContextEnvelopeReceipt` has no warnings field. |
| `_scan_receipts()` suppresses I/O errors | Individual file read failures are caught silently. |

### 8. Cache layout

| Gap | Detail |
|---|---|
| Monolithic rendering | All sections concatenated with `"\n\n".join(sections)`. No stable/dynamic separation. |
| No cache tier hints | No section ordering for prompt caching. |
| No prefix-cache-aware structure | Static sections (repo info, AGENTS.md) not separated from dynamic (dirty files, active lanes). |

### 9. Schema drift

| Gap | Detail |
|---|---|
| `packet.symbol_map` always empty | Schema expects `{"aliases": {}, "symbols": []}` but compiler never populates it. |
| `packet.optimized_packet_sha256` always equals canonical | No actual optimization/compression applied. |
| `ContextRequest` promises more than `execute()` delivers | 12 fields with behavior gating are ignored. |

### 10. RepoIndex integration absent

| Gap | Detail |
|---|---|
| `RepoContextIndex` exists but unused | `ContextCompiler.__init__` has `repo_index` parameter, but `execute()` never constructs or uses it. |
| No test/doc/schema relation expansion | Index can find related files but compiler never asks. |
| No same-package expansion | Subsystem map is flat; index could provide package-level relations. |

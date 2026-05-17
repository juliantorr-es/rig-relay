# API Boundary, Strict Concurrency, and Worker Readiness Audit v0

**Generated**: 2026-05-17
**Schema**: `rig.relay.audit.v1`
**Status**: Complete
**Subagents**: 6 concurrent (A–F), coordinator synthesis
**Repo state**: `main` @ `9717e21`, clean working tree, 7271 tests collected

---

## 1. Executive Verdict

**MOSTLY READY WITH DEFINED MUTATION GAPS**

The digestion pipeline pattern has been proven for `reserve_paths` (cross-process `fcntl.flock`, 0% double-win under stress). But only one of eight coordination mutation methods is guarded. The remaining seven have TOCTOU races. The API boundary has a mature WebSocket protocol as foundation. Worker classification reveals critical event-loop blockers from synchronous git/file-tree calls. DuckDB is safely constrained to read-side analytics. Global state has manageable hazards (4 singleton patterns, 73 Path.cwd() defaults).

**Blockers before subprocess fan-out**:
1. `claim_task`, `release_paths`, `release_task`, `mark_lease_stale` all lack digester guard
2. Stale leases block reservations forever (no expiry cleanup in `_iter_reservations`)
3. `events.jsonl` sequence numbers race under concurrent writers
4. Git subprocess calls block the async event loop in the context compiler hot path
5. No serialization boundary for subagent subprocesses (all communication is direct Python import)

**Not a blocker**: DuckDB is clean. Redaction is wired. Consent expiry is enforced. Trace scanner detects all known prefixes. Release gate CLI passes. Guard escape hatches pass.

---

## 2. Current Architecture Map

```
                        ┌─────────────────────────┐
                        │   Desktop Cockpit (UI)   │
                        │   WebSocket protocol     │ ← mature, typed messages
                        └───────────┬─────────────┘
                                    │ JSON intents (read-only)
                        ┌───────────▼─────────────┐
                        │   Agent Loop (core)      │
                        │   ┌───────────────────┐  │
                        │   │ Context Compiler   │  │ ← git subprocess (blocks loop)
                        │   │ Repo Index         │  │ ← DuckDB in-memory
                        │   │ LLM Calls          │  │ ← async (network)
                        │   │ Tool Execution     │  │ ← async tasks + supervisor
                        │   │ Telemetry Client   │  │ ← async fire-and-forget
                        │   └───────────────────┘  │
                        └───┬─────────┬───────────┘
                            │         │
              ┌─────────────▼──┐  ┌──▼──────────────────┐
              │ Coordination   │  │ Evidence/Telemetry   │
              │ Store          │  │                      │
              │ ┌────────────┐ │  │ observability.jsonl   │
              │ │ reserve    │◄├──┤ redact_for_remote()  │ ← wired
              │ │  _paths    │ │  │ consent expiry check │ ← enforced
              │ │ (DIGESTED) │ │  │ reports.jsonl        │
              │ └────────────┘ │  │ trace_events.jsonl    │
              │ ┌────────────┐ │  └──────────────────────┘
              │ │ claim_task │ │  ← TOCTOU (unlocked)
              │ │ heartbeat  │ │  ← TOCTOU (unlocked)
              │ │ release_*  │ │  ← TOCTOU (unlocked)
              │ │ mark_stale │ │  ← TOCTOU (unlocked)
              │ └────────────┘ │
              └───────┬────────┘
                      │
          ┌───────────▼───────────┐
          │  Canonical Artifacts  │
          │  .build/coordination/ │
          │  .rig/reports/        │
          │  .rig/analytics/      │
          │  ~/.rig/relay/       │
          └──────────────────────┘
```

**Legend**: ✅ Digester-guarded · ❌ TOCTOU race · ⚠️ Read-side only

---

## 3. Mutation Surface Inventory (condensed from Subagent A)

### CoordinationStore — 9 mutation methods, 1 guarded

| Method | TOCTOU? | Digester-guarded? | Verdict |
|---|---|---|---|
| `reserve_paths` | No (locked) | **Yes** (`fcntl.flock` + `threading.Lock`) | ✅ Safe |
| `claim_task` | **Yes** — exists+read+write gap | No | ❌ Must be guarded |
| `release_paths` | **Yes** — exists+read+write gap | No | ❌ Must be guarded |
| `release_task` | **Yes** — same pattern | No | ❌ Must be guarded |
| `mark_lease_stale` | **Yes** — iterates all leases, then writes | No | ❌ Must be guarded |
| `heartbeat` | **Yes** — reads session, modifies, writes back | No | ❌ Must be guarded |
| `register_session` | No (new session_id) | No | ⚠️ Safe by construction |
| `publish_artifact` | Minimal (different SHA → different file) | No | ⚠️ Safe by construction |
| `report_conflict` | Minimal (different conflict_id) | No | ⚠️ Safe by construction |
| `request_handoff` | No (append-only) | No | ⚠️ Safe by construction |
| `read_state_projection` | No (read-only + event append) | No | ⚠️ Event append only |

### Critical: Stale lease bug

`_iter_reservations()` in `store.py:91-99` reads all lease files from disk but **never filters expired leases**. An expired lease with `status="active"` blocks new reservations permanently. `_projection()` marks them stale in-memory but does NOT persist the change to disk. `read_state_projection()` skips them via expiry check. But `reserve_paths` goes through `_iter_reservations` which uses raw file read. **Result: stale leases block forever. No automatic cleanup.**

### Other write surfaces

| Surface | Safety |
|---|---|
| `events.jsonl` append | Partial — O_APPEND safe for lines ≤ PIPE_BUF, no sequence atomicity |
| `observability.jsonl` append | Partial — same, plus session-scoped (different files per session) |
| `reports.jsonl` append | Partial — same pattern, dedup key computed but not enforced |
| `write_projection()` (analytics/bash/reports indexes) | **Unsafe** — direct `write_text()`, no temp+rename |
| Static renderer (docs/pages, docs/assets, etc.) | **Unsafe** — direct `write_text()`, no staging directory |
| Release gate output | **Unsafe** — direct `write_text()`, no atomic write |
| Context layout/assembly report writes | ✅ Safe — temp+rename atomic |
| Desktop intent result writes | ✅ Safe — temp+rename atomic + try/except for concurrent writes |
| Tool cache (DuckDB) | ✅ Safe — DuckDB WAL handles concurrency |

---

## 4. API Boundary Recommendation (condensed from Subagent B)

### Foundation: Desktop WebSocket Protocol

The Desktop Cockpit already has a mature typed-message protocol:
- Discriminated `type` field + typed payload + sequence numbers
- Auth gating, rate limiting, jsonschema validation
- Request/response pattern
- This is the basis for the HTTP API

### Proposed endpoints (command/query separated)

**Commands** (POST — produce intent envelopes → digester):

| Endpoint | Backed by | Envelope needed? |
|---|---|---|
| `POST /coordination/lease-requests` | `PathLeaseManager.claim_paths()` | Yes — `rig.relay.api.lease_request.v1` |
| `POST /coordination/task-claims` | `CoordinationStore.claim_task()` | Yes — `rig.relay.api.task_claim.v1` |
| `POST /coordination/session-events` | `register_session()` + `heartbeat()` | Yes — unified event envelope |
| `POST /coordination/conflicts` | `report_conflict()` | `CoordinationConflict` model exists |
| `POST /coordination/handoffs` | `request_handoff()` | Yes |
| `POST /coordination/artifacts` | `publish_artifact()` | `CoordinationArtifactRef` model exists |
| `POST /coordination/release-tasks` | `release_task()` | Yes |
| `POST /context/requests` | `ContextCompiler.build_envelope()` | `ContextRequest` model exists |
| `POST /tools/invocations` | `RuntimeToolInvocationAdapter` | `RuntimeToolInvocationEnvelope` exists |
| `POST /telemetry/events` | `send_telemetry_event()` | `rig.relay.observability.v1` implied |
| `POST /reports/submit` | `write_report_to_ledger()` | Yes |
| `POST /release-gate/runs` | `GateRunner.run()` | `GateResult` model exists |

**Queries** (GET — read projections, never mutate):

| Endpoint | Backed by |
|---|---|
| `GET /coordination/projections/current` | `read_state_projection()` |
| `GET /coordination/projections/summary` | New — lightweight subset |
| `GET /context/packets/{id}` | `ContextPacket` retrieval (needs persistence) |
| `GET /tools/invocations/{id}` | `RuntimeToolExecutionResult` retrieval (needs async store) |
| `GET /telemetry/local-events/{session_id}` | `observability.jsonl` read |
| `GET /release-gate/runs/{id}` | `GateResult` retrieval |
| `GET /reports/query` | DuckDB-powered queries over report ledger |
| `GET /ralph/panels/{scan_id}` | Ralph panel retrieval |

**Endpoints to drop**: `POST /workstream/events`, `GET /workstream/status` — fully redundant with coordination endpoints.

### Envelope schema inventory

Of ~16 required envelope schemas: **2 exist** (`rig.context_request.v1`, `rig.relay.runtime_tool_invocation.v1`). **14 are missing**. All have backing Pydantic models that can be promoted to full JSON Schema.

---

## 5. Digestion Migration Plan

### Phase 1 (this slice): Guard remaining coordination methods

Extend the `.digester.lock` (`fcntl.flock` + `threading.Lock`) to cover:
1. `claim_task` — `tasks/*.json` read/write
2. `release_paths` — `leases/paths/*.json` read/write
3. `release_task` — `tasks/*.json` read/write
4. `mark_lease_stale` — multi-file lease iteration + write
5. `heartbeat` — `sessions/*.json` read/write

Fix the stale lease bug: `_iter_reservations` must filter expired leases on disk or write `status="stale"` back to disk.

### Phase 2: events.jsonl hardening

- Atomic sequence counter (file-backed or flock-guarded increment)
- Idempotency dedup via event_id check before append
- `fsync` after critical writes

### Phase 3: API airlock

Wrap all guarder methods behind HTTP endpoints. Subprocesses submit intent envelopes via POST. The digester is the only writer.

---

## 6. Strict Concurrency Risks (condensed from Subagent C)

### Top 10 risks ranked by severity

| # | Risk | Severity | Cause | Fix |
|---|---|---|---|---|
| 1 | Stale leases block reservations forever | **Critical** | `_iter_reservations` doesn't filter expired | Filter expired in `_iter_reservations`; persist stale status |
| 2 | `claim_task` TOCTOU | **Critical** | No digester guard | Extend `.digester.lock` coverage |
| 3 | Same-owner claim_task retry creates duplicate | **Critical** | Idempotency gap: same-owner check falls through to create new claim | Idempotency check before create |
| 4 | `release_paths` + `reserve_paths` race | **High** | `release_paths` unlocked but operates on same lease dir | Guard `release_paths` |
| 5 | `events.jsonl` sequence collision | **High** | `_next_sequence()` reads last line count — racy | Atomic counter or flock-guarded increment |
| 6 | `events.jsonl` interleaved lines > PIPE_BUF | **High** | No writer lock on events.jsonl | Flock or single-writer pattern |
| 7 | `mark_lease_stale` iteration gap | **High** | Iterates all leases, reads, writes — new leases added mid-iteration missed | Guard with digester lock |
| 8 | `heartbeat` lost update | **Medium** | Concurrent heartbeats on same session interleave | Guard with session-level lock |
| 9 | Crash between lease write and event append | **Medium** | Lease file written, event not appended → incomplete audit trail | Event-first or journal-before-commit |
| 10 | Observability sequence collision | **Medium** | Same as events.jsonl but per-session file | Atomic sequence per session |

### Lock file analysis

The `.digester.lock` (`fcntl.flock`) is:
- ✅ Released on process crash (kernel-level cleanup)
- ✅ Cross-process safe
- ✅ Re-entrant on same fd (no deadlock on nested calls)
- ⚠️ Only covers `reserve_paths` — 7 other mutation methods bypass it
- ⚠️ Lockfile deletion defeats it (new inode) — but no code deletes it

---

## 7. Safe Worker Classification (condensed from Subagent D)

### Execution pools needed

| Pool | Purpose | Size | What goes here |
|---|---|---|---|
| **Bounded Thread Pool** | I/O offload from async event loop | `os.cpu_count() + 4` | Git subprocess calls, `rglob`/`glob`/`iterdir`, file reads |
| **Process Pool** | CPU-bound parallelism | `os.cpu_count() - 1` | Trace scanner, release gate checks, static renderer, schema validation fan-out |
| **Supervisor Subprocesses** | Governed subprocess execution | Bounded by lease count | Tool execution, git operations |
| **Digester Single-Writer** | Serialized mutation | 1 per domain | All coordination mutations, context packet publish |
| **Async Task Groups** | Managed async concurrency | Per-domain semaphores (4–16) | Tool execution, telemetry send, WebSocket subscriptions |

### Critical event-loop blockers (fix now)

| Call site | Blocking operation | Latency | Fix |
|---|---|---|---|
| `context/repo_map.py:105` | `subprocess.check_output` (git) | 100ms–1s | `loop.run_in_executor()` |
| `context/repo_index.py:24` | `subprocess.check_output` (git) | 100ms–1s | `loop.run_in_executor()` |
| `core/tools/builtins/checkpoint.py:301` | `subprocess.run` (git) | 100ms–1s | `loop.run_in_executor()` |
| 65+ `rglob`/`glob`/`iterdir` calls | Sync filesystem traversal | 10ms–1s | `anyio.Path` or `run_in_executor()` |

### Hidden latency top 10

| Operation | Latency | Blocks loop? |
|---|---|---|
| Git subprocess (repo_map, repo_index) | 100ms–1s | **Yes** |
| Trace scanner (998+ files) | 1s–10s+ | No (CLI) |
| LLM API calls | 1s–30s | **Yes** (intentional) |
| Telemetry close/drain | 100ms–1s | **Yes** |
| WebSocket projection build | 1s–10s+ | No (executor) |
| DuckDB observability queries | 100ms–1s | No (on-demand) |
| Release gate checks (full suite) | 10s+ | No (CLI) |
| File tree scans (rglob) | 10ms–1s | **Yes** (many sites) |
| JSON schema validation | 10ms–100ms | No (sync paths) |
| Static renderer | 1s–10s+ | No (CLI) |

---

## 8. Global State and Cache Hazards (condensed from Subagent E)

### Critical

| Hazard | Location |
|---|---|
| Nested `asyncio.run()` in async context | `desktop/intents.py:1303,1493,2214,2222,2714` |
| Manual `asyncio.new_event_loop()` split-brain | `cli/desktop_cockpit.py:1019` |

### High

| Hazard | Location |
|---|---|
| `os.environ` mutation | `cli/desktop_cockpit.py:687,892,1252` |
| 73 `Path.cwd()` default parameters | Scattered across codebase |
| `asyncio.run()` inside ThreadPoolExecutor | `core/utils/concurrency.py:28` |
| `websearch.py` httpx client not in `async with` | `core/tools/builtins/websearch.py:84` |

### Medium

| Hazard | Location |
|---|---|
| 4 singleton patterns without locks | `dirty_guard.py`, `tool_runtime_ledger.py`, `_harness_manager.py`, `event_loop_util.py` |
| `_pending_tasks` set without lock + `aclose()` race | `core/telemetry/send.py:97` |
| `EventEmissionScanner._scan_cache` never invalidated | `tracing/_contract.py:337` |
| `walk_local_config_dirs` @cache never invalidated | `core/paths/_local_config_walk.py:184` |

---

## 9. DuckDB Utilization Plan (condensed from Subagent F)

### Current usage: Clean

DuckDB is used at 15 sites. **Zero** are canonical state. All are:
- **Derived read-side** (7 sites): analytics substrate, telemetry projection, reports query, bash query, repo index, current_state
- **Cache** (1 site): tool result cache (`tool_cache.duckdb`) — content-addressed, TTL-expiring, fail-safe (returns None on error)
- **Script/pipeline** (5 sites): compaction, bundle generation, dataset inspection, tool refinement
- **Normalization** (2 sites): bash_rows, model_rows (no direct DuckDB import)

### Architecture boundary: Enforced

`tests/core/test_architecture_boundaries.py` prohibits DuckDB imports in: `AgentLoop`, all core mixins, `runtime_state.py`, `conversation_turn.py`. This boundary is comprehensive and tested.

### Proposed new read-side projections (all safe, in-memory ephemeral)

1. Telemetry event aggregates — count/latency by event_name, session, day
2. Coordination contention hotspots — conflict rates, digester latency histogram
3. Release gate findings over time — historical pass/fail trends
4. Test-suite inventory — module-by-module test coverage, xfail ratio
5. Trace event drift reports — registered vs emitted coverage gap
6. Bash invocation risk patterns — rerouting effectiveness
7. Worker latency/queue-depth reports — for future worker pools
8. Tool refinement opportunity ranking — failure rate, fallback-to-bash rate
9. Context assembly cache hit rates — stable prefix persistence
10. Session lifecycle analytics — duration, message count, tool patterns

### Forbidden: Never use DuckDB for

- Lease grant authority (→ CoordinationStore + fcntl)
- Task claim authority (→ CoordinationStore)
- Consent source of truth (→ TelemetryConsentRecord JSON)
- Debug packet raw storage (→ file artifacts + SHA256 manifest)
- Canonical event ledger (→ events.jsonl append-only)
- Workstream canonical ledger (→ workstream JSONL)
- Release gate canonical results (→ gate JSON output)
- Subagent coordination transaction engine (→ digester)
- Agent loop runtime decisions (→ config, permissions, tool manifests)
- Model prompt construction (→ context envelope assembly)

---

## 10. Hidden Latency Map (condensed from Subagent D)

| # | Operation | Latency class | Blocks event loop? | Fix priority |
|---|---|---|---|---|
| 1 | Git subprocess (repo_map, repo_index) | 100ms–1s | **YES** | NOW |
| 2 | rglob/glob/iterdir (65+ sites) | 10ms–1s | **YES** (many) | NOW |
| 3 | LLM API calls | 1s–30s | Yes (intentional) | Async (correct) |
| 4 | Telemetry close/drain | 100ms–1s | **YES** | Add timeout |
| 5 | Trace scanner (998+ files) | 1s–10s+ | No (CLI) | Process pool |
| 6 | WebSocket projection build | 1s–10s+ | No (executor) | Correct |
| 7 | Release gate checks (full) | 10s+ | No (CLI) | Process pool |
| 8 | DuckDB observability queries | 100ms–1s | No (on-demand) | Async task |
| 9 | JSON schema validation | 10ms–100ms | No (sync paths) | Executor if async |
| 10 | Static renderer | 1s–10s+ | No (CLI) | Process pool |

---

## 11. Required Tests (ranked by risk)

| Priority | Test | Risk addressed |
|---|---|---|
| **P0** | `_iter_reservations` filters expired leases (stale lease blocks forever) | Critical — data corruption |
| **P0** | Two concurrent `claim_task` for same task_id → exactly 1 granted | Critical — double-claim |
| **P0** | `release_paths` + `reserve_paths` race → no inconsistent state | Critical — TOCTOU |
| **P0** | Same-owner `claim_task` retry is idempotent (no duplicate claim) | Critical — idempotency |
| **P1** | Event sequence numbers never collide under concurrent append | High — audit integrity |
| **P1** | events.jsonl lines > PIPE_BUF don't interleave | High — corruption |
| **P1** | Crash between lease write and event append → event recoverable | Medium — crash recovery |
| **P1** | `mark_lease_stale` + concurrent `reserve_paths` → no missed leases | High — iteration gap |
| **P2** | Git subprocess via executor doesn't deadlock | High — event loop |
| **P2** | rglob in executor doesn't block event loop | High — event loop |
| **P2** | Telemetry send pending tasks bounded by semaphore | Medium — resource leak |
| **P3** | Stale lock detection and automatic release | Low — lock hygiene |
| **P3** | Static renderer concurrent run → no corrupted output | Medium — build tool |
| **P3** | write_projection uses temp+rename → atomic | Medium — index integrity |

---

## 12. Convergent Implementation Plan

### Big Slices (in order)

| Slice | What | Why first/second/Nth |
|---|---|---|
| **A**: Local API Airlock + Envelope Schema Spine | HTTP endpoints for all digester-guarded commands; JSON Schema for all envelopes | Provides the serialization boundary subprocesses need; forces mutation through digester |
| **B**: Coordination Digester Formalization | Guard claim_task, release_paths, release_task, mark_lease_stale, heartbeat; fix stale lease bug | Completes the single-writer property; eliminates remaining TOCTOU races |
| **C**: Projection Read Purity + Observation Split | Projections must not append events.jsonl; read-side only | Separates command from query; prevents read-side mutation |
| **D**: Context Assembler Request Digestion | context.requested envelopes → context_packet.ready/rejected | Makes context assembly queueable; enables cache lifecycle |
| **E**: Hardened Tool Invocation Digestion | tool.invocation.requested → lease check → receipt emission | Completes the tool execution safety boundary |
| **F**: Worker Classification Registry + Bounded Executors | Thread pool for I/O, process pool for CPU | Fixes event-loop blocking; enables parallelism |
| **G**: DuckDB Read-Side Analytics Projections | 10 proposed projections | Read-side insight without canonical dependency |

### Next slice: Slice A — Local API Airlock + Envelope Schema Spine

**Justification**: All remaining coordination mutations need a serialization boundary before subprocesses can safely interact with the store. The Desktop WebSocket protocol provides the typed-message foundation. The envelope schemas are missing but the Pydantic models exist. This slice creates the API surface that Slice B (digester formalization) feeds into. Slice B fixes the TOCTOU races; Slice A provides the boundary that enforces them.

Building the API first (even if the mutations behind it still race) establishes:
1. The envelope contract subprocesses will use
2. The JSON Schema spine for all future digester inputs
3. The command/query separation that prevents read-side mutation
4. A foundation to test Slice B's digester guards against

---

## 13. Next Implementation Slice Prompt

```
API Airlock + Envelope Schema Spine v0

Implement the minimal safe local API surface for Rig Relay's future
subagent subprocess architecture.

Hard constraint: No new database dependencies. No SQLite.

## What exists
- Desktop WebSocket protocol: mature typed-message protocol with type
  discriminator, auth, rate limiting, jsonschema validation
- CoordinationStore with 1 digester-guarded method (reserve_paths)
- Pydantic models for all coordination operations
- Context request/packet models with JSON Schema
- Runtime tool invocation envelope model with JSON Schema
- Redaction wired into telemetry upload path
- Consent expiry enforced

## What to build

### 1. Envelope Schema Spine

Create JSON Schema files for these envelope families (Pydantic models already exist):

- rig.relay.api.lease_request.v1.json
- rig.relay.api.task_claim.v1.json
- rig.relay.api.session_event.v1.json (unifies register_session + heartbeat)
- rig.relay.api.conflict.v1.json (CoordinationConflict model exists)
- rig.relay.api.handoff.v1.json
- rig.relay.api.artifact.v1.json (CoordinationArtifactRef model exists)
- rig.relay.api.release_task.v1.json
- rig.relay.api.report_submit.v1.json
- rig.relay.api.telemetry_event.v1.json (formalizes rig.relay.observability.v1)
- rig.relay.api.release_gate_run.v1.json (GateResult model exists)
- rig.relay.coordination.state_projection.v1.json (already a model)

Where Pydantic models exist, extract the JSON Schema from the model.

### 2. Minimal HTTP API

Using the Desktop WebSocket protocol as foundation, implement:

POST endpoints (command, produce intent envelopes):
  POST /api/v1/coordination/lease-requests
  POST /api/v1/coordination/task-claims
  POST /api/v1/coordination/session-events
  POST /api/v1/coordination/handoffs
  POST /api/v1/coordination/artifacts
  POST /api/v1/coordination/release-tasks
  POST /api/v1/context/requests
  POST /api/v1/tools/invocations (deferred body, skeleton routing)
  POST /api/v1/telemetry/events
  POST /api/v1/reports/submit
  POST /api/v1/release-gate/runs

GET endpoints (query, read projections):
  GET /api/v1/coordination/projections/current
  GET /api/v1/coordination/projections/summary
  GET /api/v1/telemetry/local-events/{session_id}
  GET /api/v1/reports/query (DuckDB-powered, read-side)
  GET /api/v1/health

Use localhost-only binding. No TLS required for v0.
Use aiohttp or the existing httpx server capabilities.
Accept and validate JSON against the envelope schemas.

### 3. Content-Light Enforcement

Every POST endpoint must:
- Validate the request body against its envelope JSON Schema
- Reject requests containing forbidden fields (token, api_key, password, etc.)
- Log only content-light metadata (no raw paths, no secrets, no payloads)
- Return an idempotency-aware response (201 Created or 200 OK with existing result)

### 4. Command/Query Separation

- GET endpoints must NEVER mutate canonical state
- read_state_projection currently appends an event — fix in this slice: remove
  the event append from read paths (move to a dedicated audit log if needed)

### 5. Tests

- Contract tests: every endpoint validates its schema
- Content-light tests: POST bodies with secrets are rejected
- Idempotency tests: same request twice returns same result
- Read-purity tests: GET endpoints never produce side effects
- Integration test: full lease request → decision → projection flow via API

### Non-goals
- Do not implement API auth beyond localhost-only
- Do not implement tool invocation body (skeleton routing only)
- Do not fix TOCTOU races in coordination store (that is Slice B)
- Do not add process pool or thread pool infrastructure
- Do not touch Docker, Kubernetes, or any deployment infrastructure

## Pi subagent execution

Launch 4 implementation subagents + 1 coordinator:
- Subagent A: Envelope schemas (extract from Pydantic models, write JSON Schema files)
- Subagent B: HTTP API server (aiohttp routes, request/response models)
- Subagent C: Content-light enforcement + read purity
- Subagent D: Contract tests + integration tests
- Coordinator: Fan-in, run full suite, resolve conflicts

Run:
  uv run pytest tests/api/ -q
  uv run ruff check rig_relay/api/
  uv run pyright rig_relay/api/
```

---

## 14. Subagent Execution Summary

| Subagent | Domain | Key findings | Tables produced |
|---|---|---|---|
| **A** | Mutation Plane Audit | 7/8 coordination methods unguarded; stale lease bug; non-atomic writes in renderer/projections | Write path table (40+ rows), TOCTOU analysis, artifact inventory |
| **B** | API Boundary + Envelopes | Desktop WebSocket protocol is mature foundation; 14 envelope schemas missing; no subprocess serialization boundary | Endpoint table (20 rows), envelope inventory (16 schemas), inner protocol analysis |
| **C** | Strict Concurrency | Stale leases block forever; claim_task idempotency gap; events.jsonl no sequence atomicity | Race class table (15 rows), idempotency inventory, crash recovery inventory, lock file analysis |
| **D** | Worker Classification | Git subprocess blocks event loop; 65+ rglob calls block; no semaphore on tool execution | Workload table (47 rows), latency top 20, 5 worker pool designs |
| **E** | Global State + Cache | 2 critical asyncio anti-patterns; 73 Path.cwd() defaults; 4 singleton races | Global state table (20+ rows), cache audit, asyncio.create_task audit, HTTP client lifecycle |
| **F** | DuckDB Safe-Use | DuckDB is 100% read-side + cache; architecture boundary enforced; 10 proposed projections; tool cache concurrency acceptable | Usage table (15 rows), proposed projections (10), forbidden uses (10), concurrency safety table |

---

## Audit Metadata

- **Repo**: `main` @ `9717e21`
- **Test baseline**: 8 telemetry, 10 coordination, 20 tracing, 10 release gate, 17 guard — all passing
- **Total tests collected**: 7271
- **Subagents**: 6 concurrent general-purpose agents
- **Git discipline**: No commits, no pushes, no force operations, no dirty file overwrites
- **Time**: ~90 seconds total wall-clock

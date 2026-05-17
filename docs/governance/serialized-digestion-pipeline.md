# Serialized Digestion Pipeline v0

**Status**: v0 architecture  
**Date**: May 2026  
**Scope**: coordination artifact mutation safety, multi-agent concurrency, intent-envelope pattern

## Why direct shared mutation failed

`CoordinationStore.reserve_paths` and sibling mutation methods suffered a textbook TOCTOU (time-of-check-time-of-use) race. The pattern:

1. Agent A reads active leases → no conflict detected
2. Agent B reads active leases → no conflict detected
3. Agent A writes grant for path X
4. Agent B writes grant for path X

Both agents observed the pre-mutation state, both concluded the path was free, both wrote. Under concurrent subprocesses (asyncio tasks, future subagent processes, signal-interleaved writes), the double-win rate approached ~50% for contended paths. No lock, no serialization, no post-write validation — just a read-then-write gap wide enough for any concurrent actor to slip through.

This pattern breaks at every concurrency boundary: threads, asyncio tasks within one process, OS subprocesses sharing a filesystem-backed store, and eventually fleet agents on different machines. `tempfile.replace()` only guarantees atomicity of a single write — it does not serialize competing writes. Two processes can atomically write conflicting files to the same logical resource.

## Why the fix is digestion, not lock-scoped everything

The architectural philosophy rejects blanket locking for four reasons:

### Commands mutate, queries read — don't mix them

CQS (Command-Query Separation) applies at the architectural layer. A query (projection read) must never trigger a mutation side-effect. A command (intent envelope submission) produces decisions, not arbitrary state changes. Mixing them — locking a data structure long enough to query and then mutate — is the root cause of TOCTOU. Single-writer digestion makes the boundary absolute.

### Subagents submit intent envelopes, not direct mutations

Subagents (whether in-process, subprocess, or fleet-remote) never call `store.reserve_path()` or `store.claim_task()`. They submit typed intent envelopes (e.g., `LeaseRequestEnvelope`) to the digester. The envelope is a declaration of desired state, not a state-changing operation. This is the CQS boundary: agents express intent, digester decides outcome.

### The digester is the single writer for its canonical stream

Exactly one component — the digester — writes to canonical coordination artifacts. All other components are read-only consumers of projections. This is not "single-writer via lock" — it is architecturally single-writer. The digester processes one envelope at a time, sequentially, because it owns the write path. Adversarial or concurrent writers cannot exist by design.

### Advisory locks are an implementation detail, not the architecture

In-process, the digester may use an `asyncio.Lock` or a file-system advisory lock (`fnctl.flock`) to guard its single-writer section across subprocess boundaries. This is a correctness mechanism for the digester's own serial execution guarantee, not a general-purpose coordination primitive exposed to consumers.

### Denied and conflicting intents become evidence, not invisible failure

When lock-scoped mutation patterns deny a request, the denial is often a silent return value (or exception) with no durable record. The digestion pipeline treats every decision as a first-class artifact: granted/denied/rejected decisions are written to `events.jsonl` and conflict records to `conflicts/`. Nothing is invisible.

## Producer → Envelope → Digester → Decision → Projection flow

```
Producer                Envelope              Digester               Decision              Projection
(agent/tool/session)    (intent artifact)     (single writer)        (outcome artifact)    (read-only view)

┌──────────┐            ┌────────────────┐    ┌──────────────┐      ┌─────────────────┐    ┌────────────┐
│ Subagent │──intent──▶│ LeaseRequest    │───▶│              │─────▶│ LeaseDecision   │    │            │
│ Session  │            │ Envelope       │    │  Digester    │      │ Envelope        │    │ Projection │
│ Tool     │            │                │    │              │      │                 │    │ Layer      │
│ Ralph    │            │ schema-valid   │    │ checks       │      │ granted ────────▶──▶│ (queries)  │
│          │            │ sha256-hashed  │    │ canonical    │      │ denied  ──▶ evt  │    │            │
│          │            │ auth-attested  │    │ state        │      │ rejected──▶ evt  │    │            │
└──────────┘            └────────────────┘    └──────────────┘      └─────────────────┘    └────────────┘
```

### Step 1: Producer emits intent envelope

A producer (subagent, tool executor, session lifecycle handler, Ralph scanner) constructs a typed envelope — e.g., `LeaseRequestEnvelope` with fields: `lease_id`, `path`, `requested_by_session`, `requested_at`, `mode` (read/write/exclusive). The envelope is written as a standalone JSON artifact under a pending-intent directory or submitted via IPC (future).

### Step 2: Envelope validation

Before reaching the digester, each envelope is validated:
- **Schema validation**: matches the envelope's declared JSON schema
- **Hash integrity**: `envelope_sha256` matches the payload
- **Auth attestation**: `requested_by_session` corresponds to an active, authorized session

Invalid envelopes are rejected before digestion — they never reach the canonical state check.

### Step 3: Digester checks against canonical state

The digester reads the current canonical state for the affected resource (leases, tasks, sessions) and evaluates the request:
- Path X requested for exclusive write → check no active lease exists for X
- Task Y claimed → check no other session has claimed Y
- Session Z forked → check parent session is terminal

This is the serialized single-writer section. Only the digester performs this check-then-update sequence, and it does so one envelope at a time.

### Step 4: Digester produces a decision

The outcome is a `LeaseDecisionEnvelope` (or `TaskDecisionEnvelope`, etc.) with:
- `decision`: `granted` | `denied` | `rejected`
- `reason`: human-readable rationale for denied/rejected
- `digester_session`: session ID of the digester that processed the request
- `processed_at`: timestamp
- `evidence_sha256`: hash chain link to the request envelope

### Step 5: Decision routing

- **Granted decisions**: update canonical artifacts (`leases/paths/X.json` written). The intent envelope is moved from pending to accepted.
- **Denied decisions**: intent moved to rejected directory; `coord.path.reservation_refused` event written to `events.jsonl`; conflict record written to `conflicts/`.
- **Rejected decisions**: (schema/auth failure) — envelope discarded or moved to dead-letter; event written to `events.jsonl`.

### Step 6: Projection layer serves queries

All read-side consumers (agents checking "is path X available?", dashboard displaying active leases, Ralph scanning for mission candidates) read from projections — compiled read-only views rebuilt from canonical artifacts. No consumer reads canonical artifacts directly for query purposes. Projections are regenerated atomically (write to temp, rename over old) when canonical state changes.

## How subagent subprocesses will use this

Future Rig subagents are separate tailored agent-loop subprocesses. Each:

1. **Submits intent envelopes via artifact files or IPC** — never calls `store.*` mutation methods directly. For v0, intent envelopes are JSON files written to a well-known pending-intent directory. Future: Unix domain socket or sidecar IPC.

2. **Does NOT directly mutate shared coordination state** — the subagent binary has no import of `CoordinationStore` mutation methods. It only imports the envelope builder and the projection reader.

3. **Reads projections for state queries** — "what paths are claimed?" → read `projections/leases.json` (or query through a projection client). Projections are rebuilt by the digester after every accepted decision.

4. **Receives decisions from the digester** — the subagent polls (or subscribes, in IPC future) for decision envelopes matching its session ID. A granted decision means "proceed with work on path X". A denied decision means "path X is contested — stand down, read the conflict record".

This makes subagents truly disposable: they hold no canonical state, they don't need to coordinate among themselves, and a crashed subagent leaves no corrupted state (at most, an orphaned pending intent, which the digester can detect via heartbeat/liveness).

## Which artifacts are canonical

| Artifact path | Content | Mutation pattern |
|---|---|---|
| `leases/paths/*.json` | Path reservations with session, mode, timestamp | Write-on-grant, delete-on-release (via digester only) |
| `tasks/*.json` | Task claims with session, scope, status | Write-on-claim, update-on-complete/abandon (via digester only) |
| `sessions/*.json` | Session state, heartbeat, parent/child linkage | Write-on-create, update-on-state-change (via digester only) |
| `events.jsonl` | Append-only event ledger — every decision, conflict, state transition | Append-only (via digester only) |
| `conflicts/*.json` | Conflict records — denied/reserved intents with rationale | Write-on-conflict (via digester only) |

**Projections are NOT canonical**. They are read-only compiled views rebuilt from canonical artifacts. They can be deleted and regenerated at any time without data loss. They exist for query performance and consumer isolation.

## How denied conflicts become telemetry and evidence

Every denied lease produces:

1. **`coord.path.reservation_refused` event** — appended to `events.jsonl` with:
   - `envelope_sha256` of the denied request
   - `conflicting_lease_sha256` of the existing lease that blocked it
   - `refusal_reason` (already_leased, session_inactive, path_invalid)
   - `requested_by_session`, `processed_at`

2. **Conflict record** — written to `conflicts/<conflict_id>.json` with:
   - Full request envelope (inlined or referenced by hash)
   - Full blocking lease (inlined or referenced by hash)
   - Decision rationale
   - Timestamp and digest chain link

3. **Telemetry scope** — these events feed the `coordination_metrics` telemetry scope:
   - `denial_rate` per path prefix
   - `contention_hotspots` (paths with high refusal frequency)
   - `double_win_rate` (if detected post-digester — should be zero)
   - `digester_latency` distribution
   - `pending_intent_age` (how long intents sit before digestion)

All denial data is durable, queryable, and feeds both operational monitoring and the Ralph mission candidate scanner (contended paths → `CandidateKind.CONTENTION_HOTSPOT`).

## Why no database dependency

SQLite, DuckDB, Postgres, and Redis are out of scope for coordination artifacts. Rationale:

- **Filesystem is the universal substrate** — works across subprocesses, machines, and CI environments without setup or credentials
- **JSON/JSONL is human-readable and git-diffable** — agents and operators can inspect state with any text tool
- **Atomic file operations exist** — `tempfile + os.rename` is atomic on POSIX; `flock` provides advisory locking without a database server
- **Schemas and receipts provide integrity** — every artifact has a declared JSON schema and SHA256 hash chain; no need for database constraints
- **Projections are files too** — DuckDB may be used internally by the analytics subsystem (`rig_relay/analytics/`), but that is an analytical read-side, not the coordination write path

The digestion pipeline writes canonical JSON/JSONL artifacts using atomic file operations. The single-writer guarantee (not database transactions) provides consistency.

## How this prepares context assembler and hardened built-in tools

### Context assembler

The context assembler (`rig_relay/context/compiler.py`) currently reads repo state directly. The digestion pipeline enables:

1. **`context.requested` envelopes** — when an agent requests context for a mission, the request becomes an envelope. The digester checks: is this session authorized? has this context already been assembled within TTL? are any paths blacklisted for this session?

2. **`context_packet.ready` / `context_packet.rejected` events** — decisions on context requests become telemetry events in `events.jsonl`. Rejected packets (e.g., "path blacklisted", "session expired") become conflict records.

3. **Context packet caching** — the digester can serve cached context packets when the underlying artifacts haven't changed, avoiding redundant compilation.

### Hardened built-in tools

Every mutation-capable built-in tool (`WriteFile`, `SearchReplace`, `BashTool` with mutation side-effects, `checkpoint`) will flow through the digestion pipeline:

1. **`tool.invocation.requested` envelope** — before execution, the tool submits a lease request for the paths it intends to mutate. The digester checks: is the session authorized? does a conflicting lease exist? is the path in the session's declared scope?

2. **Lease-required mutation gate** — the tool execution is gated on receiving a `LeaseDecisionEnvelope` with `granted`. If denied, the tool raises `ToolPermissionError` with the conflict reason.

3. **Receipt emission** — after successful execution, the tool emits a receipt into the tool invocation trace. The receipt's `evidence_sha256` chains into the lease's termination event, providing end-to-end audit: request → grant → execution → receipt → release.

This eliminates the current pattern where tools check permissions inline without serialized coordination, which would produce the same TOCTOU race described above when multiple session processes run concurrently.

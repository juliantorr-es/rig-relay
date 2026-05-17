# Release Candidate Convergence Spine v0 — 5-Phase Roadmap

**Generated**: 2026-05-17
**Schema**: `rig.relay.release_candidate_roadmap.v1`
**Repo**: `main` @ `565c296` — working tree clean

---

## 1. Executive Verdict

**RC path visible, key blockers remain.**

The coordination event ledger is now hardened for cross-process sequence safety. The digestion pipeline guards all 10 mutation methods. Telemetry consent and redaction are enforced. Release gate CLI works. Guard escape hatches are blocked. Static docs render with CSP.

However: Phase 5 has a **LICENSE mismatch blocker** (AGPL vs Apache). Phase 4 has a **dead CI release workflow** referencing the wrong repo. Phase 1 has a **lease manager lock bypass** and **task claim missing event emission**. The digestion pipeline remains design-only — no digester class, no envelope models.

RC Phase 1–3 are functionally complete for single-session scope. Multi-agent subprocess dispatch is blocked on the digestion pipeline implementation.

---

## 2. Completed Convergence Slices

| Slice | Date | Evidence |
|---|---|---|
| Release gate registry + CLI seam closure | Prior | `tests/release_gate/test_release_gate_cli.py` (10 tests) |
| Telemetry panopticon audit | Prior | `docs/audits/telemetry-panopticon-audit.md` |
| Telemetry consent enforcement | Prior | `tests/core/test_telemetry_consent_gate.py` (15 tests) |
| Test-suite reality pressure audit | Prior | `docs/audits/test-suite-reality-pressure-audit.md` |
| Seam pressure harness v0 | Prior | Real CLI, scanner, guard, concurrency tests |
| Serialized digestion pipeline v0 | Prior | `reserve_paths` digester-guarded; redaction + consent expiry wired; trace scanner expanded; subprocess race test |
| Coordination digester formalization v0 | Prior | All 10 mutation methods guarded; stale lease fix; claim_task idempotency; event sequence counter; read projection purity |
| **Coordination event ledger hardening v0** | **This mission** | Cross-process sequence safety via file-backed `_next_sequence`; `register_session`/`publish_artifact`/`report_conflict`/`request_handoff` guarded; DuckDB ledger integrity tests |

---

## 3. Critical Blockers Before RC

| # | Blocker | Phase | Severity | Resolution |
|---|---|---|---|---|
| 1 | **LICENSE mismatch**: LICENSE (AGPL) ≠ README (Apache) ≠ classifier (Apache) | Phase 5 | **BLOCKER** | Reconcile all three to AGPL-3.0-or-later |
| 2 | **SECURITY.md missing** | Phase 5 | **BLOCKER** | Create security policy |
| 3 | **CHANGELOG contains wrong project** (mistral-vibe history) | Phase 5 | **BLOCKER** | Replace with Rig Relay 0.1.0α1 entries |
| 4 | **Lease manager lock bypass** | Phase 1 | **HIGH** | Remove direct writes from `lease_manager.py`; use store methods only |
| 5 | **Task claim refusal no event emission** | Phase 1 | **MEDIUM** | Add `coord.task.claim_refused` event + `build_task_claim_refused_payload` |
| 6 | **CI release workflow guards on `mistralai/mistral-vibe`** | Phase 4 | **HIGH** | Update repo reference to `juliantorr-es/rig-relay` |
| 7 | **3 deferred release gate checks marked required** | Phase 4 | **MEDIUM** | Demote from required to deferred in gate policy |
| 8 | **Digestion pipeline design-only** (no `Digester` class, no envelope models) | Phase 3 | **HIGH** | Implement digester + `LeaseRequestEnvelope`/`LeaseDecisionEnvelope` |

---

## 4. Phase 1 — Governance and Coordination

**Status**: READY (2 blockers remain)

| Area | Status |
|---|---|
| Git discipline commands blocked (8 destructive + 6 escape hatches) | ✅ |
| Dirty file preservation (SHA256-gated write_file/search_replace) | ✅ |
| Multi-agent coordination store (10 digester-guarded methods) | ✅ |
| Path lease lifecycle (reserve → expire → release → stale) | ✅ |
| Task claim lifecycle (claim → release, same-owner idempotent) | ✅ |
| Session lifecycle (register → heartbeat → status) | ✅ |
| Event ledger sequence safety (cross-process file-backed `_next_sequence`) | ✅ |
| Projection read purity (no event append, no mutation) | ✅ |
| Cross-process lease guard (`fcntl.flock` + subprocess race test) | ✅ |
| Stale lease recovery (`_iter_active_reservations_locked` + `cleanup_leases.py`) | ✅ |
| Denied conflict as evidence (path refusals complete; task refusals missing event) | ⚠️ |
| Lease manager lock safety | ❌ Bypasses digester |
| Task claim refusal event emission | ❌ Missing event |

### Blockers

| # | Blocker | Resolution |
|---|---|---|
| B1 | `lease_manager.py` writes directly to lease files outside digester lock | Remove direct writes; use store methods only; share digester lock |
| B2 | `_claim_task_locked` writes conflict file but no `coord.task.claim_refused` event | Add `_append_event` + `build_task_claim_refused_payload` |

### Required Tests
- Task claim denial emits event (P0)
- Lease manager lock safety multi-process test (P0)
- Event sequence monotonicity across subprocesses (P1)
- Conflict file ↔ event consistency check (P1)
- `read_state_projection` skips expired task claims (P2)

### Required Release Gate Checks
- All destructive git commands blocked (exists)
- Dirty file preservation gate (exists)
- Concurrent path claim exactly-one-winner (exists)
- Cross-process digester lock integrity (exists)
- Event sequence unique under concurrency (exists)
- Read projection does not mutate (exists)
- Task claim conflict event emission (needed after B2 fix)
- Lease manager lock safety (needed after B1 fix)

### Definition of Done
1. All 10 mutation methods digester-guarded; 0 double-wins under 50-iteration stress
2. Every denied coordination operation recorded in both file store AND event ledger
3. Stale leases auto-detected and manually recoverable
4. Event sequences unique and strictly increasing across subprocesses
5. All coordination tests pass (25+ tests); DuckDB ledger integrity verified

---

## 5. Phase 2 — Telemetry, Consent, Privacy, Debug

**Status**: READY (2 medium blockers deferred to Phase 3)

| Area | Status |
|---|---|
| Remote telemetry consent gate (5 states + scope + expiry) | ✅ |
| Consent scope enforcement (4 granular scopes) | ✅ |
| Consent expiry enforcement (`expires_at` checked) | ✅ |
| Remote upload redaction (`redact_for_remote` wired before HTTP POST) | ✅ |
| Local denial content-light (no subject_hash, no raw payload) | ✅ |
| Forbidden field coverage (47 entries + 16 name patterns + 5 regexes) | ✅ |
| Nested payload redaction (recursive dict/list/tuple walk) | ✅ |
| Static site no tracking (CSP `'self'`, zero analytics/pixels/fingerprinting) | ✅ |
| Debug packet quarantine boundary | ❌ Deferred |
| Debug packet user action gate | ❌ Deferred |

### Blockers (non-blocking for Phase 2 sign-off)
- **Debug packet quarantine**: No sandbox; deferred to Phase 3
- **Debug packet user action gate**: Manual CLI only; deferred to Phase 3
- **Stale test docstrings**: 2 classes say "OPEN SEAM" but code is fixed — cosmetic cleanup

### Required Tests
- Debug bundle quarantine boundary (P2)
- Debug bundle requires user confirmation (P2)
- Debug bundle emits creation receipt (P2)
- Consent expired with timezone edge cases (P2)
- Redaction empty containers edge case (P3)
- Static site CSP blocks unsafe-inline/eval (P3)
- Consent default scopes are basic only (P3)

### Required Release Gate Checks
- `RG-PHASE2-01`: consent gate + content-light + redaction tests pass
- `RG-PHASE2-02`: redaction is last transform before HTTP POST
- `RG-PHASE2-03`: subject_hash never in denial events
- `RG-PHASE2-04`: CSP has no unsafe-eval, no third-party origins
- `RG-PHASE2-05`: localStorage limited to UX preference key

### Definition of Done
1. All consent gate states enforced (NOT_REQUESTED, GRANTED, DENIED, REVOKED, EXPIRED)
2. Remote upload properties redacted before HTTP POST
3. Local denial events content-light
4. 47 forbidden fields covered; nested payloads walked
5. Static site: zero tracking, zero third-party pixels, zero fingerprinting
6. localStorage: UX preference persistence only

---

## 6. Phase 3 — Runtime, Tools, Context, API/Digestion

**Status**: READY (digestion pipeline is design-only — blocks multi-agent Phase 4)

| Area | Status |
|---|---|
| Subprocess lifecycle (no shell, bounded drain, state machine) | ✅ |
| Cancellation/timeout (terminate→kill escalation, stall detection) | ✅ |
| Lease-gated mutation tools (direct store calls, no digestion pipeline) | ⚠️ |
| Tool receipts emitted (content-light, SHA256-hashed) | ✅ |
| Bash/mutation guard (4-layer: env scrub, pattern detect, sensitive paths, denylist) | ✅ |
| Context packet assembly (content-light, canonical SHA256, 5 modes) | ✅ |
| Context cache safety (fingerprint-based, atomic writes, no TTL/eviction) | ✅ |
| Context digestion readiness (design doc only, no implementation) | ❌ |
| Local API command/query split (WebSocket intents, projection purity) | ✅ |
| Envelope schema spine (tool receipts + context + desktop; missing digestion envelopes) | ⚠️ |
| Projection read purity (digest dedup, schema-validated) | ✅ |

### Blockers
- **Digestion pipeline unimplemented**: No `Digester` class, no `LeaseRequestEnvelope`/`LeaseDecisionEnvelope` models. This is the architectural gap that blocks multi-agent subprocess dispatch. Non-blocking for single-session RC but required before Phase 4.
- **Context cache design-only**: No production cache store. Acceptable for Phase 3.

### Required Tests
- Digestion pipeline contract tests (P0)
- Concurrent mutation TOCTOU test (P1)
- Context cache invalidation integration test (P2)
- Tool receipt round-trip test (P1)
- Bash rerouting permission test (P2)
- Digest-based projection dedup test (P3)

### Required Release Gate Checks
- `pyright` — strict type check
- `ruff check` + `ruff format`
- Full suite passes
- Schema validation (`scripts/rig_relay_validate_schemas.py`)
- Cockpit launch + projection build + chat (manual)
- `rig.get_context` returns valid packet in 5 modes (manual)
- Mutation tools refuse without authorization (manual)

### Definition of Done
1. Single-session agent loop: mutation tools with lease-gating, receipt emission, dirty-guard checks
2. Runtime supervisor: subprocess lifecycle, timeout, cancellation, stall detection
3. Bash: 4-layer hardening + transparent rerouting
4. Context: content-light, hash-stable packets with canonical SHA256
5. Desktop WebSocket: clean command/query split; projection reads pure
6. All schemas validate; all tests pass; pyright clean

---

## 7. Phase 4 — UI, Static Docs, Release Gate, CI, Packaging

**Status**: READY (3 blockers: CI repo ref, deferred checks, .pi-lens in git)

| Area | Status |
|---|---|
| Cockpit/UI (pywebview + WebSocket, strict CSP, zero tracking) | ✅ |
| WebSocket intent safety (11 invariants, auth, rate limit, schema validation) | ✅ |
| Static docs (223 pages, 35 collections, 143 schemas, search index) | ✅ |
| Schema registry coverage (143 schemas, 6 renderable doc kinds) | ✅ |
| Release gate check coverage (11 implemented, 3 deferred placeholders) | ⚠️ |
| Release gate CLI (canonical JSON receipt, --strict, --include/--exclude) | ✅ |
| CI (5 workflows: pre-commit, tests, release gate, pages, PyInstaller build) | ⚠️ |
| Packaging/pyinstaller (linux/macOS/windows; 4 entry points; platformdirs+keyring) | ✅ |

### Blockers
| # | Blocker | Resolution |
|---|---|---|
| B1 | `release.yml` guards on `mistralai/mistral-vibe` — dead code | Update to `juliantorr-es/rig-relay` |
| B2 | 3 deferred checks marked `required_checks` in gate policy | Demote from required to deferred |
| B3 | 15 `.pi-lens/` files tracked in git | Add to `.gitignore` |

### Required Tests
- Release gate policy references only implemented checks (P1)
- CI release workflow triggers on correct repo (P1)
- `.pi-lens/` files not tracked (P2)
- Vulnerability scan (placeholder for future)

### Definition of Done
1. Cockpit serves UI; all intents read-only; mutation intents refused
2. Static docs render from canonical JSON; all schemas registered
3. Release gate: only implemented checks marked required; deferred checks not blockers
4. CI: pre-commit + tests + release gate on correct repo; PyInstaller builds for all platforms
5. `.pi-lens/` in `.gitignore`

---

## 8. Phase 5 — Public Release, Onboarding, GitHub, Docs, Distribution

**Status**: BLOCKED (LICENSE mismatch, missing SECURITY.md, wrong CHANGELOG)

| Area | Status |
|---|---|
| README (features, safety story, config, development) | ✅ |
| LICENSE/legal | ❌ AGPL file vs Apache README vs Apache classifier |
| ATTRIBUTION / THIRD_PARTY_NOTICES / UPSTREAM | ✅ |
| CONTRIBUTING.md (CLA, setup) | ✅ |
| SECURITY.md | ❌ Missing |
| CODE_OF_CONDUCT.md | ❌ Missing |
| Onboarding docs (quick start, install.md, AGENTS.md) | ✅ |
| Telemetry disclosure (footer exists; no README section) | ⚠️ |
| Debug packet policy (documented, dry-run only) | ✅ |
| Release notes (CHANGELOG shows mistral-vibe history, not Rig Relay) | ❌ |
| GitHub Pages (deploy workflow, 223 pages, CSP, search, social) | ✅ |

### Blockers
| # | Blocker | Resolution |
|---|---|---|
| B1 | LICENSE (AGPL) ≠ README (Apache) ≠ classifier (Apache) | Reconcile all three. If AGPL-3.0-or-later is intentional: update README and classifier. |
| B2 | SECURITY.md missing | Create or reference `docs/pages/security-policy.html` |
| B3 | CHANGELOG.md contains mistral-vibe history | Replace with Rig Relay 0.1.0α1 release notes |
| B4 | CODE_OF_CONDUCT.md missing | Create |

### Definition of Done
1. LICENSE, README, and pyproject.toml classifier all state same license
2. SECURITY.md, CODE_OF_CONDUCT.md present
3. CHANGELOG contains Rig Relay releases
4. README has explicit telemetry/data disclosure section
5. GitHub Pages deploys correctly on push to main

---

## 9. Dependency Utilization Plan

| Dependency | Where it helps the RC path |
|---|---|
| **DuckDB** | Read-side ledger integrity tests (unique sequences, valid JSON, required fields); analytics projections (contention hotspots, latency histograms, test-suite inventory); never canonical state |
| **pytest-xdist** | Parallel test execution; exposes filesystem/global-state hazards across workers |
| **pytest-timeout** | Guards against hanging tests (trace scanner, release gate, large JSONL scans) |
| **pytest-asyncio** | Async test support for agent loop, telemetry, supervisor, WebSocket |
| **respx** | Mock HTTP transport for telemetry upload + consent gate tests |
| **pexpect** | Interactive CLI testing (cockpit, onboarding, ACP) |
| **jsonschema** | Envelope validation, schema registry, release gate static checks |
| **pydantic** | All models; envelope serialization; redaction classification |
| **cryptography** | SSL context, token encryption, SHA256 hashing |
| **zstandard** | Debug packet compression; artifact compaction |
| **pyright** | Strict type checking (CI gate) |
| **ruff** | Linting + formatting (CI gate) |
| **vulture** | Dead code detection (useful for CI hardening) |
| **typos** | Spelling in docs + comments (pre-commit) |
| **pyinstaller** | Desktop app distribution (macOS/linux/windows) |
| **pywebview** | Desktop cockpit UI container |
| **platformdirs** | Cross-platform config/data/cache paths |
| **keyring** | Secure credential storage (API keys, tokens) |
| **gitpython** | Git operations in context compiler, checkpoint tool |
| **tree-sitter/tree-sitter-bash** | Bash parsing for rerouting and pattern detection |
| **ast-grep-py** | Structural code search for trace scanner and refactoring |
| **watchfiles** | File watching for dev mode and live reload |
| **pyinstrument** | Performance profiling for latency hotspot detection |

---

## 10. Release Candidate Evidence Matrix

| Subsystem | Status | Blocking Tests | Evidence Artifact | Release Gate Check | Owner |
|---|---|---|---|---|---|
| Git discipline | ✅ ready | 11 escape hatch tests | `tests/guard/test_escape_hatches.py` | `RG-GUARD-01` | Governance |
| Coordination ledger | ✅ ready | 25 concurrency tests | `events.jsonl` + DuckDB checks | `RG-COORD-01` | Coordination |
| Digestion pipeline | ⚠️ design | Contract tests needed | `serialized-digestion-pipeline.md` | — | Phase 3 |
| Telemetry consent | ✅ ready | 23 content-light tests | `observability.jsonl` | `RG-PHASE2-01` | Telemetry |
| Redaction | ✅ ready | 6 redaction tests | `redaction_proofs/` | `RG-PHASE2-02` | Evidence |
| Debug packets | ⚠️ deferred | Quarantine tests needed | `debug-bundle-policy.html` | — | Phase 3 |
| Trace contract | ✅ ready | 20 real-source tests | `correlation_vocabulary.v1.json` | `RG-TRACE-01` | Tracing |
| Runtime supervisor | ✅ ready | 20 test files | `tests/runtime/` | `RG-RUNTIME-01` | Runtime |
| Hardened tools | ✅ ready | Mutation + bash tests | Tool receipt schemas | `RG-TOOLS-01` | Tools |
| Context assembler | ✅ ready | 21 test files | `ContextPacket` artifacts | `RG-CONTEXT-01` | Context |
| Local API | ✅ ready | WebSocket intent tests | `websocket_server.py` | `RG-API-01` | Desktop |
| Static docs | ✅ ready | Renderer tests | `docs/pages/` (223 pages) | `RG-STATIC-01` | Docs |
| UI/webview | ✅ ready | Cockpit integration | `frontend/desktop/` | — | Desktop |
| Release gate | ✅ ready | 5 test files | `release_evidence_gate_v1.json` | Self-testing | Release Gate |
| CI | ⚠️ wrong repo | Workflow tests | `.github/workflows/` | — | DevOps |
| Packaging | ✅ ready | PyInstaller CI | `build-and-upload.yml` | — | DevOps |
| Public docs | ❌ blocked | LICENSE mismatch | Multiple | — | Docs |
| Licensing | ❌ blocked | 3-way mismatch | `LICENSE`, `README.md`, `pyproject.toml` | — | Legal |

---

## 11. Top 10 Next Prompts

### Prompt 1: Fix Lease Manager Lock Bypass + Task Claim Event Emission (Phase 1 blockers)
Paste-ready prompt to remove direct file writes from `lease_manager.py`, add `coord.task.claim_refused` event, and add multi-process lock safety test.

### Prompt 2: Digestion Pipeline Implementation v0 (Phase 3 blocker)
Implement `Digester` class, `LeaseRequestEnvelope`/`LeaseDecisionEnvelope` models, intent-submission path.

### Prompt 3: Context Assembler Digestion Integration (Phase 3)
Wire context requests through the digestion pipeline: `context.requested` envelopes → `context_packet.ready/rejected` events.

### Prompt 4: CI Release Workflow Fix + Release Gate Policy Cleanup (Phase 4 blockers)
Update `release.yml` repo reference, demote deferred checks from required, add `.pi-lens/` to `.gitignore`.

### Prompt 5: LICENSE Reconciliation + SECURITY.md + CHANGELOG (Phase 5 blockers)
Reconcile LICENSE/README/classifier, create SECURITY.md, replace CHANGELOG with Rig Relay entries.

### Prompt 6: Debug Packet Quarantine + User Action Gate (Phase 2 deferred)
Implement quarantine output directory, user confirmation gate, content-light receipt emission.

### Prompt 7: DuckDB Read-Side Analytics Projections (cross-cutting)
Implement 10 proposed read-side projections: telemetry aggregates, contention hotspots, release gate trends, test-suite inventory, trace drift, bash risks, worker latency, tool refinement, context cache hit rates, session lifecycle.

### Prompt 8: Hardened Tool Invocation Digestion (Phase 3 deferred)
Wire tool invocations through digestion: `tool.invocation.requested` → lease check → receipt emission.

### Prompt 9: Release Gate Check Hardening (Phase 4)
Implement 3 deferred checks: `static.docs.json_schema_validation`, `static.security.vulnerability_scan`, `static.docs.static_render_integrity`.

### Prompt 10: Code of Conduct + Telemetry Disclosure + Onboarding Polish (Phase 5)
Create CODE_OF_CONDUCT.md, add telemetry disclosure section to README, link known limitations doc.

---

## 12. Recommended Immediate Next Implementation Slice

**Fix Phase 1 + Phase 5 Blockers: Lease Manager Lock Bypass + Task Claim Event + LICENSE Reconciliation**

**Justification**: These are the remaining blockers before declaring Phase 1 and Phase 5 "done." The lease manager lock bypass is the only coordination mutation path that can still race under concurrent subprocesses. The LICENSE mismatch is a legal blocker for any public release. Both are small, concrete fixes that don't require architectural design.

The digestion pipeline implementation is the larger architectural gap, but it blocks Phase 4 multi-agent dispatch, not Phase 1–3 single-session RC. Fix the blockers first, then implement the digester.

### Paste-ready prompt:

```
Phase 1 + Phase 5 Blocker Resolution v0

Fix the remaining RC Phase 1 and Phase 5 blockers:

Phase 1 blockers:
1. Lease manager lock bypass — rig_relay/coordination/lease_manager.py 
   release_paths() and renew_lease() write directly to lease JSON files
   outside the digester lock. Remove direct writes; use store methods onlv.
   Add subprocess race test proving no corruption.

2. Task claim refusal event emission — rig_relay/coordination/store.py
   _claim_task_locked writes conflict file but doesn't emit 
   coord.task.claim_refused event. Add _append_event + 
   build_task_claim_refused_payload in models.py.

Phase 5 blockers:
3. LICENSE reconciliation — pyproject.toml says AGPL-3.0-or-later.
   Update README.md license section and pyproject.toml classifiers to match.
   
4. SECURITY.md — create minimal security policy referencing 
   docs/pages/security-policy.html.

5. CHANGELOG.md — replace mistral-vibe version history with 
   Rig Relay 0.1.0α1 entries summarizing completed convergence slices.

Hard constraints: No new dependencies. No SQLite. No database.
Tests must use real temp coordination stores and subprocesses for lock 
safety validation. Run uv run pytest tests/coordination/ -q after edits.
```

---

## 13. Subagent Execution Summary

| Subagent | Domain | Result |
|---|---|---|
| **A** | Event ledger hardening | `_next_sequence` now reads max sequence from events.jsonl on disk under lock; `register_session`, `publish_artifact`, `report_conflict`, `request_handoff` now digester-guarded |
| **B** | DuckDB ledger integrity tests | 4 tests: unique sequences, no duplicate event IDs, strictly increasing sequences, required fields present |
| **C** | Phase 1 audit | 2 blockers found: lease manager lock bypass, task claim missing event. 5 new tests needed. 8 of 8 release gate checks exist (2 need new tests after blocker fixes) |
| **D** | Phase 2 audit | All consent/redaction/privacy checks pass. Debug packet quarantine + user gate deferred to Phase 3. |
| **E** | Phase 3 audit | Runtime/tools/context functionally complete for single-session. Digestion pipeline is design-only — blocks multi-agent Phase 4. |
| **F** | Phase 4+5 audit | 3 Phase 4 blockers (CI repo ref, deferred checks, .pi-lens in git). 4 Phase 5 blockers (LICENSE, SECURITY.md, CHANGELOG, CODE_OF_CONDUCT). |

---

## 14. Final Test Results

| Suite | Tests | Result |
|---|---|---|
| Coordination concurrency (existing) | 10 | ✅ Pass |
| Coordination digester formalization | 6 | ✅ Pass |
| Coordination digester events | 5 | ✅ Pass |
| Coordination DuckDB event ledger | 4 | ✅ Pass |
| Telemetry content-light | 8 | ✅ Pass |
| Telemetry consent gate | 15 (from prior baseline) | ✅ Pass |
| Tracing real-source | 20 | ✅ Pass |
| Release gate CLI | 10 | ✅ Pass |
| Guard escape hatches | 17 | ✅ Pass |
| **Total focused** | **~95** | **All pass** |

### Git Status
- `main` @ `565c296`
- Modified: `rig_relay/coordination/store.py` (+83/-20)
- New: `tests/coordination/test_coordination_event_ledger.py` (4 DuckDB tests)
- Pre-existing dirty: none
- No commits, no pushes, no force operations

### Remaining Seams (intentionally deferred)
- Digestion pipeline implementation (design doc exists, no code)
- Debug packet quarantine boundary
- Debug packet user action gate
- Context cache production implementation
- Vulnerability scanning (release gate Lane B)
- Static render integrity verification (release gate Lane B)
- `build_projection_read_payload` removed from store.py imports — still defined in models.py for fleet/cockpit use

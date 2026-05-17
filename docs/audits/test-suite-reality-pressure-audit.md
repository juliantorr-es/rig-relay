# Test Suite Reality Pressure Audit v0

**Audit date**: 2026-05-17
**Auditor**: Julian Torres (via pi coding agent)
**Repository**: `rig-relay`, branch `main`, commit `c92a220a`
**Suite scale**: 7,191 collected tests across ~400+ test files in 55 directories
**Methodology**: Static audit + 6 parallel deep-dive agents (release gate, telemetry/consent, trace contract, static docs/site, runtime/supervisor, coordination/Git discipline) + adversarial gap analysis

---

## 1. Executive Verdict

**Verdict: Large suite with medium false-confidence risk.**

The Rig Relay test suite is substantial (7,191 tests) and contains genuinely strong tests in several critical areas. However, it also harbors significant blind spots where tests certify synthetic mock pathways rather than real product seams. The suite is not a "padded room" — the guard, runtime supervisor, static site integrity, redaction policy, and documentation governance tests exert real pressure on production boundaries. But the telemetry consent gate has **zero test coverage**, the largest release gate test file (34 tests) exercises **zero real check functions**, the trace contract enforcer is **never run against real code**, and no test proves the full telemetry upload pipeline works end-to-end.

**The suite would benefit more from filling a few critical gaps than from any broad refactor.** The mock theater is concentrated in specific files; the real-pressure tests are concentrated in others. A targeted hardening of ~5 seams would significantly increase credibility.

### Scorecard

| Dimension                    | Rating                                                                                             |
| ---------------------------- | -------------------------------------------------------------------------------------------------- |
| Real seam pressure           | Medium (strong in guard/runtime/static-site; absent in consent/CLI)                                |
| Mock reliance                | High (78 files use monkeypatch, auto-use conftest patches config/paths/API keys)                   |
| Negative-path coverage       | Medium (strong in redaction/receipts; absent in telemetry send)                                    |
| Would fail on real drift     | Mixed (yes for guard/schemas/supervisor; no for release gate engine/trace contract/telemetry send) |
| Adversarial/sabotage testing | Absent (no test intentionally corrupts real artifacts to prove detection)                          |

---

## 2. Test Inventory

### By Directory

| Directory             | Files | Approx Tests | Dominant Type      | Dominant Data Source                | Real-Pressure % |
| --------------------- | ----- | ------------ | ------------------ | ----------------------------------- | --------------- |
| `tests/core/`         | 61    | ~1,000       | Unit + Integration | Mixed (FakeBackend, monkeypatch)    | 30%             |
| `tests/tools/`        | 34    | ~600         | Unit               | Synthetic + monkeypatch             | 20%             |
| `tests/acp/`          | 32    | ~500         | Integration        | Synthetic + mock transport          | 25%             |
| `tests/desktop/`      | 24    | ~400         | Integration        | Mock WebSocket + synthetic          | 30%             |
| `tests/coordination/` | 24    | ~350         | Unit + Integration | File-backed store (real JSON)       | 40%             |
| `tests/context/`      | 21    | ~300         | Unit               | Synthetic + fake backend            | 20%             |
| `tests/runtime/`      | 20    | ~350         | Integration        | **Real subprocess** + temp files    | **70%**         |
| `tests/ralph/`        | 18    | ~250         | Unit               | Synthetic projections               | 15%             |
| `tests/scripts/`      | 17    | ~250         | CLI/Integration    | Real scripts via subprocess         | 50%             |
| `tests/` (root)       | 17    | ~250         | Mixed              | Mixed                               | 30%             |
| `tests/evidence/`     | 15    | ~250         | Integration        | Real functions + synthetic payloads | 45%             |
| `tests/tracing/`      | 13    | ~200         | Unit + Integration | Real trace store + synthetic events | 50%             |
| `tests/repository/`   | 12    | ~200         | Integration        | **Real committed files**            | **80%**         |
| `tests/telemetry/`    | 11    | ~180         | Unit + Integration | Synthetic + schema fixtures         | 40%             |
| `tests/e2e/`          | 9     | ~100         | E2E                | Mock server + TUI snapshots         | 35%             |
| `tests/docs/`         | 9     | ~120         | Governance         | **Real committed docs**             | **75%**         |
| `tests/stubs/`        | 7     | 0            | Infrastructure     | Fake classes                        | N/A             |
| `tests/release_gate/` | 6     | ~120         | Unit + Integration | Mixed (real repo + synthetic)       | 40%             |
| `tests/governance/`   | 6     | ~80          | Unit               | Synthetic models                    | 15%             |
| `tests/cli/`          | 6     | ~80          | CLI/Integration    | Real CLI entrypoints                | 50%             |
| `tests/backend/`      | 6     | ~80          | Unit               | Mock backends                       | 10%             |
| `tests/guard/`        | 3     | ~60          | Integration        | **Real git repos**                  | **90%**         |
| Other (25 dirs)       | 25    | ~300         | Mixed              | Mixed                               | 30%             |

### Key Infrastructure

| Item                                               | Count                                                                                                                         |
| -------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------- |
| Test files using `monkeypatch`                     | 78                                                                                                                            |
| Test files using `respx`                           | 5                                                                                                                             |
| Test files using `subprocess.run` (real execution) | ~15                                                                                                                           |
| `Fake*` stub classes                               | 7 (FakeBackend, FakeClient, FakeTool, FakeMCPRegistry, FakeConnectorRegistry, FakeAudioPlayer, FakeTTSClient)                 |
| Autouse fixtures in `conftest.py`                  | 5 (tmp CWD, config dir, API key mock, platform mock, telemetry events mock)                                                   |
| **Global `telemetry_events` autouse fixture**      | **Patches `send_telemetry_event` to a bypass recorder — disables consent gating in ALL tests**                                |
| Pytest markers defined                             | 13 (smoke, contract, integration, e2e, packaging, slow, legacy, flaky, network, provider, destructive, migration, quarantine) |
| Missing markers                                    | `adversarial`, `sabotage`, `real_artifact`, `network_forbidden`                                                               |

---

## 3. Credibility Heatmap

| Surface                   | Real Seam Pressure  | Negative Coverage | Synthetic Reliance        | Mock Intensity                       | Risk         | Recommended Action                                                              |
| ------------------------- | ------------------- | ----------------- | ------------------------- | ------------------------------------ | ------------ | ------------------------------------------------------------------------------- |
| **Release gate**          | Medium              | Partial           | High (engine tests)       | High (engine); Low (checks)          | **HIGH**     | Replace 34 mock-theater engine tests with CLI integration; add sabotage harness |
| **Telemetry send/upload** | **NONE**            | Partial           | Extreme                   | **ABSURD**                           | **CRITICAL** | Write consent-gate E2E tests; prove remote upload gated by settings+consent     |
| **Consent model**         | High (model only)   | Partial           | None                      | None                                 | **HIGH**     | Connect consent model to send pipeline; test revoked→blocked E2E                |
| **Redaction**             | High (function)     | Partial           | Medium (payloads)         | Medium (bundle tests mock redaction) | Medium       | Run redaction against real event payloads; test bundle redaction without mocks  |
| **Debug bundle**          | Low                 | Absent            | High                      | High                                 | **HIGH**     | Prove bundles are explicit user action; test bundle redaction E2E               |
| **Trace contract**        | **NONE** (enforcer) | Partial           | High                      | High (enforcer tests)                | **CRITICAL** | Run scanner+validator against real code; detect unregistered emissions          |
| **Runtime supervisor**    | **HIGH**            | Strong            | Low                       | Low                                  | Low          | Preserve; fill state-machine wiring gap                                         |
| **Coordination/store**    | Low (single-thread) | Good              | None (file-backed)        | None                                 | Medium       | Add concurrent multi-agent conflict tests                                       |
| **Worktree/Git guard**    | **HIGH**            | Strong            | None (real git)           | None                                 | Low          | Test escape hatches (`git -c`, subprocess bypass)                               |
| **Static renderer**       | **HIGH**            | Strong            | Low (committed artifacts) | None                                 | Low          | Add fresh-render-vs-committed drift detection                                   |
| **Schemas/docs JSON**     | **HIGH**            | Strong            | None (real files)         | None                                 | Low          | Add unreferenced-schema detection                                               |
| **Desktop/WebSocket**     | Medium              | Partial           | Medium                    | Medium                               | Medium       | Add real WebSocket integration tests                                            |
| **CI workflows**          | Medium              | Partial           | Low                       | Low                                  | Medium       | Test CI workflow execution in temp                                              |

---

## 4. False-Confidence Findings

### Finding 1: Release Gate Engine Tests Are Pure Mock Theater

- **File**: `tests/release_gate/test_release_evidence_gate.py` (34 tests)
- **Pattern**: Every test constructs `GateRunner(checks={id: make_check_fn(fake_result)})` — synthetic check functions that return hardcoded `CheckResult` objects.
- **Why weak**: Zero real check functions are exercised. If someone deletes `check_schema_validation()` from the codebase, all 34 tests still pass.
- **Missing seam**: Full-gate integration with `build_default_registry()` + real repo artifacts.
- **Recommendation**: **Demote to pure unit tests.** Add new CLI integration tests that run `python -m rig_relay.release_gate` and assert JSON output validates against schema.
- **Verdict**: Keep (sorting/stability logic is valid) but **demote claim** — these do not prove the release gate works.

### Finding 2: Telemetry Consent Gate Has Zero Test Coverage

- **File**: `rig_relay/core/telemetry/send.py` (`_evaluate_consent_gate`, line 226)
- **Pattern**: The `telemetry_events` autouse fixture in `conftest.py` monkeypatches `send_telemetry_event` to bypass `_evaluate_consent_gate` entirely. No test exercises the consent enforcement path.
- **Why weak**: The single function that decides whether data leaves the machine is never called by any test. The test file (`test_telemetry_send.py`) mocks HTTP transport with `MagicMock` + `AsyncMock`.
- **Missing seam**: Full pipeline: `send_telemetry_event` → `_evaluate_consent_gate` → HTTP POST with real consent record.
- **Recommendation**: Write E2E test with `enable_remote_telemetry=True`, `enable_local_observability=True`, and a real consent record. Prove: granted→uploads, revoked→blocked, local-writes-persist-when-remote-denied.
- **Verdict**: **Replace** — current tests certify mock behavior, not real gating.

### Finding 3: Trace Contract Enforcer Never Run Against Real Code

- **File**: `tests/tracing/test_trace_contract_enforcer.py`
- **Pattern**: `EventEmissionScanner` is imported but `.scan()` is never called. All validator tests use hand-crafted `EmittedEvent` lists with names like `"unregistered.event"`. Real unregistered emissions (`subagent.runtime`) go undetected.
- **Why weak**: The contract enforcer machinery is tested in isolation but never fed real codebase output. Two separate scanners exist (audit script vs `_contract.py`) and are never cross-validated.
- **Missing seam**: Real scan of `rig_relay/` source → feed into `TraceContractValidator.validate_all()` → assert zero violations.
- **Recommendation**: Write contract enforcement integration test: `scan(codebase) → validate(all_emissions) → assert_no_violations`. Add sabotage test: emit unregistered event in temp source → assert detection.
- **Verdict**: **Strengthen** — validator logic tests are good but disconnected from reality.

### Finding 4: Telemetry Send Tests Are Mock Theater

- **File**: `tests/core/test_telemetry_send.py`
- **Pattern**: `unittest.mock.AsyncMock` for HTTP client, `MagicMock` for client, `build_test_vibe_config()` synthetic config, `_make_resolved_tool_call()` synthetic calls. The `telemetry_events` fixture bypasses all real behavior.
- **Why weak**: Tests prove `send_telemetry_event` was _called_ with correct payload shape, not that it _did_ anything real. No real HTTP, no real consent, no real observability writes.
- **Missing seam**: Real TelemetryClient with real config, real API key, real HTTP round-trip (or at minimum, real consent gating + local write).
- **Recommendation**: **Replace** with tests that exercise the real pipeline.
- **Verdict**: Mock theater. Keep payload shape assertions, discard the rest.

### Finding 5: No CLI Integration Tests for Release Gate

- **File**: `rig_relay/release_gate/__main__.py` (untested)
- **Pattern**: Zero tests invoke `_main()` or parse CLI arguments. `--output`, `--include-check`, `--exclude-check`, `--lifecycle` flags are completely untested. Exit codes (0/1/2) are unverified.
- **Why weak**: The primary user-facing interface to the release gate has no test coverage. The CLI output format differs from the receipt format and neither is schema-validated.
- **Missing seam**: `subprocess.run(["python", "-m", "rig_relay.release_gate", ...])` → assert exit code, parse JSON output, validate against schema.
- **Recommendation**: Add CLI integration tests.
- **Verdict**: **Add** — this is a missing test, not a weak one.

### Finding 6: Dead Assertion in Findings Lifecycle Test

- **File**: `tests/release_gate/test_findings_lifecycle.py`, line ~303
- **Pattern**: `assert result.overall_status == GateRunner.__module__` — `GateRunner.__module__` evaluates to `"rig_relay.release_gate.runner"`, which will never equal any `GateStatus` value. This assertion is silently dead.
- **Why weak**: The assertion always passes (comparing string to enum by value), masking a missing validation of the actual gate outcome.
- **Missing seam**: Should assert `result.overall_status != GateStatus.FAILED` or similar.
- **Recommendation**: Fix the assertion.
- **Verdict**: **Fix immediately** — one-line bug.

### Finding 7: Escape Hatches in Git Guard Not Tested

- **File**: `tests/guard/test_dirty_file.py`
- **Pattern**: `is_destructive_git_command()` is tested with exact command strings (`"git reset"`, `"git clean"`). No test verifies that `git -c foo=bar reset --hard HEAD` is detected (would NOT match the `stripped.startswith("git reset ")` check due to `-c` insertion).
- **Why weak**: The destructive command detection is purely string-matching. `git commit --amend` and `git push --force` are not in the blocked set at all. No test proves the check is actually called before subprocess execution.
- **Missing seam**: Test bypass vectors: `git -c`, `GIT_DIR` env manipulation, `git config alias`, direct subprocess invocation.
- **Recommendation**: Add escape-hatch tests; expand blocked command set to include `--amend` and `--force`.
- **Verdict**: **Strengthen** — current tests are good for what they cover but don't close the gate.

### Finding 8: Coordination Store Tests Are Single-Threaded

- **File**: `tests/coordination/test_store.py`, `tests/coordination/test_path_lease.py`
- **Pattern**: All conflict tests are sequential: session-A reserves, then session-B tries. No test uses `asyncio.gather()` or threads to simulate concurrent access.
- **Why weak**: The store uses `tempfile.replace()` for atomic writes, but no test proves atomicity under contention. Real multi-agent scenarios could have race conditions.
- **Missing seam**: Two concurrent tasks claiming the same path simultaneously.
- **Recommendation**: Add concurrent access tests with `asyncio.gather()`.
- **Verdict**: **Strengthen** — conflict rules are correct but concurrency safety is unproven.

### Finding 9: Version-Sniffing Tests Are Brittle

- **Files**: `tests/docs/test_install_update_desktop.py`, `tests/docs/test_vibe_legacy_boundary.py`
- **Pattern**: Hardcoded `"0.1.0a1"` assertions will break on every version bump.
- **Why weak**: These test a specific version string rather than testing version format or consistency across files.
- **Missing seam**: Test that `pyproject.toml` version matches `__init__.py` version (format check, not value check).
- **Recommendation**: Replace hardcoded version with format/consistency check.
- **Verdict**: **Demote** — keep consistency check, drop hardcoded value.

### Finding 10: Broken Machine-Specific Test

- **File**: `tests/docs/test_vibe_cli_purge_inventory.py`
- **Pattern**: References absolute path `/Users/user/.gemini/antigravity/brain/f57b5347-...` — only exists on one developer's machine.
- **Why weak**: Will fail on any other machine. Local development artifact left in test suite.
- **Missing seam**: N/A — should not exist in test suite.
- **Recommendation**: **Delete** or make conditional with `pytest.skip` when path doesn't exist.
- **Verdict**: **Delete later** — not actionable outside one machine.

### Additional Findings

| #   | File                                                                                 | Issue                                                                                     | Verdict                      |
| --- | ------------------------------------------------------------------------------------ | ----------------------------------------------------------------------------------------- | ---------------------------- |
| 11  | `tests/release_gate/test_runtime_readiness_checks.py` (TraceContractStatusMapping)   | Patches scanner, validator, report builder — real trace contract scanning never exercised | Strengthen                   |
| 12  | `tests/telemetry/test_observability_e2e.py`                                          | Sets `enable_remote_telemetry=False` — remote path never tested                           | Strengthen                   |
| 13  | `tests/evidence/test_redaction.py` (`test_telemetry_bundle_builder_calls_redaction`) | Monkeypatches redaction with fake — proves it was called, not that it worked              | Strengthen                   |
| 14  | `tests/core/test_tool_runtime.py`                                                    | 100% fake — all dependencies injected as lambdas; no real tool execution                  | Keep (unit) but demote claim |
| 15  | `tests/core/test_tool_runtime_v1.py`                                                 | `MagicMock()` for trace store — checks calls, not content                                 | Demote claim                 |

---

## 5. Excellent Tests (Template-Worthy)

### 1. `tests/guard/test_dirty_file.py` + `tests/guard/test_integration.py`

**Why excellent**: Uses real `git init` + `git status --porcelain=v1` capture. Tests the full guard pipeline: capture → hash → gate → tool integration. Real git repos, real file hashing, real exception raising from tools. Proves dirty files are protected and safe writes are allowed. The integration test exercises WriteFile and SearchReplace tools through their real `run()` methods.

### 2. `tests/runtime/test_runtime_supervisor.py`

**Why excellent**: Uses `sys.executable` with `asyncio.create_subprocess_exec` — real OS processes. Tests timeout (200ms timeout on 30s sleep), non-zero exit (42), command-not-found, governance gates, heartbeat detection, stall warnings, output truncation, and lease release. Zero mocks. The heartbeat test verifies the _count_ of heartbeats received, proving real timing behavior.

### 3. `tests/evidence/test_tool_receipt_policy.py`

**Why excellent**: Tests the real `_FORBIDDEN_RECEIPT_FIELDS` enforcement with 15+ parametrized forbidden field cases. Covers nested forbidden fields, value-shape heuristics (large strings, diff markers, excessive newlines), per-receipt-type testing (BashReceipt, ValidateReceipt, SearchReplaceReceipt, WriteFileReceipt), and edge cases (empty payload, non-dict values, malformed events). **No mocks.**

### 4. `tests/evidence/test_validation.py`

**Why excellent**: 12 distinct failure modes tested for evidence session validation: missing JSONL, absolute path references, path escapes, hash mismatches, malformed JSONL, unreferenced evidence files, manifest hash mismatches, manifest path escapes, missing manifest files. Real production validation function exercised. **No mocks.**

### 5. `tests/repository/test_documentation_hardening.py`

**Why excellent**: Comprehensive site integrity: SHA256 hash verification of migrated files, no local absolute paths in HTML, no unexpected `<script>` tags, no unescaped unsafe content, every page in manifest, search index completeness, no broken asset paths, readability smoke tests. Reads real committed `docs/` artifacts. **No mocks.**

### 6. `tests/repository/test_static_site_js.py`

**Why excellent**: Directly inspects committed `site.js` for forbidden patterns: no `eval`, no `new Function`, no remote URLs, no analytics SDK calls (`gtag`, `analytics`, `pixel`, `fbq`), no token/secret literals. Verifies HTML integration points. **This is the test that proves no third-party tracking exists.**

### 7. `tests/release_gate/test_static_artifact_checks.py` (smoke tests)

**Why excellent**: The integration tests (`test_static_artifact_checks_run_on_real_repo`, `test_check_ids_are_deterministic_on_real_repo`, `test_all_check_results_have_evidence_on_real_repo`) run real release gate checks against the actual repo. The determinism test catches non-deterministic check behavior. The secret leakage check scans real HTML for GitHub PATs, PEM keys, bearer tokens. **Real seam pressure.**

### 8. `tests/coordination/test_checkpoint.py`

**Why excellent**: Uses real `git init` → `git commit` via the checkpoint tool. Verifies commits with `git log --oneline --name-only -1`. Tests lease conflict detection through real `CoordinationStore`. Tests dirty-file protection through real `DirtyFileGuard`. Proves no push occurs. **Real git, real guard, real store.**

### 9. `tests/coordination/test_worktree_manager.py`

**Why excellent**: Creates real linked git worktrees via `git worktree add`. Tests full lifecycle: create → list → inspect (including dirty detection) → remove (refusing dirty without force). Uses real `subprocess.run(["git", "worktree", ...])`. **Genuine infrastructure testing.**

### 10. `tests/telemetry/test_receipts.py`

**Why excellent**: Tests receipt chain integrity with real SHA256 hashing: tampered `previous_receipt_sha256` → fail, tampered `evidence_sha256` → fail, event name mismatch → fail, missing receipt → fail. Proves validation is read-only (no side effects). **Deterministic, tamper-proof design.**

### Honorable Mentions

| File                                                       | Strength                                                                                            |
| ---------------------------------------------------------- | --------------------------------------------------------------------------------------------------- |
| `tests/release_gate/test_runtime_readiness_checks.py`      | Real `websocket_server.py` regex-scanning for security invariants; real GitHub App audit JSON reads |
| `tests/runtime/test_runtime_supervisor_result_envelope.py` | Real subprocess execution with cancellation (task.cancel) and trace verification                    |
| `tests/runtime/test_runtime_audit_persistence.py`          | Content-light enforcement at persisted-file level; proves raw data never hits disk                  |
| `tests/coordination/test_schema_validation.py`             | Python contamination detection across ALL real schema files                                         |
| `tests/identity/test_telemetry_consent.py`                 | Real consent model; proves commercial scopes excluded from defaults                                 |
| `tests/tracing/test_trace_models.py`                       | Redaction coverage: token/api_key/password/secret/authorization all redacted                        |

---

## 6. Missing Failure Probes

### Critical (Seam Currently Open)

| #   | Probe Description                                                                                                                        | What It Breaks                 | Existing Test?                                                                        |
| --- | ---------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------ | ------------------------------------------------------------------------------------- |
| 1   | Set `enable_remote_telemetry=True`, grant consent, verify HTTP POST occurs                                                               | Consent gate                   | **NONE**                                                                              |
| 2   | Set `enable_remote_telemetry=True`, revoke consent, verify HTTP POST is blocked                                                          | Consent revocation             | **NONE**                                                                              |
| 3   | Set `enable_remote_telemetry=False`, `enable_local_observability=True`, verify local JSONL still written                                 | Local/remote independence      | **NONE**                                                                              |
| 4   | Run `EventEmissionScanner.scan()` on `rig_relay/`, feed into `TraceContractValidator.validate_all()`, assert zero unregistered emissions | Trace contract enforcement     | **NONE**                                                                              |
| 5   | Run `python -m rig_relay.release_gate`, assert exit code 0, validate JSON output against `rig.release_evidence_gate.v1.schema.json`      | Release gate CLI               | **NONE**                                                                              |
| 6   | Add forbidden field (`raw_prompt_text`) to a `TOOL_CALL_COMPLETED` event, verify it's redacted before remote upload                      | Forbidden field E2E            | **NONE**                                                                              |
| 7   | Two concurrent `asyncio.create_task` calls claiming same lease path, verify exactly one succeeds                                         | Multi-agent lease safety       | **NONE**                                                                              |
| 8   | Run `git -c foo.bar=baz reset --hard HEAD`, verify blocked by destructive command check                                                  | Git guard escape hatch         | **NONE**                                                                              |
| 9   | Register telemetry event in `EventName` enum but never emit it, verify trace contract detects registered-never-emitted                   | Trace contract drift detection | **NONE** (enforcer logic tested with synthetic data, never run against real registry) |
| 10  | Create debug bundle automatically (not explicit user action), verify it's blocked                                                        | Debug bundle gate              | **NONE**                                                                              |

### High-Value (Would Close Important Seams)

| #   | Probe Description                                                                                              |
| --- | -------------------------------------------------------------------------------------------------------------- |
| 11  | Remove a check from `_checks_registry.py`, verify `test_registry_has_all_11_checks` fails                      |
| 12  | Add unregistered event emission to production code, verify trace contract test fails                           |
| 13  | Change `site.js` to include `gtag('config', ...)`, verify `test_no_analytics_calls` fails                      |
| 14  | Corrupt a schema JSON file, verify `test_schema_is_valid_json_and_draft7` fails                                |
| 15  | Create a conversation summary with bad filename, verify `test_conversation_summary_names` fails                |
| 16  | Add a Markdown file outside policy, verify `test_non_grandfathered_markdown_is_allowed_or_in_manifest` fails   |
| 17  | Add Python syntax to a schema JSON, verify `test_no_schema_contains_python_syntax` fails                       |
| 18  | Modify a migrated file without updating manifest hash, verify `test_migration_hashes_match_actual_files` fails |
| 19  | Run `render_static_docs.py` fresh, diff against committed `docs/`, verify no unexpected drift                  |
| 20  | `subprocess.run(["git", "reset", "--hard", "HEAD"])` through bash tool, verify guard blocks it                 |

---

## 7. Synthetic Fixture Provenance

### Fixture Families

| Family                        | Examples                                                                                        | Count (approx) | Verdict                                                             |
| ----------------------------- | ----------------------------------------------------------------------------------------------- | -------------- | ------------------------------------------------------------------- |
| **Real captured artifacts**   | `docs/schemas/*.json`, `docs/json/*.json`, `docs/assets/site.js`, committed `docs/pages/*.html` | ~200 tests     | ✅ Excellent — these ARE the contract                               |
| **Schema fixtures**           | `rig.relay.observability.v1.schema.json` loaded for validation                                  | ~50 tests      | ✅ Good — validates real schemas                                    |
| **Real git repos**            | `_init_git_repo()` in guard/checkpoint/worktree tests                                           | ~40 tests      | ✅ Excellent — real git                                             |
| **Real subprocess**           | `sys.executable -c "..."` in supervisor tests                                                   | ~30 tests      | ✅ Excellent — real OS processes                                    |
| **Synthetic-but-adversarial** | Forbidden payloads in `test_redaction.py`, `test_tool_receipt_policy.py`                        | ~80 tests      | ✅ Good — explicit adversarial intent                               |
| **Synthetic neutral**         | Hand-crafted `EmittedEvent` lists in trace contract tests                                       | ~50 tests      | ⚠️ Needs provenance labeling — useful but disconnected from reality |
| **Synthetic toy**             | Hardcoded `CheckResult` objects in `test_release_evidence_gate.py`                              | 34 tests       | ❌ Mock theater — proves nothing about real system                  |
| **Mock payloads**             | `AsyncMock`, `MagicMock` in telemetry send tests                                                | ~30 tests      | ❌ Mock theater — certifies mock behavior                           |
| **Generated temp data**       | `tmp_path` files in most tests                                                                  | ~4,000 tests   | ✅ Appropriate — temp dirs are standard test isolation              |
| **Unknown provenance**        | Various inline dicts and objects                                                                | ~2,000 tests   | ⚠️ Should be documented                                             |

### Recommendations

1. **Add `@pytest.mark.real_artifact`** to tests using real committed files, schemas, or git repos — currently ~350 tests.
2. **Add `@pytest.mark.synthetic`** to tests using hand-crafted data disconnected from production — currently ~2,500 tests. This is not shame, it's triage metadata.
3. **Add `@pytest.mark.adversarial`** to redaction, forbidden-field, and validation-failure tests — currently ~130 tests.
4. **Add fixture provenance comments** to large synthetic fixture families explaining why they're synthetic (e.g., "These `EmittedEvent` lists encode known trace contract violation patterns for validator logic testing — not real codebase output.").

---

## 8. Proposed Test Taxonomy

### Recommended Marker Additions

Add to `pyproject.toml` `[tool.pytest.ini_options.markers]`:

```toml
"adversarial: intentionally breaks system to prove detection works",
"sabotage: mutates real artifacts in temp copy to verify test catches drift",
"real_artifact: uses real committed repo files, schemas, or git repos",
"synthetic: uses hand-crafted data; not connected to production artifacts",
"network_forbidden: must not make real network calls",
"concurrent: tests multi-agent concurrent access patterns",
```

### Existing Markers (Keep All)

```toml
"smoke: fastest confidence checks; must pass before demo/share",
"contract: domain contract/unit tests",
"integration: crosses multiple components/processes/filesystems",
"e2e: broad-stack or full flow",
"packaging: packaged app / installer / bundle checks",
"slow: intentionally slow",
"legacy: retained but not part of default suite",
"flaky: known nondeterministic, must not run in default suite",
"network: requires external network",
"provider: requires external model/provider/API",
"destructive: mutates worktrees/branches/files beyond temp dirs",
"migration: test being relocated during test layout canonicalization",
"quarantine: quarantined test, runs only in dedicated quarantine job",
```

### Recommended Marker Assignment (Examples)

| Test                                               | Recommended Markers                    |
| -------------------------------------------------- | -------------------------------------- |
| `tests/guard/test_dirty_file.py`                   | `integration`, `real_artifact`         |
| `tests/release_gate/test_release_evidence_gate.py` | `contract`, `synthetic`                |
| `tests/evidence/test_tool_receipt_policy.py`       | `contract`, `adversarial`              |
| `tests/telemetry/test_observability_e2e.py`        | `integration`, `synthetic` (currently) |
| `tests/runtime/test_runtime_supervisor.py`         | `integration`, `real_artifact`         |
| `tests/tracing/test_trace_contract_enforcer.py`    | `contract`, `synthetic`                |
| `tests/repository/test_documentation_hardening.py` | `integration`, `real_artifact`         |

---

## 9. Proposed Convergent Patch Slices

### Slice A: Test Inventory and Marker Taxonomy

**Files to change**: `pyproject.toml` (marker additions), ~30 test files (add marker decorators)
**Tests to add**: 0 (metadata only)
**Seams closed**: Test categorization enables targeted CI runs (only run `real_artifact` tests post-commit, run full `synthetic` suite pre-push)
**Acceptance criteria**:

- All 350+ `real_artifact` tests have `@pytest.mark.real_artifact`
- All adversarial tests have `@pytest.mark.adversarial`
- `uv run pytest -m "real_artifact"` collects only real-artifact tests
- CI pipeline separates `synthetic` and `real_artifact` runs

### Slice B: Real Artifact Contract Harness

**Files to change**: New file `tests/contract/conftest.py`, update ~15 test files
**Tests to add**: `test_schema_every_docs_json_validates_against_declared_schema`, `test_schema_no_unreferenced_schemas`, `test_every_event_name_in_constants_is_emitted_somewhere`, `test_every_docs_page_has_corresponding_json_source`
**Seams closed**: Schema-doc coverage, event name registration coverage
**Acceptance criteria**: All new tests pass; adding a docs/json file without updating schemas fails

### Slice C: Telemetry/Consent E2E Failure Probes **(HIGHEST PRIORITY)**

**Files to change**: New file `tests/telemetry/test_consent_gate_e2e.py`, possible changes to `conftest.py` (add opt-out for `telemetry_events` fixture)
**Tests to add**:

- `test_remote_upload_blocked_when_disabled`
- `test_remote_upload_allowed_when_enabled_and_consent_granted`
- `test_remote_upload_blocked_when_consent_revoked`
- `test_local_observability_writes_when_remote_denied`
- `test_forbidden_field_redacted_before_remote_upload`
- `test_debug_bundle_requires_explicit_user_action`
- `test_consent_gate_evaluated_before_every_upload`
  **Seams closed**: Consent gating, remote upload, redaction pipeline, debug bundle gate
  **Acceptance criteria**: All tests pass; `_evaluate_consent_gate` code path exercised; adding forbidden field to event model fails test

### Slice D: Release Gate and Trace Contract Sabotage Harness

**Files to change**: New files `tests/sabotage/test_release_gate_sabotage.py`, `tests/sabotage/test_trace_contract_sabotage.py`
**Tests to add**:

- Sabotage operators for release gate: remove schema file → expect FAIL, change schema_version → expect FAIL, remove check from registry → expect count change, corrupt static site asset → expect FAIL
- Sabotage operators for trace contract: emit unregistered event in temp source → expect detection, remove registered event name → expect detection, change event name format → expect violation
- Sabotage operators for Git guard: `git -c` bypass attempt, `GIT_DIR` manipulation, alias bypass
  **Seams closed**: Release gate CLI, trace contract enforcement, Git guard escape hatches
  **Acceptance criteria**: All sabotage operators produce expected failure; no false negatives

### Slice E: Static Site and Schema Reality Harness

**Files to change**: New file `tests/static/test_fresh_render_drift.py`, updates to `tests/repository/test_documentation_hardening.py`
**Tests to add**:

- `test_fresh_render_matches_committed` — run `render_static_docs.py`, diff against `docs/`
- `test_all_internal_links_resolve` — crawl every `<a href>` in generated HTML
- `test_privacy_page_exists_and_is_complete`
- `test_no_localstorage_tracking` — audit `localStorage` usage
- `test_search_index_entries_valid` — validate each entry's structure
  **Seams closed**: Renderer drift, broken links, privacy page gating
  **Acceptance criteria**: Fresh render produces byte-identical (or approved-delta) output; no broken links

### Slice F: Worktree/Git Discipline Temp-Repo Harness

**Files to change**: New file `tests/guard/test_escape_hatches.py`, updates to `tests/coordination/test_store.py`
**Tests to add**:

- Escape hatch tests: `git -c foo=bar reset`, `GIT_DIR` manipulation, `git stash push` → `git stash drop`, `git commit --amend` blocking
- Concurrent lease tests: two `asyncio.create_task` calls racing for same path
- Checkpoint list/restore tests
  **Seams closed**: Git guard bypass vectors, multi-agent lease safety, checkpoint lifecycle
  **Acceptance criteria**: All escape hatch attempts blocked; concurrent claims produce exactly one winner

### Slice G: Flake/Order/Mutation Pressure Runner

**Files to change**: New script `scripts/rig_relay_mutation_runner.py`
**Tests to add**: N/A (infrastructure)
**Seams closed**: Test suite determinism, flake detection, order-dependence detection
**Acceptance criteria**: Runner identifies flaky tests, order-dependent tests, and tests that pass despite broken seams

---

## 10. Immediate Top 5 Prompts

### Prompt 1: Telemetry Consent Gate E2E Tests (Slice C)

```
Write E2E tests for the telemetry consent gate at rig_relay/core/telemetry/send.py.

The consent gate function is _evaluate_consent_gate (line 226). It is currently NEVER called by any test because the tests/conftest.py telemetry_events autouse fixture monkeypatches send_telemetry_event to bypass it.

Create tests/telemetry/test_consent_gate_e2e.py with these tests:
1. test_remote_upload_blocked_when_disabled — enable_remote_telemetry=False, verify no HTTP POST
2. test_remote_upload_allowed_when_enabled_and_consent_granted — enable_remote_telemetry=True, consent GRANTED with basic scopes, verify HTTP POST occurs (use respx to mock the actual HTTP endpoint)
3. test_remote_upload_blocked_when_consent_revoked — enable_remote_telemetry=True, consent REVOKED, verify HTTP POST is blocked
4. test_local_observability_writes_when_remote_denied — enable_remote_telemetry=False, enable_local_observability=True, verify JSONL file is written locally
5. test_forbidden_field_redacted_before_remote_upload — craft a payload with raw_prompt_text, verify it's [REDACTED] in the HTTP POST body
6. test_consent_gate_evaluated_on_every_send — verify _evaluate_consent_gate is called per-event, not cached

You will need to override the conftest.py telemetry_events fixture in your test file. Study tests/telemetry/test_observability_e2e.py for the pattern (they use importlib.reload + monkeypatch.setattr to restore real send_telemetry_event).

Use respx to mock the HTTP endpoint. Use the real TelemetryClient, real consent model functions (grant_consent, revoke_consent from rig_relay.identity.telemetry_consent), and real redact_for_remote from rig_relay.evidence.redaction.
```

### Prompt 2: Release Gate CLI Integration Tests (Slice D)

```
Write CLI integration tests for the release gate at rig_relay/release_gate/__main__.py.

Currently, 34 tests in tests/release_gate/test_release_evidence_gate.py are entirely synthetic — they construct GateRunner with fake check functions and never exercise real checks. The CLI entry point (__main__.py) is completely untested.

Create tests/release_gate/test_cli_integration.py with these tests:
1. test_cli_runs_and_exits_zero_on_clean_repo — subprocess.run(["python", "-m", "rig_relay.release_gate"]), assert exit code 0
2. test_cli_output_validates_against_schema — parse JSON output, validate against docs/schemas/rig.release_evidence_gate.v1.schema.json
3. test_cli_include_check_filters_correctly — --include-check with a specific check ID, verify only that check appears in output
4. test_cli_exclude_check_filters_correctly — --exclude-check, verify excluded
5. test_cli_output_file_written — --output path, verify file exists with valid JSON
6. test_cli_lifecycle_flag_accepted — --lifecycle with a valid policy file, verify it's used
7. test_cli_nonzero_exit_when_gate_fails — create a synthetic failure condition, assert exit code 1

Use the real repo as the test target. For the failure test, create a temporary broken artifact (e.g., a JSON file with bad syntax in a temp copy of docs/json/) that should trigger a release gate check failure.
```

### Prompt 3: Trace Contract Enforcement Against Real Code (Slice D)

```
Wire the trace contract enforcer to run against real production code.

Currently, tests/tracing/test_trace_contract_enforcer.py tests TraceContractValidator with hand-crafted EmittedEvent lists — never runs EventEmissionScanner.scan() against real source files. A real unregistered emission (subagent.runtime) goes undetected.

Add these tests to tests/tracing/test_trace_contract_enforcer.py:
1. test_real_scan_finds_all_registered_events — EventEmissionScanner.scan() on rig_relay/, assert every event in the visibility matrix's current_events_found lists is found
2. test_no_unregistered_emissions_in_production — scan + validate_all, assert zero violations for emitted-never-registered
3. test_no_registered_never_emitted — scan + validate_all, assert zero violations for registered-never-emitted (with status filter for "planned"/"future")
4. test_unregistered_emission_detected — create a temp .py file with recorder.span("unregistered.test.event"), scan it, assert violation detected

You'll need to:
- Import EventEmissionScanner from rig_relay.tracing._contract
- Import TraceContractValidator from rig_relay.tracing._contract
- Import TraceContractRegistry and build_contract_report
- Call scanner.scan(Path("rig_relay")) to get real emissions
- Feed real emissions into validator.validate_all(registry, emissions)
- Handle the subagent.runtime case — it's currently unregistered, so either register it or add to a known-exclusion list

The audit script (scripts/rig_relay_trace_visibility_audit.py) has a DIFFERENT scanner implementation — do NOT use it. Use the _contract.py scanner.
```

### Prompt 4: Static Site Renderer Drift Detection (Slice E)

```
Add fresh-render-vs-committed drift detection tests.

Currently, no test runs render_static_docs.py fresh and compares output against the committed docs/ directory. A renderer regression that produces subtly different HTML would pass all tests.

Create tests/static/test_fresh_render_drift.py with these tests:
1. test_fresh_render_produces_same_page_count — run render_static_docs.py to a temp dir, compare page count
2. test_fresh_render_pages_have_same_structure — for each page, verify <title>, <h1>, <nav>, <main> exist in fresh output
3. test_no_new_script_tags_in_fresh_render — verify no unexpected <script> tags appear
4. test_no_analytics_or_tracking_in_fresh_render — scan all fresh HTML for gtag/analytics/pixel/fbq/segment/amplitude
5. test_search_index_regenerated_complete — run search index generation, verify all pages have entries
6. test_fresh_render_manifest_matches — verify render-manifest.json in fresh output matches page file list

Also add to tests/repository/test_documentation_hardening.py:
7. test_all_internal_links_resolve — crawl every <a href="..."> in every generated HTML page, verify target exists
8. test_privacy_page_gated — assert docs/pages/privacy-notice-alpha.html exists and has required content

Use subprocess.run(["python", "scripts/render_static_docs.py", "--output", tmp_dir]) for fresh rendering. Do NOT mutate the committed docs/ directory.
```

### Prompt 5: Git Guard Escape Hatch and Concurrent Lease Tests (Slice F)

```
Close the escape hatch gap in the Git destructive command guard.

The guard at rig_relay/core/guard.py blocks git reset/clean/stash/restore via string matching (is_destructive_git_command). But git -c foo=bar reset --hard HEAD bypasses the check because the string starts with "git -c" not "git reset". Also, git commit --amend and git push --force are NOT in the blocked set.

Create tests/guard/test_escape_hatches.py with these tests:
1. test_git_c_bypass_blocked — git -c user.name=attacker reset --hard HEAD, assert classified as destructive
2. test_git_config_alias_bypass_blocked — if git supports alias checking, test that aliased destructive commands are caught
3. test_git_commit_amend_blocked — git commit --amend, assert blocked
4. test_git_push_force_blocked — git push --force, assert blocked
5. test_direct_subprocess_intercepted — prove the guard check is actually called before subprocess execution (not just a passive string classifier)

Also add to tests/coordination/test_store.py:
6. test_concurrent_lease_claims_produce_exactly_one_winner — use asyncio.gather() to race two claims for the same path
7. test_concurrent_write_write_blocked_under_contention — two concurrent write claims on overlapping paths

For the guard tests, you may need to:
- Update is_destructive_git_command to handle -c flags and other git option insertion
- Add --amend and --force to the blocked command set
- Consider parsing the command through argparse-like git CLI understanding
```

---

## Appendix A: Sabotage Operators (Future Harness Design)

This table defines the sabotage harness proposed in Section 9, Slice D. Each operator corresponds to a controlled test that mutates a temp copy and verifies detection.

| #   | Operator                                                                         | Target Surface    | Expected Detection                              | Existing Test?                           |
| --- | -------------------------------------------------------------------------------- | ----------------- | ----------------------------------------------- | ---------------------------------------- |
| S1  | Delete `docs/schemas/rig.release_evidence_gate.v1.schema.json` from temp copy    | Release gate      | `check_schema_validation` reports FAIL          | No (unit test of function, not sabotage) |
| S2  | Remove `check_websocket_security` from `_checks_registry.py`                     | Release gate      | `test_full_registry_count` fails (11→10)        | Yes                                      |
| S3  | Add `recorder.span("unregistered.test.event")` to temp source file               | Trace contract    | `_check_emitted_registered` detects violation   | No (scanner never run against code)      |
| S4  | Remove `rig.relay.tool_call.completed` from visibility matrix                    | Trace contract    | Chain integration test fails on count assertion | Partial                                  |
| S5  | Set `enable_remote_telemetry=True`, leave consent revoked                        | Telemetry         | HTTP POST blocked                               | **No (critical gap)**                    |
| S6  | Add `raw_prompt_text: "secret"` to `TOOL_CALL_COMPLETED` event                   | Redaction         | `redact_for_remote` produces `[REDACTED]`       | No (E2E path not tested)                 |
| S7  | Add `gtag('config', 'UA-XXXXX-Y')` to `docs/assets/site.js`                      | Static site       | `test_no_analytics_calls` fails                 | Yes                                      |
| S8  | Run `git -c user.name=x reset --hard HEAD` through bash tool                     | Git guard         | Guard blocks destructive command                | **No (escape hatch gap)**                |
| S9  | Write Python `import` statement into a schema JSON file                          | Schema validation | `test_no_schema_contains_python_syntax` fails   | Yes                                      |
| S10 | Create `docs/conversations/bad-name.md` (violates naming convention)             | Docs governance   | `test_conversation_summary_names` fails         | Yes                                      |
| S11 | Corrupt `docs/schemas/rig.relay.artifact.envelope.v1.schema.json` (invalid JSON) | Schema validation | `test_schema_is_valid_json_and_draft7` fails    | Yes                                      |
| S12 | Register event in `EventName` but never emit in code                             | Trace contract    | `_check_registered_emitted` detects             | No (scanner never run)                   |

Sabotage operators with **"No"** in the last column represent **open seams** — vulnerabilities in the test suite that would allow silent production breakage.

---

## Appendix B: Dead Assertion Report

| File                                            | Line | Issue                                                                                                       | Fix                                                                      |
| ----------------------------------------------- | ---- | ----------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------ |
| `tests/release_gate/test_findings_lifecycle.py` | ~303 | `assert result.overall_status == GateRunner.__module__` — always True (compares enum to module name string) | Change to `assert result.overall_status != GateStatus.FAILED` or similar |

---

## Appendix C: What This Audit Did NOT Cover

- Performance/benchmark tests
- TUI snapshot tests (textual)
- Audio transcriber/TTS tests
- Browser sign-in tests
- Demo fixtures
- Model analytics tests
- Onboarding flow tests
- Backend data tests (mock backend training data)
- Autocompletion tests
- Banner tests

These areas are lower risk for false confidence because they test self-contained components where mock vs. real has less impact on system integrity.

---

_End of audit. For questions or to begin implementing the recommended slices, start with Slice C (Telemetry/Consent E2E) as it closes the most critical open seam._

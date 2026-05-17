from __future__ import annotations

import json
from pathlib import Path
import textwrap
from unittest.mock import patch

from rig_relay.release_gate._runtime_readiness import (
    check_ci_coverage,
    check_github_app_audit,
    check_trace_contract,
    check_websocket_security,
    load_triage_policy,
)
from rig_relay.release_gate.models import (
    CheckResult,
    CheckSeverity,
    CheckStatus,
    TriageEntry,
    TriagePolicy,
)


class TestTraceContractStatusMapping:
    def test_unregistered_events_map_to_fail_blocker(self, tmp_path: Path) -> None:
        from rig_relay.tracing._contract import (
            ContractViolation,
            EmittedEvent,
            TraceContractRegistry,
        )

        registry = TraceContractRegistry.__new__(TraceContractRegistry)
        registry._vocab_path = None
        registry._matrix_path = None
        registry._events = {}
        registry._correlation_fields = {
            "handshake_id": {
                "owner_component": "test",
                "required_optional": "optional",
                "safe_to_log": "safe",
                "propagation_rules": "id only",
            }
        }
        registry._paths = {}
        registry._loaded = True

        def fake_scan() -> list[EmittedEvent]:
            return [
                EmittedEvent(
                    event_name="unregistered.event",
                    source_file="src/module.py",
                    line=10,
                )
            ]

        def fake_validate(_emitted: list[EmittedEvent]) -> list[ContractViolation]:
            return [
                ContractViolation(
                    violation_id="TC-0001",
                    kind="unregistered_event",
                    severity="high",
                    event_name="unregistered.event",
                    source_file="src/module.py",
                    line=10,
                    description="Not in registry",
                    recommendation="Register it",
                )
            ]

        def fake_report(*_args, **_kwargs):
            return {
                "summary": {
                    "total_emitted": 1,
                    "total_registered": 0,
                    "total_violations": 1,
                    "clean": False,
                }
            }

        with (
            patch("rig_relay.tracing._contract.EventEmissionScanner") as mock_scanner,
            patch(
                "rig_relay.tracing._contract.TraceContractValidator"
            ) as mock_validator,
            patch(
                "rig_relay.tracing._contract.build_contract_report",
                side_effect=fake_report,
            ),
        ):
            mock_scanner.return_value.scan = fake_scan
            mock_validator.return_value.validate_all = fake_validate

            result = check_trace_contract()

        assert result.status == CheckStatus.FAIL
        assert result.severity == CheckSeverity.BLOCKER
        violation_findings = [
            f for f in result.findings if f.finding_id.startswith("trace.violation.")
        ]
        assert len(violation_findings) == 1
        assert violation_findings[0].severity == CheckSeverity.BLOCKER

    def test_medium_violations_map_to_warn(self, tmp_path: Path) -> None:
        from rig_relay.tracing._contract import ContractViolation, EmittedEvent

        def fake_scan() -> list[EmittedEvent]:
            return [
                EmittedEvent(event_name="registered.event", source_file="src/module.py")
            ]

        def fake_validate(_emitted: list[EmittedEvent]) -> list[ContractViolation]:
            return [
                ContractViolation(
                    violation_id="TC-0001",
                    kind="registered_never_emitted",
                    severity="medium",
                    event_name="some.event",
                    source_file="src/module.py",
                    description="Never emitted",
                    recommendation="Emit or deprecate",
                )
            ]

        def fake_report(*_args, **_kwargs):
            return {
                "summary": {
                    "total_emitted": 1,
                    "total_registered": 2,
                    "total_violations": 1,
                    "clean": False,
                }
            }

        with (
            patch("rig_relay.tracing._contract.EventEmissionScanner") as mock_scanner,
            patch(
                "rig_relay.tracing._contract.TraceContractValidator"
            ) as mock_validator,
            patch(
                "rig_relay.tracing._contract.build_contract_report",
                side_effect=fake_report,
            ),
        ):
            mock_scanner.return_value.scan = fake_scan
            mock_validator.return_value.validate_all = fake_validate

            result = check_trace_contract()

        assert result.status == CheckStatus.WARN
        assert any(f.finding_id.startswith("trace.violation.") for f in result.findings)

    def test_naming_drift_reported_as_low_finding(self, tmp_path: Path) -> None:
        from rig_relay.tracing._contract import ContractViolation, EmittedEvent

        def fake_scan() -> list[EmittedEvent]:
            return [
                EmittedEvent(event_name="registered.event", source_file="src/module.py")
            ]

        def fake_validate(_emitted: list[EmittedEvent]) -> list[ContractViolation]:
            return [
                ContractViolation(
                    violation_id="TC-0001",
                    kind="naming_inconsistency",
                    severity="low",
                    event_name="some_event",
                    source_file="src/module.py",
                    description="Dot-vs-underscore drift",
                    recommendation="Standardize",
                )
            ]

        def fake_report(*_args, **_kwargs):
            return {
                "summary": {
                    "total_emitted": 1,
                    "total_registered": 1,
                    "total_violations": 1,
                    "clean": False,
                }
            }

        with (
            patch("rig_relay.tracing._contract.EventEmissionScanner") as mock_scanner,
            patch(
                "rig_relay.tracing._contract.TraceContractValidator"
            ) as mock_validator,
            patch(
                "rig_relay.tracing._contract.build_contract_report",
                side_effect=fake_report,
            ),
        ):
            mock_scanner.return_value.scan = fake_scan
            mock_validator.return_value.validate_all = fake_validate

            result = check_trace_contract()

        drift = [
            f
            for f in result.findings
            if f.finding_id == "trace.naming.dot_underscore_drift"
        ]
        assert len(drift) == 1
        assert drift[0].severity == CheckSeverity.LOW

    def test_triaged_high_violations_excluded(self, tmp_path: Path) -> None:
        from rig_relay.tracing._contract import ContractViolation, EmittedEvent

        triage = TriagePolicy(
            path=tmp_path / "triage.json",
            entries=[
                TriageEntry(
                    finding_id="trace.violation.TC-0001",
                    reason="Known false positive — test event",
                )
            ],
        )

        def fake_scan() -> list[EmittedEvent]:
            return [
                EmittedEvent(
                    event_name="unregistered.event", source_file="src/module.py"
                )
            ]

        def fake_validate(_emitted: list[EmittedEvent]) -> list[ContractViolation]:
            return [
                ContractViolation(
                    violation_id="TC-0001",
                    kind="unregistered_event",
                    severity="high",
                    event_name="unregistered.event",
                    source_file="src/module.py",
                    description="Not in registry",
                    recommendation="Register it",
                )
            ]

        def fake_report(*_args, **_kwargs):
            return {
                "summary": {
                    "total_emitted": 1,
                    "total_registered": 0,
                    "total_violations": 1,
                    "clean": False,
                }
            }

        with (
            patch("rig_relay.tracing._contract.EventEmissionScanner") as mock_scanner,
            patch(
                "rig_relay.tracing._contract.TraceContractValidator"
            ) as mock_validator,
            patch(
                "rig_relay.tracing._contract.build_contract_report",
                side_effect=fake_report,
            ),
        ):
            mock_scanner.return_value.scan = fake_scan
            mock_validator.return_value.validate_all = fake_validate

            result = check_trace_contract(triage=triage)

        violation_findings = [
            f for f in result.findings if f.finding_id.startswith("trace.violation.")
        ]
        assert len(violation_findings) == 0


class TestWebSocketInvariantProbes:
    def test_all_invariants_detected_on_live_source(self) -> None:
        result = check_websocket_security()
        invariants = result.evidence.get("invariants", {})

        assert invariants.get("origin_exact_match"), "origin exact match NOT detected"
        assert invariants.get("auth_before_subscribe"), (
            "auth before subscribe NOT detected"
        )
        assert invariants.get("reject_non_dict_json"), (
            "non-dict JSON rejection NOT detected"
        )
        assert invariants.get("max_invalid_messages"), (
            "max invalid messages NOT detected"
        )
        assert invariants.get("message_size_cap"), "message size cap NOT detected"
        assert invariants.get("rate_limiting"), "rate limiting NOT detected"
        assert invariants.get("message_schema_validation"), (
            "schema validation NOT detected"
        )
        assert invariants.get("content_light_trace_events"), (
            "golden event emission NOT detected"
        )

    def test_invariant_values_populated(self) -> None:
        result = check_websocket_security()
        assert result.evidence["max_invalid_messages"] == 3
        assert result.evidence["max_message_bytes"] == 65536
        assert result.evidence["rate_limit_per_minute"] == 60

    def test_missing_websocket_source_fails_blocker(self, tmp_path: Path) -> None:
        with patch(
            "rig_relay.release_gate._runtime_readiness._WEBSOCKET_SERVER_PATH",
            tmp_path / "nope.py",
        ):
            result = check_websocket_security()
        assert result.status == CheckStatus.FAIL
        assert result.severity == CheckSeverity.BLOCKER
        assert any(f.finding_id == "ws.invariant.file_missing" for f in result.findings)

    def test_synthetic_ws_minimal_invariant_detection(self, tmp_path: Path) -> None:
        minimal = textwrap.dedent("""\
            ALLOWED_MESSAGE_TYPES = frozenset({})
            DEFAULT_MAX_MESSAGE_BYTES = 65536
            DEFAULT_RATE_LIMIT_PER_MINUTE = 60
            MAX_INVALID_WEBSOCKET_MESSAGES = 3
            _RATE_WINDOW_SECONDS = 60
            class FakeServer:
                def __init__(self):
                    self._allowed_origins = frozenset()
                async def _handle_auth(self, ws, msg, corr, tid):
                    if not authenticated:
                        return False
                    return True
                def _parse_message(self, raw):
                    pass
                def _validate_message_shape(self, msg_type, message):
                    pass
                def _emit_golden_event(self, *a, **kw):
                    pass
            """)
        ws_path = tmp_path / "fake_ws.py"
        ws_path.write_text(minimal, encoding="utf-8")
        with patch(
            "rig_relay.release_gate._runtime_readiness._WEBSOCKET_SERVER_PATH", ws_path
        ):
            result = check_websocket_security()
        invariants = result.evidence.get("invariants", {})
        assert invariants.get("auth_before_subscribe"), (
            "auth guard not detected in synthetic source"
        )

    def test_loopback_substring_documented_as_low_finding(self) -> None:
        result = check_websocket_security()
        loopback_finding = [
            f
            for f in result.findings
            if f.finding_id == "ws.invariant.origin_loopback_substring"
        ]
        assert len(loopback_finding) == 1
        assert loopback_finding[0].severity == CheckSeverity.LOW

    def test_does_not_duplicate_security_test_coverage(self) -> None:
        result = check_websocket_security()
        assert result.status in (CheckStatus.PASS, CheckStatus.WARN, CheckStatus.FAIL)


class TestGitHubAppAuditReadiness:
    def test_audit_missing_fails_blocker(self, tmp_path: Path) -> None:
        with patch(
            "rig_relay.release_gate._runtime_readiness._GITHUB_AUDIT_PATH",
            tmp_path / "nope.json",
        ):
            result = check_github_app_audit()
        assert result.status == CheckStatus.FAIL
        assert result.severity == CheckSeverity.BLOCKER
        assert any(f.finding_id == "github.audit.missing" for f in result.findings)

    def test_audit_backend_not_implemented_yields_deferred(self) -> None:
        result = check_github_app_audit()
        assert result.status == CheckStatus.DEFERRED, (
            f"Expected DEFERRED when backend not implemented, got {result.status.value}"
        )
        impl_finding = [
            f
            for f in result.findings
            if f.finding_id == "github.implementation.backend_not_implemented"
        ]
        assert len(impl_finding) == 1
        assert impl_finding[0].severity == CheckSeverity.MEDIUM

    def test_audit_distinguishes_audit_complete_from_backend_implemented(self) -> None:
        result = check_github_app_audit()
        evidence = result.evidence
        assert "audit_status" in evidence, (
            "audit_status should be present (audit exists)"
        )
        assert "backend_modules" in evidence, (
            "backend_modules should report implementation status"
        )
        assert not all(evidence["backend_modules"].values()), (
            "Backend modules should not all be implemented (they're deferred)"
        )

    def test_synthetic_audit_with_signature_events_does_not_warn(
        self, tmp_path: Path
    ) -> None:
        audit = {
            "schema_version": "rig.github_app.integration_audit.v1",
            "audit_id": "test-audit",
            "status": "draft",
            "trace_events": [
                {"event_name": "github.webhook.signature_verified"},
                {"event_name": "github.webhook.signature_rejected"},
                {"event_name": "github.webhook.received"},
            ],
            "webhook_subscriptions": [
                {
                    "event": "push",
                    "requires_signature": True,
                    "signature_method": "X-Hub-Signature-256",
                }
            ],
            "permission_profiles": [{"name": "read"}],
            "trust_boundaries": [{"name": "webhook"}],
            "release_gates": [{"name": "signature"}],
            "implementation_phases": [],
        }
        audit_path = tmp_path / "audit.json"
        audit_path.write_text(json.dumps(audit), encoding="utf-8")
        with patch(
            "rig_relay.release_gate._runtime_readiness._GITHUB_AUDIT_PATH", audit_path
        ):
            result = check_github_app_audit()
        sig_findings = [
            f for f in result.findings if "signature" in f.finding_id.lower()
        ]
        assert len(sig_findings) == 0, (
            f"Should not warn about signature events when present: {sig_findings}"
        )

    def test_synthetic_audit_with_raw_secret_detected(self, tmp_path: Path) -> None:
        audit = {
            "schema_version": "rig.github_app.integration_audit.v1",
            "audit_id": "test-audit",
            "status": "draft",
            "trace_events": [],
            "webhook_subscriptions": [],
            "permission_profiles": [],
            "trust_boundaries": [],
            "release_gates": [],
            "implementation_phases": [],
            "notes": "Use token ghp_1234567890abcdef1234567890abcdef123456",
        }
        audit_path = tmp_path / "audit.json"
        audit_path.write_text(json.dumps(audit), encoding="utf-8")
        with patch(
            "rig_relay.release_gate._runtime_readiness._GITHUB_AUDIT_PATH", audit_path
        ):
            result = check_github_app_audit()
        secret_findings = [
            f
            for f in result.findings
            if f.finding_id.startswith("github.audit.raw_secret.")
        ]
        assert len(secret_findings) >= 1
        assert secret_findings[0].severity == CheckSeverity.BLOCKER


class TestCiWorkflowParser:
    def test_real_workflows_found(self) -> None:
        result = check_ci_coverage()
        assert result.evidence["workflow_count"] > 0
        assert isinstance(result.evidence["coverage"], dict)

    def test_missing_ci_dir_fails(self, tmp_path: Path) -> None:
        with patch(
            "rig_relay.release_gate._runtime_readiness._CI_DIR",
            tmp_path / "no_workflows",
        ):
            result = check_ci_coverage()
        assert result.status == CheckStatus.FAIL
        assert result.severity == CheckSeverity.BLOCKER

    def test_no_release_gate_step_warns(self, tmp_path: Path) -> None:
        wf_dir = tmp_path / "workflows"
        wf_dir.mkdir()
        wf = wf_dir / "ci.yml"
        wf.write_text(
            textwrap.dedent("""\
            name: CI
            on: push
            jobs:
              test:
                runs-on: ubuntu-latest
                steps:
                  - run: pytest
                  - run: pyright
            """),
            encoding="utf-8",
        )
        with patch("rig_relay.release_gate._runtime_readiness._CI_DIR", wf_dir):
            result = check_ci_coverage()
        assert result.status in (CheckStatus.WARN, CheckStatus.FAIL)
        assert any(
            f.finding_id == "ci.workflow.no_release_gate" for f in result.findings
        )

    def test_ci_with_all_steps_passes(self, tmp_path: Path) -> None:
        wf_dir = tmp_path / "workflows"
        wf_dir.mkdir()
        wf = wf_dir / "ci.yml"
        wf.write_text(
            textwrap.dedent("""\
            name: CI
            on: push
            jobs:
              gate:
                runs-on: ubuntu-latest
                steps:
                  - name: Run release evidence gate
                    run: uv run python -m rig_relay.release_gate --output .build/rig-relay/release-gate-ci.json
                  - name: Validate schemas
                    run: uv run python scripts/rig_relay_validate_schemas.py
              test:
                runs-on: ubuntu-latest
                steps:
                  - name: Run tests
                    run: uv run pytest
                  - name: Type check
                    run: uv run pyright
                  - name: Generated site safety
                    run: uv run python scripts/verify_generated_docs_safety.py
            """),
            encoding="utf-8",
        )
        with patch("rig_relay.release_gate._runtime_readiness._CI_DIR", wf_dir):
            result = check_ci_coverage()
        assert result.status == CheckStatus.PASS
        coverage = result.evidence["coverage"]
        assert coverage.get("release_gate"), "release_gate step should be detected"
        assert coverage.get("schema_validation"), (
            "schema_validation step should be detected"
        )
        assert coverage.get("tests"), "tests step should be detected"
        assert coverage.get("pyright"), "pyright step should be detected"
        assert coverage.get("generated_site_safety"), (
            "generated_site_safety step should be detected"
        )

    def test_degenerate_yaml_does_not_crash(self, tmp_path: Path) -> None:
        wf_dir = tmp_path / "workflows"
        wf_dir.mkdir()
        bad_wf = wf_dir / "broken.yml"
        bad_wf.write_text(":::\n\tnot:\nyaml:\n", encoding="utf-8")
        with patch("rig_relay.release_gate._runtime_readiness._CI_DIR", wf_dir):
            result = check_ci_coverage()
        assert result.evidence["workflow_count"] == 1


class TestTriagePolicy:
    def test_load_empty_triage_when_missing(self, tmp_path: Path) -> None:
        policy = load_triage_policy(tmp_path / "nope.json")
        assert policy.path.name == "nope.json"
        assert len(policy.entries) == 0
        assert not policy.is_triaged("anything")

    def test_load_triage_entries_from_json(self, tmp_path: Path) -> None:
        data = {
            "entries": [
                {
                    "finding_id": "trace.violation.TC-0001",
                    "reason": "Known false positive",
                    "expires": "2026-12-31",
                }
            ]
        }
        path = tmp_path / "triage.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        policy = load_triage_policy(path)
        assert policy.is_triaged("trace.violation.TC-0001")
        assert policy.triage_reason("trace.violation.TC-0001") == "Known false positive"
        assert not policy.is_triaged("trace.violation.TC-0002")

    def test_malformed_triage_json_returns_empty(self, tmp_path: Path) -> None:
        path = tmp_path / "bad.json"
        path.write_text("not json", encoding="utf-8")
        policy = load_triage_policy(path)
        assert len(policy.entries) == 0


class TestPublicApiIntegration:
    def test_run_all_runtime_checks_returns_gate_result(self) -> None:
        from rig_relay.release_gate import run_all_runtime_checks

        result = run_all_runtime_checks()
        assert result.schema_version == "rig.release_evidence_gate.v1"
        assert result.gate_id == "runtime_readiness"
        assert result.overall_status is not None
        assert result.summary.total_checks == 5
        assert len(result.checks) == 5

    def test_run_single_check_by_id(self) -> None:
        from rig_relay.release_gate import run_runtime_check

        result = run_runtime_check("runtime.ci.workflow_coverage")
        assert result.check_id == "runtime.ci.workflow_coverage"
        assert result.status is not None

    def test_register_checks_populates_registry(self) -> None:
        from rig_relay.release_gate import CheckContext, register_checks

        registry: dict = {}
        register_checks(registry)
        assert len(registry) == 5
        for check_id in [
            "runtime.trace_contract.clean_or_triaged",
            "runtime.visibility_matrix.release_paths",
            "runtime.websocket.security_invariants",
            "runtime.github_app.audit_readiness",
            "runtime.ci.workflow_coverage",
        ]:
            assert check_id in registry, f"{check_id} should be registered"
            runner = registry[check_id]
            ctx = CheckContext(repo_root=Path.cwd(), output_dir=Path.cwd())
            result = runner(ctx)
            assert isinstance(result, CheckResult)
            assert result.check_id == check_id

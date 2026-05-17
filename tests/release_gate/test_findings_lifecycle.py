"""Findings lifecycle tests — schema validation, policy loading, matching,
expiration, status derivation, and GateRunner integration.

Governed by docs/schemas/rig.release_gate.findings_lifecycle.v1.schema.json
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from rig_relay.release_gate.findings_lifecycle import (
    apply_lifecycle,
    load_lifecycle_policy,
)
from rig_relay.release_gate.models import (
    CheckContext,
    CheckResult,
    CheckSeverity,
    CheckStatus,
    Finding,
    LifecycleEntry,
    LifecyclePolicy,
    LifecycleState,
)
from rig_relay.release_gate.runner import GateRunner

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCHEMA_PATH = (
    _REPO_ROOT
    / "docs"
    / "schemas"
    / "rig.release_gate.findings_lifecycle.v1.schema.json"
)


def _make_policy_json(**overrides) -> dict:
    base = {
        "schema_version": "rig.release_gate.findings_lifecycle.v1",
        "policy_id": "test-lifecycle-v0",
        "entries": [],
    }
    base.update(overrides)
    return base


def _make_entry(
    finding_id: str = "tf-001",
    check_id: str = "test.check",
    lifecycle_state: str = "accepted_false_positive",
    reason: str = "Test entry",
    owner: str = "test-owner",
    **kwargs,
) -> dict:
    entry: dict = {
        "finding_id": finding_id,
        "check_id": check_id,
        "lifecycle_state": lifecycle_state,
        "reason": reason,
        "owner": owner,
    }
    entry.update(kwargs)
    return entry


def _write_policy(path: Path, entries: list[dict], **overrides) -> Path:
    policy = _make_policy_json(**overrides)
    policy["entries"] = entries
    path.write_text(json.dumps(policy), encoding="utf-8")
    return path


# ── Schema validation ───────────────────────────────────────────────


class TestLifecycleSchema:
    def test_valid_minimal_policy_validates(self, tmp_path: Path) -> None:
        policy = _make_policy_json(entries=[_make_entry()])
        path = tmp_path / "policy.json"
        path.write_text(json.dumps(policy), encoding="utf-8")
        result = load_lifecycle_policy(path, schema_path=_SCHEMA_PATH)
        assert result.policy_id == "test-lifecycle-v0"
        assert len(result.entries) == 1

    def test_rejects_malformed_lifecycle_state(self, tmp_path: Path) -> None:
        policy = _make_policy_json(entries=[_make_entry(lifecycle_state="banana")])
        path = tmp_path / "bad.json"
        path.write_text(json.dumps(policy), encoding="utf-8")
        with pytest.raises((ValueError, Exception)):
            load_lifecycle_policy(path, schema_path=_SCHEMA_PATH)

    def test_rejects_missing_finding_id(self, tmp_path: Path) -> None:
        entry = _make_entry()
        del entry["finding_id"]
        policy = _make_policy_json(entries=[entry])
        path = tmp_path / "bad.json"
        path.write_text(json.dumps(policy), encoding="utf-8")
        with pytest.raises((ValueError, Exception)):
            load_lifecycle_policy(path, schema_path=_SCHEMA_PATH)

    def test_rejects_missing_check_id(self, tmp_path: Path) -> None:
        entry = _make_entry()
        del entry["check_id"]
        policy = _make_policy_json(entries=[entry])
        path = tmp_path / "bad.json"
        path.write_text(json.dumps(policy), encoding="utf-8")
        with pytest.raises((ValueError, Exception)):
            load_lifecycle_policy(path, schema_path=_SCHEMA_PATH)

    def test_rejects_missing_reason(self, tmp_path: Path) -> None:
        entry = _make_entry()
        del entry["reason"]
        policy = _make_policy_json(entries=[entry])
        path = tmp_path / "bad.json"
        path.write_text(json.dumps(policy), encoding="utf-8")
        with pytest.raises((ValueError, Exception)):
            load_lifecycle_policy(path, schema_path=_SCHEMA_PATH)

    def test_rejects_missing_owner(self, tmp_path: Path) -> None:
        entry = _make_entry()
        del entry["owner"]
        policy = _make_policy_json(entries=[entry])
        path = tmp_path / "bad.json"
        path.write_text(json.dumps(policy), encoding="utf-8")
        with pytest.raises((ValueError, Exception)):
            load_lifecycle_policy(path, schema_path=_SCHEMA_PATH)

    def test_rejects_invalid_expires_format(self, tmp_path: Path) -> None:
        policy = _make_policy_json(entries=[_make_entry(expires="tomorrow")])
        path = tmp_path / "bad.json"
        path.write_text(json.dumps(policy), encoding="utf-8")
        with pytest.raises((ValueError, Exception)):
            load_lifecycle_policy(path, schema_path=_SCHEMA_PATH)

    def test_accepts_valid_expires(self, tmp_path: Path) -> None:
        policy = _make_policy_json(entries=[_make_entry(expires="2099-12-31")])
        path = tmp_path / "good.json"
        path.write_text(json.dumps(policy), encoding="utf-8")
        result = load_lifecycle_policy(path, schema_path=_SCHEMA_PATH)
        assert result.entries[0].expires == "2099-12-31"

    def test_accepts_severity_override(self, tmp_path: Path) -> None:
        entry = _make_entry(
            finding_id="f1", severity_override="low", release_blocking_override=False
        )
        policy = _make_policy_json(entries=[entry])
        path = tmp_path / "good.json"
        path.write_text(json.dumps(policy), encoding="utf-8")
        result = load_lifecycle_policy(path, schema_path=_SCHEMA_PATH)
        e = result.entries[0]
        assert e.severity_override == CheckSeverity.LOW
        assert e.release_blocking_override is False

    def test_rejects_invalid_severity_override(self, tmp_path: Path) -> None:
        policy = _make_policy_json(
            entries=[_make_entry(severity_override="catastrophic")]
        )
        path = tmp_path / "bad.json"
        path.write_text(json.dumps(policy), encoding="utf-8")
        with pytest.raises((ValueError, Exception)):
            load_lifecycle_policy(path, schema_path=_SCHEMA_PATH)


# ── Policy loading ───────────────────────────────────────────────────


class TestLifecycleLoader:
    def test_returns_empty_policy_for_missing_file(self, tmp_path: Path) -> None:
        result = load_lifecycle_policy(tmp_path / "nope.json")
        assert result.policy_id == ""
        assert len(result.entries) == 0

    def test_returns_empty_policy_for_none_path(self) -> None:
        result = load_lifecycle_policy(None)
        assert len(result.entries) == 0

    def test_loads_entries_deterministically(self, tmp_path: Path) -> None:
        entries = [
            _make_entry(finding_id=f"f{i}", check_id="c1", lifecycle_state="known_debt")
            for i in range(3)
        ]
        _write_policy(tmp_path / "p.json", entries)
        result = load_lifecycle_policy(tmp_path / "p.json")
        assert len(result.entries) == 3
        assert result.lookup("f0", "c1") is not None

    def test_malformed_json_reported(self, tmp_path: Path) -> None:
        path = tmp_path / "bad.json"
        path.write_text("not json", encoding="utf-8")
        with pytest.raises((json.JSONDecodeError, ValueError)):
            load_lifecycle_policy(path, schema_path=_SCHEMA_PATH)

    def test_builds_lookup_index(self, tmp_path: Path) -> None:
        entries = [
            _make_entry(finding_id="a", check_id="x"),
            _make_entry(finding_id="b", check_id="y"),
        ]
        _write_policy(tmp_path / "p.json", entries)
        result = load_lifecycle_policy(tmp_path / "p.json")
        assert result.lookup("a", "x") is not None
        assert result.lookup("b", "y") is not None
        assert result.lookup("c", "z") is None


# ── Lifecycle application ────────────────────────────────────────────


class TestLifecycleApplication:
    def test_exact_match_applies_lifecycle(self) -> None:
        policy = LifecyclePolicy(
            entries=[
                LifecycleEntry(
                    finding_id="tf-001",
                    check_id="test.check",
                    lifecycle_state=LifecycleState.ACCEPTED_FALSE_POSITIVE,
                    reason="Known false positive",
                    owner="test-owner",
                )
            ]
        )
        policy.build_index()

        findings: list[dict] = [
            {
                "finding_id": "tf-001",
                "check_id": "test.check",
                "severity": "blocker",
                "category": "test",
                "description": "A false positive",
                "source": "test.py",
                "recommendation": "Ignore",
            }
        ]
        enriched, report = apply_lifecycle(findings, policy)

        assert report.entries_applied == 1
        assert report.entries_unmatched == 0
        assert enriched[0]["lifecycle_state"] == "accepted_false_positive"
        assert enriched[0]["effective_severity"] == "info"
        assert enriched[0]["release_blocking"] is False
        assert enriched[0]["original_severity"] == "blocker"

    def test_unmatched_entry_reported(self) -> None:
        policy = LifecyclePolicy(
            entries=[
                LifecycleEntry(
                    finding_id="ghost",
                    check_id="phantom.check",
                    lifecycle_state=LifecycleState.KNOWN_DEBT,
                    reason="Orphaned",
                    owner="nobody",
                )
            ]
        )
        policy.build_index()

        findings: list[dict] = [
            {"finding_id": "real", "check_id": "real.check", "severity": "medium"}
        ]
        enriched, report = apply_lifecycle(findings, policy)

        assert report.entries_applied == 0
        assert report.entries_unmatched == 1
        assert len(report.policy_findings) == 1
        details = report.policy_findings[0].get("details", [])
        assert any(d["finding_id"] == "ghost" for d in details)

    def test_finding_not_deleted_after_triage(self) -> None:
        policy = LifecyclePolicy(
            entries=[
                LifecycleEntry(
                    finding_id="keep-me",
                    check_id="test.check",
                    lifecycle_state=LifecycleState.ACCEPTED_FALSE_POSITIVE,
                    reason="Still visible",
                    owner="test",
                )
            ]
        )
        policy.build_index()

        findings: list[dict] = [
            {"finding_id": "keep-me", "check_id": "test.check", "severity": "blocker"}
        ]
        enriched, _ = apply_lifecycle(findings, policy)
        assert len(enriched) == 1
        assert enriched[0]["finding_id"] == "keep-me"

    def test_original_severity_preserved(self) -> None:
        policy = LifecyclePolicy(
            entries=[
                LifecycleEntry(
                    finding_id="f1",
                    check_id="c1",
                    lifecycle_state=LifecycleState.INTENTIONAL_DEFERRED,
                    reason="Deferred intentionally",
                    owner="test",
                    severity_override=CheckSeverity.LOW,
                )
            ]
        )
        policy.build_index()

        findings: list[dict] = [
            {"finding_id": "f1", "check_id": "c1", "severity": "blocker"}
        ]
        enriched, _ = apply_lifecycle(findings, policy)

        assert enriched[0]["original_severity"] == "blocker"
        assert enriched[0]["effective_severity"] == "low"

    def test_all_lifecycle_states(self) -> None:
        states = [
            ("accepted_false_positive", False),
            ("intentional_deferred", False),
            ("known_debt", True),
            ("needs_fix", True),
            ("not_applicable", False),
            ("watch", False),
        ]
        for state, expected_blocking in states:
            policy = LifecyclePolicy(
                entries=[
                    LifecycleEntry(
                        finding_id=f"f-{state}",
                        check_id="c1",
                        lifecycle_state=LifecycleState(state),
                        reason=f"Testing {state}",
                        owner="test",
                    )
                ]
            )
            policy.build_index()
            findings: list[dict] = [
                {"finding_id": f"f-{state}", "check_id": "c1", "severity": "blocker"}
            ]
            enriched, _ = apply_lifecycle(findings, policy)
            actual_blocking = enriched[0].get("release_blocking", True)
            assert actual_blocking == expected_blocking, (
                f"{state}: expected release_blocking={expected_blocking}, got {actual_blocking}"
            )


# ── Expiration ───────────────────────────────────────────────────────


class TestLifecycleExpiration:
    def test_expired_entry_does_not_suppress_blocker(self) -> None:
        policy = LifecyclePolicy(
            entries=[
                LifecycleEntry(
                    finding_id="expired-one",
                    check_id="c1",
                    lifecycle_state=LifecycleState.ACCEPTED_FALSE_POSITIVE,
                    reason="Should be expired",
                    owner="test",
                    expires="2020-01-01",
                )
            ]
        )
        policy.build_index()

        findings: list[dict] = [
            {"finding_id": "expired-one", "check_id": "c1", "severity": "blocker"}
        ]
        enriched, report = apply_lifecycle(findings, policy)

        assert report.entries_expired == 1
        assert enriched[0]["triage_expired"] is True
        assert enriched[0]["effective_severity"] == "blocker"
        assert enriched[0]["release_blocking"] is True
        assert "EXPIRED" in enriched[0]["triage_reason"]

    def test_non_expired_entry_suppresses(self) -> None:
        policy = LifecyclePolicy(
            entries=[
                LifecycleEntry(
                    finding_id="fresh-one",
                    check_id="c1",
                    lifecycle_state=LifecycleState.ACCEPTED_FALSE_POSITIVE,
                    reason="Still valid",
                    owner="test",
                    expires="2099-12-31",
                )
            ]
        )
        policy.build_index()

        findings: list[dict] = [
            {"finding_id": "fresh-one", "check_id": "c1", "severity": "blocker"}
        ]
        enriched, report = apply_lifecycle(findings, policy)

        assert report.entries_expired == 0
        assert enriched[0]["triage_expired"] is False
        assert enriched[0]["release_blocking"] is False

    def test_no_expires_means_permanent(self) -> None:
        policy = LifecyclePolicy(
            entries=[
                LifecycleEntry(
                    finding_id="permanent",
                    check_id="c1",
                    lifecycle_state=LifecycleState.ACCEPTED_FALSE_POSITIVE,
                    reason="Permanent",
                    owner="test",
                )
            ]
        )
        policy.build_index()

        findings: list[dict] = [
            {"finding_id": "permanent", "check_id": "c1", "severity": "blocker"}
        ]
        enriched, _ = apply_lifecycle(findings, policy)

        assert enriched[0]["triage_expired"] is False
        assert enriched[0]["release_blocking"] is False


# ── GateRunner integration ───────────────────────────────────────────


class TestGateRunnerLifecycle:
    def test_blocker_triaged_as_false_positive_passes_gate(self) -> None:
        lifecycle = LifecyclePolicy(
            entries=[
                LifecycleEntry(
                    finding_id="fake-blocker",
                    check_id="test.fail_check",
                    lifecycle_state=LifecycleState.ACCEPTED_FALSE_POSITIVE,
                    reason="Known false positive",
                    owner="test",
                )
            ]
        )
        lifecycle.build_index()

        def _fail_check(ctx: CheckContext) -> CheckResult:
            return CheckResult(
                check_id="test.fail_check",
                title="Always fails",
                status=CheckStatus.FAIL,
                severity=CheckSeverity.BLOCKER,
                findings=[
                    Finding(
                        finding_id="fake-blocker",
                        category="test",
                        description="A triaged false positive",
                        severity=CheckSeverity.BLOCKER,
                    )
                ],
            )

        registry = {"test.fail_check": _fail_check}
        runner = GateRunner(checks=registry, lifecycle=lifecycle)
        ctx = CheckContext(repo_root=Path("."), output_dir=Path("."))
        result = runner.run(ctx)

        assert result.overall_status != "failed", (
            f"Expected PASSED or WARNING with all blockers triaged, got {result.overall_status}"
        )

    def test_untriaged_blocker_still_fails_gate(self) -> None:
        def _fail_check(ctx: CheckContext) -> CheckResult:
            return CheckResult(
                check_id="test.fail_check",
                title="Always fails",
                status=CheckStatus.FAIL,
                severity=CheckSeverity.BLOCKER,
                findings=[
                    Finding(
                        finding_id="real-blocker",
                        category="test",
                        description="A real blocker",
                        severity=CheckSeverity.BLOCKER,
                    )
                ],
            )

        registry = {"test.fail_check": _fail_check}
        runner = GateRunner(checks=registry)
        ctx = CheckContext(repo_root=Path("."), output_dir=Path("."))
        result = runner.run(ctx)

        assert result.overall_status == "failed"

    def test_one_triaged_one_untriaged_still_fails(self) -> None:
        lifecycle = LifecyclePolicy(
            entries=[
                LifecycleEntry(
                    finding_id="triaged-one",
                    check_id="test.fail_check",
                    lifecycle_state=LifecycleState.ACCEPTED_FALSE_POSITIVE,
                    reason="Triaged",
                    owner="test",
                )
            ]
        )
        lifecycle.build_index()

        def _fail_check(ctx: CheckContext) -> CheckResult:
            return CheckResult(
                check_id="test.fail_check",
                title="Two findings — one triaged",
                status=CheckStatus.FAIL,
                severity=CheckSeverity.BLOCKER,
                findings=[
                    Finding(
                        finding_id="triaged-one",
                        category="test",
                        description="Triaged",
                        severity=CheckSeverity.BLOCKER,
                    ),
                    Finding(
                        finding_id="untriaged-one",
                        category="test",
                        description="Real blocker",
                        severity=CheckSeverity.BLOCKER,
                    ),
                ],
            )

        registry = {"test.fail_check": _fail_check}
        runner = GateRunner(checks=registry, lifecycle=lifecycle)
        ctx = CheckContext(repo_root=Path("."), output_dir=Path("."))
        result = runner.run(ctx)

        assert result.overall_status == "failed"

    def test_known_debt_with_release_blocking_override_false_passes(self) -> None:
        lifecycle = LifecyclePolicy(
            entries=[
                LifecycleEntry(
                    finding_id="debt-1",
                    check_id="test.check",
                    lifecycle_state=LifecycleState.KNOWN_DEBT,
                    reason="Known debt — not blocking this release",
                    owner="test",
                    release_blocking_override=False,
                )
            ]
        )
        lifecycle.build_index()

        def _check(ctx: CheckContext) -> CheckResult:
            return CheckResult(
                check_id="test.check",
                title="Has known debt",
                status=CheckStatus.FAIL,
                severity=CheckSeverity.HIGH,
                findings=[
                    Finding(
                        finding_id="debt-1",
                        category="test",
                        description="Known debt",
                        severity=CheckSeverity.HIGH,
                    )
                ],
            )

        registry = {"test.check": _check}
        runner = GateRunner(checks=registry, lifecycle=lifecycle)
        ctx = CheckContext(repo_root=Path("."), output_dir=Path("."))
        result = runner.run(ctx)

        assert result.overall_status != "failed"

    def test_known_debt_without_override_still_blocks(self) -> None:
        lifecycle = LifecyclePolicy(
            entries=[
                LifecycleEntry(
                    finding_id="debt-1",
                    check_id="test.check",
                    lifecycle_state=LifecycleState.KNOWN_DEBT,
                    reason="Known debt — still blocks",
                    owner="test",
                )
            ]
        )
        lifecycle.build_index()

        def _check(ctx: CheckContext) -> CheckResult:
            return CheckResult(
                check_id="test.check",
                title="Has known debt",
                status=CheckStatus.FAIL,
                severity=CheckSeverity.HIGH,
                findings=[
                    Finding(
                        finding_id="debt-1",
                        category="test",
                        description="Known debt",
                        severity=CheckSeverity.HIGH,
                    )
                ],
            )

        registry = {"test.check": _check}
        runner = GateRunner(checks=registry, lifecycle=lifecycle)
        ctx = CheckContext(repo_root=Path("."), output_dir=Path("."))
        result = runner.run(ctx)

        assert result.overall_status == "failed"

    def test_expired_triage_does_not_suppress(self) -> None:
        lifecycle = LifecyclePolicy(
            entries=[
                LifecycleEntry(
                    finding_id="expired-blocker",
                    check_id="test.check",
                    lifecycle_state=LifecycleState.ACCEPTED_FALSE_POSITIVE,
                    reason="Expired triage",
                    owner="test",
                    expires="2020-01-01",
                )
            ]
        )
        lifecycle.build_index()

        def _check(ctx: CheckContext) -> CheckResult:
            return CheckResult(
                check_id="test.check",
                title="Expired triage",
                status=CheckStatus.FAIL,
                severity=CheckSeverity.BLOCKER,
                findings=[
                    Finding(
                        finding_id="expired-blocker",
                        category="test",
                        description="Should not be suppressed",
                        severity=CheckSeverity.BLOCKER,
                    )
                ],
            )

        registry = {"test.check": _check}
        runner = GateRunner(checks=registry, lifecycle=lifecycle)
        ctx = CheckContext(repo_root=Path("."), output_dir=Path("."))
        result = runner.run(ctx)

        assert result.overall_status == "failed"

    def test_include_check_behavior_unchanged(self) -> None:
        """GateRunner with include_checks still works with lifecycle."""
        lifecycle = LifecyclePolicy(
            entries=[
                LifecycleEntry(
                    finding_id="anything",
                    check_id="test.a",
                    lifecycle_state=LifecycleState.ACCEPTED_FALSE_POSITIVE,
                    reason="test",
                    owner="test",
                )
            ]
        )
        lifecycle.build_index()

        def _check_a(ctx: CheckContext) -> CheckResult:
            return CheckResult(check_id="test.a", title="A", status=CheckStatus.PASS)

        def _check_b(ctx: CheckContext) -> CheckResult:
            return CheckResult(
                check_id="test.b",
                title="B",
                status=CheckStatus.FAIL,
                severity=CheckSeverity.BLOCKER,
                findings=[
                    Finding(
                        finding_id="real-b",
                        category="test",
                        description="Real",
                        severity=CheckSeverity.BLOCKER,
                    )
                ],
            )

        registry: dict = {"test.a": _check_a, "test.b": _check_b}
        runner = GateRunner(checks=registry, lifecycle=lifecycle)
        ctx = CheckContext(repo_root=Path("."), output_dir=Path("."))

        result_a = runner.run(ctx, include_checks={"test.a"})
        assert result_a.overall_status != "failed"
        assert len(result_a.checks) == 1

        result_b = runner.run(ctx, include_checks={"test.b"})
        assert result_b.overall_status == "failed"
        assert len(result_b.checks) == 1

    def test_lifecycle_output_in_gate_json(self) -> None:
        lifecycle = LifecyclePolicy(
            policy_id="test-lifecycle",
            entries=[
                LifecycleEntry(
                    finding_id="fp-1",
                    check_id="test.check",
                    lifecycle_state=LifecycleState.ACCEPTED_FALSE_POSITIVE,
                    reason="Test FP",
                    owner="test-owner",
                )
            ],
        )
        lifecycle.build_index()

        def _check(ctx: CheckContext) -> CheckResult:
            return CheckResult(
                check_id="test.check",
                title="Has FP",
                status=CheckStatus.FAIL,
                severity=CheckSeverity.BLOCKER,
                findings=[
                    Finding(
                        finding_id="fp-1",
                        category="test",
                        description="FP",
                        severity=CheckSeverity.BLOCKER,
                    )
                ],
            )

        registry = {"test.check": _check}
        runner = GateRunner(checks=registry, lifecycle=lifecycle)
        ctx = CheckContext(repo_root=Path("."), output_dir=Path("."))
        result = runner.run(ctx)

        lc = result.lifecycle
        assert lc.get("policy_id") == "test-lifecycle"
        assert lc.get("entries_loaded") == 1
        assert lc.get("entries_applied") == 1
        assert lc.get("entries_expired") == 0
        assert lc.get("entries_unmatched") == 0

        finding = result.findings[0]
        assert finding["lifecycle_state"] == "accepted_false_positive"
        assert finding["triage_owner"] == "test-owner"
        assert finding["release_blocking"] is False


# ── Realistic regression ─────────────────────────────────────────────


class TestRealisticRegression:
    def test_trace_contract_runtime_ids_as_false_positives(self) -> None:
        """The runtime readiness check IDs appear as trace event strings and are
        detected as unregistered events. Classify them as accepted_false_positive.
        """
        lifecycle = LifecyclePolicy(
            entries=[
                LifecycleEntry(
                    finding_id=f"trace.violation.TC-{n:04d}",
                    check_id="runtime.trace_contract.clean_or_triaged",
                    lifecycle_state=LifecycleState.ACCEPTED_FALSE_POSITIVE,
                    reason="Runtime readiness check IDs are string literals in _runtime_readiness.py, not trace events",
                    owner="lane-c",
                )
                for n in [21, 22, 23, 24, 25]
            ]
        )
        lifecycle.build_index()

        findings: list[dict] = [
            {
                "finding_id": f"trace.violation.TC-{n:04d}",
                "check_id": "runtime.trace_contract.clean_or_triaged",
                "severity": "blocker",
                "category": "trace_contract",
                "description": f"False positive trace event {n}",
            }
            for n in [21, 22, 23, 24, 25]
        ]
        findings.append({
            "finding_id": "trace.violation.TC-0026",
            "check_id": "runtime.trace_contract.clean_or_triaged",
            "severity": "blocker",
            "category": "trace_contract",
            "description": "A REAL unregistered event — should still block",
        })

        enriched, report = apply_lifecycle(findings, lifecycle)

        assert report.entries_applied == 5
        assert report.entries_unmatched == 0

        fp_findings = [
            f
            for f in enriched
            if f["finding_id"]
            in {f"trace.violation.TC-{n:04d}" for n in [21, 22, 23, 24, 25]}
        ]
        for f in fp_findings:
            assert f["lifecycle_state"] == "accepted_false_positive", (
                f"{f['finding_id']} should be classified"
            )
            assert f["release_blocking"] is False

        real = [f for f in enriched if f["finding_id"] == "trace.violation.TC-0026"]
        assert real[0]["lifecycle_state"] == ""
        assert real[0]["release_blocking"] is True


# ── Existing registry tests still pass ───────────────────────────────


class TestExistingRegistryStillWorks:
    """Verify seam-closure tests still pass with lifecycle integrated."""

    def test_registry_has_all_11_checks(self) -> None:
        from rig_relay.release_gate._checks_registry import build_default_registry

        registry = build_default_registry()
        assert len(registry) == 11

    def test_registry_runtime_checks_are_ctx_wrappers(self) -> None:
        from rig_relay.release_gate._checks_registry import build_default_registry

        registry = build_default_registry()
        ctx = CheckContext(repo_root=Path("."), output_dir=Path("."))
        for cid in [
            "runtime.trace_contract.clean_or_triaged",
            "runtime.visibility_matrix.release_paths",
        ]:
            fn = registry[cid]
            result = fn(ctx)
            assert isinstance(result, CheckResult)
            assert result.check_id == cid

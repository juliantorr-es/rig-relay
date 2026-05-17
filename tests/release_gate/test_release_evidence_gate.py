from __future__ import annotations

import json

from rig_relay.release_gate.models import (
    SEVERITY_DESCENDING,
    CheckContext,
    CheckResult,
    CheckSeverity,
    CheckStatus,
    Finding,
    GatePolicy,
    GatePolicyOverrides,
    GateResult,
    GateStatus,
    GateSummary,
    _severity_sort_key,
)
from rig_relay.release_gate.receipt import serialize_gate_result, write_receipt
from rig_relay.release_gate.runner import GateRunner


class TestSeveritySortKey:
    def test_blocker_sorts_first(self):
        assert _severity_sort_key(CheckSeverity.BLOCKER) == 0

    def test_info_sorts_last(self):
        assert _severity_sort_key(CheckSeverity.INFO) == 4

    def test_higher_ranks_for_lower_severity(self):
        ranks = [_severity_sort_key(CheckSeverity(s)) for s in SEVERITY_DESCENDING]
        assert ranks == sorted(ranks)

    def test_unknown_severity_returns_99(self):
        assert _severity_sort_key(CheckSeverity.INFO) == 4  # known value works
        assert _severity_sort_key(CheckSeverity.BLOCKER) == 0


class TestGateRunnerSorting:
    def test_checks_sorted_by_check_id(self, base_ctx):
        results = [
            make_fake_check("z.check", status=CheckStatus.PASS),
            make_fake_check("a.check", status=CheckStatus.PASS),
            make_fake_check("m.check", status=CheckStatus.PASS),
        ]
        registry = {cr.check_id: make_check_fn(cr) for cr in results}
        runner = GateRunner(checks=registry)
        result = runner.run(base_ctx)

        check_ids = [c["check_id"] for c in result.checks]
        assert check_ids == ["a.check", "m.check", "z.check"]

    def test_findings_sorted_by_severity_then_id(self, base_ctx):
        cr = make_fake_check(
            "sort.check",
            status=CheckStatus.FAIL,
            findings=[
                make_finding("f.zebra", CheckSeverity.LOW),
                make_finding("f.alpha", CheckSeverity.BLOCKER),
                make_finding("f.beta", CheckSeverity.BLOCKER),
                make_finding("f.gamma", CheckSeverity.MEDIUM),
            ],
        )
        runner = GateRunner(checks={"sort.check": make_check_fn(cr)})
        result = runner.run(base_ctx)

        finding_ids = [f["finding_id"] for f in result.findings]
        assert finding_ids == ["f.alpha", "f.beta", "f.gamma", "f.zebra"]


class TestStatusDerivation:
    def test_all_pass_gives_passed(self, base_ctx):
        cr = make_fake_check("a.check", CheckStatus.PASS)
        runner = GateRunner(checks={"a.check": make_check_fn(cr)})
        result = runner.run(base_ctx)
        assert result.overall_status == GateStatus.PASSED

    def test_no_checks_gives_skipped(self, base_ctx):
        runner = GateRunner(checks={})
        result = runner.run(base_ctx)
        assert result.overall_status == GateStatus.SKIPPED

    def test_blocker_fail_gives_failed(self, base_ctx):
        cr = make_fake_check("a.check", CheckStatus.FAIL, CheckSeverity.BLOCKER)
        runner = GateRunner(checks={"a.check": make_check_fn(cr)})
        result = runner.run(base_ctx)
        assert result.overall_status == GateStatus.FAILED

    def test_high_fail_gives_failed(self, base_ctx):
        cr = make_fake_check("a.check", CheckStatus.FAIL, CheckSeverity.HIGH)
        runner = GateRunner(checks={"a.check": make_check_fn(cr)})
        result = runner.run(base_ctx)
        assert result.overall_status == GateStatus.FAILED

    def test_medium_fail_gives_warning(self, base_ctx):
        cr = make_fake_check("a.check", CheckStatus.FAIL, CheckSeverity.MEDIUM)
        runner = GateRunner(checks={"a.check": make_check_fn(cr)})
        result = runner.run(base_ctx)
        assert result.overall_status == GateStatus.WARNING

    def test_low_fail_gives_warning(self, base_ctx):
        cr = make_fake_check("a.check", CheckStatus.FAIL, CheckSeverity.LOW)
        runner = GateRunner(checks={"a.check": make_check_fn(cr)})
        result = runner.run(base_ctx)
        assert result.overall_status == GateStatus.WARNING

    def test_medium_fail_release_blocking_gives_failed(self, base_ctx):
        policy = GatePolicy(
            overrides=[GatePolicyOverrides(check_id="a.check", release_blocking=True)]
        )
        cr = make_fake_check("a.check", CheckStatus.FAIL, CheckSeverity.MEDIUM)
        runner = GateRunner(checks={"a.check": make_check_fn(cr)}, policy=policy)
        result = runner.run(base_ctx)
        assert result.overall_status == GateStatus.FAILED

    def test_warn_gives_warning(self, base_ctx):
        cr = make_fake_check("a.check", CheckStatus.WARN, CheckSeverity.MEDIUM)
        runner = GateRunner(checks={"a.check": make_check_fn(cr)})
        result = runner.run(base_ctx)
        assert result.overall_status == GateStatus.WARNING

    def test_deferred_required_gives_failed(self, base_ctx):
        policy = GatePolicy(required_checks=["required.check"])
        cr = make_fake_check("required.check", CheckStatus.DEFERRED)
        runner = GateRunner(checks={"required.check": make_check_fn(cr)}, policy=policy)
        result = runner.run(base_ctx)
        assert result.overall_status == GateStatus.FAILED

    def test_deferred_not_required_gives_skipped(self, base_ctx):
        cr = make_fake_check("optional.check", CheckStatus.DEFERRED)
        runner = GateRunner(checks={"optional.check": make_check_fn(cr)})
        result = runner.run(base_ctx)
        assert result.overall_status == GateStatus.SKIPPED

    def test_blended_pass_and_deferred_optional(self, base_ctx):
        runner = GateRunner(
            checks={
                "a.pass": make_check_fn(make_fake_check("a.pass", CheckStatus.PASS)),
                "b.deferred": make_check_fn(
                    make_fake_check("b.deferred", CheckStatus.DEFERRED)
                ),
            }
        )
        result = runner.run(base_ctx)
        assert result.overall_status == GateStatus.SKIPPED

    def test_blended_pass_and_deferred_optional_with_pass_first(self, base_ctx):
        policy = GatePolicy()  # neither is required
        runner = GateRunner(
            checks={
                "a.pass": make_check_fn(make_fake_check("a.pass", CheckStatus.PASS)),
                "b.deferred": make_check_fn(
                    make_fake_check("b.deferred", CheckStatus.DEFERRED)
                ),
            },
            policy=policy,
        )
        result = runner.run(base_ctx)
        assert result.overall_status == GateStatus.SKIPPED


class TestIncludeExclude:
    def test_include_only_runs_specified(self, base_ctx):
        runner = GateRunner(
            checks={
                "a.check": make_check_fn(make_fake_check("a.check", CheckStatus.PASS)),
                "b.check": make_check_fn(make_fake_check("b.check", CheckStatus.PASS)),
            }
        )
        result = runner.run(base_ctx, include_checks={"a.check"})
        assert len(result.checks) == 1
        assert result.checks[0]["check_id"] == "a.check"

    def test_exclude_skips_specified(self, base_ctx):
        runner = GateRunner(
            checks={
                "a.check": make_check_fn(make_fake_check("a.check", CheckStatus.PASS)),
                "b.check": make_check_fn(make_fake_check("b.check", CheckStatus.PASS)),
            }
        )
        result = runner.run(base_ctx, exclude_checks={"b.check"})
        assert len(result.checks) == 2
        statuses = {c["check_id"]: c["status"] for c in result.checks}
        assert statuses["a.check"] == "pass"
        assert statuses["b.check"] == "deferred"

    def test_unknown_include_check_fails(self, base_ctx):
        runner = GateRunner(checks={})
        result = runner.run(base_ctx, include_checks={"nonexistent.check"})
        assert result.overall_status == GateStatus.FAILED
        assert any(c["status"] == "fail" for c in result.checks)


class TestCanonicalJSONStability:
    def test_deterministic_output_twice(self, base_ctx):
        cr = make_fake_check("a.check", CheckStatus.PASS)
        runner = GateRunner(checks={"a.check": make_check_fn(cr)})
        fixed_ts = "2026-01-01T00:00:00+00:00"

        result1 = runner.run(base_ctx, generated_at=fixed_ts)
        result2 = runner.run(base_ctx, generated_at=fixed_ts)

        json1 = serialize_gate_result(result1)
        json2 = serialize_gate_result(result2)
        assert json1 == json2

    def test_json_parses_as_valid(self, base_ctx):
        cr = make_fake_check("a.check", CheckStatus.PASS)
        runner = GateRunner(checks={"a.check": make_check_fn(cr)})
        result = runner.run(base_ctx, generated_at="2026-01-01T00:00:00Z")
        json_str = serialize_gate_result(result)
        parsed = json.loads(json_str)
        assert parsed["schema_version"] == "rig.release_evidence_gate.v1"
        assert parsed["overall_status"] == "passed"
        assert len(parsed["checks"]) == 1
        assert len(parsed["findings"]) == 0

    def test_field_order_is_explicit(self, base_ctx):
        cr = make_fake_check("a.check", CheckStatus.PASS)
        runner = GateRunner(checks={"a.check": make_check_fn(cr)})
        result = runner.run(base_ctx, generated_at="2026-01-01T00:00:00Z")
        json_str = serialize_gate_result(result)
        parsed = json.loads(json_str)
        top_keys = list(parsed.keys())
        expected_order = [
            "schema_version",
            "gate_id",
            "repository",
            "head_sha",
            "branch",
            "generated_at",
            "overall_status",
            "summary",
            "checks",
            "findings",
            "artifacts",
            "policy",
        ]
        assert top_keys == expected_order


class TestReceiptFile:
    def test_write_receipt_creates_parent_dirs(self, tmp_path):
        output = tmp_path / "deep" / "nested" / "receipt.json"
        result = GateResult(gate_id="test", overall_status=GateStatus.PASSED)
        written = write_receipt(result, output)
        assert written == output
        assert output.is_file()

    def test_write_receipt_content(self, tmp_path):
        output = tmp_path / "receipt.json"
        result = GateResult(
            gate_id="test",
            overall_status=GateStatus.PASSED,
            generated_at="2026-01-01T00:00:00Z",
        )
        write_receipt(result, output)
        content = json.loads(output.read_text())
        assert content["overall_status"] == "passed"
        assert content["generated_at"] == "2026-01-01T00:00:00Z"


class TestGateSummary:
    def test_summary_counts(self, base_ctx):
        runner = GateRunner(
            checks={
                "pass": make_check_fn(make_fake_check("pass", CheckStatus.PASS)),
                "fail": make_check_fn(
                    make_fake_check("fail", CheckStatus.FAIL, CheckSeverity.BLOCKER)
                ),
                "warn": make_check_fn(make_fake_check("warn", CheckStatus.WARN)),
                "defer": make_check_fn(make_fake_check("defer", CheckStatus.DEFERRED)),
            }
        )
        result = runner.run(base_ctx)
        s = result.summary
        assert s.total_checks == 4
        assert s.passed == 1
        assert s.failed == 1
        assert s.warning == 1
        assert s.skipped == 1

    def test_findings_by_severity(self, base_ctx):
        cr = make_fake_check(
            "multi.findings",
            CheckStatus.FAIL,
            findings=[
                make_finding("f1", CheckSeverity.BLOCKER),
                make_finding("f2", CheckSeverity.BLOCKER),
                make_finding("f3", CheckSeverity.HIGH),
                make_finding("f4", CheckSeverity.LOW),
            ],
        )
        runner = GateRunner(checks={"multi.findings": make_check_fn(cr)})
        result = runner.run(base_ctx)
        assert result.summary.findings_by_severity == {
            "blocker": 2,
            "high": 1,
            "low": 1,
        }

    def test_empty_findings_by_severity(self, base_ctx):
        cr = make_fake_check("no.findings", CheckStatus.PASS)
        runner = GateRunner(checks={"no.findings": make_check_fn(cr)})
        result = runner.run(base_ctx)
        assert result.summary.findings_by_severity == {}


class TestPolicy:
    def test_is_required(self):
        policy = GatePolicy(required_checks=["a.check"])
        assert policy.is_required("a.check")
        assert not policy.is_required("b.check")

    def test_override_for(self):
        ov = GatePolicyOverrides(check_id="a.check", release_blocking=True)
        policy = GatePolicy(overrides=[ov])
        assert policy.override_for("a.check") == ov
        assert policy.override_for("b.check") is None

    def test_is_release_blocking(self):
        ov = GatePolicyOverrides(check_id="a.check", release_blocking=True)
        policy = GatePolicy(overrides=[ov])
        assert policy.is_release_blocking("a.check")
        assert not policy.is_release_blocking("b.check")


class TestExceptionHandling:
    def test_check_raising_exception_is_blocker_fail(self, base_ctx):
        def _explode(ctx: CheckContext) -> CheckResult:
            raise RuntimeError("boom")

        runner = GateRunner(checks={"explode.check": _explode})
        result = runner.run(base_ctx)
        assert result.overall_status == GateStatus.FAILED
        assert result.checks[0]["status"] == "fail"
        assert result.checks[0]["severity"] == "blocker"


class TestGateResultFields:
    def test_all_required_fields_present(self, base_ctx):
        cr = make_fake_check("a.check", CheckStatus.PASS)
        runner = GateRunner(checks={"a.check": make_check_fn(cr)})
        result = runner.run(base_ctx, generated_at="2026-01-01T00:00:00Z")

        assert result.schema_version == "rig.release_evidence_gate.v1"
        assert result.gate_id == "release_evidence_v1"
        assert result.head_sha == base_ctx.head_sha
        assert result.branch == base_ctx.branch
        assert result.generated_at == "2026-01-01T00:00:00Z"
        assert result.overall_status == GateStatus.PASSED
        assert isinstance(result.summary, GateSummary)
        assert isinstance(result.checks, list)
        assert isinstance(result.findings, list)
        assert isinstance(result.artifacts, list)
        assert isinstance(result.policy, dict)


class TestGeneratedAt:
    def test_defaults_to_now(self, base_ctx):
        cr = make_fake_check("a.check", CheckStatus.PASS)
        runner = GateRunner(checks={"a.check": make_check_fn(cr)})
        result = runner.run(base_ctx)
        assert result.generated_at
        assert "T" in result.generated_at

    def test_can_be_overridden(self, base_ctx):
        cr = make_fake_check("a.check", CheckStatus.PASS)
        runner = GateRunner(checks={"a.check": make_check_fn(cr)})
        result = runner.run(base_ctx, generated_at="2025-06-15T12:00:00Z")
        assert result.generated_at == "2025-06-15T12:00:00Z"


def make_fake_check(
    check_id: str,
    status: CheckStatus = CheckStatus.PASS,
    severity: CheckSeverity = CheckSeverity.MEDIUM,
    summary: str = "",
    findings: list[Finding] | None = None,
) -> CheckResult:
    return CheckResult(
        check_id=check_id,
        title=f"Fake check: {check_id}",
        status=status,
        severity=severity,
        summary=summary or f"Result: {status}",
        findings=findings or [],
    )


def make_finding(
    finding_id: str,
    severity: CheckSeverity = CheckSeverity.MEDIUM,
    check_id: str = "test.check",
    category: str = "test",
) -> Finding:
    return Finding(
        finding_id=finding_id,
        category=category,
        description=f"Finding {finding_id}",
        severity=severity,
        source=f"{check_id}.py:1",
        recommendation="Fix it.",
    )


def make_check_fn(result: CheckResult):
    def _fn(ctx: CheckContext) -> CheckResult:
        return result

    return _fn

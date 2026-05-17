"""Release Evidence Gate — deterministic top-level runner.

Sorts checks and findings by stable identifiers. Derives overall_status from
check results and policy. Never depends on wall-clock order, random seeds,
or any non-deterministic source except the explicit generated_at timestamp.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, datetime
import traceback

from rig_relay.release_gate.models import (
    SEVERITY_DESCENDING,
    CheckContext,
    CheckResult,
    CheckSeverity,
    CheckStatus,
    GatePolicy,
    GateResult,
    GateSeverity,
    GateStatus,
    GateSummary,
    ReleaseGateCheck,
    _severity_sort_key,
)


class GateRunner:
    def __init__(
        self, checks: dict[str, ReleaseGateCheck], policy: GatePolicy | None = None
    ) -> None:
        self._checks = checks
        self._policy = policy or GatePolicy()

    def run(
        self,
        ctx: CheckContext,
        *,
        include_checks: set[str] | None = None,
        exclude_checks: set[str] | None = None,
        generated_at: str | None = None,
    ) -> GateResult:
        check_ids = self._resolve_check_ids(include_checks, exclude_checks)

        unknown = include_checks - set(self._checks.keys()) if include_checks else set()
        if unknown:
            check_ids |= unknown

        results: list[CheckResult] = []
        ran: set[str] = set()
        for cid in sorted(check_ids):
            if cid in ran:
                continue
            ran.add(cid)
            if cid in unknown:
                results.append(
                    CheckResult(
                        check_id=cid,
                        title=f"Unknown check: {cid}",
                        status=CheckStatus.FAIL,
                        severity=CheckSeverity.BLOCKER,
                        summary="Check not registered in the gate runner.",
                    )
                )
                continue
            if exclude_checks and cid in exclude_checks:
                results.append(
                    CheckResult(
                        check_id=cid,
                        title=self._checks[cid].__class__.__name__,
                        status=CheckStatus.DEFERRED,
                        severity=CheckSeverity.INFO,
                        summary="Excluded by --exclude-check.",
                    )
                )
                continue
            check_fn = self._checks[cid]
            try:
                cr = check_fn(ctx)
            except Exception:
                cr = CheckResult(
                    check_id=cid,
                    title=cid,
                    status=CheckStatus.FAIL,
                    severity=CheckSeverity.BLOCKER,
                    summary=f"Check raised exception: {traceback.format_exc()[-500:]}",
                )
            results.append(cr)

        findings = self._flatten_findings(results)
        overall_status = self._derive_status(results)
        summary = self._build_summary(results, findings)

        return GateResult(
            gate_id="release_evidence_v1",
            repository=str(ctx.repo_root.resolve()),
            head_sha=ctx.head_sha,
            branch=ctx.branch,
            generated_at=generated_at or datetime.now(UTC).isoformat(),
            overall_status=overall_status,
            summary=summary,
            checks=[self._check_dict(cr) for cr in results],
            findings=findings,
            artifacts=[],
            policy={
                "required_checks": self._policy.required_checks,
                "overrides": [asdict(ov) for ov in self._policy.overrides],
                "artifact_allowlist": self._policy.artifact_allowlist,
                "cache_policy": self._policy.cache_policy,
            },
        )

    def _resolve_check_ids(
        self, include_checks: set[str] | None, exclude_checks: set[str] | None
    ) -> set[str]:
        if include_checks:
            return set(include_checks)
        base = set(self._checks.keys())
        if exclude_checks:
            base -= exclude_checks
        return base

    def _flatten_findings(self, results: list[CheckResult]) -> list[dict[str, object]]:
        flat: list[dict[str, object]] = []
        for cr in results:
            for f in cr.findings:
                flat.append({
                    "finding_id": f.finding_id,
                    "check_id": cr.check_id,
                    "category": f.category,
                    "description": f.description,
                    "severity": str(f.severity),
                    "source": f.source,
                    "recommendation": f.recommendation,
                })
        flat.sort(
            key=lambda f: (
                _severity_sort_key(CheckSeverity(f["severity"])),
                f["finding_id"],
            )
        )
        return flat

    def _derive_status(self, results: list[CheckResult]) -> GateStatus:
        if not results:
            return GateStatus.SKIPPED

        worst = GateStatus.PASSED
        for cr in results:
            match cr.status:
                case CheckStatus.FAIL:
                    gs = GateSeverity(cr.severity)
                    if gs in {GateSeverity.BLOCKER, GateSeverity.HIGH}:
                        return GateStatus.FAILED
                    if self._policy.is_release_blocking(cr.check_id):
                        return GateStatus.FAILED
                    if worst == GateStatus.PASSED:
                        worst = GateStatus.WARNING
                case CheckStatus.WARN:
                    if worst == GateStatus.PASSED:
                        worst = GateStatus.WARNING
                case CheckStatus.DEFERRED:
                    if self._policy.is_required(cr.check_id):
                        return GateStatus.FAILED
                    if worst == GateStatus.PASSED:
                        worst = GateStatus.SKIPPED
                case CheckStatus.PASS:
                    pass
        return worst

    def _build_summary(
        self, results: list[CheckResult], findings: list[dict[str, object]]
    ) -> GateSummary:
        total_checks = len(results)
        passed = sum(1 for cr in results if cr.status == CheckStatus.PASS)
        failed = sum(1 for cr in results if cr.status == CheckStatus.FAIL)
        warning = sum(1 for cr in results if cr.status == CheckStatus.WARN)
        skipped = sum(1 for cr in results if cr.status == CheckStatus.DEFERRED)

        by_sev: dict[str, int] = {str(s): 0 for s in SEVERITY_DESCENDING}
        for f in findings:
            sev = str(f["severity"])
            by_sev[sev] = by_sev.get(sev, 0) + 1
        by_sev = {k: v for k, v in by_sev.items() if v > 0}

        return GateSummary(
            total_checks=total_checks,
            passed=passed,
            failed=failed,
            warning=warning,
            skipped=skipped,
            total_findings=len(findings),
            findings_by_severity=by_sev,
        )

    @staticmethod
    def _check_dict(cr: CheckResult) -> dict[str, object]:
        return {
            "check_id": cr.check_id,
            "title": cr.title,
            "status": cr.status,
            "severity": str(cr.severity),
            "summary": cr.summary,
            "evidence": cr.evidence,
        }

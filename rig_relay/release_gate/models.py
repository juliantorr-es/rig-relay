"""Release Evidence Gate — shared models for check results and triage policy.

Lane A: top-level gate and receipt models (GateSeverity, GateStatus, GateResult, etc.).
Lane C: per-check models (CheckResult, Finding, TriagePolicy) consumed by the runtime
readiness scanner. Lane C values are upward-compatible with Lane A gate aggregation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol

# ── Lane C: per-check models ───────────────────────────────────────


class CheckStatus(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    DEFERRED = "deferred"
    WARN = "warn"


class CheckSeverity(StrEnum):
    BLOCKER = "blocker"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


@dataclass
class CheckResult:
    check_id: str
    title: str
    status: CheckStatus
    severity: CheckSeverity = CheckSeverity.MEDIUM
    summary: str = ""
    findings: list[Finding] = field(default_factory=list)
    evidence: dict[str, Any] = field(default_factory=dict)


@dataclass
class Finding:
    finding_id: str
    category: str
    description: str
    severity: CheckSeverity = CheckSeverity.MEDIUM
    source: str = ""
    recommendation: str = ""


@dataclass
class TriagePolicy:
    """Known false positives triaged via policy, not ignored in code."""

    path: Path
    entries: list[TriageEntry] = field(default_factory=list)

    def is_triaged(self, finding_id: str) -> bool:
        return any(e.finding_id == finding_id for e in self.entries)

    def triage_reason(self, finding_id: str) -> str:
        for e in self.entries:
            if e.finding_id == finding_id:
                return e.reason
        return ""


@dataclass
class TriageEntry:
    finding_id: str
    reason: str
    expires: str = ""


# ── Lane A: top-level gate models ──────────────────────────────────────


class GateStatus(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    WARNING = "warning"
    SKIPPED = "skipped"


class GateSeverity(StrEnum):
    BLOCKER = "blocker"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


SEVERITY_RANK: dict[GateSeverity, int] = {
    GateSeverity.BLOCKER: 0,
    GateSeverity.HIGH: 1,
    GateSeverity.MEDIUM: 2,
    GateSeverity.LOW: 3,
    GateSeverity.INFO: 4,
}

SEVERITY_DESCENDING: list[GateSeverity] = [
    GateSeverity.BLOCKER,
    GateSeverity.HIGH,
    GateSeverity.MEDIUM,
    GateSeverity.LOW,
    GateSeverity.INFO,
]


def _severity_sort_key(sev: CheckSeverity) -> int:
    try:
        return SEVERITY_RANK[GateSeverity(sev)]
    except (ValueError, KeyError):
        return 99


def _check_severity_to_gate(cs: CheckSeverity) -> GateSeverity:
    return GateSeverity(cs)


# ── Check context ──────────────────────────────────────────────────────


@dataclass
class CheckContext:
    repo_root: Path
    output_dir: Path
    head_sha: str = ""
    branch: str = ""
    policy: GatePolicy = field(default_factory=lambda: GatePolicy())
    triage: TriagePolicy | None = None


# ── Release gate check protocol ────────────────────────────────────────


class ReleaseGateCheck(Protocol):
    """Protocol satisfied by any callable that accepts CheckContext and returns CheckResult."""

    def __call__(self, ctx: CheckContext) -> CheckResult: ...


# ── Gate policy ────────────────────────────────────────────────────────


@dataclass
class GatePolicyOverrides:
    check_id: str
    severity: GateSeverity | None = None
    release_blocking: bool | None = None


@dataclass
class GatePolicy:
    required_checks: list[str] = field(default_factory=list)
    overrides: list[GatePolicyOverrides] = field(default_factory=list)
    artifact_allowlist: list[str] = field(default_factory=list)
    cache_policy: str = "default"
    strict_warnings_exit_nonzero: bool = False
    triage: TriagePolicy | None = None

    def is_required(self, check_id: str) -> bool:
        return check_id in self.required_checks

    def override_for(self, check_id: str) -> GatePolicyOverrides | None:
        for ov in self.overrides:
            if ov.check_id == check_id:
                return ov
        return None

    def is_release_blocking(self, check_id: str) -> bool:
        ov = self.override_for(check_id)
        if ov is not None and ov.release_blocking is not None:
            return ov.release_blocking
        return False


# ── Gate result ────────────────────────────────────────────────────────


@dataclass
class GateSummary:
    total_checks: int = 0
    passed: int = 0
    failed: int = 0
    warning: int = 0
    skipped: int = 0
    total_findings: int = 0
    findings_by_severity: dict[str, int] = field(default_factory=dict)


@dataclass
class GateResult:
    schema_version: str = "rig.release_evidence_gate.v1"
    gate_id: str = ""
    repository: str = ""
    head_sha: str = ""
    branch: str = ""
    generated_at: str = ""
    overall_status: GateStatus = GateStatus.SKIPPED
    summary: GateSummary = field(default_factory=GateSummary)
    checks: list[dict[str, Any]] = field(default_factory=list)
    findings: list[dict[str, Any]] = field(default_factory=list)
    artifacts: list[str] = field(default_factory=list)
    policy: dict[str, Any] = field(default_factory=dict)

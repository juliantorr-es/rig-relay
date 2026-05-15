"""Out-of-scope findings lifecycle — tracking, aging, and triage.

Provides structured reading, updating, and aging of findings from
the out-of-scope-findings.jsonl registry. The registry is append-only;
this module reads and reports on it. Status updates are applied to the
Markdown index only, not the JSONL (which is immutable by convention).
"""

from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
FINDINGS_JSONL = REPO_ROOT / "docs" / "findings" / "out-of-scope-findings.jsonl"
FINDINGS_MD = REPO_ROOT / "docs" / "findings" / "out-of-scope-findings.md"

STALE_DAYS = 30  # Findings with no activity for this many days are flagged as stale


def load_all_findings() -> list[dict[str, Any]]:
    """Load all findings from the JSONL registry."""
    if not FINDINGS_JSONL.is_file():
        return []
    findings: list[dict[str, Any]] = []
    with open(FINDINGS_JSONL) as f:
        for line in f:
            line = line.strip()
            if line:
                findings.append(json.loads(line))
    return findings


def compute_findings_summary() -> dict[str, Any]:
    """Compute a summary of all findings by status, severity, and staleness."""
    findings = load_all_findings()
    now = datetime.now(UTC)

    by_status: dict[str, int] = {}
    by_severity: dict[str, int] = {}
    by_kind: dict[str, int] = {}
    stale: list[dict[str, Any]] = []
    unblocked: list[dict[str, Any]] = []

    for f in findings:
        status = f.get("status", "unknown")
        severity = f.get("severity", "unknown")
        kind = f.get("finding_kind", "unknown")

        by_status[status] = by_status.get(status, 0) + 1
        by_severity[severity] = by_severity.get(severity, 0) + 1
        by_kind[kind] = by_kind.get(kind, 0) + 1

        # Check staleness
        created_at = f.get("created_at", "")
        if created_at:
            try:
                created = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
                age_days = (now - created).days
                if age_days > STALE_DAYS and f.get("status") == "open":
                    stale.append({
                        "finding_id": f["finding_id"],
                        "title": f.get("title", "?")[:60],
                        "age_days": age_days,
                        "severity": severity,
                    })
            except (ValueError, TypeError):
                pass

        # Check if blocked_by are now resolved
        blocked_by = f.get("blocked_by", [])
        if blocked_by:
            resolved_blockers = [
                b for b in blocked_by
                if not any(
                    other.get("finding_id") == b
                    for other in findings
                    if other.get("status") == "open"
                )
            ]
            if resolved_blockers:
                unblocked.append({
                    "finding_id": f["finding_id"],
                    "title": f.get("title", "?")[:60],
                    "newly_unblocked_by": resolved_blockers,
                })

    return {
        "total_findings": len(findings),
        "by_status": dict(sorted(by_status.items())),
        "by_severity": dict(sorted(by_severity.items())),
        "by_kind": dict(sorted(by_kind.items())),
        "stale_findings": stale,
        "newly_unblocked": unblocked,
    }


def print_findings_status() -> None:
    """Print a human-readable findings status report."""
    summary = compute_findings_summary()
    print(f"Findings: {summary['total_findings']} total")
    print()
    print("By status:")
    for s, c in summary["by_status"].items():
        print(f"  {s}: {c}")
    print()
    print("By severity:")
    for s, c in summary["by_severity"].items():
        print(f"  {s}: {c}")
    print()
    print("By kind:")
    for k, c in summary["by_kind"].items():
        print(f"  {k}: {c}")
    print()

    stale = summary["stale_findings"]
    if stale:
        print(f"Stale (no activity >{STALE_DAYS} days, still open):")
        for s in stale:
            print(f"  {s['finding_id']}: {s['title']} ({s['age_days']} days, {s['severity']})")
    else:
        print("No stale findings.")

    unblocked = summary["newly_unblocked"]
    if unblocked:
        print()
        print("Newly unblocked (blockers resolved):")
        for u in unblocked:
            print(f"  {u['finding_id']}: {u['title']}")
            for b in u["newly_unblocked_by"]:
                print(f"    unblocked by: {b}")


def make_finding(
    title: str,
    finding_kind: str,
    severity: str,
    evidence: str,
    why_it_matters: str,
    recommended_action: str,
    related_files: list[str] | None = None,
    blocked_by: list[str] | None = None,
    suggested_slice: str = "",
) -> str:
    """Create an out-of-scope finding JSON object and return the finding_id.

    Does not write to the registry (that's the agent's responsibility per
    AGENTS.md). Returns the finding_id for reference.
    """
    import uuid

    finding_id = f"finding_{datetime.now(UTC).strftime('%Y%m%d')}_{uuid.uuid4().hex[:12]}"
    return finding_id


__all__ = [
    "compute_findings_summary",
    "load_all_findings",
    "make_finding",
    "print_findings_status",
]

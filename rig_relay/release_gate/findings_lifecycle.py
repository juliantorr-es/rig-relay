"""Release Evidence Gate — Findings Lifecycle v0.

Policy loader, schema validator, matching engine, and lifecycle applicator
for release gate findings. Each finding is classified by exact finding_id +
check_id match. Lifecycle state, severity override, and release-blocking
override are applied deterministically. Expired entries are reported but
do not suppress or downgrade findings.

Architecture:
    load_lifecycle_policy()  — loads and schema-validates a lifecycle policy JSON
    apply_lifecycle()        — applies policy to flattened findings, returns
                               enriched findings + lifecycle report
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from rig_relay.release_gate.models import (
    CheckSeverity,
    LifecycleApplication,
    LifecycleEntry,
    LifecyclePolicy,
    LifecycleReport,
    LifecycleState,
    _today_str,
)


def load_lifecycle_policy(
    policy_path: Path | None = None, *, schema_path: Path | None = None
) -> LifecyclePolicy:
    """Load and schema-validate a lifecycle policy from JSON.

    Returns an empty LifecyclePolicy if no path is given or the file
    is missing. Raises ValueError for schema validation failures.
    """
    if policy_path is None:
        return LifecyclePolicy()

    if not policy_path.is_file():
        return LifecyclePolicy()

    raw = json.loads(policy_path.read_text(encoding="utf-8"))

    if schema_path is not None and schema_path.is_file():
        _validate_against_schema(raw, schema_path)

    policy = LifecyclePolicy(
        schema_version=raw.get("schema_version", ""),
        policy_id=raw.get("policy_id", ""),
        description=raw.get("description", ""),
        updated_at=raw.get("updated_at", ""),
        entries=[_parse_entry(e) for e in raw.get("entries", [])],
    )
    policy.build_index()
    return policy


def apply_lifecycle(
    findings: list[dict[str, Any]], policy: LifecyclePolicy
) -> tuple[list[dict[str, Any]], LifecycleReport]:
    """Apply lifecycle policy to flattened gate findings.

    Returns (enriched_findings, lifecycle_report). Findings are NEVER
    deleted — they are enriched with lifecycle metadata. The lifecycle
    report tracks applied, expired, unmatched, and invalid entries.
    """
    report = LifecycleReport(
        policy_id=policy.policy_id,
        schema_version=policy.schema_version,
        entries_loaded=len(policy.entries),
    )
    today = _today_str()

    applied_ids: set[tuple[str, str]] = set()
    expired_count = 0

    enriched: list[dict[str, Any]] = []
    for f in findings:
        finding_id = str(f.get("finding_id", ""))
        check_id = str(f.get("check_id", ""))
        orig_severity = CheckSeverity(str(f.get("severity", "medium")))

        entry = policy.lookup(finding_id, check_id)
        app = _build_application(finding_id, check_id, entry, orig_severity, today)

        if app.matched and entry is not None:
            applied_ids.add((finding_id, check_id))
            if app.expired:
                expired_count += 1

        enriched.append(_enrich_finding(f, app))

    unmatched = [
        (e.finding_id, e.check_id)
        for e in policy.entries
        if (e.finding_id, e.check_id) not in applied_ids
    ]

    report.entries_applied = len(applied_ids)
    report.entries_expired = expired_count
    report.entries_unmatched = len(unmatched)

    if unmatched:
        report.policy_findings.append({
            "finding_id": "lifecycle.unmatched_entries",
            "check_id": "release_gate",
            "category": "findings_lifecycle",
            "description": f"{len(unmatched)} lifecycle policy entries did not match any gate finding",
            "severity": "low",
            "source": "findings_lifecycle.apply_lifecycle",
            "recommendation": "Review unmatched entries. They may reference resolved or renamed findings.",
            "details": [
                {"finding_id": fid, "check_id": cid} for fid, cid in unmatched[:20]
            ],
        })

    return enriched, report


def _parse_entry(raw: dict[str, Any]) -> LifecycleEntry:
    return LifecycleEntry(
        finding_id=raw["finding_id"],
        check_id=raw["check_id"],
        lifecycle_state=LifecycleState(raw["lifecycle_state"]),
        reason=raw["reason"],
        owner=raw["owner"],
        severity_override=(
            CheckSeverity(raw["severity_override"])
            if raw.get("severity_override")
            else None
        ),
        release_blocking_override=raw.get("release_blocking_override"),
        expires=raw.get("expires", ""),
        evidence_refs=raw.get("evidence_refs", []),
    )


def _build_application(
    finding_id: str,
    check_id: str,
    entry: LifecycleEntry | None,
    original_severity: CheckSeverity,
    today: str,
) -> LifecycleApplication:
    if entry is None:
        return LifecycleApplication(
            finding_id=finding_id,
            check_id=check_id,
            matched=False,
            original_severity=original_severity,
            effective_severity=original_severity,
            release_blocking=_is_release_blocking(original_severity, None),
        )

    expired = entry.is_expired(today)
    lifecycle_state = entry.lifecycle_state.value

    effective_severity = original_severity
    release_blocking = _is_release_blocking(original_severity, entry)

    if not expired:
        match entry.lifecycle_state:
            case LifecycleState.ACCEPTED_FALSE_POSITIVE:
                effective_severity = entry.severity_override or CheckSeverity.INFO
                release_blocking = (
                    entry.release_blocking_override
                    if entry.release_blocking_override is not None
                    else False
                )
            case LifecycleState.INTENTIONAL_DEFERRED:
                effective_severity = entry.severity_override or CheckSeverity.INFO
                release_blocking = (
                    entry.release_blocking_override
                    if entry.release_blocking_override is not None
                    else False
                )
            case LifecycleState.NOT_APPLICABLE:
                effective_severity = CheckSeverity.INFO
                release_blocking = False
            case LifecycleState.KNOWN_DEBT:
                effective_severity = entry.severity_override or original_severity
                release_blocking = (
                    entry.release_blocking_override
                    if entry.release_blocking_override is not None
                    else _is_release_blocking(original_severity, None)
                )
            case LifecycleState.NEEDS_FIX:
                effective_severity = entry.severity_override or original_severity
                release_blocking = True
            case LifecycleState.WATCH:
                effective_severity = entry.severity_override or CheckSeverity.LOW
                release_blocking = False

    if entry.severity_override is not None and not expired:
        effective_severity = entry.severity_override

    if entry.release_blocking_override is not None and not expired:
        release_blocking = entry.release_blocking_override

    return LifecycleApplication(
        finding_id=finding_id,
        check_id=check_id,
        matched=True,
        entry=entry,
        expired=expired,
        original_severity=original_severity,
        effective_severity=effective_severity,
        release_blocking=release_blocking,
        lifecycle_state=lifecycle_state if not expired else "",
        triage_reason=entry.reason if not expired else f"[EXPIRED] {entry.reason}",
        triage_owner=entry.owner,
        triage_expires=entry.expires,
        triage_evidence_refs=entry.evidence_refs,
    )


def _is_release_blocking(severity: CheckSeverity, entry: LifecycleEntry | None) -> bool:
    return severity in {CheckSeverity.BLOCKER, CheckSeverity.HIGH}


def _enrich_finding(raw: dict[str, Any], app: LifecycleApplication) -> dict[str, Any]:
    enriched: dict[str, Any] = dict(raw)
    enriched["original_severity"] = app.original_severity.value
    enriched["effective_severity"] = app.effective_severity.value
    enriched["lifecycle_state"] = app.lifecycle_state
    enriched["release_blocking"] = app.release_blocking
    enriched["triage_reason"] = app.triage_reason
    enriched["triage_owner"] = app.triage_owner
    enriched["triage_expires"] = app.triage_expires
    enriched["triage_evidence_refs"] = app.triage_evidence_refs
    enriched["triage_expired"] = app.expired
    return enriched


def _validate_against_schema(raw: dict[str, Any], schema_path: Path) -> None:
    import jsonschema

    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    jsonschema.validate(raw, schema)


def build_lifecycle_report_dict(report: LifecycleReport) -> dict[str, Any]:
    return {
        "policy_id": report.policy_id,
        "schema_version": report.schema_version,
        "entries_loaded": report.entries_loaded,
        "entries_applied": report.entries_applied,
        "entries_expired": report.entries_expired,
        "entries_unmatched": report.entries_unmatched,
        "invalid_entries": report.invalid_entries,
        "policy_findings": report.policy_findings,
    }

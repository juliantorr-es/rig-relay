"""Report tool name, constants, and helpers for the rig.report built-in tool."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any
from uuid import uuid4

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
DEFAULT_LEDGER_DIR = REPO_ROOT / ".rig" / "reports"
DEFAULT_LEDGER_PATH = DEFAULT_LEDGER_DIR / "reports.jsonl"

REPORT_KINDS = frozenset({
    "mission_report",
    "out_of_scope_finding",
    "bug_report",
    "architecture_seam",
    "implementation_seam",
    "data_race",
    "security_concern",
    "validation_gap",
    "test_gap",
    "tooling_gap",
    "context_gap",
    "coordination_gap",
    "regression_risk",
    "handoff_note",
})

SEVERITY_LEVELS = frozenset({"low", "medium", "high", "critical"})
CONFIDENCE_LEVELS = frozenset({"low", "medium", "high", "confirmed"})
SCOPE_RELATIONS = frozenset({
    "in_scope",
    "out_of_scope_for_current_mission",
    "adjacent",
    "regression",
    "pre_existing",
})
STATUSES = frozenset({
    "open",
    "acknowledged",
    "triaged",
    "accepted",
    "deferred",
    "blocked",
    "in_progress",
    "resolved",
    "wont_fix",
    "superseded",
    "duplicate",
    "invalid",
})


def generate_report_id() -> str:
    """Generate a stable, unique report identifier."""
    return f"report_{uuid4().hex[:16]}"


def derive_dedupe_key(report: dict[str, Any]) -> str:
    """Derive a stable deduplication key from the report content.

    Uses kind + title + sorted affected_paths.
    """
    kind = report.get("kind", "unknown")
    title = report.get("title", "")
    paths = sorted(report.get("affected_paths", []))
    raw = f"{kind}:{title}:{json.dumps(paths, sort_keys=True)}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def compute_report_sha256(report: dict[str, Any]) -> str:
    """Compute the SHA256 hash of the canonical JSON report."""
    raw = json.dumps(report, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def write_report_to_ledger(
    report: dict[str, Any], ledger_path: Path = DEFAULT_LEDGER_PATH
) -> Path:
    """Append a report to the JSONL ledger. Creates the directory if needed.

    Returns the ledger path.
    """
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(report, sort_keys=True, ensure_ascii=False)
    with open(ledger_path, "a") as f:
        f.write(line + "\n")
    return ledger_path


def find_existing_report(
    dedupe_key: str, ledger_path: Path = DEFAULT_LEDGER_PATH
) -> dict[str, Any] | None:
    """Check if a report with the given dedupe_key already exists.

    Scans the ledger for an exact dedupe_key match. Returns the first
    match found, or None.
    """
    if not ledger_path.is_file():
        return None
    with open(ledger_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                existing = json.loads(line)
                if existing.get("dedupe_key") == dedupe_key:
                    return existing
            except (json.JSONDecodeError, KeyError):
                continue
    return None

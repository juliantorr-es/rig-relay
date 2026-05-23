"""Issue-ledger work orchestration for the OpenCode steward.

Owns: reading the repo-local issue ledger, materializing issue prompts,
and converting open issues into roadmap-shaped steward work items.
Does not own: queue selection, execution, coordination events, or docs rendering.
"""

from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any

from rig_relay.cli._steward._constants import PROMPTS_DIR, now_iso, read_jsonl, sha256

ISSUE_LEDGER_PATH = Path("docs/json/issues/issue_ledger.v1.jsonl")
_ISSUE_PROMPTS_DIR = f"{PROMPTS_DIR}/issues"
_OPEN_STATUSES = frozenset({"open", "in_progress", "blocked"})
_TERMINAL_STATUSES = frozenset({
    "resolved",
    "accepted",
    "deferred",
    "wont_fix",
    "superseded",
})
_PRIORITY_RANK = {"p0": 0, "p1": 10, "p2": 20, "p3": 30}


def read_issue_ledger(root: Path) -> list[dict[str, Any]]:
    return read_jsonl(root / ISSUE_LEDGER_PATH)


def append_issue_ledger_row(root: Path, row: dict[str, Any]) -> None:
    ledger_path = root / ISSUE_LEDGER_PATH
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    with ledger_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def _issue_slug(issue_id: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "-", issue_id).strip("._-")
    if slug:
        return slug
    return f"issue-{sha256(issue_id)[:12]}"


def issue_prompt_path(issue: dict[str, Any]) -> str:
    return f"{_ISSUE_PROMPTS_DIR}/{_issue_slug(str(issue.get('issue_id', '')))}.txt"


def _priority_rank(priority: Any) -> int:
    if isinstance(priority, str):
        return _PRIORITY_RANK.get(priority.lower(), 99)
    return 99


def _latest_issue_rows(issues: list[dict[str, Any]]) -> list[dict[str, Any]]:
    latest: dict[str, tuple[int, dict[str, Any]]] = {}
    for index, issue in enumerate(issues):
        issue_id = str(issue.get("issue_id", ""))
        if not issue_id:
            continue
        latest[issue_id] = (index, issue)
    return [issue for _, issue in sorted(latest.values(), key=lambda item: item[0])]


def _queue_status(issue_status: Any) -> str | None:
    if issue_status in _OPEN_STATUSES:
        if issue_status == "blocked":
            return "blocked"
        return "queued"
    if issue_status in _TERMINAL_STATUSES:
        return None
    return None


def issue_prompt_text(issue: dict[str, Any]) -> str:
    lines = [
        "Resolve this tracked issue in a narrow, additive repo-local slice.",
        "",
        f"Issue ID: {issue.get('issue_id', '')}",
        f"Tracker: {issue.get('tracker_id', '')}",
        f"Area: {issue.get('area', '')}",
        f"Severity: {issue.get('severity', '')}",
        f"Priority: {issue.get('priority', '')}",
        f"Status: {issue.get('status', '')}",
        "",
        f"Title: {issue.get('title', '')}",
        "",
        "Summary:",
        str(issue.get("summary", "")),
        "",
        "Why it matters:",
        str(issue.get("why_it_matters", "")),
        "",
        "Recommended action:",
        str(issue.get("recommended_action", "")),
        "",
        "Evidence:",
        str(issue.get("evidence", "")),
    ]
    related_files = issue.get("related_files") or []
    if related_files:
        lines.extend(["", "Related files:"])
        for rel in related_files:
            lines.append(f"- {rel}")
    validation_commands = issue.get("validation_commands") or []
    if validation_commands:
        lines.extend(["", "Validation commands:"])
        for cmd in validation_commands:
            lines.append(f"- {cmd}")
    blocked_by = issue.get("blocked_by") or []
    if blocked_by:
        lines.extend(["", "Blocked by:"])
        for blocker in blocked_by:
            lines.append(f"- {blocker}")
    lines.extend([
        "",
        "Constraints:",
        "- Preserve unrelated dirty work.",
        "- Keep the change scoped and additive.",
        "- Add or update tests that prove the fix.",
    ])
    return "\n".join(lines).strip() + "\n"


def materialize_issue_prompt(root: Path, issue: dict[str, Any]) -> str:
    rel_path = issue_prompt_path(issue)
    path = root / rel_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(issue_prompt_text(issue), encoding="utf-8")
    return rel_path


def issue_to_queue_item(root: Path, issue: dict[str, Any]) -> dict[str, Any] | None:
    issue_status = issue.get("status")
    queue_status = _queue_status(issue_status)
    if queue_status is None:
        return None
    rel_prompt_path = materialize_issue_prompt(root, issue)
    related_files = [str(path) for path in issue.get("related_files") or []]
    validation_commands = [str(cmd) for cmd in issue.get("validation_commands") or []]
    return {
        "schema_version": "rig.relay.opencode_roadmap_queue_item.v1",
        "task_id": str(issue.get("issue_id", "")),
        "status": queue_status,
        "priority": _priority_rank(issue.get("priority")),
        "prompt_path": rel_prompt_path,
        "title": str(issue.get("title", issue.get("issue_id", ""))),
        "agent": "build",
        "allowed_files": related_files,
        "forbidden_files": [],
        "stop_on_dirty_overlap": True,
        "issue_id": str(issue.get("issue_id", "")),
        "issue_status": issue_status,
        "issue_priority": issue.get("priority", ""),
        "issue_severity": issue.get("severity", ""),
        "issue_kind": issue.get("issue_kind", ""),
        "issue_area": issue.get("area", ""),
        "source_kind": "issue_ledger",
        "source_tracker_id": str(issue.get("tracker_id", "")),
        "source_label": str(issue.get("source_label", "")),
        "related_files": related_files,
        "validation_commands": validation_commands,
        "recommended_action": str(issue.get("recommended_action", "")),
    }


def _is_match(validation_run: dict[str, Any], issue: dict[str, Any]) -> bool:
    issue_id = str(issue.get("issue_id", ""))
    command = " ".join(str(validation_run.get("command", "")).split())
    evidence_paths = "\n".join(
        str(path) for path in validation_run.get("evidence_paths") or []
    )
    validation_run_id = str(validation_run.get("validation_run_id", ""))

    if issue_id and (
        issue_id == validation_run_id
        or issue_id in command
        or issue_id in evidence_paths
    ):
        return True

    for expected in issue.get("validation_commands") or []:
        expected_command = " ".join(str(expected).split())
        if not expected_command:
            continue
        if expected_command == command:
            return True
        if expected_command in command or command in expected_command:
            return True

    for related in issue.get("related_files") or []:
        related_text = str(related)
        if not related_text:
            continue
        if related_text in command or related_text in evidence_paths:
            return True

    for phase_id in validation_run.get("phase_ids") or []:
        if issue_id and str(phase_id) == issue_id:
            return True

    return False


def _resolved_summary(issue: dict[str, Any]) -> str:
    summary = str(issue.get("summary", "")).strip()
    if summary.startswith("Open."):
        return "Resolved." + summary[len("Open.") :]
    if summary:
        return f"Resolved. {summary}"
    title = str(issue.get("title", issue.get("issue_id", ""))).strip()
    return f"Resolved. {title}" if title else "Resolved."


def _resolution_text(validation_run: dict[str, Any]) -> str:
    validation_run_id = str(validation_run.get("validation_run_id", "")).strip()
    command = " ".join(str(validation_run.get("command", "")).split())
    if validation_run_id and command:
        return f"Validation run {validation_run_id} passed: {command}"
    if validation_run_id:
        return f"Validation run {validation_run_id} passed"
    if command:
        return f"Validation command passed: {command}"
    return "Validation evidence passed."


def reconcile_issue_ledger(
    root: Path, validation_run: dict[str, Any], *, issue_id: str | None = None
) -> dict[str, Any]:
    result = str(validation_run.get("result", "")).strip().lower()
    if result != "passed":
        return {
            "status": "skipped",
            "reason": "validation_run_not_passed",
            "resolved_issue_ids": [],
            "matched_issue_ids": [],
            "validation_run_id": str(validation_run.get("validation_run_id", "")),
        }

    latest_issues = _latest_issue_rows(read_issue_ledger(root))
    if issue_id:
        candidates = [
            issue
            for issue in latest_issues
            if str(issue.get("issue_id", "")) == issue_id
            and issue.get("status") in _OPEN_STATUSES
        ]
    else:
        candidates = [
            issue
            for issue in latest_issues
            if issue.get("status") in _OPEN_STATUSES
            and _is_match(validation_run, issue)
        ]

    resolved_issue_ids: list[str] = []
    for issue in candidates:
        resolved_row = dict(issue)
        resolved_row["status"] = "resolved"
        resolved_row["summary"] = _resolved_summary(issue)
        resolved_row["resolution"] = _resolution_text(validation_run)
        resolved_row["resolved_at"] = str(validation_run.get("created_at", now_iso()))
        resolved_row["updated_at"] = now_iso()
        resolved_row["verification_state"] = "verified"
        append_issue_ledger_row(root, resolved_row)
        resolved_issue_ids.append(str(issue.get("issue_id", "")))

    return {
        "status": "resolved" if resolved_issue_ids else "no_match",
        "reason": "validation_run_passed",
        "validation_run_id": str(validation_run.get("validation_run_id", "")),
        "command": str(validation_run.get("command", "")),
        "matched_issue_ids": [str(issue.get("issue_id", "")) for issue in candidates],
        "resolved_issue_ids": resolved_issue_ids,
    }


def read_issue_work_items(root: Path) -> list[dict[str, Any]]:
    issues = _latest_issue_rows(read_issue_ledger(root))
    work_items: list[dict[str, Any]] = []
    for issue in sorted(
        issues,
        key=lambda issue: (
            _priority_rank(issue.get("priority")),
            str(issue.get("created_at", "")),
            str(issue.get("issue_id", "")),
        ),
    ):
        item = issue_to_queue_item(root, issue)
        if item is not None:
            work_items.append(item)
    return work_items


__all__ = [
    "ISSUE_LEDGER_PATH",
    "append_issue_ledger_row",
    "issue_prompt_path",
    "issue_prompt_text",
    "issue_to_queue_item",
    "materialize_issue_prompt",
    "read_issue_ledger",
    "read_issue_work_items",
    "reconcile_issue_ledger",
]

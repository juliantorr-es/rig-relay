"""Bash row normalization and pattern/risk tagging for the analytical compiler.

Normalizes raw bash invocation records into fact_bash_invocations rows with
deterministic pattern tags, risk tags, and replacement candidates.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

# ── Command family detection ────────────────────────────────────

_COMMAND_FAMILIES: dict[str, set[str]] = {
    "git_status": {"git", "status"},
    "git_diff": {"git", "diff"},
    "git_log": {"git", "log"},
    "git_show": {"git", "show"},
    "git_branch": {"git", "branch"},
    "git": {"git"},
    "pytest": {"pytest"},
    "ruff": {"ruff"},
    "pyright": {"pyright"},
    "rg": {"rg", "ripgrep"},
    "fd": {"fd"},
    "cat": {"cat"},
    "sed": {"sed"},
    "awk": {"awk"},
    "jq": {"jq"},
    "find": {"find"},
    "ls": {"ls"},
    "mkdir": {"mkdir"},
    "cp": {"cp"},
    "mv": {"mv"},
    "rm": {"rm"},
    "chmod": {"chmod"},
    "curl": {"curl"},
    "sleep": {"sleep"},
    "sudo": {"sudo"},
}


def detect_command_family(command_text: str) -> str:
    """Detect the command family from the command text.

    Checks argv tokens against known families. Returns the first match,
    or 'other' for unknown commands.
    """
    tokens = command_text.split()
    if not tokens:
        return "other"

    # Try to match the base command (first token after sudo, or first token)
    start = 1 if tokens[0] == "sudo" and len(tokens) > 1 else 0
    cmd = tokens[start] if start < len(tokens) else tokens[0]

    # Check for git subcommands
    if cmd == "git" and len(tokens) > start + 1:
        sub = tokens[start + 1]
        family = f"git_{sub}"
        if family in _COMMAND_FAMILIES:
            return family
        return "git"

    # Direct match
    for family in sorted(_COMMAND_FAMILIES.keys(), key=len, reverse=True):
        if family == cmd:
            return family

    return "other"


def detect_pattern_tags(command_text: str) -> list[str]:
    """Detect pattern tags from the command text."""
    tags: list[str] = []
    tokens = command_text.split()
    if not tokens:
        return tags

    family = detect_command_family(command_text)
    if family != "other":
        parts = family.split("_")
        tags.extend(parts)

    # Shell features
    if "|" in command_text:
        tags.append("shell_pipe")
    if ">" in command_text:
        tags.append("shell_redirect")
    if any(c in command_text for c in "*?[]"):
        tags.append("shell_glob")
    if "$(" in command_text or "`" in command_text:
        tags.append("subshell")
    if "python" in command_text and "-c" in command_text:
        tags.append("python_heredoc")
    if "&&" in command_text or ";" in command_text:
        tags.append("subshell")

    # Specific tools
    if "rg " in command_text or "ripgrep" in command_text:
        tags.append("rg")

    return tags


def detect_risk_tags(
    command_text: str, record: dict[str, Any] | None = None
) -> list[str]:
    """Detect risk tags from the command text and optional record fields."""
    tags: list[str] = []
    tokens = command_text.split()

    if not tokens:
        return tags

    # Shell usage
    for shell in ("bash", "sh", "zsh", "dash", "fish"):
        if tokens[0] == shell:
            tags.append("uses_shell")
            break

    if any(t == "sudo" for t in tokens):
        tags.append("uses_sudo")

    # Destructive file operations
    if any(t in {"rm", "rmdir", "mv"} for t in tokens):
        tags.append("mutates_repo")
        if "rm" in tokens:
            tags.append("uses_rm")
        if "-rf" in command_text or "-fr" in command_text:
            tags.append("uses_recursive_delete")
        if "-f" in command_text:
            tags.append("uses_force")

    if "chmod" in tokens:
        tags.append("mutates_repo")

    # Network
    for tool in ("curl", "wget", "nc", "netcat", "ssh", "scp", "rsync"):
        if tokens[0] == tool:
            tags.append("uses_network")
            break

    if "sleep" in tokens:
        tags.append("sleep")
    if "&" in command_text and "&&" not in command_text:
        tags.append("uses_background_process")

    # Timeout risk from record
    if record:
        if record.get("status") == "timed_out":
            tags.append("timeout_prone")
        stdout_bytes = record.get("stdout_bytes", 0) or 0
        if stdout_bytes > 100_000:
            tags.append("large_output")

    return tags


def detect_replacement_candidate(command_text: str) -> str | None:
    """Detect if this bash command should be a deterministic built-in tool.

    Returns the proposed tool name, or None.
    """
    family = detect_command_family(command_text)

    replacement_map = {
        "git_status": "git_status",
        "git_diff": "git_diff",
        "git_log": "git_log",
        "git_show": "git_show",
        "git_branch": "git_branch",
        "rg": "grep",
        "cat": "read_file",
    }

    return replacement_map.get(family)


# ── Normalization ───────────────────────────────────────────────


def normalize_bash_record(record: dict[str, Any]) -> dict[str, Any]:
    """Normalize a raw bash invocation record into a tabular fact row."""
    command_text = record.get("command_text", record.get("command", ""))
    command_sha256 = hashlib.sha256(command_text.encode("utf-8")).hexdigest()
    family = detect_command_family(command_text)
    status = record.get("status", "unknown")
    pattern_tags = detect_pattern_tags(command_text)
    risk_tags = detect_risk_tags(command_text, record)
    replacement = detect_replacement_candidate(command_text)
    mutation = record.get("mutation_detected", False)

    stdout_bytes = record.get("stdout_bytes", 0) or 0
    stderr_bytes = record.get("stderr_bytes", 0) or 0

    return {
        "bash_invocation_id": record.get(
            "bash_invocation_id", record.get("event_id", "")
        ),
        "event_name": record.get("event_name", "rig.bash.invocation.completed"),
        "session_id": record.get("session_id", ""),
        "turn_id": record.get("turn_id", ""),
        "tool_call_id": record.get("tool_call_id", ""),
        "agent_id": record.get("agent_id", ""),
        "mission_id": record.get("mission_id", ""),
        "created_at": record.get("created_at", record.get("captured_at", "")),
        "cwd": record.get("cwd", ""),
        "command_text": command_text,
        "command_sha256": command_sha256,
        "command_family": family,
        "shell_used": 1 if record.get("shell_used", False) else 0,
        "timeout_seconds": record.get("timeout", record.get("timeout_seconds", 0)),
        "duration_ms": record.get("duration_ms", 0),
        "exit_code": record.get("exit_code", -1),
        "status": status,
        "stdout_bytes": stdout_bytes,
        "stderr_bytes": stderr_bytes,
        "stdout_sha256": record.get("stdout_sha256", ""),
        "stderr_sha256": record.get("stderr_sha256", ""),
        "mutation_detected": 1 if mutation else 0,
        "affected_path_count": len(record.get("affected_paths", [])),
        "pattern_tags_json": json.dumps(pattern_tags),
        "risk_tags_json": json.dumps(risk_tags),
        "refusal_reason": record.get("refusal_reason", record.get("error_kind", "")),
        "receipt_id": record.get("receipt_id", ""),
        "replacement_candidate": replacement or "",
        "is_success": 1 if status == "completed" else 0,
        "is_failure": 1 if status in {"failed", "failure"} else 0,
        "is_timeout": 1 if status == "timed_out" else 0,
        "is_refusal": 1 if status == "refused" else 0,
        "is_validation_command": 1 if family in {"pytest", "ruff", "pyright"} else 0,
        "is_git_command": 1 if family.startswith("git") else 0,
        "is_search_command": 1 if family in {"rg", "fd", "jq"} else 0,
        "is_python_heredoc": 1
        if "python" in command_text and "-c" in command_text
        else 0,
        "is_destructive_candidate": 1
        if "mutates_repo" in risk_tags or "uses_rm" in risk_tags
        else 0,
        "is_replacement_candidate": 1 if replacement is not None else 0,
    }


def create_bash_invocations_table(con: Any, records: list[dict[str, Any]]) -> None:
    """Create the fact_bash_invocations table from normalized records."""
    if records:
        con.execute(
            f"CREATE OR REPLACE TABLE fact_bash_invocations AS "
            f"SELECT * FROM ({_build_values_sql(records)}) AS t"
        )
    else:
        con.execute(
            "CREATE TABLE IF NOT EXISTS fact_bash_invocations ("
            "bash_invocation_id VARCHAR, event_name VARCHAR, "
            "session_id VARCHAR, turn_id VARCHAR, tool_call_id VARCHAR, "
            "agent_id VARCHAR, mission_id VARCHAR, created_at VARCHAR, "
            "cwd VARCHAR, command_text VARCHAR, command_sha256 VARCHAR, "
            "command_family VARCHAR, shell_used INTEGER, "
            "timeout_seconds INTEGER, duration_ms INTEGER, "
            "exit_code INTEGER, status VARCHAR, "
            "stdout_bytes INTEGER, stderr_bytes INTEGER, "
            "stdout_sha256 VARCHAR, stderr_sha256 VARCHAR, "
            "mutation_detected INTEGER, affected_path_count INTEGER, "
            "pattern_tags_json VARCHAR, risk_tags_json VARCHAR, "
            "refusal_reason VARCHAR, receipt_id VARCHAR, "
            "replacement_candidate VARCHAR, "
            "is_success INTEGER, is_failure INTEGER, is_timeout INTEGER, "
            "is_refusal INTEGER, is_validation_command INTEGER, "
            "is_git_command INTEGER, is_search_command INTEGER, "
            "is_python_heredoc INTEGER, "
            "is_destructive_candidate INTEGER, is_replacement_candidate INTEGER)"
        )


def _build_values_sql(records: list[dict[str, Any]]) -> str:
    """Build a DuckDB VALUES clause from normalized records."""
    if not records:
        return "SELECT NULL LIMIT 0"

    columns = list(records[0].keys())
    rows: list[str] = []

    for rec in records:
        vals: list[str] = []
        for col in columns:
            v = rec.get(col)
            if v is None:
                vals.append("NULL")
            elif isinstance(v, int):
                vals.append(str(v))
            elif isinstance(v, float):
                vals.append(str(v))
            else:
                escaped = str(v).replace("'", "''")
                vals.append(f"'{escaped}'")
        rows.append("(" + ", ".join(vals) + ")")

    return "SELECT * FROM (VALUES " + ", ".join(rows) + f") AS t({', '.join(columns)})"

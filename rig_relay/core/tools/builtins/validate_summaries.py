"""Validate tool — parsed summary parsers.

Each parser reads stdout text from a known command family and returns a
content-light structured dict. Parser failure never fails validation —
None is returned for unparseable output.
"""

from __future__ import annotations

import json
import re


def _parse_ruff_summary(stdout: str) -> dict[str, object] | None:
    """Parse ruff check text output for structured summary.

    Extracts violation counts, rule code frequencies, and affected files.
    All data is content-light: no full messages, no raw diffs.

    Handles ruff's default text format:
        path:line:col: CODE message
    """
    if not stdout:
        return None
    lines = stdout.strip().split("\n")
    violations: list[dict[str, str]] = []
    for line in lines:
        # Match "path:line:col: CODE message" pattern
        parts = line.split(":", 3)
        if len(parts) >= 4:  # noqa: PLR2004
            file_part = parts[0]
            code_part = parts[3].strip().split(" ")[0] if parts[3] else ""
            violations.append({"file": file_part, "code": code_part})

    if not violations:
        return None

    # Count by rule code
    rule_counts: dict[str, int] = {}
    files_set: set[str] = set()
    for v in violations:
        rule_counts[v["code"]] = rule_counts.get(v["code"], 0) + 1
        files_set.add(v["file"])

    files_sorted = sorted(files_set)
    return {
        "parser_name": "ruff_text",
        "parser_status": "parsed",
        "violation_count": len(violations),
        "rule_counts": dict(sorted(rule_counts.items())),
        "files": files_sorted,
    }


def _parse_pyright_summary(stdout: str) -> dict[str, object] | None:
    """Parse pyright terminal summary line for structured summary.

    Handles forms like:
        0 errors, 0 warnings, 0 informations
        1 error, 2 warnings, 0 informations
    """
    if not stdout:
        return None
    # Take the last line with summary info
    lines = stdout.strip().split("\n")
    summary_line = ""
    for line in reversed(lines):
        if "error" in line and "warning" in line:
            summary_line = line
            break
    if not summary_line:
        return None

    errors = 0
    warnings = 0
    infos = 0
    err_match = re.search(r"(\d+)\s+error", summary_line)
    warn_match = re.search(r"(\d+)\s+warning", summary_line)
    info_match = re.search(r"(\d+)\s+information", summary_line)
    if err_match:
        errors = int(err_match.group(1))
    if warn_match:
        warnings = int(warn_match.group(1))
    if info_match:
        infos = int(info_match.group(1))

    return {
        "parser_name": "pyright_text",
        "parser_status": "parsed",
        "error_count": errors,
        "warning_count": warnings,
        "information_count": infos,
    }


def _parse_pytest_summary(stdout: str) -> dict[str, object] | None:
    """Parse pytest terminal summary for structured counts.

    Handles forms like:
        3 passed
        1 failed, 2 passed
        2 skipped, 1 xfailed
        1 passed, 1 failed, 2 skipped
    """
    if not stdout:
        return None

    lines = stdout.strip().split("\n")
    summary_line = ""
    for line in reversed(lines):
        stripped = line.strip()
        if any(kw in stripped for kw in ("passed", "failed", "skipped")):
            summary_line = stripped
            break
    if not summary_line:
        return None

    result: dict[str, object] = {
        "parser_name": "pytest_text",
        "parser_status": "parsed",
    }

    for key in ("passed", "failed", "skipped", "xfailed", "xpassed", "error"):
        match = re.search(r"(\d+)\s+" + re.escape(key), summary_line)
        if match:
            result[f"{key}_count"] = int(match.group(1))

    return result if any(k.endswith("_count") for k in result) else None


def _parse_schema_summary(stdout: str) -> dict[str, object] | None:
    """Parse schema validation script output for structured summary.

    Handles:
        Passed: N
        Failed: M
        Total: N+M
    or
        N/N schemas valid
    """
    if not stdout:
        return None

    lines = stdout.strip().split("\n")

    # Try "N/N schemas valid" format
    for line in lines:
        match = re.search(r"(\d+)/(\d+)\s+schemas\s+valid", line)
        if match:
            total = int(match.group(2))
            passed = int(match.group(1))
            return {
                "parser_name": "schema_text",
                "parser_status": "parsed",
                "valid_count": passed,
                "total_count": total,
                "failed_count": total - passed,
            }

    # Try "Passed: N" format
    passed = failed = total = 0
    for line in lines:
        pm = re.search(r"Passed:\s*(\d+)", line)
        fm = re.search(r"Failed:\s*(\d+)", line)
        if pm:
            passed = int(pm.group(1))
        if fm:
            failed = int(fm.group(1))

    if passed > 0 or failed > 0:
        return {
            "parser_name": "schema_text",
            "parser_status": "parsed",
            "valid_count": passed,
            "total_count": passed + failed,
            "failed_count": failed,
        }

    return None


def _parse_policy_summary(stdout: str) -> dict[str, object] | None:
    """Parse receipt policy validation output for structured summary.

    Handles JSON output with top-level counts, or text summary.
    """
    if not stdout:
        return None

    lines = stdout.strip().split("\n")
    result: dict[str, object] = {
        "parser_name": "policy_text",
        "parser_status": "unparsed",
    }

    # Try JSON extraction from any line
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("{"):
            try:
                data = json.loads(stripped)
                findings = data.get("findings") or data.get("violations") or []
                result = {
                    "parser_name": "policy_json",
                    "parser_status": "parsed",
                    "finding_count": len(findings) if isinstance(findings, list) else 0,
                }
                break
            except (json.JSONDecodeError, TypeError):
                continue

    # Fallback: count lines mentioning "finding" or "violation"
    if result["parser_status"] == "unparsed":
        finding_count = sum(1 for l in lines if "finding" in l.lower())
        violation_count = sum(1 for l in lines if "violation" in l.lower())
        if finding_count > 0 or violation_count > 0:
            result["finding_count"] = finding_count
            result["violation_count"] = violation_count
            result["parser_status"] = "parsed"

    return result if result.get("parser_status") == "parsed" else None


def _parse_check_summary(
    command_kind: str, stdout: str, stderr: str, exit_code: int
) -> dict[str, object] | None:
    """Dispatch to the appropriate parser for a check's command_kind.

    Parser failure never fails validation. Returns None for unparseable output.
    """
    if command_kind == "ruff":
        return _parse_ruff_summary(stdout)
    if command_kind == "pyright":
        return _parse_pyright_summary(stdout)
    if command_kind == "pytest":
        return _parse_pytest_summary(stdout)
    if command_kind == "schema":
        return _parse_schema_summary(stdout)
    if command_kind == "policy":
        return _parse_policy_summary(stdout)
    return None

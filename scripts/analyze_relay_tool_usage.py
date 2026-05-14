#!/usr/bin/env python3
"""Analyze local Relay evidence for tool usage and hardening priorities."""

from __future__ import annotations

import argparse
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
import gzip
import json
from pathlib import Path
from statistics import median
from typing import Any, TextIO

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_RELAY_ROOT = Path.home() / ".rig" / "relay"
DEFAULT_OUT_DIR = REPO_ROOT / "docs" / "audits" / "tool-usage-analysis"
RAW_CONTENT_KEYS = {
    "args",
    "arguments",
    "completion",
    "content",
    "diff",
    "output",
    "prompt",
    "source",
    "stderr",
    "stdout",
    "text",
    "transcript",
}
HIGH_RISK_TIER = 3


@dataclass
class ToolStats:
    tool_name: str
    count: int = 0
    success_count: int = 0
    failure_count: int = 0
    skipped_count: int = 0
    latencies: list[float] = field(default_factory=list)
    output_sizes: list[int] = field(default_factory=list)
    has_path: bool = False
    has_subprocess: bool = False
    has_network: bool = False
    has_git: bool = False
    may_expose_private_content: bool = False
    has_receipts: bool = False
    has_schema_validation: bool = False
    has_tests: bool = False
    risk_tier: int = 0

    def add_status(self, status: str) -> None:
        if status in {"success", "ok", "done", "passed"}:
            self.success_count += 1
        elif status in {"skipped", "noop", "no-op"}:
            self.skipped_count += 1
        elif status:
            self.failure_count += 1

    def add_latency(self, value: Any) -> None:
        try:
            self.latencies.append(float(value))
        except (TypeError, ValueError):
            pass

    def add_output_size(self, value: Any) -> None:
        try:
            self.output_sizes.append(int(value))
        except (TypeError, ValueError):
            pass

    def finalize(self) -> None:
        self.risk_tier = infer_risk_tier(self.tool_name)


def _open_text(path: Path) -> TextIO:
    if path.suffix == ".gz":
        return gzip.open(path, "rt", encoding="utf-8", errors="replace")
    return path.open("r", encoding="utf-8", errors="replace")


def _safe_json_loads(text: str) -> Any | None:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def _walk_files(
    root: Path, include_gz: bool = True, max_files: int | None = None
) -> list[Path]:
    files: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix == ".gz" and not include_gz:
            continue
        files.append(path)
        if max_files is not None and len(files) >= max_files:
            break
    return files


def _iter_records(path: Path) -> tuple[dict[str, Any], ...]:
    if path.suffix in {".jsonl", ".ndjson"} or path.name.endswith(".jsonl.gz"):
        records: list[dict[str, Any]] = []
        with _open_text(path) as handle:
            for line in handle:
                stripped = line.strip()
                if not stripped:
                    continue
                row = _safe_json_loads(stripped)
                if isinstance(row, dict):
                    records.append(row)
        return tuple(records)
    if path.suffix == ".json":
        data = _safe_json_loads(path.read_text(encoding="utf-8", errors="replace"))
        if isinstance(data, dict):
            if isinstance(data.get("records"), list):
                return tuple(row for row in data["records"] if isinstance(row, dict))
            return (data,)
        if isinstance(data, list):
            return tuple(row for row in data if isinstance(row, dict))
    return ()


def _dig(row: dict[str, Any], *keys: str) -> Any:
    current: Any = row
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _first_nonempty(row: dict[str, Any], *paths: tuple[str, ...]) -> Any:
    for path in paths:
        match len(path):
            case 0:
                continue
            case 1:
                value = row.get(path[0])
            case _:
                value = _dig(row, *path)
        if value not in (None, "", [], {}):
            return value
    return None


def normalize_tool_name(row: dict[str, Any]) -> str | None:
    value = _first_nonempty(
        row,
        ("tool_name",),
        ("tool",),
        ("tool_kind",),
        ("payload", "tool_name"),
        ("payload", "tool"),
        ("payload", "tool_kind"),
        ("tool_call",),
    )
    if value is None:
        event_name = str(_first_nonempty(row, ("event_name",), ("event_type",)) or "")
        if "tool" in event_name:
            return event_name.rsplit(".", 1)[-1]
        return None
    return str(value)


def _extract_status(row: dict[str, Any]) -> str:
    value = _first_nonempty(
        row, ("status",), ("payload", "status"), ("result",), ("payload", "result")
    )
    return str(value).lower() if value is not None else ""


def _extract_latency(row: dict[str, Any]) -> Any:
    return _first_nonempty(
        row,
        ("duration_ms",),
        ("latency_ms",),
        ("elapsed_ms",),
        ("payload", "duration_ms"),
        ("payload", "latency_ms"),
    )


def _extract_output_size(row: dict[str, Any]) -> Any:
    return _first_nonempty(
        row,
        ("output_bytes",),
        ("stdout_bytes",),
        ("stderr_bytes",),
        ("payload", "output_bytes"),
        ("payload", "stdout_bytes"),
        ("payload", "stderr_bytes"),
    )


def _has_private_content(row: dict[str, Any]) -> bool:
    keys = {key.lower() for key in row}
    return bool(keys & RAW_CONTENT_KEYS)


def infer_risk_tier(tool_name: str) -> int:
    tool = tool_name.lower()
    tier = 0
    if any(
        token in tool
        for token in ("read", "search", "inspect", "list", "scan", "query", "find")
    ):
        tier = 1
    if any(token in tool for token in ("write", "edit", "save", "patch", "apply")):
        tier = 2
    if any(
        token in tool
        for token in ("shell", "bash", "python", "subprocess", "exec", "run", "command")
    ):
        tier = 3
    if any(
        token in tool for token in ("git", "branch", "worktree", "checkpoint", "commit")
    ):
        tier = 4
    if any(
        token in tool
        for token in (
            "upload",
            "drive",
            "google",
            "api",
            "http",
            "webhook",
            "browser",
            "mail",
            "calendar",
        )
    ):
        tier = 5
    if any(
        token in tool
        for token in ("delete", "remove", "cleanup", "gc", "prune", "compact")
    ):
        tier = 6
    return tier


def _update_flags(stats: ToolStats, row: dict[str, Any]) -> None:
    blob = json.dumps(row, sort_keys=True, default=str).lower()
    keys = {key.lower() for key in row}
    stats.has_path = stats.has_path or any(
        "path" in key or "file" in key for key in keys
    )
    stats.has_subprocess = stats.has_subprocess or any(
        token in blob
        for token in ("subprocess", "stdout", "stderr", "shell", "cmd", "command")
    )
    stats.has_network = stats.has_network or any(
        token in blob
        for token in ("http://", "https://", "network", "api", "webhook", "browser")
    )
    stats.has_git = stats.has_git or any(
        token in blob for token in ("git", "branch", "commit", "worktree", "checkpoint")
    )
    stats.may_expose_private_content = (
        stats.may_expose_private_content or _has_private_content(row)
    )
    stats.has_receipts = stats.has_receipts or "receipt" in keys or "receipt" in blob
    stats.has_schema_validation = (
        stats.has_schema_validation or "schema_version" in keys or "schema" in blob
    )
    stats.has_tests = stats.has_tests or "test" in blob


def _scan_path(
    path: Path,
    stats: dict[str, ToolStats],
    content_key_hits: Counter[str],
    schema_gaps: Counter[str],
) -> tuple[int, int, int]:
    parseable_records = 0
    tool_event_records = 0
    malformed_records = 0
    is_line_json = path.suffix in {".jsonl", ".ndjson"} or path.name.endswith(".jsonl.gz")
    if not is_line_json and path.suffix != ".json":
        return 0, 0, 0
    for row in _iter_records(path):
        parseable_records += 1
        for key in row:
            if key in RAW_CONTENT_KEYS:
                content_key_hits[key] += 1
        tool_name = normalize_tool_name(row)
        if tool_name is None:
            continue
        tool_event_records += 1
        bucket = stats.setdefault(tool_name, ToolStats(tool_name))
        bucket.count += 1
        bucket.add_status(_extract_status(row))
        bucket.add_latency(_extract_latency(row))
        bucket.add_output_size(_extract_output_size(row))
        _update_flags(bucket, row)
        if not any(
            key in row
            or (isinstance(row.get("payload"), dict) and key in row["payload"])
            for key in ("status", "payload", "event_name", "event_type")
        ):
            schema_gaps["missing_core_fields"] += 1
    if is_line_json:
        malformed_records = _count_malformed_lines(path)
    return parseable_records, tool_event_records, malformed_records


def _count_malformed_lines(path: Path) -> int:
    malformed_records = 0
    try:
        with _open_text(path) as handle:
            for line in handle:
                if line.strip() and _safe_json_loads(line.strip()) is None:
                    malformed_records += 1
    except OSError:
        return 0
    return malformed_records


def _build_tool_rows(stats: dict[str, ToolStats]) -> list[dict[str, Any]]:
    tool_rows: list[dict[str, Any]] = []
    for bucket in stats.values():
        latencies = sorted(bucket.latencies)
        outputs = sorted(bucket.output_sizes)
        tool_rows.append(
            {
                "tool_name": bucket.tool_name,
                "risk_tier": bucket.risk_tier,
                "count": bucket.count,
                "success_count": bucket.success_count,
                "failure_count": bucket.failure_count,
                "skipped_count": bucket.skipped_count,
                "failure_rate": round(bucket.failure_count / bucket.count, 4)
                if bucket.count
                else 0.0,
                "median_latency_ms": round(median(latencies), 2) if latencies else None,
                "p95_latency_ms": percentile(latencies, 95),
                "median_output_bytes": int(median(outputs)) if outputs else None,
                "p95_output_bytes": percentile(outputs, 95),
                "has_path": bucket.has_path,
                "has_subprocess": bucket.has_subprocess,
                "has_network": bucket.has_network,
                "has_git": bucket.has_git,
                "may_expose_private_content": bucket.may_expose_private_content,
                "has_receipts": bucket.has_receipts,
                "has_schema_validation": bucket.has_schema_validation,
                "has_tests": bucket.has_tests,
            }
        )
    tool_rows.sort(
        key=lambda row: (-row["count"], -row["failure_count"], row["tool_name"])
    )
    return tool_rows


def _rank(rows: list[dict[str, Any]], *, mode: str) -> list[dict[str, Any]]:
    if mode == "failure":
        return sorted(
            rows,
            key=lambda row: (-row["failure_count"], -row["failure_rate"], row["tool_name"]),
        )
    if mode == "latency":
        return sorted(
            (row for row in rows if row["median_latency_ms"] is not None),
            key=lambda row: (-(row["p95_latency_ms"] or 0), -row["count"], row["tool_name"]),
        )
    if mode == "output":
        return sorted(
            (row for row in rows if row["median_output_bytes"] is not None),
            key=lambda row: (-(row["p95_output_bytes"] or 0), -row["count"], row["tool_name"]),
        )
    return sorted(
        rows,
        key=lambda row: (-row["failure_count"], -row["risk_tier"], -row["count"], row["tool_name"]),
    )


def analyze_relay(
    root: Path, *, include_gz: bool = True, max_files: int | None = None
) -> dict[str, Any]:
    files = _walk_files(root, include_gz=include_gz, max_files=max_files)
    stats: dict[str, ToolStats] = {}
    parseable_records = 0
    tool_event_records = 0
    malformed_records = 0
    content_key_hits: Counter[str] = Counter()
    schema_gaps: Counter[str] = Counter()

    for path in files:
        found_parseable, found_tools, found_malformed = _scan_path(
            path, stats, content_key_hits, schema_gaps
        )
        parseable_records += found_parseable
        tool_event_records += found_tools
        malformed_records += found_malformed

    for bucket in stats.values():
        bucket.finalize()

    tool_rows = _build_tool_rows(stats)
    aggregate = {
        "evidence_root": str(root),
        "files_scanned": len(files),
        "parseable_records": parseable_records,
        "tool_event_records": tool_event_records,
        "malformed_records": malformed_records,
        "tools": tool_rows,
        "top_by_failure": _rank(tool_rows, mode="failure")[:10],
        "top_by_latency": _rank(tool_rows, mode="latency")[:10],
        "top_by_output_size": _rank(tool_rows, mode="output")[:10],
        "priority_tools": _rank(tool_rows, mode="priority")[:10],
        "schema_gaps": {
            "missing_core_fields": schema_gaps["missing_core_fields"],
            "raw_content_keys_seen": dict(content_key_hits.most_common()),
        },
    }
    return aggregate


def percentile(values: Sequence[float | int], pct: int) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return int(ordered[0])
    index = min(len(ordered) - 1, max(0, round((pct / 100) * len(ordered)) - 1))
    return int(ordered[index])


def render_summary(aggregate: dict[str, Any]) -> str:
    lines = [
        "# Local Relay Tool Usage Summary",
        "",
        f"- Evidence root: `{aggregate['evidence_root']}`",
        f"- Files scanned: `{aggregate['files_scanned']}`",
        f"- Parseable records: `{aggregate['parseable_records']}`",
        f"- Tool/event records: `{aggregate['tool_event_records']}`",
        f"- Malformed records: `{aggregate['malformed_records']}`",
        "",
        "## Top Tools by Usage",
    ]
    lines.extend(_bullet_rows(aggregate["tools"][:10], key="count"))
    lines.extend(["", "## Top Tools by Failure"])
    lines.extend(_bullet_rows(aggregate["top_by_failure"], key="failure_count"))
    lines.extend(["", "## Top Tools by Latency"])
    lines.extend(_bullet_rows(aggregate["top_by_latency"], key="p95_latency_ms"))
    lines.extend(["", "## Top Tools by Output Size"])
    lines.extend(_bullet_rows(aggregate["top_by_output_size"], key="p95_output_bytes"))
    lines.extend(["", "## Hardening Priorities"])
    for row in aggregate["priority_tools"][:8]:
        lines.append(
            f"- `{row['tool_name']}` tier `{row['risk_tier']}` count `{row['count']}` failures `{row['failure_count']}`"
        )
    lines.append("")
    return "\n".join(lines)


def render_hardening(aggregate: dict[str, Any]) -> str:
    lines = ["# Tool Hardening Priority", ""]
    for row in aggregate["priority_tools"][:8]:
        lines.extend([
            f"## `{row['tool_name']}`",
            f"- Risk tier: `{row['risk_tier']}`",
            f"- Observed usage: `{row['count']}` calls",
            f"- Failure count: `{row['failure_count']}`",
            "- Guardrails: schema validation, max output size, timeout, structured refusal, content-light summaries",
            "- Tests: malformed input, refusal path, truncation, protected content redaction",
            f"- Deterministic Rig-managed tool: {'yes' if row['risk_tier'] >= HIGH_RISK_TIER else 'maybe'}",
            "",
        ])
    return "\n".join(lines)


def render_schema_gaps(aggregate: dict[str, Any]) -> str:
    gaps = aggregate["schema_gaps"]
    lines = [
        "# Schema Gaps",
        "",
        f"- Missing core fields detected: `{gaps['missing_core_fields']}`",
        f"- Raw content keys seen: `{', '.join(gaps['raw_content_keys_seen']) if gaps['raw_content_keys_seen'] else 'none'}`",
        "",
        "Recommended additions:",
        "- explicit `tool_name`, `status`, `duration_ms`, `output_bytes`, `error_kind`, `receipt_id`, `schema_version`",
        "- normalized outcome field for success/failure/skipped/refused",
        "- stable tool invocation id and session id linkage",
        "- redaction-safe hashes for any content-bearing fields",
        "",
        "Forbidden fields in shared reports:",
        "- raw prompts",
        "- raw args",
        "- raw stdout/stderr",
        "- raw completions or transcripts",
        "- raw private file contents",
        "",
    ]
    return "\n".join(lines)


def _bullet_rows(rows: list[dict[str, Any]], *, key: str) -> list[str]:
    out: list[str] = []
    for row in rows:
        value = row.get(key)
        out.append(
            f"- `{row['tool_name']}`: `{key}` `{value}` failures `{row['failure_count']}` tier `{row['risk_tier']}`"
        )
    return out


def write_outputs(aggregate: dict[str, Any], out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "tool-usage-summary.md").write_text(
        render_summary(aggregate), encoding="utf-8"
    )
    (out_dir / "tool-hardening-priority.md").write_text(
        render_hardening(aggregate), encoding="utf-8"
    )
    (out_dir / "schema-gaps.md").write_text(
        render_schema_gaps(aggregate), encoding="utf-8"
    )
    (out_dir / "tool-usage-aggregates.json").write_text(
        json.dumps(aggregate, indent=2, sort_keys=True), encoding="utf-8"
    )


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--relay-root", type=Path, default=DEFAULT_RELAY_ROOT)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--max-files", type=int)
    parser.add_argument("--include-gz", action="store_true", default=False)
    parser.add_argument("--redacted-samples", action="store_true")
    parser.add_argument("--fail-on-raw-content", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    aggregate = analyze_relay(
        args.relay_root, include_gz=args.include_gz, max_files=args.max_files
    )
    if args.fail_on_raw_content and aggregate["schema_gaps"]["raw_content_keys_seen"]:
        raise SystemExit(2)
    write_outputs(aggregate, args.out)
    print(
        json.dumps(
            {
                k: aggregate[k]
                for k in ("files_scanned", "parseable_records", "tool_event_records")
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

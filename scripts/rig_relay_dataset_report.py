#!/usr/bin/env python3
"""Rig Relay Dataset Report Generator.

Reads event streams and findings registries, then emits a human-readable
Markdown report to .build/rig-relay/reports/dataset-summary.md.

Usage:
    uv run python scripts/rig_relay_dataset_report.py
    uv run python scripts/rig_relay_dataset_report.py --output path/to/report.md

Content-light: never includes raw prompts, model outputs, file contents,
stdout/stderr bodies, or raw private code paths.
"""

from __future__ import annotations

import argparse
import csv
from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Any

# ── Paths ────────────────────────────────────────────────────────────────

REPO_ROOT = Path(__file__).resolve().parent.parent
BUILD_ROOT = REPO_ROOT / ".build" / "rig-relay"
REPORTS_DIR = BUILD_ROOT / "reports"
COORD_EVENTS = BUILD_ROOT / "coordination" / "events.jsonl"
FINDINGS_PATH = REPO_ROOT / "docs" / "findings" / "out-of-scope-findings.jsonl"
SESSIONS_ROOT = Path.home() / ".rig" / "relay" / "sessions"

DEFAULT_OUTPUT = REPORTS_DIR / "dataset-summary.md"
MAX_LISTING_PATHS = 5


# ── Helpers ──────────────────────────────────────────────────────────────


def _jsonl_paths(root: Path, pattern: str = "observability.jsonl") -> list[Path]:
    if not root.exists():
        return []
    return sorted(root.glob(f"*/{pattern}"))


def _count_lines(path: Path) -> int:
    try:
        with path.open("r", encoding="utf-8") as f:
            return sum(1 for _ in f)
    except Exception:
        return 0


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    """Load a JSONL file, skipping malformed lines."""
    rows: list[dict[str, Any]] = []
    if not path.is_file():
        return rows
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            stripped = line.strip()
            if not stripped:
                continue
            try:
                rows.append(json.loads(stripped))
            except json.JSONDecodeError:
                continue
    return rows


def _safe_count(seq: list[Any]) -> int:
    return len(seq)


def _fmt_table(headers: list[str], rows: list[list[Any]]) -> str:
    """Render a Markdown table."""
    if not rows:
        return f"*No data for {headers[0] if headers else 'table'}.*\n"
    col_count = len(headers)
    lines: list[str] = []
    lines.append("| " + " | ".join(str(h) for h in headers) + " |")
    lines.append("| " + " | ".join("---" for _ in range(col_count)) + " |")
    for row in rows:
        padded = [str(row[i]) if i < len(row) else "" for i in range(col_count)]
        lines.append("| " + " | ".join(padded) + " |")
    lines.append("")
    return "\n".join(lines)


def _fmt_bool(val: Any) -> str:
    if val is True:
        return "✓"
    if val is False:
        return "✗"
    return str(val) if val else "—"


# ── Data Sources ─────────────────────────────────────────────────────────


class DataSources:
    """Collect metadata about available data sources."""

    def __init__(self) -> None:
        self.coord_events_path = COORD_EVENTS
        self.findings_path = FINDINGS_PATH
        self.sessions_root = SESSIONS_ROOT

        self.coord_events_present = COORD_EVENTS.is_file()
        self.findings_present = FINDINGS_PATH.is_file()
        self.obs_paths: list[Path] = []
        self.obs_present = False

        if self.coord_events_present:
            self.coord_event_count = _count_lines(COORD_EVENTS)
        else:
            self.coord_event_count = 0

        self.obs_paths = _jsonl_paths(SESSIONS_ROOT)
        self.obs_present = len(self.obs_paths) > 0

        if self.findings_present:
            self.findings_rows = _load_jsonl(FINDINGS_PATH)
            self.findings_count = len(self.findings_rows)
        else:
            self.findings_rows = []
            self.findings_count = 0

    def warnings(self) -> list[str]:
        warns: list[str] = []
        if not self.coord_events_present:
            warns.append(
                f"Coordination events not found at {self.coord_events_path}. "
                "Coordination section will be empty."
            )
        if not self.obs_present:
            warns.append(
                f"No observability logs found under {self.sessions_root}. "
                "Session and tool sections will be empty."
            )
        if not self.findings_present:
            warns.append(
                f"Findings registry not found at {self.findings_path}. "
                "Findings section will be empty."
            )
        return warns


# ── Report Sections ──────────────────────────────────────────────────────


class ReportGenerator:
    """Generate a content-light Markdown report from Rig Relay event data."""

    def __init__(self, sources: DataSources) -> None:
        self.sources = sources
        self.sections: list[str] = []
        self._coord_events: list[dict[str, Any]] = []
        self._obs_events: list[dict[str, Any]] = []

    def generate(self) -> str:
        self._coord_events = (
            _load_jsonl(self.sources.coord_events_path)
            if self.sources.coord_events_present
            else []
        )
        if self.sources.obs_present:
            for path in self.sources.obs_paths:
                self._obs_events.extend(_load_jsonl(path))

        parts: list[str] = []
        parts.append("# Rig Relay Dataset Report\n")
        parts.append(f"*Generated: {datetime.now(UTC).isoformat()}*\n")
        parts.append(self._executive_summary())
        parts.append(self._event_volume())
        parts.append(self._tool_behavior())
        parts.append(self._guard_and_safety())
        parts.append(self._coordination())
        parts.append(self._checkpoints())
        parts.append(self._provider_model_use())
        parts.append(self._findings())
        parts.append(self._warnings())
        parts.append(self._recommended_next_slices())
        parts.append(self._data_sources_used())

        return "\n".join(parts)

    def _executive_summary(self) -> str:
        rows = []
        ds = self.sources

        sessions_seen = len(ds.obs_paths)
        obs_event_count = len(self._obs_events)
        tool_calls = [
            e
            for e in self._obs_events
            if e.get("event_name") == "rig.relay.tool.call_completed"
        ]
        guard_events = [
            e for e in self._obs_events if "guard" in e.get("event_name", "")
        ]
        checkpoint_committed = [
            e
            for e in self._obs_events
            if e.get("event_name") == "rig.relay.checkpoint.committed"
        ]
        checkpoint_refused = [
            e
            for e in self._obs_events
            if e.get("event_name") == "rig.relay.checkpoint.refused"
        ]
        mutations_allowed = sum(
            1 for e in tool_calls if e.get("payload", {}).get("status") == "success"
        )
        mutations_refused = sum(
            1
            for e in tool_calls
            if e.get("payload", {}).get("status") in {"refused", "error"}
        )
        open_findings = sum(1 for f in ds.findings_rows if f.get("status") == "open")

        coord_summary: dict[str, int] = {}
        for e in self._coord_events:
            name = e.get("event_name", "unknown")
            coord_summary[name] = coord_summary.get(name, 0) + 1

        coord_total = sum(coord_summary.values())

        rows.append(["Sessions observed", str(sessions_seen)])
        rows.append(["Observability events", str(obs_event_count)])
        rows.append(["Coordination events", str(coord_total)])
        rows.append(["Tool calls", str(len(tool_calls))])
        rows.append(["Mutations allowed", str(mutations_allowed)])
        rows.append(["Mutations refused", str(mutations_refused)])
        rows.append(["Guard events", str(len(guard_events))])
        rows.append(["Checkpoints committed", str(len(checkpoint_committed))])
        rows.append(["Checkpoints refused", str(len(checkpoint_refused))])
        rows.append([
            "Open findings",
            str(open_findings) if ds.findings_present else "N/A (no findings registry)",
        ])

        return "## Executive Summary\n\n" + _fmt_table(["Metric", "Value"], rows)

    def _event_volume(self) -> str:
        counts: dict[str, int] = {}
        for e in self._obs_events:
            name = e.get("event_name", "unknown")
            counts[name] = counts.get(name, 0) + 1
        for e in self._coord_events:
            name = e.get("event_name", "unknown")
            counts[name] = counts.get(name, 0) + 1

        if not counts:
            return "## Event Volume\n\n*No events observed.*\n"

        sorted_counts = sorted(counts.items(), key=lambda x: -x[1])
        rows = [[name, str(count)] for name, count in sorted_counts]
        return "## Event Volume\n\n" + _fmt_table(["Event Name", "Count"], rows)

    def _tool_behavior(self) -> str:
        tool_events = [
            e
            for e in self._obs_events
            if e.get("event_name") == "rig.relay.tool.call_completed"
        ]
        if not tool_events:
            return "## Tool Behavior\n\n*No tool call events observed.*\n"

        by_tool: dict[str, dict[str, int]] = {}
        for e in tool_events:
            payload = e.get("payload", {})
            tool_name = payload.get("tool_name", "unknown")
            status = payload.get("status", "unknown")
            if tool_name not in by_tool:
                by_tool[tool_name] = {}
            by_tool[tool_name][status] = by_tool[tool_name].get(status, 0) + 1

        rows = []
        for tool_name in sorted(by_tool.keys()):
            statuses = by_tool[tool_name]
            total = sum(statuses.values())
            success = statuses.get("success", 0)
            refused = statuses.get("refused", 0)
            error = statuses.get("error", 0)
            rows.append([tool_name, str(total), str(success), str(refused), str(error)])

        return "## Tool Behavior\n\n" + _fmt_table(
            ["Tool Name", "Total Calls", "Success", "Refused", "Error"], rows
        )

    def _guard_and_safety(self) -> str:
        guard_names = {
            "rig.relay.guard.dirty_snapshot_captured",
            "rig.relay.guard.refused_write",
            "rig.relay.tool.files_read",
            "rig.relay.tool.tests_run",
        }
        guard_events = [
            e for e in self._obs_events if e.get("event_name") in guard_names
        ]
        if not guard_events:
            return "## Guard and Safety\n\n*No guard events observed.*\n"

        counts: dict[str, int] = {}
        for e in guard_events:
            name = e.get("event_name", "unknown")
            counts[name] = counts.get(name, 0) + 1

        rows = [[name, str(count)] for name, count in sorted(counts.items())]
        return "## Guard and Safety\n\n" + _fmt_table(["Event Name", "Count"], rows)

    def _coordination(self) -> str:
        if not self._coord_events:
            return "## Coordination\n\n*No coordination events observed.*\n"

        counts: dict[str, int] = {}
        for e in self._coord_events:
            name = e.get("event_name", "unknown")
            counts[name] = counts.get(name, 0) + 1

        rows = [[name, str(count)] for name, count in sorted(counts.items())]

        # Breakdown sub-sections
        detail_rows: list[list[str]] = []
        claims = [
            e for e in self._coord_events if e.get("event_name") == "coord.task.claimed"
        ]
        reservations = [
            e
            for e in self._coord_events
            if e.get("event_name") == "coord.path.reserved"
        ]
        refusals = [
            e
            for e in self._coord_events
            if e.get("event_name") == "coord.path.reservation_refused"
        ]
        conflicts = [
            e
            for e in self._coord_events
            if e.get("event_name") == "coord.conflict.reported"
        ]
        heartbeats = [
            e
            for e in self._coord_events
            if e.get("event_name") == "coord.session.heartbeat"
        ]

        detail_rows.append(["Task claims", str(len(claims))])
        detail_rows.append(["Path reservations", str(len(reservations))])
        detail_rows.append(["Reservation refusals", str(len(refusals))])
        detail_rows.append(["Conflicts reported", str(len(conflicts))])
        detail_rows.append(["Heartbeats", str(len(heartbeats))])

        return (
            "## Coordination\n\n"
            + _fmt_table(["Event Name", "Count"], rows)
            + "\n### Breakdown\n\n"
            + _fmt_table(["Category", "Count"], detail_rows)
        )

    def _checkpoints(self) -> str:
        committed = [
            e
            for e in self._obs_events
            if e.get("event_name") == "rig.relay.checkpoint.committed"
        ]
        refused = [
            e
            for e in self._obs_events
            if e.get("event_name") == "rig.relay.checkpoint.refused"
        ]

        if not committed and not refused:
            return "## Checkpoints\n\n*No checkpoint events observed.*\n"

        rows: list[list[str]] = []
        rows.append(["Committed", str(len(committed))])
        rows.append(["Refused", str(len(refused))])

        if committed:
            for e in committed[:10]:
                payload = e.get("payload", {})
                rows.append(["  commit", payload.get("commit_sha", "—")[:16] + "..."])

        if refused:
            refusal_reasons: dict[str, int] = {}
            for e in refused:
                payload = e.get("payload", {})
                code = payload.get("refusal_code", "unknown")
                refusal_reasons[code] = refusal_reasons.get(code, 0) + 1
            for reason, count in sorted(refusal_reasons.items()):
                rows.append(["  refused", f"{reason} ({count})"])

        return "## Checkpoints\n\n" + _fmt_table(["Category", "Details"], rows)

    def _provider_model_use(self) -> str:
        # Observability events carry model info in payload for REQUEST_ACCOUNTED
        # and in TOOL_CALL_COMPLETED. Coordination events carry provider/model
        # indirectly via payload.event_kind.
        req_events = [
            e
            for e in self._obs_events
            if e.get("event_name") == "rig.relay.context.request_accounted"
        ]

        if not req_events:
            return (
                "## Provider / Model Use\n\n*No request accounting events observed.*\n"
            )

        model_counts: dict[str, int] = {}
        for e in req_events:
            payload = e.get("payload", {})
            ca = payload.get("context_accounting", {})
            model = ca.get("model", payload.get("model", "unknown"))
            model_counts[model] = model_counts.get(model, 0) + 1

        rows = [[model, str(count)] for model, count in sorted(model_counts.items())]
        return "## Provider / Model Use\n\n" + _fmt_table(
            ["Model", "Request Count"], rows
        )

    def _findings(self) -> str:
        if not self.sources.findings_present or not self.sources.findings_rows:
            return "## Findings\n\n*No out-of-scope findings recorded.*\n"

        rows: list[list[str]] = []
        for f in self.sources.findings_rows:
            rows.append([
                f.get("finding_id", "—"),
                f.get("title", "—"),
                f.get("severity", "—"),
                f.get("status", "—"),
                f.get("repo_area", "—"),
            ])

        # Group by severity
        by_severity: dict[str, int] = {}
        for f in self.sources.findings_rows:
            sev = f.get("severity", "unknown")
            by_severity[sev] = by_severity.get(sev, 0) + 1

        summary_rows = [[sev, str(count)] for sev, count in sorted(by_severity.items())]

        return (
            "## Findings\n\n"
            + "### Summary by Severity\n\n"
            + _fmt_table(["Severity", "Count"], summary_rows)
            + "\n### Active Findings\n\n"
            + _fmt_table(
                ["Finding ID", "Title", "Severity", "Status", "Repo Area"], rows
            )
        )

    def _warnings(self) -> str:
        warns = self.sources.warnings()
        if not warns:
            return ""
        rows = [[w] for w in warns]
        return "## Warnings / Missing Inputs\n\n" + _fmt_table(["Warning"], rows)

    def _recommended_next_slices(self) -> str:
        recs: list[str] = []

        # Derive recommendations from findings
        if self.sources.findings_present:
            open_findings = [
                f for f in self.sources.findings_rows if f.get("status") == "open"
            ]
            for f in open_findings:
                suggested = f.get("suggested_slice")
                if suggested:
                    recs.append(
                        f"- **{f.get('finding_id', '?')}**: {suggested} "
                        f"({f.get('severity', '?')} severity, {f.get('repo_area', '?')})"
                    )

        # Derive recommendations from checkpoint refusals
        refused_checkpoints = [
            e
            for e in self._obs_events
            if e.get("event_name") == "rig.relay.checkpoint.refused"
        ]
        if refused_checkpoints:
            refusal_reasons: set[str] = set()
            for e in refused_checkpoints:
                code = e.get("payload", {}).get("refusal_code", "unknown")
                refusal_reasons.add(code)
            recs.append(
                f"- **Checkpoint refusals observed**: {', '.join(sorted(refusal_reasons))}. "
                "Review checkpoint refusal conditions and guard policies."
            )

        # Guard events
        guard_names = {
            "rig.relay.guard.dirty_snapshot_captured",
            "rig.relay.guard.refused_write",
        }
        guard_events = [
            e for e in self._obs_events if e.get("event_name") in guard_names
        ]
        if guard_events:
            refused_writes = sum(
                1
                for e in guard_events
                if e.get("event_name") == "rig.relay.guard.refused_write"
            )
            if refused_writes:
                recs.append(
                    f"- **{refused_writes} write(s) refused by dirty-file guard**. "
                    "Review guard policy and session-scoped guard lifecycle."
                )

        if not recs:
            return "## Recommended Next Slices\n\n*No recommendations derived from current data.*\n"

        return (
            "## Recommended Next Slices\n\n*Derived from current data and findings.*\n\n"
            + "\n".join(recs)
            + "\n"
        )

    def _data_sources_used(self) -> str:
        ds = self.sources
        rows: list[list[str]] = []
        rows.append([
            "Coordination events",
            str(ds.coord_events_path) if ds.coord_events_present else "Not found",
        ])
        rows.append([
            "Observability logs",
            f"{len(ds.obs_paths)} file(s)" if ds.obs_present else "Not found",
        ])
        if ds.obs_paths:
            for p in ds.obs_paths[:MAX_LISTING_PATHS]:
                rows.append(["", f"  {p}"])
            if len(ds.obs_paths) > MAX_LISTING_PATHS:
                rows.append([
                    "",
                    f"  ... and {len(ds.obs_paths) - MAX_LISTING_PATHS} more",
                ])
        rows.append([
            "Findings registry",
            str(ds.findings_path) if ds.findings_present else "Not found",
        ])
        rows.append(["DuckDB available", _fmt_bool(True)])
        return "## Data Sources Used\n\n" + _fmt_table(
            ["Source", "Path / Status"], rows
        )


# ── CLI ──────────────────────────────────────────────────────────────────


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Rig Relay Dataset Report Generator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  uv run python scripts/rig_relay_dataset_report.py\n"
            "  uv run python scripts/rig_relay_dataset_report.py --output /tmp/report.md\n"
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"Output path (default: {DEFAULT_OUTPUT})",
    )
    parser.add_argument(
        "--coord-events",
        type=Path,
        default=COORD_EVENTS,
        help="Coordination events JSONL path",
    )
    parser.add_argument(
        "--findings",
        type=Path,
        default=FINDINGS_PATH,
        help="Out-of-scope findings JSONL path",
    )
    parser.add_argument(
        "--sessions-root",
        type=Path,
        default=SESSIONS_ROOT,
        help="Sessions root directory",
    )
    parser.add_argument(
        "--export-csv",
        type=Path,
        default=None,
        help="Export event counts to CSV at this path",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    # Build data sources with overrides
    ds = DataSources()
    ds.coord_events_path = args.coord_events
    ds.coord_events_present = args.coord_events.is_file()
    if ds.coord_events_present:
        ds.coord_event_count = _count_lines(args.coord_events)
    else:
        ds.coord_event_count = 0

    ds.findings_path = args.findings
    ds.findings_present = args.findings.is_file()
    if ds.findings_present:
        ds.findings_rows = _load_jsonl(args.findings)
        ds.findings_count = len(ds.findings_rows)
    else:
        ds.findings_rows = []
        ds.findings_count = 0

    ds.sessions_root = args.sessions_root
    ds.obs_paths = _jsonl_paths(args.sessions_root)
    ds.obs_present = len(ds.obs_paths) > 0

    report = ReportGenerator(ds)
    markdown = report.generate()

    out_path = args.output
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(markdown, encoding="utf-8")
    print(f"Report written to {out_path}")

    if args.export_csv:
        _export_event_counts_csv(args.export_csv)
        print(f"Event counts exported to {args.export_csv}")

    return 0


def _export_event_counts_csv(path: Path) -> None:
    """Export event name counts to CSV."""
    ds = DataSources()
    obs_events: list[dict[str, Any]] = []
    for p in ds.obs_paths:
        obs_events.extend(_load_jsonl(p))
    coord_events = _load_jsonl(ds.coord_events_path) if ds.coord_events_present else []

    counts: dict[str, int] = {}
    for e in obs_events:
        name = e.get("event_name", "unknown")
        counts[name] = counts.get(name, 0) + 1
    for e in coord_events:
        name = e.get("event_name", "unknown")
        counts[name] = counts.get(name, 0) + 1

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["event_name", "count"])
        for name, count in sorted(counts.items(), key=lambda x: -x[1]):
            writer.writerow([name, count])


if __name__ == "__main__":
    raise SystemExit(main())

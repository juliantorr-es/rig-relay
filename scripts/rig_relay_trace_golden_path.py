#!/usr/bin/env python3
"""Rig Relay Golden Path Trace Summary.

Reads the local trace store (JSONL) and prints a compact summary for a
handshake_id or the latest desktop_launch_trace. Exits nonzero in strict
mode when required golden-path stages are missing.

Usage:
    uv run python scripts/rig_relay_trace_golden_path.py
    uv run python scripts/rig_relay_trace_golden_path.py --latest --strict
    uv run python scripts/rig_relay_trace_golden_path.py --handshake-id hs_abc123
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

REQUIRED_STAGES = [
    "desktop.bridge.launch_requested",
    "desktop.bridge.frontend_resolved",
    "desktop.bridge.runtime_config_built",
    "desktop.bridge.server_bound",
    "desktop.bridge.health_probe_passed",
    "desktop.websocket.accepted",
    "desktop.websocket.auth_received",
    "desktop.websocket.auth_ok",
    "desktop.projection.sent",
]

FRONTEND_STAGES = [
    "frontend.boot_started",
    "frontend.runtime_config_loaded",
    "frontend.websocket_connecting",
    "frontend.auth_ok",
    "frontend.projection_received",
    "frontend.projection_rendered",
    "frontend.status_rendered",
    "frontend.ready",
]

SHUTDOWN_STAGES = ["desktop.websocket.closed", "desktop.bridge.shutdown"]

_MAGIC_MIN_TOKEN_LEN = 8
RECONNECT_LOOP_THRESHOLD = 3  # >3 cycles flags reconnect loop

FAILURE_CHECK_NAMES = {
    "frontend.auth_ok": "desktop.websocket.auth_ok",
    "desktop.projection.sent": "frontend.projection_received",
    "frontend.projection_received": "frontend.projection_rendered",
}


def _default_trace_path() -> Path:
    env_path = os.getenv("RIG_RELAY_TRACE_PATH")
    if env_path:
        return Path(env_path)
    app_support = os.path.expanduser("~/Library/Application Support/Rig Relay")
    return Path(app_support) / "traces" / "trace_events.jsonl"


def _load_events(path: Path) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    if not path.exists():
        return events
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(event, dict):
                events.append(event)
    return events


def _find_trace_id(
    events: list[dict[str, Any]], handshake_id: str | None = None
) -> str | None:
    if handshake_id:
        for event in events:
            corr = event.get("correlation")
            if isinstance(corr, dict) and corr.get("handshake_id") == handshake_id:
                return str(event.get("trace_id", ""))
        # Fallback: check attributes
        for event in events:
            attrs = event.get("attributes") or event.get("payload") or {}
            if isinstance(attrs, dict):
                if attrs.get("handshake_id") == handshake_id:
                    return str(event.get("trace_id", ""))
    return _latest_trace_id(events)


def _latest_trace_id(events: list[dict[str, Any]]) -> str | None:
    trace_ids: dict[str, str] = {}
    for event in events:
        tid = event.get("trace_id")
        if isinstance(tid, str) and tid:
            ts = str(event.get("timestamp", ""))
            if tid not in trace_ids or ts > trace_ids.get(f"{tid}_ts", ""):
                trace_ids[tid] = ts
                trace_ids[f"{tid}_ts"] = ts
    if not trace_ids:
        return None
    return max(trace_ids, key=lambda k: trace_ids.get(k, ""))  # type: ignore[arg-type]


def _events_for_trace(
    events: list[dict[str, Any]], trace_id: str
) -> list[dict[str, Any]]:
    matched: list[dict[str, Any]] = []
    for event in events:
        if event.get("trace_id") == trace_id:
            matched.append(event)
    # Also match by correlation
    for event in events:
        corr = event.get("correlation")
        if not isinstance(corr, dict):
            continue
        for m in matched:
            m_corr = m.get("correlation")
            if not isinstance(m_corr, dict):
                continue
            if m_corr.get("handshake_id") != corr.get("handshake_id"):
                continue
            if event not in matched:
                matched.append(event)
            break
    matched.sort(key=lambda e: str(e.get("timestamp", "")))
    return matched


def _event_name(event: dict[str, Any]) -> str:
    return str(event.get("event_type") or event.get("name") or "")


def _check_failures(events: list[dict[str, Any]]) -> list[str]:
    failures: list[str] = []
    event_names = {_event_name(e) for e in events}

    # Missing trace_id
    missing_trace = any(not e.get("trace_id") for e in events)
    if missing_trace:
        failures.append("missing_trace_id: Some events lack trace_id")

    # Token value check
    for event in events:
        redact = event.get("redaction")
        if isinstance(redact, dict) and redact.get("token_value_included"):
            failures.append(f"token_value_included=true in event {_event_name(event)}")
        payload = event.get("payload") or event.get("attributes") or {}
        if isinstance(payload, dict):
            for v in payload.values():
                if isinstance(v, str) and len(v) > _MAGIC_MIN_TOKEN_LEN:
                    # Heuristic: long string in payload — check if it's not a URL
                    if "://" not in v and "/" not in v[:20]:
                        pass  # could be a hash or name

    # Split-brain auth trace
    has_frontend_auth_ok = (
        "frontend.auth_ok" in event_names or "frontend_auth_ok" in event_names
    )
    has_backend_auth_ok = "desktop.websocket.auth_ok" in event_names
    if has_frontend_auth_ok and not has_backend_auth_ok:
        failures.append(
            "split_brain_auth: frontend.auth_ok without desktop.websocket.auth_ok"
        )

    # Transport seam
    has_projection_sent = "desktop.projection.sent" in event_names
    has_projection_received = (
        "frontend.projection_received" in event_names
        or "frontend_projection_received" in event_names
    )
    if has_projection_sent and not has_projection_received:
        failures.append("transport_seam_broken: projection sent but not received")

    # Renderer seam
    has_projection_rendered = (
        "frontend.projection_rendered" in event_names
        or "frontend_projection_rendered" in event_names
    )
    if has_projection_received and not has_projection_rendered:
        failures.append("renderer_seam_broken: projection received but not rendered")

    # Status contradiction
    contradiction_events = [
        e
        for e in events
        if _event_name(e)
        in {
            "frontend.status_contradiction_detected",
            "frontend_status_contradiction_detected",
        }
    ]
    if contradiction_events:
        failures.append(
            f"status_contradiction: {len(contradiction_events)} contradiction events found"
        )

    return failures


def _find_handshake_id(events: list[dict[str, Any]]) -> str:
    for event in events:
        corr = event.get("correlation")
        if isinstance(corr, dict) and corr.get("handshake_id"):
            return str(corr["handshake_id"])
        attrs = event.get("payload") or event.get("attributes") or {}
        if isinstance(attrs, dict) and attrs.get("handshake_id"):
            return str(attrs["handshake_id"])
    return "unknown"


def _analyze_cycles(events: list[dict[str, Any]]) -> dict[str, Any]:
    """Count WebSocket connection cycles. >3 = reconnect loop."""
    connecting_events = [
        e for e in events
        if _event_name(e) in {"frontend_websocket_connecting", "frontend.websocket_connecting"}
    ]
    auth_events = [
        e for e in events
        if _event_name(e) in {"frontend_auth_ok", "frontend.auth_ok"}
    ]
    connecting_events.sort(key=lambda e: str(e.get("timestamp", "")))
    auth_events.sort(key=lambda e: str(e.get("timestamp", "")))

    # Pair each connecting with the next auth
    used_auth: set[int] = set()
    cycles: list[dict[str, Any]] = []
    for ci, ce in enumerate(connecting_events):
        paired: dict[str, Any] | None = None
        paired_idx = -1
        ce_ts = str(ce.get("timestamp", ""))
        for ai, ae in enumerate(auth_events):
            if ai in used_auth:
                continue
            ae_ts = str(ae.get("timestamp", ""))
            if ae_ts >= ce_ts:
                paired = ae
                paired_idx = ai
                break
        if paired_idx >= 0:
            used_auth.add(paired_idx)
        cycles.append({
            "cycle_index": ci,
            "start_timestamp": ce_ts,
            "auth_timestamp": str(paired.get("timestamp", "")) if paired else "",
        })

    reconnect_loop = len(cycles) > RECONNECT_LOOP_THRESHOLD
    return {
        "cycles": cycles,
        "total_cycles": len(cycles),
        "reconnect_loop": reconnect_loop,
    }


def summarize(events: list[dict[str, Any]], trace_id: str) -> dict[str, Any]:
    matched = _events_for_trace(events, trace_id)
    event_names = {_event_name(e) for e in matched}

    start_ts = ""
    end_ts = ""
    for e in matched:
        ts = str(e.get("timestamp", ""))
        if ts:
            if not start_ts or ts < start_ts:
                start_ts = ts
            if not end_ts or ts > end_ts:
                end_ts = ts

    handshake_id = _find_handshake_id(matched)
    commit_sha = ""
    for e in matched:
        corr = e.get("correlation")
        if isinstance(corr, dict) and corr.get("commit_sha"):
            commit_sha = str(corr["commit_sha"])
            break

    all_stages = REQUIRED_STAGES + FRONTEND_STAGES + SHUTDOWN_STAGES
    present = [
        s for s in all_stages if s in event_names or s.replace(".", "_") in event_names
    ]
    missing = [
        s
        for s in all_stages
        if s not in event_names and s.replace(".", "_") not in event_names
    ]

    failure_events = [
        e
        for e in matched
        if e.get("status") in {"error", "refused", "failed"}
        or _event_name(e) in {"frontend.status_contradiction_detected"}
    ]

    contradiction_events = [
        e
        for e in matched
        if _event_name(e)
        in {
            "frontend.status_contradiction_detected",
            "frontend_status_contradiction_detected",
        }
    ]

    failures = _check_failures(matched)
    required_missing = [
        s
        for s in REQUIRED_STAGES
        if s not in event_names and s.replace(".", "_") not in event_names
    ]

    cycle_analysis = _analyze_cycles(matched)

    return {
        "trace_id": trace_id,
        "handshake_id": handshake_id,
        "commit_sha": commit_sha,
        "start_timestamp": start_ts,
        "end_timestamp": end_ts,
        "total_events": len(matched),
        "present_stages": present,
        "missing_stages": missing,
        "failure_events": [_event_name(e) for e in failure_events],
        "contradiction_events": len(contradiction_events),
        "failures": failures,
        "required_missing": required_missing,
        "cycle_analysis": cycle_analysis,
        "ok": len(required_missing) == 0 and len(failures) == 0,
    }


def print_summary(summary: dict[str, Any]) -> None:
    print(f"Trace ID:     {summary['trace_id']}")
    print(f"Handshake ID: {summary['handshake_id']}")
    print(f"Commit SHA:   {summary['commit_sha'] or '(none)'}")
    print(f"Start:        {summary['start_timestamp']}")
    print(f"End:          {summary['end_timestamp']}")
    print(f"Events:       {summary['total_events']}")
    print()

    # Print cycle analysis if present
    cycle_analysis = summary.get("cycle_analysis", {})
    cycles = cycle_analysis.get("cycles", [])
    if cycles:
        total = cycle_analysis.get("total_cycles", len(cycles))
        print(f"WebSocket connection cycles: {total}")
        if cycle_analysis.get("reconnect_loop"):
            print("  ⚠️ RECONNECT LOOP DETECTED (>3 cycles)")
        for c in cycles:
            print(f"  [#{c['cycle_index']}] start={c.get('start_timestamp', '')}")
        if total > 1 and not cycle_analysis.get("reconnect_loop"):
            print("  ℹ️ Multiple cycles — likely page reload or reconnect lifecycle")
        print()

    print("Stage checklist:")
    for stage in REQUIRED_STAGES + FRONTEND_STAGES + SHUTDOWN_STAGES:
        present = (
            stage in summary["present_stages"]
            or stage.replace(".", "_") in summary["present_stages"]
        )
        icon = "✅" if present else "❌"
        print(f"  {icon} {stage}")
    print()
    if summary["failure_events"]:
        print("Failure events:")
        for fe in summary["failure_events"]:
            print(f"  ❌ {fe}")
    if summary["contradiction_events"]:
        print(f"Contradiction events: {summary['contradiction_events']}")
    if summary["failures"]:
        print("Failures:")
        for f in summary["failures"]:
            print(f"  ❌ {f}")
    print()
    if summary["ok"]:
        print("✅ Golden path trace: ALL REQUIRED STAGES PRESENT")
    else:
        print("❌ Golden path trace: ISSUES FOUND")
        if summary["required_missing"]:
            print(
                f"   Missing required stages: {', '.join(summary['required_missing'])}"
            )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Print golden-path trace summary for Rig Relay desktop launch."
    )
    parser.add_argument(
        "--handshake-id",
        type=str,
        default=None,
        help="Specific handshake_id to summarize",
    )
    parser.add_argument(
        "--latest", action="store_true", default=False, help="Select the latest trace"
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        default=False,
        help="Exit nonzero if required stages are missing or failures detected",
    )
    parser.add_argument(
        "--path", type=Path, default=None, help="Path to trace_events.jsonl"
    )
    parser.add_argument(
        "--fail-on-reconnect-loop",
        action="store_true",
        default=False,
        help="Exit nonzero if reconnect loop detected (>3 WebSocket connection cycles)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    trace_path = args.path or _default_trace_path()
    events = _load_events(trace_path)

    if not events:
        print("No trace events found.")
        return 1 if args.strict else 0

    trace_id = _find_trace_id(events, args.handshake_id)
    if trace_id is None:
        print("No trace found for the requested criteria.")
        return 1 if args.strict else 0

    if args.latest:
        trace_id = _latest_trace_id(events) or trace_id

    summary = summarize(events, trace_id)
    print_summary(summary)

    exit_code = 0
    if args.strict and not summary["ok"]:
        exit_code = 1
    if args.fail_on_reconnect_loop:
        cycle_analysis = summary.get("cycle_analysis", {})
        if cycle_analysis.get("reconnect_loop"):
            print("❌ Reconnect loop detected (>3 cycles). Failing.")
            exit_code = 1
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())

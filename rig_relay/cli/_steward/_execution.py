"""OpenCode execution for the steward — streaming and non-streaming modes.

Owns: subprocess management, JSON stream parsing, terminal display,
content-light event recording, stderr capture, environment sanitization.
Does not own: classification, capsule assembly, tracing (receives trace from caller).
"""

from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
import signal
import subprocess
import threading
from typing import Any

from rig_relay.cli._steward._constants import (
    _BOUNDED_SUMMARY_MAX_CHARS as _BSMC,
    _LAUNCHABLE_STATES,
    append_event,
    now_iso,
    sha256,
)


def build_command(
    item: dict[str, Any],
    project_root: Path,
    opencode_path: str = "opencode",
    *,
    show_reasoning: bool = False,
) -> list[str]:
    title = item.get("title", "Idle Steward Task")
    agent = item.get("agent", "build")
    model = item.get("model")
    cmd = [
        opencode_path,
        "run",
        "--pure",
        "--format",
        "json",
        "--title",
        title,
        "--agent",
        agent,
        "--dir",
        str(project_root),
    ]
    if show_reasoning:
        cmd.insert(cmd.index("--format") + 2, "--thinking")
    if model:
        cmd.extend(["--model", model])
    return cmd


def sanitize_env() -> dict[str, str]:
    from rig_relay.core.tools.security import sanitize_env_for_subprocess

    env = sanitize_env_for_subprocess()
    env.pop("OPENCODE_SERVER_PASSWORD", None)
    env.pop("OPENCODE_API_KEY", None)
    return env


def parse_opencode_line(line: str) -> dict[str, Any] | None:
    try:
        return json.loads(line)
    except (json.JSONDecodeError, TypeError):
        return None


def extract_paths_from_tool_input(tool_input: dict[str, Any]) -> list[str]:
    for key in ("filePath", "path", "target_directory", "dir", "file_path"):
        val = tool_input.get(key)
        if isinstance(val, str) and val:
            return [val]
    return []


def to_stream_event(raw: dict[str, Any], *, redact_reasoning: bool) -> dict[str, Any]:
    event_type = raw.get("type", "unknown")
    part = raw.get("part", {})
    session_id = raw.get("sessionID", "")

    role: str | None = None
    tool_name: str | None = None
    tool_status: str | None = None
    tool_title: str | None = None
    paths: list[str] = []
    path_hashes: list[str] = []
    summary_text = ""
    reasoning_redacted = False
    exit_code: int | None = None
    tokens: dict[str, Any] | None = None
    cost: float | None = None

    if event_type == "reasoning":
        reasoning_redacted = True
        summary_text = "<reasoning redacted>"
    elif event_type == "text":
        role = "assistant"
        summary_text = str(part.get("text", ""))[:_BSMC]
    elif event_type in ("tool_use", "tool_result"):
        tool_name = part.get("tool", "")
        state: dict[str, Any] = part.get("state") or {}
        tool_status = state.get("status", "")
        tool_title = state.get("title", "")
        exit_code_raw = state.get("metadata", {}).get("exit")
        if isinstance(exit_code_raw, int):
            exit_code = exit_code_raw
        tool_input = state.get("input", {})
        paths = extract_paths_from_tool_input(tool_input)
        path_hashes = [sha256(p) for p in paths]
        label = f"{tool_name}: {tool_title}" if tool_title else str(tool_name)
        summary_text = label[:_BSMC]
    elif event_type == "step_start":
        summary_text = "step start"
    elif event_type == "step_finish":
        summary_text = "step finish"
        tok = part.get("tokens", {})
        if tok:
            tokens = {
                "input": tok.get("input", 0),
                "output": tok.get("output", 0),
                "total": tok.get("total", 0),
            }
        cost = part.get("cost")
    elif event_type == "error":
        err: dict[str, Any] = raw.get("error") or {}
        summary_text = str(err.get("name", err.get("message", "unknown error")))[:_BSMC]

    return {
        "event": "opencode_stream",
        "generated_at": now_iso(),
        "session_id": session_id,
        "timestamp_ms": raw.get("timestamp"),
        "stream_event_type": event_type,
        "role": role,
        "tool_name": tool_name,
        "tool_status": tool_status,
        "tool_title": tool_title,
        "summary_text": summary_text,
        "paths": paths,
        "path_hashes": path_hashes,
        "reasoning_redacted": reasoning_redacted,
        "exit_code": exit_code,
        "tokens": tokens,
        "cost": cost,
    }


def print_compact_progress(raw: dict[str, Any], *, show_reasoning: bool) -> None:
    event_type = raw.get("type", "unknown")
    part = raw.get("part", {})

    if event_type == "step_start":
        print("\u25b6 step start", flush=True)
    elif event_type == "step_finish":
        tok = part.get("tokens", {})
        inp = tok.get("input", 0)
        out = tok.get("output", 0)
        print(f"\u25c0 step done \u00b7 {inp}\u2192{out} tokens", flush=True)
    elif event_type == "reasoning":
        if show_reasoning:
            text = part.get("text", "")
            truncated = str(text)[:120]
            print(f"  \U0001f9e0 thinking: {truncated}", flush=True)
    elif event_type == "text":
        text = part.get("text", "")
        truncated = str(text).replace("\n", " ")[:150]
        if truncated:
            print(f"  \U0001f4ac assistant: {truncated}", flush=True)
    elif event_type in ("tool_use", "tool_result"):
        tool_name = part.get("tool", "?")
        state: dict[str, Any] = part.get("state") or {}
        title = state.get("title", "")
        status = state.get("status", "")
        exit_code_raw = state.get("metadata", {}).get("exit")
        status_icon = "\u2713" if status == "completed" else "\u2026"
        exit_str = f" (exit {exit_code_raw})" if isinstance(exit_code_raw, int) else ""
        label = title if title else tool_name
        print(f"  \U0001f527 {tool_name}: {label} {status_icon}{exit_str}", flush=True)
    elif event_type == "error":
        err = raw.get("error", {})
        msg = err.get("name") or err.get("message", "unknown error")
        print(f"  \u26a0 error: {msg}", flush=True)


def stream_opencode(
    argv: list[str],
    prompt_text: str,
    root: Path,
    *,
    show_reasoning: bool = False,
    events_path: Path | None = None,
) -> dict[str, Any]:
    env = sanitize_env()
    try:
        process = subprocess.Popen(
            argv + [prompt_text],
            cwd=root,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
        )
    except FileNotFoundError:
        return {
            "exit_code": -1,
            "stderr_sha256": None,
            "stderr_truncated_bytes": 0,
            "streaming": True,
            "duration_ms": 0,
            "stream_error": "opencode binary not found",
        }

    stderr_lines: list[str] = []

    def _read_stderr() -> None:
        if process.stderr:
            for line in process.stderr:
                stderr_lines.append(line.rstrip("\n"))

    stderr_thread = threading.Thread(target=_read_stderr, daemon=True)
    stderr_thread.start()

    start_time = datetime.now(UTC)
    try:
        if process.stdout:
            for line in process.stdout:
                line = line.rstrip("\n")
                if not line:
                    continue
                raw = parse_opencode_line(line)
                if raw is None:
                    continue
                print_compact_progress(raw, show_reasoning=show_reasoning)
                if events_path:
                    event = to_stream_event(raw, redact_reasoning=True)
                    append_event(events_path, event)
        process.wait()
    except KeyboardInterrupt:
        process.send_signal(signal.SIGINT)
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()

    stderr_thread.join(timeout=5)
    exit_code = process.returncode
    stderr_text = "\n".join(stderr_lines)

    max_stderr_bytes = 4_096
    stderr_bytes = stderr_text.encode("utf-8", errors="replace")
    if len(stderr_bytes) > max_stderr_bytes:
        stderr_bytes = stderr_bytes[:max_stderr_bytes]
    stderr_truncated = stderr_bytes.decode("utf-8", errors="replace")
    stderr_hash = sha256(stderr_truncated) if stderr_truncated else None
    duration_ms = int((datetime.now(UTC) - start_time).total_seconds() * 1000)

    return {
        "exit_code": exit_code,
        "stderr_sha256": stderr_hash,
        "stderr_truncated_bytes": len(stderr_truncated.encode()),
        "streaming": True,
        "duration_ms": duration_ms,
    }


def try_launch(
    item: dict[str, Any],
    state: str,
    root: Path,
    dry_run: bool,
    *,
    no_stream: bool = False,
    show_reasoning: bool = False,
    opencode_path: str = "opencode",
    events_path: Path | None = None,
) -> dict[str, Any] | None:
    if state not in _LAUNCHABLE_STATES:
        return None
    prompt_path = item.get("prompt_path", "")
    from rig_relay.cli._steward._classification import read_prompt_text

    prompt_text = read_prompt_text(root, prompt_path)
    if prompt_text is None:
        return None
    argv = build_command(
        item, root, opencode_path=opencode_path, show_reasoning=show_reasoning
    )
    prompt_hash = sha256(prompt_text)
    argv_sha256 = sha256(json.dumps(argv, sort_keys=True))
    base_meta = {
        "prompt_path": prompt_path,
        "prompt_sha256": prompt_hash,
        "title": item.get("title", ""),
        "agent": item.get("agent", "build"),
        "argv": argv + ["<prompt body omitted>"],
        "argv_sha256": argv_sha256,
    }
    if dry_run:
        return {**base_meta, "launched": False, "dry_run": True, "streaming": True}
    if no_stream:
        result = subprocess.run(argv + [prompt_text], cwd=root)
        return {
            **base_meta,
            "launched": True,
            "dry_run": False,
            "streaming": False,
            "exit_code": result.returncode,
        }
    streaming_meta = stream_opencode(
        argv, prompt_text, root, show_reasoning=show_reasoning, events_path=events_path
    )
    return {**base_meta, "launched": True, "dry_run": False, **streaming_meta}


__all__ = [
    "build_command",
    "parse_opencode_line",
    "print_compact_progress",
    "sanitize_env",
    "stream_opencode",
    "to_stream_event",
    "try_launch",
]

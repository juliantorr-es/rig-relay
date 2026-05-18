from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
import subprocess
import uuid

import pytest

from rig_relay.context.models import ContextMode
from rig_relay.core.telemetry.local import (
    get_degradation_marker_path,
    get_observability_log_path,
    log_local_event,
    read_degradation_marker,
)
from rig_relay.core.telemetry.quarantine import (
    get_quarantine_summary,
    list_quarantined_packets,
)
from rig_relay.core.tools.builtins.get_context import (
    GetContext,
    GetContextArgs,
    GetContextResult,
    GetContextToolConfig,
)
from rig_relay.core.paths._vibe_home import SESSIONS_ROOT
from rig_relay.coordination.watcher import CoordinationWatcher
from tests.helpers.rc_live_harness import RCLiveServer


def _init_repo(repo_root: Path) -> None:
    repo_root.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "init", "-b", "main"],
        cwd=repo_root,
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "rc@test.invalid"],
        cwd=repo_root,
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "RC Test"],
        cwd=repo_root,
        capture_output=True,
        check=True,
    )
    (repo_root / "README.md").write_text("Context digest test repo\n", encoding="utf-8")
    subprocess.run(
        ["git", "add", "README.md"],
        cwd=repo_root,
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=repo_root,
        capture_output=True,
        check=True,
    )


def _write_jsonl(path: Path, entries: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for entry in entries:
            handle.write(json.dumps(entry, sort_keys=True) + "\n")


def _desktop_intent_request(
    intent_name: str, parameters: dict[str, object] | None = None
) -> dict[str, object]:
    return {
        "type": "desktop_intent_request",
        "schema_version": "rig.relay.desktop_intent_request.v1",
        "intent_id": f"intent_{uuid.uuid4().hex[:12]}",
        "created_at": datetime.now(UTC).isoformat(),
        "intent_name": intent_name,
        "parameters": parameters or {},
        "dry_run": True,
    }


async def _run_get_context_digest(repo_root: Path) -> GetContextResult:
    original_cwd = Path.cwd()
    tool = GetContext.from_config(lambda: GetContextToolConfig())
    try:
        import os

        os.chdir(repo_root)
        result: GetContextResult | None = None
        async for item in tool.run(GetContextArgs(mode=ContextMode.DIGEST.value)):
            if isinstance(item, GetContextResult):
                result = item
        if result is None:
            raise AssertionError("GetContext digest mode did not return a result")
        return result
    finally:
        import os

        os.chdir(original_cwd)


@pytest.mark.integration
@pytest.mark.timeout(120)
def test_live_server_startup_smoke_captures_healthz_and_logs(tmp_path: Path) -> None:
    with RCLiveServer(
        home_root=tmp_path / "home",
        evidence_root=tmp_path / "evidence",
        telemetry_enabled=True,
    ) as server:
        healthz = server.read_healthz()
        runtime_config = server.read_runtime_config()

        assert healthz["ok"] is True
        assert healthz["bridge_mode"] == "single"
        assert healthz["frontend_url"] == server.frontend_url
        assert runtime_config["schema_version"] == "rig.desktop.runtime_config.v1"
        assert runtime_config["frontend_url"] == server.frontend_url
        assert runtime_config["ws_url"] == server.ws_url
        assert server.startup_log.is_file()
        assert server.startup_summary.is_file()

        startup_log = server.startup_log.read_text(encoding="utf-8")
        assert "Server-only mode. Bridge is running." in startup_log
        assert "URL: " in startup_log
        assert "WebSocket Token: [REDACTED]" in startup_log

        summary = json.loads(server.startup_summary.read_text(encoding="utf-8"))
        assert summary["healthz"]["ok"] is True
        assert summary["runtime_config"]["frontend_url"] == server.frontend_url
        assert summary["startup_duration_ms"] >= 0

    shutdown_summary = json.loads(
        server.shutdown_summary.read_text(encoding="utf-8")
    )
    assert shutdown_summary["clean_exit"] is True
    assert shutdown_summary["port_processes_remaining"] == []


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.timeout(120)
async def test_live_read_only_intent_round_trip(tmp_path: Path) -> None:
        with RCLiveServer(
            home_root=tmp_path / "home",
            evidence_root=tmp_path / "evidence",
            telemetry_enabled=True,
        ) as server:
            messages = await server.websocket_exchange(
                _desktop_intent_request("worktree_list"),
                expect_type="desktop_intent_result",
            )

        result = messages[-1]["data"]
        assert result["intent_name"] == "worktree_list"
        assert result["status"] in {"completed", "dry_run_completed", "partial"}
        assert result["summary"]


@pytest.mark.asyncio
@pytest.mark.adversarial
@pytest.mark.integration
@pytest.mark.timeout(120)
async def test_unsupported_intent_is_structured_refusal(tmp_path: Path) -> None:
        with RCLiveServer(
            home_root=tmp_path / "home",
            evidence_root=tmp_path / "evidence",
            telemetry_enabled=True,
        ) as server:
            messages = await server.websocket_exchange(
                _desktop_intent_request("<script>alert(1)</script>"),
                expect_type="desktop_intent_result",
            )

        result = messages[-1]["data"]
        assert result["intent_name"] == "<script>alert(1)</script>"
        assert result["status"] == "refused"
        assert result["error_code"] == "unsupported_intent"
        assert result["summary"]


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.real_artifact
@pytest.mark.timeout(120)
async def test_telemetry_disabled_mode_is_visible_and_non_destructive(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("RIG_TELEMETRY_ENABLED", "0")
    session_id = "rc-telemetry-disabled-visibility"

    with RCLiveServer(
        home_root=tmp_path / "home",
        evidence_root=tmp_path / "evidence",
        telemetry_enabled=False,
    ) as server:
        projection_messages = await server.websocket_exchange(
            {"type": "get_projection"},
            expect_type="projection",
        )
        projection = projection_messages[-1]["data"]

        assert projection["telemetry_mode"] == "disabled"
        assert projection["telemetry_degraded"] is True

        log_local_event(session_id, "telemetry.disabled.test", {"sample": "value"})
        marker_path = get_degradation_marker_path(session_id)
        observability_path = get_observability_log_path(session_id)

        assert marker_path.is_file()
        assert read_degradation_marker(session_id)["session_id"] == session_id
        assert not observability_path.exists()


@pytest.mark.integration
@pytest.mark.real_artifact
@pytest.mark.timeout(120)
def test_debug_packet_quarantine_is_inspectable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RIG_TELEMETRY_ENABLED", "1")
    session_id = "rc-debug-quarantine-visibility"

    log_local_event(session_id, "debug.packet", {"payload": "value"})

    summary = get_quarantine_summary(SESSIONS_ROOT.path, session_id)
    packets = list_quarantined_packets(SESSIONS_ROOT.path, session_id)
    observability_path = get_observability_log_path(session_id)

    assert summary["packet_count"] == 1
    assert summary["file_path"].endswith("debug_quarantine.jsonl")
    assert len(packets) == 1
    assert packets[0]["event_name"] == "rig.relay.debug.packet"
    assert not observability_path.exists()


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.real_artifact
@pytest.mark.timeout(120)
async def test_coordination_watcher_detects_appended_events(tmp_path: Path) -> None:
    store_root = tmp_path / "coordination"
    events_path = store_root / "events.jsonl"
    _write_jsonl(
        events_path,
        [
            {
                "schema_version": "rig.relay.coordination.event.v1",
                "event_id": "evt-0",
                "sequence": 1,
                "event_name": "coord.session.registered",
                "payload": {"session_id": "sess-0"},
            }
        ],
    )

    watcher = CoordinationWatcher(store_root, poll_interval_s=0.05)
    await watcher.start()

    async def _collect_next() -> dict[str, object]:
        async for event in watcher.events():
            return event.model_dump(mode="json")
        raise AssertionError("Watcher stopped before detecting new events")

    task = asyncio.create_task(_collect_next())
    await asyncio.sleep(0.1)

    with events_path.open("a", encoding="utf-8") as handle:
        handle.write(
            json.dumps(
                {
                    "schema_version": "rig.relay.coordination.event.v1",
                    "event_id": "evt-1",
                    "sequence": 2,
                    "event_name": "coord.session.heartbeat",
                    "payload": {"session_id": "sess-0"},
                },
                sort_keys=True,
            )
            + "\n"
        )

    event = await asyncio.wait_for(task, timeout=5)
    await watcher.stop()

    assert event["event_type"] == "events_appended"
    assert event["event_count"] == 1
    assert event["events"][0]["event_name"] == "coord.session.heartbeat"


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.real_artifact
@pytest.mark.timeout(120)
async def test_context_digest_mode_uses_cache_and_redacts_private_content(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    repo_root = tmp_path / "context-repo"
    _init_repo(repo_root)

    build_root = repo_root / ".build" / "rig-relay"
    coordination_root = build_root / "coordination"
    coordination_root.mkdir(parents=True, exist_ok=True)
    _write_jsonl(
        coordination_root / "events.jsonl",
        [
            {
                "schema_version": "rig.relay.coordination.event.v1",
                "event_id": "evt-1",
                "sequence": 1,
                "event_name": "coord.session.registered",
                "payload": {"session_id": "ctx-digest-session"},
            }
        ],
    )
    secret_text = "PRIVATE_CONTEXT_SECRET_DO_NOT_LEAK"
    (repo_root / "private").mkdir(parents=True, exist_ok=True)
    (repo_root / "private" / "secret.txt").write_text(secret_text, encoding="utf-8")

    monkeypatch.chdir(repo_root)
    result = await _run_get_context_digest(repo_root)
    packet_json = json.dumps(result.model_dump(mode="json"), sort_keys=True)

    cache_dir = build_root / "cache"
    cache_files = sorted(cache_dir.glob("*.json"))

    assert result.mode == ContextMode.DIGEST.value
    assert result.receipt["kind"] == "rig.context.receipt.v1"
    assert result.receipt["estimated_tokens"] > 0
    assert result.repo["root"] == str(repo_root.resolve())
    assert cache_files, "ContextCache did not write any cache file"
    assert secret_text not in packet_json


@pytest.mark.integration
@pytest.mark.real_artifact
@pytest.mark.timeout(120)
def test_live_run_creates_no_markdown_evidence(tmp_path: Path) -> None:
    with RCLiveServer(
        home_root=tmp_path / "home",
        evidence_root=tmp_path / "evidence",
        telemetry_enabled=True,
    ) as server:
        server.read_healthz()

        markdown_paths = [
            path
            for path in server.home_root.rglob("*")
            if path.is_file()
            and path.suffix.lower() in {".md", ".mdx", ".markdown"}
        ]
        markdown_paths.extend(
            path
            for path in server.evidence_root.rglob("*")
            if path.is_file()
            and path.suffix.lower() in {".md", ".mdx", ".markdown"}
        )

        assert markdown_paths == []

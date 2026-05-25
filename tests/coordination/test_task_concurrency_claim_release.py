from __future__ import annotations

import concurrent.futures
import json
from pathlib import Path
import subprocess
import textwrap

from jsonschema import validate
import pytest
import tomli_w

from rig_relay.coordination.store import CoordinationStore

PROJECT_ROOT = Path(__file__).resolve().parents[2]
TRACE_SCHEMA_PATH = PROJECT_ROOT / "docs" / "schemas" / "rig.trace_event.v1.schema.json"

pytestmark = [
    pytest.mark.integration,
    pytest.mark.real_artifact,
    pytest.mark.substrate,
    pytest.mark.concurrency,
    pytest.mark.timeout(120),
]

_LANE_SCRIPT = textwrap.dedent(
    """
    import asyncio
    import hashlib
    import json
    import os
    import sys
    from datetime import UTC, datetime
    from pathlib import Path

    import tomli_w

    from rig_relay.coordination.models import reset_path_salt_for_testing
    from rig_relay.coordination.store import CoordinationStore
    from rig_relay.core.agents.manager import AgentManager
    from rig_relay.core.config.harness_files import init_harness_files_manager
    from rig_relay.core.llm.backend.factory import BACKEND_FACTORY
    from rig_relay.core.tools.base import BaseToolState, InvokeContext
    from rig_relay.core.tools.builtins.task import Task, TaskArgs, TaskToolConfig
    from rig_relay.core.types import Backend
    from tests.conftest import build_test_vibe_config
    from tests.mock.utils import collect_result, mock_llm_chunk
    from tests.stubs.fake_backend import FakeBackend

    def _canonical(payload: dict[str, object]) -> str:
        return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)

    def _append_trace(path: Path, *, event_type: str, event_kind: str, status: str, trace_id: str, span_id: str, payload: dict[str, object]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        event = {
            "schema_version": "rig.trace_event.v1",
            "event_type": event_type,
            "timestamp": datetime.now(UTC).isoformat(),
            "trace_id": trace_id,
            "span_id": span_id,
            "event_kind": event_kind,
            "status": status,
            "correlation": {
                "session_id": payload.get("session_id"),
                "intent_id": payload.get("tool_call_id"),
            },
            "authority": {
                "authority_kind": "tool_result",
                "trusted": True,
                "source_path": "tests/coordination/test_task_concurrency_claim_release.py",
                "notes": "content-light lane evidence",
            },
            "payload": payload,
        }
        with path.open("a", encoding="utf-8") as f:
            f.write(_canonical(event) + "\\n")

    async def _run() -> None:
        request = json.loads(sys.stdin.read())
        repo_root = Path(request["repo_root"])
        home_root = Path(request["home_root"])
        evidence_path = Path(request["evidence_path"])
        session_id = request["session_id"]
        tool_call_id = request["tool_call_id"]
        lane_id = request["lane_id"]
        task_text = request["task_text"]
        expected_status = request.get("expected_status", "completed")
        os.environ["RIG_RELAY_HOME"] = str(home_root)
        os.environ["RIG_RELAY_DISABLE_LEGACY_CONFIG"] = "1"
        os.environ["DEEPSEEK_API_KEY"] = "mock"
        os.chdir(repo_root)
        init_harness_files_manager("user")
        reset_path_salt_for_testing()

        session_dir = repo_root / ".build" / "task-sessions" / session_id
        session_dir.mkdir(parents=True, exist_ok=True)
        (session_dir / "manifest.json").write_text("{}", encoding="utf-8")

        config = build_test_vibe_config()
        manager = AgentManager(lambda: config)
        ctx = InvokeContext(
            tool_call_id=tool_call_id,
            agent_manager=manager,
            session_dir=session_dir,
            parent_turn_id="parent-turn",
        )
        task_tool = Task(config_getter=lambda: TaskToolConfig(), state=BaseToolState())

        original_backend = BACKEND_FACTORY[Backend.GENERIC]
        BACKEND_FACTORY[Backend.GENERIC] = lambda provider, timeout: FakeBackend(
            [mock_llm_chunk(content="done")]
        )
        trace_id = request["trace_id"]
        try:
            _append_trace(
                evidence_path,
                event_type="task_lane.start",
                event_kind="span.start",
                status="ok",
                trace_id=trace_id,
                span_id=f"{lane_id}-start",
                payload={
                    "lane_id": lane_id,
                    "session_id": session_id,
                    "tool_call_id": tool_call_id,
                    "repo_root": str(repo_root),
                },
            )
            result = await collect_result(
                task_tool.run(TaskArgs(task=task_text, agent="explore"), ctx)
            )
            coord = CoordinationStore(repo_root / ".build" / "rig-relay" / "coordination")
            projection = coord.read_state_projection()
            events_path = coord.root / "events.jsonl"
            coord_events = []
            if events_path.exists():
                coord_events = [
                    json.loads(line)
                    for line in events_path.read_text(encoding="utf-8").splitlines()
                    if line.strip()
                ]
            task_claim_events = [
                event for event in coord_events if event["event_name"] == "coord.task.claimed"
            ]
            task_release_events = [
                event for event in coord_events if event["event_name"] == "coord.task.released"
            ]
            artifact_events = [
                event for event in coord_events if event["event_name"] == "coord.artifact.published"
            ]
            summary = {
                "lane_id": lane_id,
                "session_id": session_id,
                "tool_call_id": tool_call_id,
                "result_status": "completed" if result.completed else "refused",
                "completed": result.completed,
                "turns_used": result.turns_used,
                "task_result_sha256": result.task_result_sha256,
                "response_sha256": hashlib.sha256(result.response.encode("utf-8")).hexdigest(),
                "coordination_claim_count": len(projection.active_task_claims),
                "coordination_release_count": len(task_release_events),
                "coordination_claim_event_count": len(task_claim_events),
                "coordination_artifact_event_count": len(artifact_events),
                "coordination_events_sha256": hashlib.sha256(
                    events_path.read_bytes()
                ).hexdigest()
                if events_path.exists()
                else None,
                "task_claim_statuses": {
                    task_id: claim.status for task_id, claim in projection.active_task_claims.items()
                },
                "coordination_root": str(coord.root),
            }
            _append_trace(
                evidence_path,
                event_type="task_lane.complete",
                event_kind="span.end",
                status="ok" if result.completed else "refused",
                trace_id=trace_id,
                span_id=f"{lane_id}-end",
                payload=summary,
            )
            print(json.dumps(summary))
        finally:
            BACKEND_FACTORY[Backend.GENERIC] = original_backend

    asyncio.run(_run())
    """
)


def _make_git_repo(root: Path) -> Path:
    repo = root / "repo"
    repo.mkdir(parents=True)
    subprocess.run(["git", "init"], cwd=repo, capture_output=True, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=repo,
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Rig Relay Test"],
        cwd=repo,
        capture_output=True,
        check=True,
    )
    (repo / "README.md").write_text("seed\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=repo, capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "seed"],
        cwd=repo,
        capture_output=True,
        check=True,
    )
    return repo


def _write_home_config(home_root: Path) -> None:
    home_root.mkdir(parents=True, exist_ok=True)
    (home_root / "config.toml").write_text(
        tomli_w.dumps(
            {
                "active_model": "deepseek-v4-flash",
                "providers": [
                    {
                        "name": "deepseek",
                        "api_base": "https://api.deepseek.com",
                        "api_key_env_var": "DEEPSEEK_API_KEY",
                        "api_style": "openai",
                        "backend": "generic",
                    }
                ],
                "models": [
                    {
                        "name": "deepseek-v4-flash",
                        "provider": "deepseek",
                        "alias": "deepseek-v4-flash",
                    }
                ],
                "enable_auto_update": False,
                "enable_telemetry": False,
            }
        ),
        encoding="utf-8",
    )


def _run_lane(
    *,
    repo_root: Path,
    home_root: Path,
    evidence_path: Path,
    lane_id: str,
    session_id: str,
    tool_call_id: str,
    task_text: str,
) -> dict[str, object]:
    project_root = PROJECT_ROOT
    proc = subprocess.run(
        [
            "uv",
            "run",
            "--directory",
            str(project_root),
            "python",
            "-c",
            _LANE_SCRIPT,
        ],
        input=json.dumps(
            {
                "repo_root": str(repo_root),
                "home_root": str(home_root),
                "evidence_path": str(evidence_path),
                "lane_id": lane_id,
                "session_id": session_id,
                "tool_call_id": tool_call_id,
                "task_text": task_text,
                "trace_id": "task-concurrency-trace",
                "expected_status": "completed",
            }
        ),
        capture_output=True,
        text=True,
        cwd=str(repo_root),
        timeout=60,
    )
    assert proc.returncode == 0, (
        f"Lane {lane_id} failed: rc={proc.returncode}\nstdout={proc.stdout}\nstderr={proc.stderr}"
    )
    return json.loads(proc.stdout.strip())


def _validate_trace_evidence(path: Path) -> None:
    schema = json.loads(TRACE_SCHEMA_PATH.read_text(encoding="utf-8"))
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        validate(instance=json.loads(line), schema=schema)


class TestTaskConcurrencyClaimRelease:
    def test_three_lanes_release_claims_after_completion(self, tmp_path: Path) -> None:
        """integration + real-artifact + concurrency: three lanes complete and release task claims."""
        repo_root = _make_git_repo(tmp_path)
        home_root = tmp_path / "home"
        _write_home_config(home_root)
        evidence_path = repo_root / ".build" / "rig-relay" / "concurrency" / "task_lane_trace.jsonl"

        lane_specs = [
            ("lane-1", "session-1", "task-1", "task for lane 1"),
            ("lane-2", "session-2", "task-2", "task for lane 2"),
            ("lane-3", "session-3", "task-3", "task for lane 3"),
        ]

        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
            futures = [
                executor.submit(
                    _run_lane,
                    repo_root=repo_root,
                    home_root=home_root,
                    evidence_path=evidence_path,
                    lane_id=lane_id,
                    session_id=session_id,
                    tool_call_id=tool_call_id,
                    task_text=task_text,
                )
                for lane_id, session_id, tool_call_id, task_text in lane_specs
            ]
            results = [future.result() for future in futures]

        assert all(result["result_status"] == "completed" for result in results)
        assert all(result["completed"] is True for result in results)

        coord = CoordinationStore(repo_root / ".build" / "rig-relay" / "coordination")
        projection = coord.read_state_projection()
        assert not projection.active_task_claims

        events_path = coord.root / "events.jsonl"
        events = [
            json.loads(line)
            for line in events_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        assert len([e for e in events if e["event_name"] == "coord.task.claimed"]) == 3
        assert len([e for e in events if e["event_name"] == "coord.task.released"]) == 3
        assert len([e for e in events if e["event_name"] == "coord.artifact.published"]) == 3

        _validate_trace_evidence(evidence_path)

    def test_contested_claim_refuses_losing_lane_without_hanging(
        self, tmp_path: Path
    ) -> None:
        """integration + real-artifact + concurrency + adversarial: one of two contested lanes refuses and the trio still finishes."""
        repo_root = _make_git_repo(tmp_path)
        home_root = tmp_path / "home"
        _write_home_config(home_root)
        evidence_path = repo_root / ".build" / "rig-relay" / "concurrency" / "task_lane_trace.jsonl"

        lane_specs = [
            ("lane-1", "session-1", "shared-task", "task for shared lane 1"),
            ("lane-2", "session-2", "shared-task", "task for shared lane 2"),
            ("lane-3", "session-3", "unique-task", "task for unique lane"),
        ]

        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
            futures = [
                executor.submit(
                    _run_lane,
                    repo_root=repo_root,
                    home_root=home_root,
                    evidence_path=evidence_path,
                    lane_id=lane_id,
                    session_id=session_id,
                    tool_call_id=tool_call_id,
                    task_text=task_text,
                )
                for lane_id, session_id, tool_call_id, task_text in lane_specs
            ]
            results = [future.result() for future in futures]

        assert len(results) == 3
        assert any(not result["completed"] for result in results)
        assert all("coordination_root" in result for result in results)

        coord = CoordinationStore(repo_root / ".build" / "rig-relay" / "coordination")
        projection = coord.read_state_projection()
        assert not projection.active_task_claims

        events_path = coord.root / "events.jsonl"
        events = [
            json.loads(line)
            for line in events_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        assert len([e for e in events if e["event_name"] == "coord.task.released"]) == 2

        _validate_trace_evidence(evidence_path)

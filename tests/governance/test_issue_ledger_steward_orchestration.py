from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

from rig_relay.cli._steward._coordination import StewardCoordinationBridge
from rig_relay.cli._steward._issues import read_issue_work_items

STEWARD_PATH = (
    Path(__file__).resolve().parent.parent.parent
    / "scripts"
    / "rig_opencode_idle_steward.py"
)


def _run_steward(
    root: Path,
    worktree: str = "default-worktree",
    *,
    dry_run: bool = False,
    no_stream: bool = False,
    show_reasoning: bool = False,
    opencode_path: str | None = None,
) -> subprocess.CompletedProcess:
    cmd = [
        sys.executable,
        str(STEWARD_PATH),
        "--project-root",
        str(root),
        "--worktree",
        worktree,
    ]
    if dry_run:
        cmd.append("--dry-run")
    if no_stream:
        cmd.append("--no-stream")
    if show_reasoning:
        cmd.append("--show-reasoning-stream")
    if opencode_path:
        cmd.extend(["--opencode-path", opencode_path])
    return subprocess.run(cmd, capture_output=True, text=True, cwd=root, timeout=30)


def _write_issue_ledger(root: Path, issues: list[dict]) -> Path:
    ledger_dir = root / "docs" / "json" / "issues"
    ledger_dir.mkdir(parents=True, exist_ok=True)
    ledger_path = ledger_dir / "issue_ledger.v1.jsonl"
    with ledger_path.open("w", encoding="utf-8") as f:
        for issue in issues:
            f.write(json.dumps(issue) + "\n")
    return ledger_path


def _base_issue(issue_id: str, **overrides: object) -> dict:
    issue = {
        "schema_version": "rig.relay.issue.v1",
        "issue_id": issue_id,
        "tracker_id": "archive-3-review-tracker",
        "area": "rig_relay/core/tools/cache.py",
        "title": "Fix cache workspace scoping",
        "summary": "Open. The tool result cache still falls back to ambient cwd.",
        "issue_kind": "safety_guard_gap",
        "severity": "high",
        "priority": "p1",
        "status": "open",
        "verification_state": "verified",
        "source_kind": "transcript",
        "source_label": "Archive 3 review transcript",
        "evidence": "Cache reads still default to Path.cwd() when workspace_root is omitted.",
        "why_it_matters": "Cross-worktree cache collisions remain possible.",
        "recommended_action": "Pass explicit workspace identity through the cache adapters.",
        "related_files": [
            "rig_relay/core/tools/cache.py",
            "rig_relay/core/conversation_loop_adapter.py",
        ],
        "validation_commands": [
            "uv run pytest tests/core/test_tool_cache_safety.py -q"
        ],
        "created_at": "2026-05-22T10:56:02Z",
        "updated_at": "2026-05-22T10:56:02Z",
    }
    issue.update(overrides)
    return issue


def _init_git(root: Path) -> None:
    subprocess.run(["git", "init"], cwd=root, capture_output=True, timeout=10)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=root,
        capture_output=True,
        timeout=10,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=root,
        capture_output=True,
        timeout=10,
    )
    (root / "placeholder.txt").write_text("initial", encoding="utf-8")
    subprocess.run(
        ["git", "add", "placeholder.txt"], cwd=root, capture_output=True, timeout=10
    )
    subprocess.run(
        ["git", "commit", "-m", "init"], cwd=root, capture_output=True, timeout=10
    )


def _read_last_run(root: Path) -> dict:
    p = (
        root
        / ".build"
        / "rig-relay"
        / "derived"
        / "opencode_idle_steward_last_run_v1.json"
    )
    return json.loads(p.read_text(encoding="utf-8"))


def _read_coord_events(root: Path) -> list[dict]:
    p = root / ".build" / "rig-relay" / "coordination" / "events.jsonl"
    if not p.exists():
        return []
    return [
        json.loads(line)
        for line in p.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


class TestIssueLedgerWorkItems:
    def test_open_issue_materializes_prompt_and_queue_item(
        self, tmp_path: Path
    ) -> None:
        _init_git(tmp_path)
        _write_issue_ledger(tmp_path, [_base_issue("issue_1")])

        items = read_issue_work_items(tmp_path)

        assert len(items) == 1
        item = items[0]
        assert item["task_id"] == "issue_1"
        assert item["status"] == "queued"
        assert item["priority"] == 10
        assert item["prompt_path"].startswith(".rig/roadmap/prompts/issues/")

        prompt_path = tmp_path / item["prompt_path"]
        assert prompt_path.exists()
        prompt = prompt_path.read_text(encoding="utf-8")
        assert "Fix cache workspace scoping" in prompt
        assert "rig_relay/core/tools/cache.py" in prompt

    def test_resolved_issue_is_not_materialized_as_work(self, tmp_path: Path) -> None:
        _init_git(tmp_path)
        _write_issue_ledger(tmp_path, [_base_issue("issue_1", status="resolved")])

        items = read_issue_work_items(tmp_path)

        assert items == []
        assert not (tmp_path / ".rig" / "roadmap" / "prompts" / "issues").exists()


class TestIssueLedgerStewardIntegration:
    def test_issue_work_item_is_used_for_selection_and_queue_read_counts(
        self, tmp_path: Path
    ) -> None:
        _init_git(tmp_path)
        _write_issue_ledger(tmp_path, [_base_issue("issue_1", priority="p0")])
        queue_dir = tmp_path / ".rig" / "roadmap"
        queue_dir.mkdir(parents=True, exist_ok=True)
        queue_path = queue_dir / "queue.jsonl"
        queue_path.write_text(
            json.dumps({
                "schema_version": "rig.relay.opencode_roadmap_queue_item.v1",
                "task_id": "slice-99",
                "status": "queued",
                "priority": 50,
                "prompt_path": ".rig/roadmap/prompts/slice-99.txt",
                "title": "Existing roadmap item",
                "agent": "build",
                "allowed_files": [],
                "forbidden_files": [],
                "stop_on_dirty_overlap": False,
            })
            + "\n",
            encoding="utf-8",
        )
        prompt_path = tmp_path / ".rig" / "roadmap" / "prompts" / "slice-99.txt"
        prompt_path.parent.mkdir(parents=True, exist_ok=True)
        prompt_path.write_text("Existing roadmap prompt.", encoding="utf-8")

        result = _run_steward(tmp_path, dry_run=True)

        assert result.returncode == 0
        run = _read_last_run(tmp_path)
        selected = run.get("selected_task")
        assert selected is not None
        assert selected["task_id"] == "issue_1"
        command_meta = run.get("command_meta")
        assert command_meta is not None
        assert command_meta["prompt_path"].startswith(".rig/roadmap/prompts/issues/")

        events = _read_coord_events(tmp_path)
        queue_reads = [e for e in events if e["event_name"] == "steward.queue.read"]
        assert len(queue_reads) == 1
        payload = queue_reads[0]["payload"]
        assert payload["queue_item_count"] == 1
        assert payload["issue_item_count"] == 1
        assert payload["work_item_count"] == 2

    def test_claimed_active_item_does_not_block_issue_selection(
        self, tmp_path: Path
    ) -> None:
        _init_git(tmp_path)
        _write_issue_ledger(tmp_path, [_base_issue("issue_1", priority="p0")])

        queue_dir = tmp_path / ".rig" / "roadmap"
        queue_dir.mkdir(parents=True, exist_ok=True)
        queue_path = queue_dir / "queue.jsonl"
        queue_path.write_text(
            json.dumps({
                "schema_version": "rig.relay.opencode_roadmap_queue_item.v1",
                "task_id": "slice-02",
                "status": "active",
                "priority": 50,
                "prompt_path": ".rig/roadmap/prompts/slice-02.txt",
                "title": "Existing active lane item",
                "agent": "build",
                "allowed_files": [],
                "forbidden_files": [],
                "stop_on_dirty_overlap": False,
            })
            + "\n",
            encoding="utf-8",
        )
        prompt_path = tmp_path / ".rig" / "roadmap" / "prompts" / "slice-02.txt"
        prompt_path.parent.mkdir(parents=True, exist_ok=True)
        prompt_path.write_text("Existing active lane prompt.", encoding="utf-8")

        bridge = StewardCoordinationBridge(tmp_path)
        bridge.register_cycle("steward-claim", branch="main", head="abc123")
        bridge.claim_task(
            "steward-claim",
            "slice-02",
            ["rig_relay/evidence/**", "rig_relay/analytics/**"],
            ttl_seconds=1800,
        )

        result = _run_steward(tmp_path, dry_run=True)

        assert result.returncode == 0
        run = _read_last_run(tmp_path)
        selected = run.get("selected_task")
        assert selected is not None
        assert selected["task_id"] == "issue_1"
        assert run["steward_state"] in {"continue_lane", "advance_to_next_lane"}

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

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


def _make_queue_item(
    task_id: str,
    status: str = "queued",
    priority: int = 1,
    prompt_path: str | None = None,
    **overrides,
) -> dict:
    if prompt_path is None:
        prompt_path = f".rig/roadmap/prompts/{task_id}.txt"
    base = {
        "schema_version": "rig.relay.opencode_roadmap_queue_item.v1",
        "task_id": task_id,
        "status": status,
        "priority": priority,
        "prompt_path": prompt_path,
        "title": f"Test: {task_id}",
        "agent": "general-purpose",
    }
    base.update(overrides)
    return base


def _write_queue(root: Path, items: list[dict]) -> Path:
    queue_dir = root / ".rig" / "roadmap"
    queue_dir.mkdir(parents=True, exist_ok=True)
    queue_path = queue_dir / "queue.jsonl"
    with queue_path.open("w", encoding="utf-8") as f:
        for item in items:
            f.write(json.dumps(item) + "\n")
    return queue_path


def _write_prompt(
    root: Path, prompt_path: str, content: str = "Test prompt content."
) -> Path:
    full = root / prompt_path
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_text(content, encoding="utf-8")
    return full


def _write_lanes(root: Path, lanes: list[dict]) -> Path:
    lanes_dir = root / ".rig" / "roadmap"
    lanes_dir.mkdir(parents=True, exist_ok=True)
    lanes_path = lanes_dir / "lanes.jsonl"
    with lanes_path.open("w", encoding="utf-8") as f:
        for lane in lanes:
            f.write(json.dumps(lane) + "\n")
    return lanes_path


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


def _dirty_file(root: Path, rel_path: str, content: str = "dirty") -> None:
    full = root / rel_path
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_text(content, encoding="utf-8")


def _read_last_run(root: Path) -> dict:
    p = (
        root
        / ".build"
        / "rig-relay"
        / "derived"
        / "opencode_idle_steward_last_run_v1.json"
    )
    return json.loads(p.read_text(encoding="utf-8"))


def _read_events(root: Path) -> list[dict]:
    p = (
        root
        / ".build"
        / "rig-relay"
        / "derived"
        / "opencode_idle_steward_events_v1.jsonl"
    )
    if not p.exists():
        return []
    return [
        json.loads(line)
        for line in p.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


class TestNoQueueNoAction:
    def test_no_queue_directory_produces_no_action_artifact(
        self, tmp_path: Path
    ) -> None:
        _init_git(tmp_path)
        result = _run_steward(tmp_path)
        assert result.returncode == 0
        run = _read_last_run(tmp_path)
        assert run["steward_state"] == "no_action"
        assert "no_queue_items" in run.get("blocker_reasons", [])

    def test_empty_queue_file_produces_no_action_artifact(self, tmp_path: Path) -> None:
        _init_git(tmp_path)
        _write_queue(tmp_path, [])
        result = _run_steward(tmp_path)
        assert result.returncode == 0
        run = _read_last_run(tmp_path)
        assert run["steward_state"] == "no_action"


class TestMalformedQueue:
    def test_malformed_queue_item_missing_fields_produces_blocker(
        self, tmp_path: Path
    ) -> None:
        _init_git(tmp_path)
        bad = _make_queue_item("t1", prompt_path=".rig/roadmap/prompts/t1.txt")
        del bad["task_id"]
        _write_queue(tmp_path, [bad])
        _write_prompt(tmp_path, ".rig/roadmap/prompts/t1.txt")
        result = _run_steward(tmp_path)
        assert result.returncode == 0
        run = _read_last_run(tmp_path)
        assert run["steward_state"] == "audit_unblock_plan"

    def test_invalid_status_produces_blocker(self, tmp_path: Path) -> None:
        _init_git(tmp_path)
        bad = _make_queue_item("t1", status="invalid_status")
        _write_queue(tmp_path, [bad])
        _write_prompt(tmp_path, ".rig/roadmap/prompts/t1.txt")
        result = _run_steward(tmp_path)
        assert result.returncode == 0
        run = _read_last_run(tmp_path)
        assert run["steward_state"] in ("no_action", "audit_unblock_plan")


class TestMissingPrompt:
    def test_queued_task_with_missing_prompt_file_is_blocked(
        self, tmp_path: Path
    ) -> None:
        _init_git(tmp_path)
        item = _make_queue_item("t1")
        _write_queue(tmp_path, [item])
        result = _run_steward(tmp_path)
        assert result.returncode == 0
        run = _read_last_run(tmp_path)
        assert run["steward_state"] in ("blocked", "audit_unblock_plan")

    def test_queued_task_with_prompt_outside_prompts_dir_is_blocked(
        self, tmp_path: Path
    ) -> None:
        _init_git(tmp_path)
        item = _make_queue_item("t1", prompt_path="outside.txt")
        _write_queue(tmp_path, [item])
        _write_prompt(tmp_path, "outside.txt")
        result = _run_steward(tmp_path)
        assert result.returncode == 0
        run = _read_last_run(tmp_path)
        assert run["steward_state"] in ("blocked", "audit_unblock_plan")


class TestDirtyOverlap:
    def test_queued_task_with_dirty_allowed_file_is_blocked(
        self, tmp_path: Path
    ) -> None:
        _init_git(tmp_path)
        item = _make_queue_item("t1", allowed_files=["src/touched.py"])
        _write_queue(tmp_path, [item])
        _write_prompt(tmp_path, ".rig/roadmap/prompts/t1.txt")
        _dirty_file(tmp_path, "src/touched.py")
        result = _run_steward(tmp_path)
        assert result.returncode == 0
        run = _read_last_run(tmp_path)
        assert run["steward_state"] in ("blocked", "audit_unblock_plan")

    def test_queued_task_with_dirty_forbidden_file_is_blocked(
        self, tmp_path: Path
    ) -> None:
        _init_git(tmp_path)
        item = _make_queue_item("t1", forbidden_files=["secrets/token.env"])
        _write_queue(tmp_path, [item])
        _write_prompt(tmp_path, ".rig/roadmap/prompts/t1.txt")
        _dirty_file(tmp_path, "secrets/token.env")
        result = _run_steward(tmp_path)
        assert result.returncode == 0
        run = _read_last_run(tmp_path)
        assert run["steward_state"] in ("blocked", "audit_unblock_plan")


class TestGateFailure:
    def test_queued_task_with_failed_required_gate_is_blocked(
        self, tmp_path: Path
    ) -> None:
        _init_git(tmp_path)
        gate_path = ".build/rig-relay/derived/test_gate.json"
        _write_prompt(tmp_path, gate_path, json.dumps({"verdict": "FAIL"}))
        item = _make_queue_item("t1", required_gates_before=[gate_path])
        _write_queue(tmp_path, [item])
        _write_prompt(tmp_path, ".rig/roadmap/prompts/t1.txt")
        result = _run_steward(tmp_path)
        assert result.returncode == 0
        run = _read_last_run(tmp_path)
        assert run["steward_state"] in ("blocked", "audit_unblock_plan")

    def test_missing_gate_file_is_blocked(self, tmp_path: Path) -> None:
        _init_git(tmp_path)
        item = _make_queue_item("t1", required_gates_before=["nonexistent.json"])
        _write_queue(tmp_path, [item])
        _write_prompt(tmp_path, ".rig/roadmap/prompts/t1.txt")
        result = _run_steward(tmp_path)
        assert result.returncode == 0
        run = _read_last_run(tmp_path)
        assert run["steward_state"] in ("blocked", "audit_unblock_plan")


class TestLaneOwnership:
    def test_active_lane_ownership_collision_is_blocked(self, tmp_path: Path) -> None:
        _init_git(tmp_path)
        item = _make_queue_item("t1", allowed_files=["src/shared.py"])
        _write_queue(tmp_path, [item])
        _write_prompt(tmp_path, ".rig/roadmap/prompts/t1.txt")
        _write_lanes(
            tmp_path,
            [
                {
                    "lane_id": "other-lane",
                    "task_id": "other-task",
                    "status": "active",
                    "owned_files": ["src/shared.py"],
                }
            ],
        )
        result = _run_steward(tmp_path)
        assert result.returncode == 0
        run = _read_last_run(tmp_path)
        assert run["steward_state"] in ("blocked", "audit_unblock_plan")


class TestDryRun:
    def test_safe_queued_task_in_dry_run_constructs_command_but_does_not_launch(
        self, tmp_path: Path
    ) -> None:
        _init_git(tmp_path)
        item = _make_queue_item("t1")
        _write_queue(tmp_path, [item])
        _write_prompt(tmp_path, ".rig/roadmap/prompts/t1.txt")
        result = _run_steward(tmp_path, dry_run=True)
        assert result.returncode == 0
        run = _read_last_run(tmp_path)
        assert run["steward_state"] in ("continue_lane", "advance_to_next_lane")
        cmd = run.get("command_meta")
        assert cmd is not None
        assert cmd["dry_run"] is True
        assert cmd["launched"] is False
        assert "--dangerously-skip-permissions" not in str(cmd.get("argv", []))


class TestCompletionCriteria:
    def test_completion_criteria_satisfied_moves_to_finalize_or_advance(
        self, tmp_path: Path
    ) -> None:
        _init_git(tmp_path)
        art_path = ".build/rig-relay/derived/final_report.json"
        _write_prompt(tmp_path, art_path, "{}")
        item = _make_queue_item(
            "t1",
            status="active",
            completion_criteria={
                "required_artifacts": [art_path],
                "final_report_path": art_path,
            },
        )
        _write_queue(tmp_path, [item])
        _write_prompt(tmp_path, ".rig/roadmap/prompts/t1.txt")
        result = _run_steward(tmp_path)
        assert result.returncode == 0
        run = _read_last_run(tmp_path)
        assert run["steward_state"] in ("finalize_lane", "advance_to_next_lane")

    def test_incomplete_completion_criteria_stays_continue(
        self, tmp_path: Path
    ) -> None:
        _init_git(tmp_path)
        item = _make_queue_item(
            "t1", completion_criteria={"required_artifacts": ["nonexistent.json"]}
        )
        _write_queue(tmp_path, [item])
        _write_prompt(tmp_path, ".rig/roadmap/prompts/t1.txt")
        result = _run_steward(tmp_path)
        assert result.returncode == 0
        run = _read_last_run(tmp_path)
        comp = run.get("completion_check")
        if comp:
            assert comp.get("required_artifacts_present") is False


class TestMaxContinuations:
    def test_max_continuations_exceeded_is_blocked(self, tmp_path: Path) -> None:
        _init_git(tmp_path)
        item = _make_queue_item("t1", max_continuations=1, continuation_count=1)
        _write_queue(tmp_path, [item])
        _write_prompt(tmp_path, ".rig/roadmap/prompts/t1.txt")
        result = _run_steward(tmp_path)
        assert result.returncode == 0
        run = _read_last_run(tmp_path)
        assert run["steward_state"] in ("blocked", "audit_unblock_plan")


class TestNoDangerousSkip:
    def test_command_never_contains_dangerously_skip_permissions(
        self, tmp_path: Path
    ) -> None:
        _init_git(tmp_path)
        item = _make_queue_item("t1")
        _write_queue(tmp_path, [item])
        _write_prompt(tmp_path, ".rig/roadmap/prompts/t1.txt")
        result = _run_steward(tmp_path, dry_run=True)
        assert result.returncode == 0
        run = _read_last_run(tmp_path)
        cmd = run.get("command_meta")
        if cmd and cmd.get("argv"):
            argv_str = " ".join(cmd["argv"])
            assert "--dangerously-skip-permissions" not in argv_str


class TestArtifactValidation:
    def test_last_run_artifact_is_valid_json(self, tmp_path: Path) -> None:
        _init_git(tmp_path)
        _write_queue(tmp_path, [])
        _run_steward(tmp_path)
        run = _read_last_run(tmp_path)
        assert "schema_version" in run
        assert "generated_at" in run
        assert "steward_state" in run
        assert run["steward_state"] in (
            "no_action",
            "blocked",
            "continue_lane",
            "finalize_lane",
            "advance_to_next_lane",
            "audit_unblock_plan",
        )

    def test_jsonl_event_is_append_only_and_valid_json_per_line(
        self, tmp_path: Path
    ) -> None:
        _init_git(tmp_path)
        _write_queue(tmp_path, [])
        _run_steward(tmp_path)
        events = _read_events(tmp_path)
        assert len(events) >= 1
        for ev in events:
            assert "event" in ev
            assert "state" in ev


class TestAuditUnblockPlan:
    def test_all_queue_items_blocked_produces_audit_unblock_plan(
        self, tmp_path: Path
    ) -> None:
        _init_git(tmp_path)
        items = [
            _make_queue_item("t1", required_gates_before=["nonexistent.json"]),
            _make_queue_item("t2", forbidden_files=["secrets.env"]),
        ]
        _write_queue(tmp_path, items)
        _write_prompt(tmp_path, ".rig/roadmap/prompts/t1.txt")
        _write_prompt(tmp_path, ".rig/roadmap/prompts/t2.txt")
        _dirty_file(tmp_path, "secrets.env")
        result = _run_steward(tmp_path)
        assert result.returncode == 0
        run = _read_last_run(tmp_path)
        assert run["steward_state"] == "audit_unblock_plan"
        assert run.get("audit_path") is not None

    def test_mixed_blocked_completed_queue_with_no_runnable_produces_audit(
        self, tmp_path: Path
    ) -> None:
        _init_git(tmp_path)
        items = [
            _make_queue_item("t1", status="completed"),
            _make_queue_item("t2", required_gates_before=["nonexistent.json"]),
        ]
        _write_queue(tmp_path, items)
        _write_prompt(tmp_path, ".rig/roadmap/prompts/t2.txt")
        result = _run_steward(tmp_path)
        assert result.returncode == 0
        run = _read_last_run(tmp_path)
        assert run["steward_state"] == "audit_unblock_plan"


class TestAuditContent:
    def test_audit_groups_blockers_by_blocker_class(self, tmp_path: Path) -> None:
        _init_git(tmp_path)
        items = [
            _make_queue_item("t1", required_gates_before=["nonexistent.json"]),
            _make_queue_item("t2", forbidden_files=["secrets.env"]),
        ]
        _write_queue(tmp_path, items)
        _write_prompt(tmp_path, ".rig/roadmap/prompts/t1.txt")
        _write_prompt(tmp_path, ".rig/roadmap/prompts/t2.txt")
        _dirty_file(tmp_path, "secrets.env")
        _run_steward(tmp_path)
        audit_path = (
            tmp_path
            / ".build"
            / "rig-relay"
            / "derived"
            / "opencode_idle_steward_unblock_audit_v1.json"
        )
        assert audit_path.exists()
        audit = json.loads(audit_path.read_text(encoding="utf-8"))
        assert "blocker_summary" in audit
        bs = audit["blocker_summary"]
        assert bs.get("failed_gate", 0) > 0
        assert bs.get("forbidden_file_scope", 0) > 0

    def test_audit_emits_per_task_blocker_records(self, tmp_path: Path) -> None:
        _init_git(tmp_path)
        items = [_make_queue_item("t1", required_gates_before=["nonexistent.json"])]
        _write_queue(tmp_path, items)
        _write_prompt(tmp_path, ".rig/roadmap/prompts/t1.txt")
        _run_steward(tmp_path)
        audit_path = (
            tmp_path
            / ".build"
            / "rig-relay"
            / "derived"
            / "opencode_idle_steward_unblock_audit_v1.json"
        )
        audit = json.loads(audit_path.read_text(encoding="utf-8"))
        pbt = audit.get("per_task_blockers", [])
        assert len(pbt) >= 1
        assert any(t.get("task_id") == "t1" for t in pbt)

    def test_audit_emits_recommended_unblock_slices(self, tmp_path: Path) -> None:
        _init_git(tmp_path)
        items = [
            _make_queue_item("t1", prompt_path="missing.txt"),
            _make_queue_item("t2", allowed_files=["src/dirty.py"]),
        ]
        _write_queue(tmp_path, items)
        _dirty_file(tmp_path, "src/dirty.py")
        _run_steward(tmp_path)
        audit_path = (
            tmp_path
            / ".build"
            / "rig-relay"
            / "derived"
            / "opencode_idle_steward_unblock_audit_v1.json"
        )
        audit = json.loads(audit_path.read_text(encoding="utf-8"))
        slices = audit.get("recommended_unblock_slices", [])
        assert len(slices) > 0
        for s in slices:
            assert "recommendation_id" in s
            assert "blocker_classes_addressed" in s
            assert "risk_level" in s

    def test_audit_does_not_include_raw_prompt_text(self, tmp_path: Path) -> None:
        _init_git(tmp_path)
        items = [_make_queue_item("t1", required_gates_before=["nonexistent.json"])]
        _write_queue(tmp_path, items)
        _write_prompt(tmp_path, ".rig/roadmap/prompts/t1.txt", "SECRET_PROMPT_BODY")
        _run_steward(tmp_path)
        audit_path = (
            tmp_path
            / ".build"
            / "rig-relay"
            / "derived"
            / "opencode_idle_steward_unblock_audit_v1.json"
        )
        raw = audit_path.read_text(encoding="utf-8")
        assert "SECRET_PROMPT_BODY" not in raw

    def test_audit_does_not_launch_opencode(self, tmp_path: Path) -> None:
        _init_git(tmp_path)
        items = [_make_queue_item("t1", required_gates_before=["nonexistent.json"])]
        _write_queue(tmp_path, items)
        _write_prompt(tmp_path, ".rig/roadmap/prompts/t1.txt")
        _run_steward(tmp_path, dry_run=True)
        run = _read_last_run(tmp_path)
        assert run["steward_state"] == "audit_unblock_plan"
        cmd = run.get("command_meta")
        assert cmd is None or cmd.get("launched") is False

    def test_audit_json_validates_against_schema(self, tmp_path: Path) -> None:
        _init_git(tmp_path)
        items = [_make_queue_item("t1", required_gates_before=["nonexistent.json"])]
        _write_queue(tmp_path, items)
        _write_prompt(tmp_path, ".rig/roadmap/prompts/t1.txt")
        _run_steward(tmp_path)
        audit_path = (
            tmp_path
            / ".build"
            / "rig-relay"
            / "derived"
            / "opencode_idle_steward_unblock_audit_v1.json"
        )
        audit = json.loads(audit_path.read_text(encoding="utf-8"))
        assert audit["schema_version"] == "rig.relay.opencode_unblock_audit.v1"
        assert "generated_at" in audit
        assert "blocker_summary" in audit
        assert "per_task_blockers" in audit
        assert "recommended_unblock_slices" in audit
        assert "safety_stop_reason" in audit

    def test_audit_jsonl_candidates_are_valid_json_per_line(
        self, tmp_path: Path
    ) -> None:
        _init_git(tmp_path)
        items = [_make_queue_item("t1", required_gates_before=["nonexistent.json"])]
        _write_queue(tmp_path, items)
        _write_prompt(tmp_path, ".rig/roadmap/prompts/t1.txt")
        _run_steward(tmp_path)
        candidates_path = (
            tmp_path
            / ".build"
            / "rig-relay"
            / "derived"
            / "opencode_idle_steward_unblock_candidates_v1.jsonl"
        )
        assert candidates_path.exists()
        for line in candidates_path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped:
                evt = json.loads(stripped)
                assert "event" in evt
                assert evt["event"] == "unblock_candidate"


class TestSafeQueuedTask:
    def test_safe_queued_task_with_no_dirty_files_is_runnable(
        self, tmp_path: Path
    ) -> None:
        _init_git(tmp_path)
        item = _make_queue_item("t1")
        _write_queue(tmp_path, [item])
        _write_prompt(tmp_path, ".rig/roadmap/prompts/t1.txt")
        result = _run_steward(tmp_path, dry_run=True)
        assert result.returncode == 0
        run = _read_last_run(tmp_path)
        assert run["steward_state"] in ("continue_lane", "advance_to_next_lane")
        cmd = run.get("command_meta")
        assert cmd is not None
        assert cmd["dry_run"] is True

    def test_active_lane_continuation_preferred_over_queued(
        self, tmp_path: Path
    ) -> None:
        _init_git(tmp_path)
        active = _make_queue_item("active-t1", status="active", priority=10)
        queued = _make_queue_item("queued-t1", status="queued", priority=0)
        _write_queue(tmp_path, [active, queued])
        _write_prompt(tmp_path, ".rig/roadmap/prompts/active-t1.txt")
        _write_prompt(tmp_path, ".rig/roadmap/prompts/queued-t1.txt")
        result = _run_steward(tmp_path, dry_run=True)
        assert result.returncode == 0
        run = _read_last_run(tmp_path)
        selected = run.get("selected_task")
        if selected:
            assert selected["task_id"] == "active-t1"


class TestNoActionWhenOnlyCompleted:
    def test_only_completed_items_produces_no_action(self, tmp_path: Path) -> None:
        _init_git(tmp_path)
        item = _make_queue_item("t1", status="completed")
        _write_queue(tmp_path, [item])
        _write_prompt(tmp_path, ".rig/roadmap/prompts/t1.txt")
        result = _run_steward(tmp_path)
        assert result.returncode == 0
        run = _read_last_run(tmp_path)
        assert run["steward_state"] in ("no_action", "audit_unblock_plan")


class TestCommandConstruction:
    def test_command_includes_format_json_agent_title(self, tmp_path: Path) -> None:
        _init_git(tmp_path)
        item = _make_queue_item("t1", title="My Task", agent="custom-agent")
        _write_queue(tmp_path, [item])
        _write_prompt(tmp_path, ".rig/roadmap/prompts/t1.txt")
        result = _run_steward(tmp_path, dry_run=True)
        assert result.returncode == 0
        run = _read_last_run(tmp_path)
        cmd = run.get("command_meta")
        if cmd and cmd.get("argv"):
            argv_str = " ".join(cmd["argv"])
            assert "--format" in argv_str
            assert "json" in argv_str
            assert "--title" in argv_str
            assert "My Task" in argv_str
            assert "--agent" in argv_str
            assert "custom-agent" in argv_str

    def test_command_excludes_prompt_body_in_evidence(self, tmp_path: Path) -> None:
        _init_git(tmp_path)
        item = _make_queue_item("t1")
        _write_queue(tmp_path, [item])
        _write_prompt(
            tmp_path, ".rig/roadmap/prompts/t1.txt", "This is the actual prompt body"
        )
        result = _run_steward(tmp_path, dry_run=True)
        assert result.returncode == 0
        run = _read_last_run(tmp_path)
        cmd = run.get("command_meta")
        if cmd:
            raw_str = json.dumps(cmd)
            assert "actual prompt body" not in raw_str


class TestJsonlAppendOnly:
    def test_multiple_runs_append_events_not_overwrite(self, tmp_path: Path) -> None:
        _init_git(tmp_path)
        items = [
            _make_queue_item("t1", required_gates_before=["nonexistent.json"]),
            _make_queue_item("t2", forbidden_files=["secrets.env"]),
        ]
        _write_queue(tmp_path, items)
        _write_prompt(tmp_path, ".rig/roadmap/prompts/t1.txt")
        _write_prompt(tmp_path, ".rig/roadmap/prompts/t2.txt")
        _dirty_file(tmp_path, "secrets.env")
        _run_steward(tmp_path)
        events1 = len(_read_events(tmp_path))
        _run_steward(tmp_path)
        events2 = len(_read_events(tmp_path))
        assert events2 >= events1


class TestSafetyStops:
    def test_blocked_state_exits_zero(self, tmp_path: Path) -> None:
        _init_git(tmp_path)
        item = _make_queue_item("t1", allowed_files=["src/touched.py"])
        _write_queue(tmp_path, [item])
        _write_prompt(tmp_path, ".rig/roadmap/prompts/t1.txt")
        _dirty_file(tmp_path, "src/touched.py")
        result = _run_steward(tmp_path)
        assert result.returncode == 0

    def test_audit_unblock_plan_exits_zero(self, tmp_path: Path) -> None:
        _init_git(tmp_path)
        items = [_make_queue_item("t1", required_gates_before=["nonexistent.json"])]
        _write_queue(tmp_path, items)
        _write_prompt(tmp_path, ".rig/roadmap/prompts/t1.txt")
        result = _run_steward(tmp_path)
        assert result.returncode == 0


class TestRunArtifactContentLight:
    def test_last_run_artifact_excludes_prompt_body(self, tmp_path: Path) -> None:
        _init_git(tmp_path)
        item = _make_queue_item("t1")
        _write_queue(tmp_path, [item])
        _write_prompt(tmp_path, ".rig/roadmap/prompts/t1.txt", "SECRET_PROMPT_CONTENT")
        result = _run_steward(tmp_path, dry_run=True)
        assert result.returncode == 0
        run = _read_last_run(tmp_path)
        raw = json.dumps(run)
        assert "SECRET_PROMPT_CONTENT" not in raw

    def test_last_run_includes_prompt_sha256_not_body(self, tmp_path: Path) -> None:
        _init_git(tmp_path)
        item = _make_queue_item("t1")
        _write_queue(tmp_path, [item])
        _write_prompt(tmp_path, ".rig/roadmap/prompts/t1.txt", "prompt content")
        result = _run_steward(tmp_path, dry_run=True)
        assert result.returncode == 0
        run = _read_last_run(tmp_path)
        cmd = run.get("command_meta")
        if cmd:
            assert "prompt_sha256" in cmd
            assert "prompt_path" in cmd


class TestDryRunNoSubprocessLaunch:
    def test_dry_run_never_calls_opencode_subprocess(self, tmp_path: Path) -> None:
        _init_git(tmp_path)
        item = _make_queue_item("t1")
        _write_queue(tmp_path, [item])
        _write_prompt(tmp_path, ".rig/roadmap/prompts/t1.txt")
        result = _run_steward(tmp_path, dry_run=True)
        assert result.returncode == 0
        run = _read_last_run(tmp_path)
        cmd_meta = run.get("command_meta")
        if cmd_meta:
            assert cmd_meta["launched"] is False


class TestStreamingFlags:
    def test_dry_run_reports_streaming_true_even_when_not_launched(
        self, tmp_path: Path
    ) -> None:
        _init_git(tmp_path)
        item = _make_queue_item("t1")
        _write_queue(tmp_path, [item])
        _write_prompt(tmp_path, ".rig/roadmap/prompts/t1.txt")
        _run_steward(tmp_path, dry_run=True)
        run = _read_last_run(tmp_path)
        cmd = run.get("command_meta")
        if cmd:
            assert cmd.get("streaming") is True
            assert cmd["launched"] is False

    def test_opencode_path_appears_in_argv(self, tmp_path: Path) -> None:
        _init_git(tmp_path)
        item = _make_queue_item("t1")
        _write_queue(tmp_path, [item])
        _write_prompt(tmp_path, ".rig/roadmap/prompts/t1.txt")
        _run_steward(tmp_path, dry_run=True, opencode_path="/custom/opencode")
        run = _read_last_run(tmp_path)
        cmd = run.get("command_meta")
        if cmd and cmd.get("argv"):
            assert cmd["argv"][0] == "/custom/opencode"

    def test_thinking_flag_in_argv(self, tmp_path: Path) -> None:
        _init_git(tmp_path)
        item = _make_queue_item("t1")
        _write_queue(tmp_path, [item])
        _write_prompt(tmp_path, ".rig/roadmap/prompts/t1.txt")
        _run_steward(tmp_path, dry_run=True, show_reasoning=True)
        run = _read_last_run(tmp_path)
        cmd = run.get("command_meta")
        if cmd and cmd.get("argv"):
            assert "--thinking" in cmd["argv"]

    def test_no_stream_flag_accepted_in_parse_args(self, tmp_path: Path) -> None:
        _init_git(tmp_path)
        item = _make_queue_item("t1")
        _write_queue(tmp_path, [item])
        _write_prompt(tmp_path, ".rig/roadmap/prompts/t1.txt")
        result = _run_steward(tmp_path, dry_run=True, no_stream=True)
        assert result.returncode == 0
        run = _read_last_run(tmp_path)
        assert run["steward_state"] in ("continue_lane", "advance_to_next_lane")


class TestStreamingWithFakeOpencode:
    def test_streaming_parses_json_events_and_writes_records(
        self, tmp_path: Path
    ) -> None:
        _init_git(tmp_path)
        fake_opencode = tmp_path / "fake_opencode"
        fake_opencode.write_text(
            """#!/usr/bin/env python3
import sys, json
events = [
    {"type": "step_start", "timestamp": 1000, "sessionID": "ses_test", "part": {"type": "step-start"}},
    {"type": "reasoning", "timestamp": 1001, "sessionID": "ses_test", "part": {"type": "reasoning", "text": "I need to read the file"}},
    {"type": "tool_use", "timestamp": 1002, "sessionID": "ses_test", "part": {"type": "tool", "tool": "read", "state": {"status": "completed", "input": {"filePath": "src/main.py"}, "title": "src/main.py"}}},
    {"type": "text", "timestamp": 1003, "sessionID": "ses_test", "part": {"type": "text", "text": "The file says hello"}},
    {"type": "step_finish", "timestamp": 1004, "sessionID": "ses_test", "part": {"type": "step-finish", "tokens": {"input": 10, "output": 5, "total": 15}, "cost": 0.001}},
]
for e in events:
    print(json.dumps(e), flush=True)
sys.exit(0)
"""
        )
        fake_opencode.chmod(0o755)
        item = _make_queue_item("t1")
        _write_queue(tmp_path, [item])
        _write_prompt(tmp_path, ".rig/roadmap/prompts/t1.txt", "read src/main.py")
        result = _run_steward(tmp_path, dry_run=False, opencode_path=str(fake_opencode))
        assert result.returncode == 0
        run = _read_last_run(tmp_path)
        assert run["steward_state"] in ("continue_lane", "advance_to_next_lane")
        cmd = run.get("command_meta")
        assert cmd is not None
        assert cmd["launched"] is True
        assert cmd.get("streaming") is True
        assert cmd.get("exit_code") == 0
        events = _read_events(tmp_path)
        stream_events = [e for e in events if e.get("event") == "opencode_stream"]
        assert len(stream_events) == 5
        event_types = [e["stream_event_type"] for e in stream_events]
        assert "step_start" in event_types
        assert "reasoning" in event_types
        assert "tool_use" in event_types
        assert "text" in event_types
        assert "step_finish" in event_types

    def test_streaming_redacts_reasoning_in_artifacts(self, tmp_path: Path) -> None:
        _init_git(tmp_path)
        fake_opencode = tmp_path / "fake_opencode"
        fake_opencode.write_text(
            """#!/usr/bin/env python3
import sys, json
events = [
    {"type": "reasoning", "timestamp": 1001, "sessionID": "ses_test", "part": {"type": "reasoning", "text": "The plan is to modify the config file to add a new backend."}},
]
for e in events:
    print(json.dumps(e), flush=True)
sys.exit(0)
"""
        )
        fake_opencode.chmod(0o755)
        item = _make_queue_item("t1")
        _write_queue(tmp_path, [item])
        _write_prompt(tmp_path, ".rig/roadmap/prompts/t1.txt", "do something")
        _run_steward(tmp_path, dry_run=False, opencode_path=str(fake_opencode))
        events = _read_events(tmp_path)
        reasoning_events = [
            e
            for e in events
            if e.get("event") == "opencode_stream"
            and e.get("stream_event_type") == "reasoning"
        ]
        assert len(reasoning_events) >= 1
        for rev in reasoning_events:
            assert rev["reasoning_redacted"] is True
            assert "plan" not in rev.get("summary_text", "")

    def test_streaming_tool_event_includes_tool_name_and_status(
        self, tmp_path: Path
    ) -> None:
        _init_git(tmp_path)
        fake_opencode = tmp_path / "fake_opencode"
        fake_opencode.write_text(
            """#!/usr/bin/env python3
import sys, json
events = [
    {"type": "tool_use", "timestamp": 1002, "sessionID": "ses_test", "part": {"type": "tool", "tool": "bash", "state": {"status": "completed", "input": {"command": "ls"}, "metadata": {"exit": 0}, "title": "List files"}}},
]
for e in events:
    print(json.dumps(e), flush=True)
sys.exit(0)
"""
        )
        fake_opencode.chmod(0o755)
        item = _make_queue_item("t1")
        _write_queue(tmp_path, [item])
        _write_prompt(tmp_path, ".rig/roadmap/prompts/t1.txt", "run ls")
        _run_steward(tmp_path, dry_run=False, opencode_path=str(fake_opencode))
        events = _read_events(tmp_path)
        tool_events = [
            e
            for e in events
            if e.get("event") == "opencode_stream"
            and e.get("stream_event_type") == "tool_use"
        ]
        assert len(tool_events) >= 1
        te = tool_events[0]
        assert te["tool_name"] == "bash"
        assert te["tool_status"] == "completed"
        assert te["exit_code"] == 0
        assert "List files" in te.get("summary_text", "")

    def test_streaming_extracts_paths_from_read_tool(self, tmp_path: Path) -> None:
        _init_git(tmp_path)
        fake_opencode = tmp_path / "fake_opencode"
        fake_opencode.write_text(
            """#!/usr/bin/env python3
import sys, json
events = [
    {"type": "tool_use", "timestamp": 1002, "sessionID": "ses_test", "part": {"type": "tool", "tool": "read", "state": {"status": "completed", "input": {"filePath": "/tmp/test-opencode/test.py"}, "title": "test.py"}}},
]
for e in events:
    print(json.dumps(e), flush=True)
sys.exit(0)
"""
        )
        fake_opencode.chmod(0o755)
        item = _make_queue_item("t1")
        _write_queue(tmp_path, [item])
        _write_prompt(tmp_path, ".rig/roadmap/prompts/t1.txt", "read test.py")
        _run_steward(tmp_path, dry_run=False, opencode_path=str(fake_opencode))
        events = _read_events(tmp_path)
        tool_events = [
            e
            for e in events
            if e.get("event") == "opencode_stream"
            and e.get("stream_event_type") == "tool_use"
        ]
        assert len(tool_events) >= 1
        te = tool_events[0]
        assert len(te.get("paths", [])) >= 1
        assert "/tmp/test-opencode/test.py" in te["paths"]
        assert len(te.get("path_hashes", [])) >= 1

    def test_streaming_does_not_store_tool_output_content(self, tmp_path: Path) -> None:
        _init_git(tmp_path)
        fake_opencode = tmp_path / "fake_opencode"
        fake_opencode.write_text(
            """#!/usr/bin/env python3
import sys, json
events = [
    {"type": "tool_use", "timestamp": 1002, "sessionID": "ses_test", "part": {"type": "tool", "tool": "read", "state": {"status": "completed", "input": {"filePath": "/tmp/f.py"}, "output": "SECRET_FILE_CONTENT\\nline2", "title": "f.py"}}},
]
for e in events:
    print(json.dumps(e), flush=True)
sys.exit(0)
"""
        )
        fake_opencode.chmod(0o755)
        item = _make_queue_item("t1")
        _write_queue(tmp_path, [item])
        _write_prompt(tmp_path, ".rig/roadmap/prompts/t1.txt", "read f.py")
        _run_steward(tmp_path, dry_run=False, opencode_path=str(fake_opencode))
        events_path = (
            tmp_path
            / ".build"
            / "rig-relay"
            / "derived"
            / "opencode_idle_steward_events_v1.jsonl"
        )
        raw = events_path.read_text(encoding="utf-8")
        assert "SECRET_FILE_CONTENT" not in raw

    def test_streaming_no_stream_flag_uses_subprocess_run(self, tmp_path: Path) -> None:
        _init_git(tmp_path)
        fake_opencode = tmp_path / "fake_opencode"
        fake_opencode.write_text(
            """#!/usr/bin/env python3
print("not json")
"""
        )
        fake_opencode.chmod(0o755)
        item = _make_queue_item("t1")
        _write_queue(tmp_path, [item])
        _write_prompt(tmp_path, ".rig/roadmap/prompts/t1.txt", "run something")
        result = _run_steward(
            tmp_path, dry_run=False, no_stream=True, opencode_path=str(fake_opencode)
        )
        assert result.returncode == 0
        run = _read_last_run(tmp_path)
        cmd = run.get("command_meta")
        assert cmd is not None
        assert cmd.get("streaming") is False

    def test_streaming_event_record_schema_fields(self, tmp_path: Path) -> None:
        _init_git(tmp_path)
        fake_opencode = tmp_path / "fake_opencode"
        fake_opencode.write_text(
            """#!/usr/bin/env python3
import sys, json
events = [
    {"type": "step_start", "timestamp": 1000, "sessionID": "ses_test", "part": {"type": "step-start"}},
    {"type": "text", "timestamp": 1003, "sessionID": "ses_test", "part": {"type": "text", "text": "hello"}},
    {"type": "step_finish", "timestamp": 1004, "sessionID": "ses_test", "part": {"type": "step-finish", "tokens": {"input": 10, "output": 5, "total": 15}, "cost": 0.001}},
]
for e in events:
    print(json.dumps(e), flush=True)
sys.exit(0)
"""
        )
        fake_opencode.chmod(0o755)
        item = _make_queue_item("t1")
        _write_queue(tmp_path, [item])
        _write_prompt(tmp_path, ".rig/roadmap/prompts/t1.txt", "say hello")
        _run_steward(tmp_path, dry_run=False, opencode_path=str(fake_opencode))
        events = _read_events(tmp_path)
        stream_events = [e for e in events if e.get("event") == "opencode_stream"]
        for se in stream_events:
            assert "generated_at" in se
            assert "session_id" in se
            assert "stream_event_type" in se
            assert "summary_text" in se
            assert "reasoning_redacted" in se
            assert "paths" in se
            assert "path_hashes" in se

    def test_streaming_stderr_captured_and_hashed(self, tmp_path: Path) -> None:
        _init_git(tmp_path)
        fake_opencode = tmp_path / "fake_opencode"
        fake_opencode.write_text(
            """#!/usr/bin/env python3
import sys
print("stdout ok", flush=True)
print("diagnostic message", file=sys.stderr, flush=True)
sys.exit(0)
"""
        )
        fake_opencode.chmod(0o755)
        item = _make_queue_item("t1")
        _write_queue(tmp_path, [item])
        _write_prompt(tmp_path, ".rig/roadmap/prompts/t1.txt", "run something")
        _run_steward(tmp_path, dry_run=False, opencode_path=str(fake_opencode))
        run = _read_last_run(tmp_path)
        cmd = run.get("command_meta")
        assert cmd is not None
        assert cmd.get("streaming") is True
        assert cmd.get("exit_code") == 0
        assert cmd.get("stderr_sha256") is not None
        assert cmd.get("stderr_truncated_bytes", 0) > 0

    def test_streaming_does_not_store_raw_prompt_text(self, tmp_path: Path) -> None:
        _init_git(tmp_path)
        fake_opencode = tmp_path / "fake_opencode"
        fake_opencode.write_text(
            """#!/usr/bin/env python3
import sys, json
events = [
    {"type": "text", "timestamp": 1003, "sessionID": "ses_test", "part": {"type": "text", "text": "ok"}},
]
for e in events:
    print(json.dumps(e), flush=True)
sys.exit(0)
"""
        )
        fake_opencode.chmod(0o755)
        item = _make_queue_item("t1")
        _write_queue(tmp_path, [item])
        _write_prompt(
            tmp_path, ".rig/roadmap/prompts/t1.txt", "SUPER_SECRET_PROMPT_CONTENT"
        )
        _run_steward(tmp_path, dry_run=False, opencode_path=str(fake_opencode))
        events_path = (
            tmp_path
            / ".build"
            / "rig-relay"
            / "derived"
            / "opencode_idle_steward_events_v1.jsonl"
        )
        raw = events_path.read_text(encoding="utf-8")
        assert "SUPER_SECRET_PROMPT_CONTENT" not in raw
        run_raw = (
            tmp_path
            / ".build"
            / "rig-relay"
            / "derived"
            / "opencode_idle_steward_last_run_v1.json"
        ).read_text(encoding="utf-8")
        assert "SUPER_SECRET_PROMPT_CONTENT" not in run_raw

    def test_streaming_show_reasoning_flag_accepted(self, tmp_path: Path) -> None:
        _init_git(tmp_path)
        fake_opencode = tmp_path / "fake_opencode"
        fake_opencode.write_text(
            """#!/usr/bin/env python3
import sys, json
events = [
    {"type": "step_start", "timestamp": 1000, "sessionID": "ses_test", "part": {"type": "step-start"}},
    {"type": "text", "timestamp": 1003, "sessionID": "ses_test", "part": {"type": "text", "text": "done"}},
]
for e in events:
    print(json.dumps(e), flush=True)
sys.exit(0)
"""
        )
        fake_opencode.chmod(0o755)
        item = _make_queue_item("t1")
        _write_queue(tmp_path, [item])
        _write_prompt(tmp_path, ".rig/roadmap/prompts/t1.txt", "do task")
        result = _run_steward(
            tmp_path,
            dry_run=False,
            show_reasoning=True,
            opencode_path=str(fake_opencode),
        )
        assert result.returncode == 0

    def test_streaming_nonzero_exit_code_captured(self, tmp_path: Path) -> None:
        _init_git(tmp_path)
        fake_opencode = tmp_path / "fake_opencode"
        fake_opencode.write_text(
            """#!/usr/bin/env python3
import sys, json
print(json.dumps({"type": "step_start", "timestamp": 1000, "sessionID": "ses_test", "part": {"type": "step-start"}}), flush=True)
sys.exit(2)
"""
        )
        fake_opencode.chmod(0o755)
        item = _make_queue_item("t1")
        _write_queue(tmp_path, [item])
        _write_prompt(tmp_path, ".rig/roadmap/prompts/t1.txt", "do task")
        _run_steward(tmp_path, dry_run=False, opencode_path=str(fake_opencode))
        run = _read_last_run(tmp_path)
        cmd = run.get("command_meta")
        assert cmd is not None
        assert cmd.get("exit_code") == 2

    def test_streaming_duration_measured(self, tmp_path: Path) -> None:
        _init_git(tmp_path)
        fake_opencode = tmp_path / "fake_opencode"
        fake_opencode.write_text(
            """#!/usr/bin/env python3
import sys, json
print(json.dumps({"type": "text", "timestamp": 1003, "sessionID": "ses_test", "part": {"type": "text", "text": "ok"}}), flush=True)
sys.exit(0)
"""
        )
        fake_opencode.chmod(0o755)
        item = _make_queue_item("t1")
        _write_queue(tmp_path, [item])
        _write_prompt(tmp_path, ".rig/roadmap/prompts/t1.txt", "do task")
        _run_steward(tmp_path, dry_run=False, opencode_path=str(fake_opencode))
        run = _read_last_run(tmp_path)
        cmd = run.get("command_meta")
        assert cmd is not None
        assert cmd.get("duration_ms", -1) >= 0


class TestSanitizeEnv:
    def test_sanitize_env_strips_sensitive_vars(self, tmp_path: Path) -> None:
        import os as _os

        _init_git(tmp_path)
        fake_opencode = tmp_path / "fake_opencode"
        fake_opencode.write_text(
            """#!/usr/bin/env python3
import os, sys, json
has_token = "GITHUB_TOKEN" in os.environ
print(json.dumps({"type": "text", "timestamp": 1, "sessionID": "s", "part": {"type": "text", "text": str(not has_token)}}), flush=True)
sys.exit(0)
"""
        )
        fake_opencode.chmod(0o755)
        item = _make_queue_item("t1")
        _write_queue(tmp_path, [item])
        _write_prompt(tmp_path, ".rig/roadmap/prompts/t1.txt", "do task")
        env = _os.environ.copy()
        env["GITHUB_TOKEN"] = "ghp_fake_token"
        result = subprocess.run(
            [
                sys.executable,
                str(STEWARD_PATH),
                "--project-root",
                str(tmp_path),
                "--worktree",
                "default",
                "--opencode-path",
                str(fake_opencode),
            ],
            capture_output=True,
            text=True,
            cwd=tmp_path,
            timeout=30,
            env=env,
        )
        assert result.returncode == 0
        events = _read_events(tmp_path)
        text_events = [
            e
            for e in events
            if e.get("event") == "opencode_stream"
            and e.get("stream_event_type") == "text"
        ]
        assert len(text_events) >= 1
        assert "True" in text_events[0].get("summary_text", "")


def _write_capsule(root: Path, capsule: dict) -> Path:
    capsule_dir = root / ".build" / "rig-relay" / "derived"
    capsule_dir.mkdir(parents=True, exist_ok=True)
    capsule_path = capsule_dir / "opencode_steward_context_capsule_v1.json"
    capsule_path.write_text(json.dumps(capsule), encoding="utf-8")
    return capsule_path


def _read_capsule(root: Path) -> dict:
    p = (
        root
        / ".build"
        / "rig-relay"
        / "derived"
        / "opencode_steward_context_capsule_v1.json"
    )
    return json.loads(p.read_text(encoding="utf-8"))


def _minimal_capsule(**overrides) -> dict:
    from datetime import UTC, datetime

    base = {
        "schema_version": "rig.relay.opencode_steward_context_capsule.v1",
        "capsule_id": "test-capsule-001",
        "generated_at": datetime.now(UTC).isoformat(),
        "source_artifact_paths": [],
        "source_artifact_hashes": [],
        "active_lane_summary": {"total_active_lanes": 0, "lanes": []},
        "worker_report_summary": {"total_reports": 0, "completed_lane_ids": []},
        "lease_summary": {
            "active_lane_leases": 0,
            "active_path_leases": 0,
            "collision_count": 0,
        },
        "dirty_state_summary": {
            "modified_count": 0,
            "staged_count": 0,
            "untracked_count": 0,
        },
        "evidence_digest": {
            "total_evidence_artifacts": 0,
            "relevant_finding_count": 0,
            "relevant_gate_count": 0,
        },
        "gate_status": {
            "total_gates_checked": 0,
            "passed_count": 0,
            "failed_count": 0,
            "missing_count": 0,
        },
        "completion_criteria_status": {
            "required_artifacts_present": False,
            "required_tests_present": False,
            "final_report_present": False,
            "schema_validation_passed": False,
            "max_continuations_exceeded": False,
            "max_failed_attempts_exceeded": False,
        },
        "unresolved_seams": [],
        "decision_inputs": {
            "total_queue_items": 0,
            "runnable_count": 0,
            "blocked_count": 0,
            "active_count": 0,
            "completed_count": 0,
            "blocker_summary": {},
            "selected_task_id": "",
            "selected_task_status": "",
            "selected_task_priority": 0,
        },
        "recommended_action": "no_action",
        "recommendation_rationale_codes": ["empty_queue"],
        "redaction_status": "content_light",
        "compiler_fallback_status": "present",
    }
    base.update(overrides)
    if "decision_inputs" in overrides:
        base["decision_inputs"].update(overrides["decision_inputs"])
    return base


class TestCapsuleSchemaContract:
    def test_valid_capsule_is_accepted(self, tmp_path: Path) -> None:
        _init_git(tmp_path)
        _write_capsule(tmp_path, _minimal_capsule())
        _write_queue(tmp_path, [])
        result = _run_steward(tmp_path, dry_run=True)
        assert result.returncode == 0
        run = _read_last_run(tmp_path)
        assert run["compiler_fallback_status"] == "present"

    def test_capsule_missing_schema_version_is_rejected(self, tmp_path: Path) -> None:
        _init_git(tmp_path)
        capsule = _minimal_capsule()
        capsule["schema_version"] = "wrong.version"
        _write_capsule(tmp_path, capsule)
        _write_queue(tmp_path, [])
        result = _run_steward(tmp_path, dry_run=True)
        assert result.returncode == 0
        run = _read_last_run(tmp_path)
        assert run["compiler_fallback_status"].startswith("invalid")

    def test_capsule_missing_required_keys_is_rejected(self, tmp_path: Path) -> None:
        _init_git(tmp_path)
        capsule = _minimal_capsule()
        del capsule["decision_inputs"]
        _write_capsule(tmp_path, capsule)
        _write_queue(tmp_path, [])
        result = _run_steward(tmp_path, dry_run=True)
        assert result.returncode == 0
        run = _read_last_run(tmp_path)
        assert run["compiler_fallback_status"].startswith("invalid")

    def test_capsule_not_redacted_is_rejected(self, tmp_path: Path) -> None:
        _init_git(tmp_path)
        capsule = _minimal_capsule()
        capsule["redaction_status"] = "not_redacted"
        _write_capsule(tmp_path, capsule)
        _write_queue(tmp_path, [])
        result = _run_steward(tmp_path, dry_run=True)
        assert result.returncode == 0
        run = _read_last_run(tmp_path)
        assert run["compiler_fallback_status"].startswith("invalid")


class TestCapsuleConsumption:
    def test_steward_writes_capsule_after_run(self, tmp_path: Path) -> None:
        _init_git(tmp_path)
        item = _make_queue_item("t1")
        _write_queue(tmp_path, [item])
        _write_prompt(tmp_path, ".rig/roadmap/prompts/t1.txt")
        _run_steward(tmp_path, dry_run=True)
        capsule = _read_capsule(tmp_path)
        assert (
            capsule["schema_version"] == "rig.relay.opencode_steward_context_capsule.v1"
        )
        assert "capsule_id" in capsule
        assert capsule["redaction_status"] == "content_light"
        di = capsule["decision_inputs"]
        assert di["total_queue_items"] == 1
        assert di["selected_task_id"] == "t1"

    def test_capsule_includes_correct_recommended_action(self, tmp_path: Path) -> None:
        _init_git(tmp_path)
        item = _make_queue_item("t1", status="queued")
        _write_queue(tmp_path, [item])
        _write_prompt(tmp_path, ".rig/roadmap/prompts/t1.txt")
        _run_steward(tmp_path, dry_run=True)
        capsule = _read_capsule(tmp_path)
        assert capsule["recommended_action"] in (
            "continue_lane",
            "advance_to_next_lane",
        )

    def test_steward_reads_valid_capsule_and_records_present(
        self, tmp_path: Path
    ) -> None:
        _init_git(tmp_path)
        _write_capsule(
            tmp_path,
            _minimal_capsule(
                recommended_action="no_action",
                recommendation_rationale_codes=["empty_queue"],
            ),
        )
        _write_queue(tmp_path, [])
        _run_steward(tmp_path, dry_run=True)
        run = _read_last_run(tmp_path)
        assert run["steward_state"] == "no_action"
        assert run["compiler_fallback_status"] == "present"


class TestCapsuleFallback:
    def test_no_capsule_produces_missing_fallback(self, tmp_path: Path) -> None:
        _init_git(tmp_path)
        _write_queue(tmp_path, [])
        _run_steward(tmp_path, dry_run=True)
        run = _read_last_run(tmp_path)
        assert run["compiler_fallback_status"] == "missing"

    def test_corrupt_capsule_json_produces_invalid_fallback(
        self, tmp_path: Path
    ) -> None:
        _init_git(tmp_path)
        capsule_dir = tmp_path / ".build" / "rig-relay" / "derived"
        capsule_dir.mkdir(parents=True, exist_ok=True)
        (capsule_dir / "opencode_steward_context_capsule_v1.json").write_text(
            "not json", encoding="utf-8"
        )
        _write_queue(tmp_path, [])
        _run_steward(tmp_path, dry_run=True)
        run = _read_last_run(tmp_path)
        assert run["compiler_fallback_status"].startswith("invalid")

    def test_fallback_does_not_prevent_steward_decision(self, tmp_path: Path) -> None:
        _init_git(tmp_path)
        item = _make_queue_item("t1")
        _write_queue(tmp_path, [item])
        _write_prompt(tmp_path, ".rig/roadmap/prompts/t1.txt")
        _run_steward(tmp_path, dry_run=True)
        run = _read_last_run(tmp_path)
        assert run["steward_state"] in ("continue_lane", "advance_to_next_lane")
        assert run["compiler_fallback_status"] == "missing"
        assert run.get("selected_task") is not None

    def test_stale_capsule_produces_stale_fallback(self, tmp_path: Path) -> None:
        from datetime import UTC, datetime, timedelta

        _init_git(tmp_path)
        stale_time = (datetime.now(UTC) - timedelta(hours=2)).isoformat()
        _write_capsule(
            tmp_path,
            _minimal_capsule(
                generated_at=stale_time,
                recommended_action="no_action",
                recommendation_rationale_codes=["empty_queue"],
            ),
        )
        _write_queue(tmp_path, [])
        _run_steward(tmp_path, dry_run=True)
        run = _read_last_run(tmp_path)
        assert run["compiler_fallback_status"] == "stale"


class TestCapsuleDispatchAuthority:
    def test_compiler_recommendation_does_not_bypass_steward_safety(
        self, tmp_path: Path
    ) -> None:
        _init_git(tmp_path)
        _write_capsule(
            tmp_path,
            _minimal_capsule(
                recommended_action="continue_lane",
                recommendation_rationale_codes=["safe"],
                decision_inputs={
                    "total_queue_items": 1,
                    "runnable_count": 1,
                    "selected_task_id": "t1",
                },
            ),
        )
        item = _make_queue_item("t1", allowed_files=["src/touched.py"])
        _write_queue(tmp_path, [item])
        _write_prompt(tmp_path, ".rig/roadmap/prompts/t1.txt")
        _dirty_file(tmp_path, "src/touched.py")
        result = _run_steward(tmp_path)
        assert result.returncode == 0
        run = _read_last_run(tmp_path)
        assert run["compiler_fallback_status"] == "present"
        assert run["steward_state"] in ("blocked", "audit_unblock_plan")

    def test_blocked_evidence_in_capsule_routes_to_audit(self, tmp_path: Path) -> None:
        _init_git(tmp_path)
        _write_capsule(
            tmp_path,
            _minimal_capsule(
                recommended_action="blocked",
                recommendation_rationale_codes=["blocker:failed_gate"],
                decision_inputs={
                    "total_queue_items": 2,
                    "runnable_count": 0,
                    "blocked_count": 2,
                },
            ),
        )
        items = [
            _make_queue_item("t1", required_gates_before=["nonexistent.json"]),
            _make_queue_item("t2", forbidden_files=["secrets.env"]),
        ]
        _write_queue(tmp_path, items)
        _write_prompt(tmp_path, ".rig/roadmap/prompts/t1.txt")
        _write_prompt(tmp_path, ".rig/roadmap/prompts/t2.txt")
        _dirty_file(tmp_path, "secrets.env")
        _run_steward(tmp_path)
        run = _read_last_run(tmp_path)
        assert run["compiler_fallback_status"] == "present"
        assert run["steward_state"] == "audit_unblock_plan"

    def test_capsule_action_mismatch_emits_event(self, tmp_path: Path) -> None:
        _init_git(tmp_path)
        _write_capsule(
            tmp_path,
            _minimal_capsule(
                recommended_action="finalize_lane",
                recommendation_rationale_codes=["all_criteria_met"],
                decision_inputs={
                    "total_queue_items": 1,
                    "runnable_count": 1,
                    "selected_task_id": "t1",
                },
            ),
        )
        item = _make_queue_item("t1", status="queued")
        _write_queue(tmp_path, [item])
        _write_prompt(tmp_path, ".rig/roadmap/prompts/t1.txt")
        _run_steward(tmp_path, dry_run=True)
        run = _read_last_run(tmp_path)
        assert run["compiler_fallback_status"] == "present"
        assert run["steward_state"] == "advance_to_next_lane"
        events = _read_events(tmp_path)
        mismatch_events = [
            e for e in events if e.get("event") == "capsule_action_mismatch"
        ]
        assert len(mismatch_events) >= 1
        assert mismatch_events[0]["capsule_action"] == "finalize_lane"
        assert mismatch_events[0]["steward_action"] == "advance_to_next_lane"


class TestCapsuleRedaction:
    def test_capsule_never_contains_raw_prompt_text(self, tmp_path: Path) -> None:
        _init_git(tmp_path)
        item = _make_queue_item("t1")
        _write_queue(tmp_path, [item])
        _write_prompt(tmp_path, ".rig/roadmap/prompts/t1.txt", "CLASSIFIED_PROMPT_BODY")
        _run_steward(tmp_path, dry_run=True)
        capsule = _read_capsule(tmp_path)
        raw = json.dumps(capsule)
        assert "CLASSIFIED_PROMPT_BODY" not in raw

    def test_capsule_stores_prompt_sha256_not_body(self, tmp_path: Path) -> None:
        _init_git(tmp_path)
        item = _make_queue_item("t1")
        _write_queue(tmp_path, [item])
        _write_prompt(tmp_path, ".rig/roadmap/prompts/t1.txt", "prompt text")
        _run_steward(tmp_path, dry_run=True)
        capsule = _read_capsule(tmp_path)
        di = capsule.get("decision_inputs", {})
        psha = di.get("selected_task_prompt_sha256", "")
        assert len(psha) == 64
        assert "prompt text" not in psha

    def test_capsule_never_contains_reasoning_chain_of_thought(
        self, tmp_path: Path
    ) -> None:
        _init_git(tmp_path)
        item = _make_queue_item("t1")
        _write_queue(tmp_path, [item])
        _write_prompt(tmp_path, ".rig/roadmap/prompts/t1.txt", "do something")
        _run_steward(tmp_path, dry_run=True)
        capsule = _read_capsule(tmp_path)
        raw = json.dumps(capsule)
        assert "reasoning" not in raw.lower() or "reasoning_redacted" in raw
        assert "chain_of_thought" not in raw

    def test_steward_capsule_self_written_is_content_light(
        self, tmp_path: Path
    ) -> None:
        _init_git(tmp_path)
        item = _make_queue_item("t1")
        _write_queue(tmp_path, [item])
        _write_prompt(tmp_path, ".rig/roadmap/prompts/t1.txt", "do task")
        _run_steward(tmp_path, dry_run=True)
        capsule = _read_capsule(tmp_path)
        assert capsule["redaction_status"] == "content_light"
        assert "prompt_body" not in str(capsule.get("decision_inputs", {}))

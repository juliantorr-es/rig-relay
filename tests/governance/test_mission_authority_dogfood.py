from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from pathlib import Path
import subprocess
import tempfile
from typing import Any


async def _minimal_invoke(args_dict: dict[str, Any]) -> AsyncGenerator[Any, None]:
    """Async generator producing a single dummy result model for invoke_tool."""

    class _DummyResult:
        def model_dump(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
            return {"status": "simulated_ok"}

    yield _DummyResult()


async def _run_dogfood() -> int:
    from rig_relay.coordination.models import CoordinationTaskClaim
    from rig_relay.coordination.store import CoordinationStore
    from rig_relay.core.tool_runtime import ToolRuntime
    from rig_relay.core.tool_runtime_models import (
        RefusalCode,
        ToolRuntimeExecutionMode,
        ToolRuntimeRequest,
        ToolRuntimeStatus,
    )
    from rig_relay.core.tool_runtime_policy import ToolRuntimePolicy
    from rig_relay.governance.mission_authority import derive_authority_from_claim

    results: list[tuple[str, bool]] = []

    with tempfile.TemporaryDirectory() as base:
        base_path = Path(base)
        repo = base_path / "repo"
        repo.mkdir()
        coord_dir = base_path / "coordination"
        coord_dir.mkdir()

        subprocess.run(
            ["git", "init", "-b", "main"], cwd=repo, check=True, capture_output=True
        )
        subprocess.run(
            ["git", "config", "user.email", "dogfood@test.local"], cwd=repo, check=True
        )
        subprocess.run(
            ["git", "config", "user.name", "Dogfood Test"], cwd=repo, check=True
        )
        for d in ["src", "tests", "docs", "other"]:
            (repo / d).mkdir(exist_ok=True)
        (repo / "src" / "app.py").write_text("# app")
        (repo / "tests" / "test_app.py").write_text("# test")
        (repo / "docs" / "readme.md").write_text("# docs")
        subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "initial"],
            cwd=repo,
            check=True,
            capture_output=True,
        )

        # ── 1. Create coordination claim ──────────────────────────────
        store = CoordinationStore(root=coord_dir)
        claim_result = store.claim_task(
            session_id="dogfood-sess",
            task_id="dogfood-task",
            claim_kind="implementation",
            ttl_seconds=3600,
            scope={"allowed_paths": [str(repo / "src"), str(repo / "tests")]},
        )
        assert claim_result is not None
        claim = claim_result.claim
        assert claim is not None
        assert claim.status == "active"
        results.append(("claim created (active)", True))

        # ── 2. Derive authority ──────────────────────────────────────
        authority = derive_authority_from_claim(
            claim,
            worktree_root=str(repo),
            mission_id="dogfood-mission",
            admitted_checkpoint=True,
        )
        assert authority.is_active()
        results.append(("authority derived (active)", True))

        # ── 3. Install authority on ToolRuntime ──────────────────────
        #
        # We need to inject callbacks that let all governance gates pass
        # so we can observe authority decisions.  Using a ToolRuntimePolicy
        # with a no-op patch_gate and a successful permission callback
        # (or bypass_permissions).  For invoke_tool we supply a minimal
        # async generator that yields a dummy result so the invocation
        # step doesn't crash.
        policy = ToolRuntimePolicy(patch_gate_check=lambda _tc, _ti: None)
        runtime = ToolRuntime(policy_object=policy, invoke_tool=_minimal_invoke)
        runtime._mission_authority = authority

        # ── 4. Read outside write scope (docs/ not in scope paths) ───
        read_req = ToolRuntimeRequest(
            tool_name="read_file",
            tool_call_id="dogfood-read-docs",
            tool_args={"file_path": str(repo / "docs" / "readme.md")},
            execution_mode=ToolRuntimeExecutionMode.READ_ONLY,
            session_id="dogfood-sess",
            bypass_permissions=True,
            mutation_class="read_only",
        )
        read_result = await runtime.execute_one(read_req)
        read_passed = read_result.authority_decision == "allowed_in_scope"
        results.append((
            f"read outside write scope (docs/) → authority={read_result.authority_decision}",
            read_passed,
        ))

        # ── 5. Write inside scope (src/) — auto-allowed ──────────────
        write_in_req = ToolRuntimeRequest(
            tool_name="write_file",
            tool_call_id="dogfood-write-src",
            tool_args={"file_path": str(repo / "src" / "new.py"), "content": "# new"},
            execution_mode=ToolRuntimeExecutionMode.MUTATION_PROPOSAL,
            session_id="dogfood-sess",
            bypass_permissions=True,
            mutation_class="writes_workspace",
        )
        write_in_result = await runtime.execute_one(write_in_req)
        in_scope_passed = write_in_result.authority_decision == "allowed_in_scope"
        results.append((
            f"write inside scope (src/) → authority={write_in_result.authority_decision}, status={write_in_result.status.value}",
            in_scope_passed,
        ))

        # ── 6. Write outside scope (other/) — refused with SCOPE_EXPANSION_REQUIRED ──
        write_out_req = ToolRuntimeRequest(
            tool_name="write_file",
            tool_call_id="dogfood-write-other",
            tool_args={
                "file_path": str(repo / "other" / "secret.py"),
                "content": "# secret",
            },
            execution_mode=ToolRuntimeExecutionMode.MUTATION_PROPOSAL,
            session_id="dogfood-sess",
            bypass_permissions=True,
            mutation_class="writes_workspace",
        )
        write_out_result = await runtime.execute_one(write_out_req)
        out_of_scope_refused = (
            write_out_result.status == ToolRuntimeStatus.REFUSED
            and write_out_result.refusal is not None
            and write_out_result.refusal.refusal_code
            == RefusalCode.SCOPE_EXPANSION_REQUIRED
        )
        results.append((
            f"write outside scope (other/) → status={write_out_result.status.value}, "
            f"refusal={write_out_result.refusal.refusal_code if write_out_result.refusal else None}, "
            f"authority={write_out_result.authority_decision}",
            out_of_scope_refused,
        ))

        # ── 7. Release claim and verify authority becomes inactive ───
        store.release_task(session_id="dogfood-sess", task_id="dogfood-task")

        # Re-read the claim file to derive authority from the released state
        released_claim_path = coord_dir / "tasks" / "dogfood-task.json"
        released_claim = CoordinationTaskClaim.model_validate_json(
            released_claim_path.read_text(encoding="utf-8")
        )
        assert released_claim.status == "released"
        results.append(("claim status is 'released' after release_task", True))

        released_authority = derive_authority_from_claim(
            released_claim,
            worktree_root=str(repo),
            mission_id="dogfood-mission",
            admitted_checkpoint=True,
        )
        assert not released_authority.is_active()
        results.append(("authority inactive after release", True))

        # Install the now-inactive authority and verify writes are refused
        runtime._mission_authority = released_authority
        write_post_req = ToolRuntimeRequest(
            tool_name="write_file",
            tool_call_id="dogfood-write-post-release",
            tool_args={"file_path": str(repo / "src" / "new2.py"), "content": "# new2"},
            execution_mode=ToolRuntimeExecutionMode.MUTATION_PROPOSAL,
            session_id="dogfood-sess",
            bypass_permissions=True,
            mutation_class="writes_workspace",
        )
        write_post_result = await runtime.execute_one(write_post_req)
        post_release_refused = write_post_result.status == ToolRuntimeStatus.REFUSED
        results.append((
            f"write inside scope after release → status={write_post_result.status.value}, "
            f"refusal={write_post_result.refusal.refusal_code if write_post_result.refusal else None}",
            post_release_refused,
        ))

        # Additional: verify the released claim is not in the active projection
        proj = store.read_state_projection()
        not_active = "dogfood-task" not in proj.active_task_claims
        results.append((
            "released claim absent from active_task_claims projection",
            not_active,
        ))

    # ── Print summary ─────────────────────────────────────────────────
    print("\n=== Dogfood Results ===")
    for label, passed in results:
        status = "PASS" if passed else "FAIL"
        print(f"[{status}] {label}")

    total = len(results)
    passed_count = sum(1 for _, p in results if p)
    print(f"\n{passed_count}/{total} passed\n")

    return 0 if passed_count == total else 1


if __name__ == "__main__":
    exit_code = asyncio.run(_run_dogfood())
    raise SystemExit(exit_code)

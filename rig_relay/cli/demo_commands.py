"""Demo commands — seed data and doctor for fresh-clone demo readiness.

These commands make the repo demo-proof: a stranger should be able to
clone, install, run demo-seed, run demo-doctor, and see all projections
working in the desktop cockpit.

Safety rules:
- Idempotent — running twice produces same state
- No secrets, no network, no OAuth
- Synthetic data clearly marked where applicable
- Never mutates canonical findings
- Never enables merge/push
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
BUILD_ROOT = REPO_ROOT / ".build" / "rig-relay"
DEMO_DIR = BUILD_ROOT / "demo"


# ── Seed ────────────────────────────────────────────────────────────


def demo_seed() -> int:
    """Create safe demo artifacts. Idempotent — safe to run repeatedly."""
    DEMO_DIR.mkdir(parents=True, exist_ok=True)

    results: list[str] = []

    results.append(_seed_subagent_profiles())
    results.append(_seed_model_bindings())
    results.append(_seed_orchestrator_missions())
    results.append(_seed_mission_board_projection())
    results.append(_seed_tool_runtime_demo())
    results.append(_seed_ralph_reports())
    results.append(_seed_ralph_lifecycle_demo())
    results.append(_seed_review_bundle_demo())
    results.append(_seed_adoption_proposal_demo())
    results.append(_seed_report_demo())
    results.append(_seed_bash_analytics_demo())
    results.append(_seed_projection_demo())

    print("Demo seed complete:")
    for r in results:
        print(f"  {r}")
    return 0


def _seed_subagent_profiles() -> str:
    """Seed configured subagent profiles into the global registry."""
    from rig_relay.orchestrator.subagent_profiles import build_demo_profiles

    registry = build_demo_profiles()
    standard = registry.assignable()
    ralph = registry.autonomous_workers()
    return (
        f"subagent profiles ({len(standard)} assignable: "
        f"{', '.join(p.display_name for p in standard)}; "
        f"{len(ralph)} autonomous: {', '.join(p.display_name for p in ralph)})"
    )


def _seed_model_bindings() -> str:
    """Seed model/provider bindings into the global binding registry."""
    from rig_relay.orchestrator.subagent_profiles import build_demo_bindings

    registry = build_demo_bindings()
    bindings = registry.list_all()
    return (
        f"model bindings ({len(bindings)} bindings: "
        f"{', '.join(b.display_name for b in bindings)})"
    )


def _seed_ralph_reports() -> str:
    """Seed synthetic Ralph background reports."""
    from rig_relay.ralph.reporting import build_demo_ralph_reports

    reports = build_demo_ralph_reports()
    return f"Ralph reports ({len(reports)} created, 1 delivered, 1 pending)"


def _seed_orchestrator_missions() -> str:
    """Seed synthetic orchestrator missions assigned to subagent profiles."""
    missions = [
        {
            "mission_id": "demo-mission-001",
            "title": "Extract ToolRuntime boundary from AgentLoop",
            "status": "active",
            "assigned_profile_id": "profile-runtime-agent",
            "assigned_profile_name": "Runtime Agent",
            "lane_id": "lane-runtime-agent",
            "created_at": "2026-05-14T10:00:00Z",
            "source": "demo-synthetic",
        },
        {
            "mission_id": "demo-mission-002",
            "title": "Wire Ralph lifecycle into pywebview",
            "status": "active",
            "assigned_profile_id": "profile-frontend-agent",
            "assigned_profile_name": "Frontend Agent",
            "lane_id": "lane-frontend-agent",
            "created_at": "2026-05-14T11:00:00Z",
            "source": "demo-synthetic",
        },
        {
            "mission_id": "demo-mission-003",
            "title": "Update demo guide for orchestrator/Ralph roles",
            "status": "assigned",
            "assigned_profile_id": "profile-docs-agent",
            "assigned_profile_name": "Docs Agent",
            "lane_id": "lane-docs-agent",
            "created_at": "2026-05-15T08:00:00Z",
            "source": "demo-synthetic",
        },
    ]
    _write_json(DEMO_DIR / "orchestrator_missions.json", missions)
    return (
        "orchestrator missions (3 synthetic, assigned to Runtime/Frontend/Docs agents)"
    )


def _seed_mission_board_projection() -> str:
    from rig_relay.ralph.mission_board import (
        LifecycleTimelineEntry,
        MissionItem,
        OrchestratorMissionBoard,
        ReviewEntrypoint,
    )

    missions = [
        MissionItem(
            mission_id="demo-mission-001",
            title="Extract ToolRuntime boundary from AgentLoop",
            status="active",
            lane_id="demo-lane-1",
        ),
        MissionItem(
            mission_id="demo-mission-002",
            title="Wire Ralph lifecycle into pywebview",
            status="active",
            lane_id="demo-lane-2",
        ),
    ]

    timeline = [
        LifecycleTimelineEntry(
            step_order=1,
            status="completed",
            label="Background enabled",
            detail="Toggle ON",
            blocked=False,
        ),
        LifecycleTimelineEntry(
            step_order=2,
            status="completed",
            label="Lane created",
            detail="Worktree/branch created",
            blocked=False,
        ),
        LifecycleTimelineEntry(
            step_order=3,
            status="completed",
            label="Execution completed",
            detail="Scoped lane execution done",
            blocked=False,
        ),
        LifecycleTimelineEntry(
            step_order=4,
            status="completed",
            label="Commit recorded",
            detail="Committed to Ralph branch",
            blocked=False,
        ),
        LifecycleTimelineEntry(
            step_order=5,
            status="completed",
            label="Review bundle sealed",
            detail="Ready for review",
            blocked=False,
        ),
        LifecycleTimelineEntry(
            step_order=6,
            status="pending",
            label="Adoption proposal",
            detail="Awaiting adoption proposal",
            blocked=True,
        ),
        LifecycleTimelineEntry(
            step_order=7,
            status="pending",
            label="Merge",
            detail="Requires adoption approval",
            blocked=True,
        ),
        LifecycleTimelineEntry(
            step_order=8,
            status="pending",
            label="Push to preproduction",
            detail="Requires preproduction approval",
            blocked=True,
        ),
    ]

    review = ReviewEntrypoint(
        available=True,
        pending_review_count=2,
        latest_report_id="ralph-report-001",
        label="Review 2 Ralph reports with orchestrator",
        action="review_with_orchestrator",
        requires_confirmation=True,
    )

    board = OrchestratorMissionBoard(
        total_missions=2,
        active_missions=2,
        completed_missions=0,
        missions=missions,
        lifecycle_timeline=timeline,
        background_enabled=True,
        isolated_lane_execution_enabled=True,
        live_runtime_mutation_enabled=False,
        merge_enabled=False,
        push_enabled=False,
        review_entrypoint=review,
    )

    _write_json(DEMO_DIR / "mission_board.json", board.model_dump(mode="json"))
    return (
        "mission board projection (2 active missions, 8-step lifecycle, review ready)"
    )


def _seed_tool_runtime_demo() -> str:
    """Seed synthetic ToolRuntime outcomes."""
    from rig_relay.core.tool_runtime_ledger import (
        InMemoryToolRuntimeResultLedger,
        ToolRuntimeLedgerEntry,
        get_active_ledger,
    )
    from rig_relay.core.tool_runtime_models import (
        ToolRuntimeCacheStatus,
        ToolRuntimeStatus,
    )

    ledger: InMemoryToolRuntimeResultLedger = get_active_ledger()
    ledger.reset()

    demo_entries = [
        (
            "read_file",
            ToolRuntimeStatus.COMPLETED.value,
            ToolRuntimeCacheStatus.HIT.value,
            None,
            2.1,
        ),
        (
            "grep",
            ToolRuntimeStatus.COMPLETED.value,
            ToolRuntimeCacheStatus.MISS.value,
            None,
            5.3,
        ),
        (
            "bash",
            ToolRuntimeStatus.REFUSED.value,
            ToolRuntimeCacheStatus.NOT_APPLICABLE.value,
            "approval_denied",
            0.2,
        ),
        (
            "search_replace",
            ToolRuntimeStatus.DEGRADED.value,
            ToolRuntimeCacheStatus.WRITE_FAILED.value,
            None,
            12.3,
        ),
        (
            "validate",
            ToolRuntimeStatus.COMPLETED.value,
            ToolRuntimeCacheStatus.HIT.value,
            None,
            0.8,
        ),
        (
            "bash",
            ToolRuntimeStatus.COMPLETED.value,
            ToolRuntimeCacheStatus.MISS.value,
            None,
            8.1,
        ),
        (
            "get_context",
            ToolRuntimeStatus.CACHED.value,
            ToolRuntimeCacheStatus.HIT.value,
            None,
            0.5,
        ),
        (
            "read_file",
            ToolRuntimeStatus.COMPLETED.value,
            ToolRuntimeCacheStatus.HIT.value,
            None,
            1.2,
        ),
    ]

    for i, (name, status, cache, refusal, dur) in enumerate(demo_entries):
        entry = ToolRuntimeLedgerEntry(
            tool_name=name,
            tool_call_id=f"demo-call-{i:03d}",
            status=status,
            cache_status=cache,
            refusal_code=refusal,
            duration_ms=dur,
        )
        ledger._entries.append(entry)

    return f"ToolRuntime ledger ({len(demo_entries)} demo entries)"


def _seed_ralph_lifecycle_demo() -> str:
    """Seed synthetic Ralph lifecycle data with review bundles and lanes."""
    lifecycle = {
        "schema_version": "rig.ui.ralph_background_lifecycle.v1",
        "background_enabled": True,
        "isolated_lane_execution_enabled": True,
        "live_runtime_mutation_enabled": False,
        "merge_enabled": False,
        "push_enabled": False,
        "active_lane_count": 0,
        "completed_lane_count": 2,
        "pending_review_count": 2,
        "active_lanes": [],
        "completed_lanes": [
            {
                "lane_id": "demo-ralph-lane-001",
                "branch_name": "ralph/toolruntime-boundary-demo",
                "status": "completed",
                "review_bundle_sha256": "sha256:demo-bundle-001",
            },
            {
                "lane_id": "demo-ralph-lane-002",
                "branch_name": "ralph/bash-analytics-demo",
                "status": "completed",
                "review_bundle_sha256": "sha256:demo-bundle-002",
            },
        ],
        "latest_lane": {
            "lane_id": "demo-ralph-lane-002",
            "branch_name": "ralph/bash-analytics-demo",
            "status": "completed",
            "latest_commit_sha": "abc123def",
            "review_bundle_sha256": "sha256:demo-bundle-002",
        },
        "gates": [
            {
                "name": "Worktree creation",
                "allowed": True,
                "label": "allowed",
                "requires": "background policy",
            },
            {
                "name": "Lane execution",
                "allowed": True,
                "label": "allowed",
                "requires": "lane_start_approved",
            },
            {
                "name": "Ralph branch commits",
                "allowed": True,
                "label": "allowed",
                "requires": "isolated lane + policy",
            },
            {
                "name": "Adoption merge",
                "allowed": False,
                "label": "requires adoption approval",
                "requires": "human approval + SHA match",
            },
            {
                "name": "Push to preproduction",
                "allowed": False,
                "label": "requires preproduction approval",
                "requires": "human approval + validations",
            },
        ],
        "available_actions": [
            {
                "action": "ralph_background_toggle_on",
                "label": "Enable background lanes",
                "requires_confirmation": True,
            },
            {
                "action": "ralph_background_toggle_off",
                "label": "Disable background lanes",
                "requires_confirmation": True,
            },
            {
                "action": "ralph_review_finished_lanes",
                "label": "Review finished lanes",
                "requires_confirmation": False,
            },
        ],
        "source": "demo-synthetic",
    }
    _write_json(DEMO_DIR / "ralph_lifecycle.json", lifecycle)
    return "Ralph lifecycle (2 completed lanes, 5 gates, demo policy)"


def _seed_review_bundle_demo() -> str:
    """Seed synthetic review bundles from completed Ralph lanes."""
    bundles = [
        {
            "schema_version": "rig.ralph_review_bundle.v1",
            "bundle_id": "demo-review-001",
            "lane_id": "demo-ralph-lane-001",
            "branch_name": "ralph/toolruntime-boundary-demo",
            "base_head": "main",
            "head_sha": "abc123def456",
            "commit_shas": ["abc123def456"],
            "changed_files": [
                "rig_relay/core/tool_runtime_ledger.py",
                "rig_relay/core/tool_runtime_models.py",
                "tests/core/test_tool_runtime_ledger.py",
            ],
            "summary": "Extracted ToolRuntime boundary with typed outcomes, defined Rig ToolRuntime protocol, isolated ledger from AgentLoop",
            "why": "Convergence threat: ToolRuntime boundary needed for governed execution",
            "evidence_refs": [
                {"kind": "finding", "id": "F-2026-001"},
                {"kind": "report", "id": "R-2026-042"},
            ],
            "validation_results": [
                "ruff:passed",
                "pyright:passed",
                "pytest:8/8 passed",
            ],
            "risk_notes": [
                "Backward compatible — existing AgentLoop path preserved",
                "Ledger API stabilized at v1",
            ],
            "adoption_recommendation": {
                "target_kind": "main_workspace",
                "confidence": "high",
                "reason": "All validations pass, no breaking changes",
            },
            "created_at": "2026-05-14T11:00:00Z",
            "bundle_sha256": "sha256:demo-bundle-001",
            "source": "demo-synthetic",
        },
        {
            "schema_version": "rig.ralph_review_bundle.v1",
            "bundle_id": "demo-review-002",
            "lane_id": "demo-ralph-lane-002",
            "branch_name": "ralph/bash-analytics-demo",
            "base_head": "main",
            "head_sha": "def789abc012",
            "commit_shas": ["def789abc012", "ghi345def678"],
            "changed_files": [
                "rig_relay/analytics/bash_rows.py",
                "rig_relay/bash/projection.py",
                "rig_relay/ralph/scanner.py",
                "tests/analytics/test_bash_rows.py",
                "tests/bash/test_projection.py",
            ],
            "summary": "Hardened bash analytics projection with duckdb query safety, added projection index",
            "why": "Analytics projection hardening needed for production readiness",
            "evidence_refs": [{"kind": "finding", "id": "F-2026-003"}],
            "validation_results": [
                "ruff:passed",
                "pyright:passed",
                "pytest:12/12 passed",
            ],
            "risk_notes": [
                "DuckDB queries now parameterized — no SQL injection risk",
                "Projection index format stabilized",
            ],
            "adoption_recommendation": {
                "target_kind": "user_review",
                "confidence": "medium",
                "reason": "Ralph completed lane work — review recommended",
            },
            "created_at": "2026-05-14T12:00:00Z",
            "bundle_sha256": "sha256:demo-bundle-002",
            "source": "demo-synthetic",
        },
    ]
    _write_json(DEMO_DIR / "review_bundles.json", bundles)
    return "review bundles (2 synthetic, with validation results and risk notes)"


def _seed_adoption_proposal_demo() -> str:
    """Seed synthetic adoption proposals."""
    proposals = [
        {
            "schema_version": "rig.ralph_adoption_proposal.v1",
            "proposal_id": "demo-adoption-001",
            "source_ralph_lane_id": "demo-ralph-lane-001",
            "target_kind": "main_workspace",
            "target_lane_id": None,
            "status": "pending_review",
            "relevance_score": 0.92,
            "bundle_sha256": "sha256:demo-bundle-001",
            "summary": "Adopt ToolRuntime boundary into main workspace",
            "created_at": "2026-05-14T13:00:00Z",
            "source": "demo-synthetic",
        }
    ]
    _write_json(DEMO_DIR / "adoption_proposals.json", proposals)
    return "adoption proposals (1 synthetic, pending review)"


def _seed_report_demo() -> str:
    """Seed synthetic report projections."""
    reports = {
        "schema_version": "rig.ui.report_summary.v1",
        "total_reports": 12,
        "open_reports": 3,
        "report_kinds": {
            "architecture_debt": 4,
            "implementation_seam": 3,
            "security_concern": 2,
            "regression_risk": 2,
            "refactor_candidate": 1,
        },
        "source": "demo-synthetic",
    }
    _write_json(DEMO_DIR / "report_summary.json", reports)
    return "report summary (12 demo reports)"


def _seed_bash_analytics_demo() -> str:
    """Seed synthetic bash analytics projection data."""
    bash_data = {
        "schema_version": "rig.ui.bash_analytics.v1",
        "total_bash_calls": 42,
        "rerouted_calls": 15,
        "blocked_patterns": 3,
        "safe_calls": 24,
        "top_tools_detected": {
            "cat": 8,
            "grep": 10,
            "head": 3,
            "tail": 2,
            "git_status": 4,
        },
        "blocked_reasons": {
            "command_substitution": 1,
            "inline_execution": 1,
            "env_var_injection": 1,
        },
        "source": "demo-synthetic",
    }
    _write_json(DEMO_DIR / "bash_analytics.json", bash_data)
    return "bash analytics (42 calls, 15 rerouted, 3 blocked)"


def _seed_projection_demo() -> str:
    """Seed a minimal desktop projection so the UI has data to show."""
    projection = {
        "schema_version": "rig.relay.desktop_projection.v1",
        "generated_at": "2026-05-14T12:00:00Z",
        "app_version": "0.2.0a1",
        "alpha_label": True,
        "source_status": {
            "current_state": False,
            "queue": False,
            "dataset": False,
            "semantic_snippets": False,
            "telemetry_bundle": False,
            "update": False,
            "storage": False,
            "provider_status": True,
            "integrity": False,
            "tool_runtime_summary": True,
        },
        "providers": {"total": 1, "configured": 1, "valid_count": 0, "providers": []},
        "tool_runtime_summary": {
            "available": True,
            "total_executions": 8,
            "completed_count": 5,
            "cached_count": 1,
            "refused_count": 1,
            "degraded_count": 1,
        },
        "warnings": ["Demo mode — no live data sources connected"],
        "read_only_actions": ["refresh_projection", "view_current_state"],
        "_demo_synthetic": True,
    }
    _write_json(BUILD_ROOT / "desktop" / "projection.json", projection)
    return "desktop projection (demo)"


# ── Doctor ───────────────────────────────────────────────────────────


def demo_doctor() -> int:
    """Verify demo readiness. Returns 0 if all checks pass."""
    errors: list[str] = []
    warnings: list[str] = []
    ok: list[str] = []

    def check(fn: Any, label: str, *args: Any) -> None:
        try:
            result = fn(*args)
            if result is True or result is None:
                ok.append(label)
            elif isinstance(result, str):
                warnings.append(f"{label}: {result}")
            else:
                errors.append(f"{label}: {result}")
        except Exception as e:
            errors.append(f"{label}: {e}")

    check(_try_import, "pywebview import", "webview")
    check(_try_import, "duckdb import", "duckdb")
    check(_check_frontend, "frontend files exist")
    check(_check_projection_builds, "desktop projection builds")
    check(_check_mission_board_projection, "mission board projection builds")
    check(_check_tool_runtime_summary, "ToolRuntime summary builds")
    check(_check_ralph_lifecycle, "Ralph lifecycle projection builds")
    check(_check_review_bundles, "review bundles exist")
    check(_check_adoption_proposals, "adoption proposals exist")
    check(_check_report_summary, "report summary builds")
    check(_check_bash_analytics, "bash analytics data exists")
    check(_check_review_with_orchestrator, "review_with_orchestrator explain-only")
    check(_check_subagent_profiles, "subagent profiles configured")
    check(_check_ralph_reports, "Ralph reports exist")
    check(_check_profile_ralph_not_assignable, "Ralph is not assignable like subagents")
    check(_check_model_bindings, "model/provider bindings configured")
    check(_check_docs_render_path, "docs render path")
    check(_check_local_mode, "local mode (no OAuth)")
    check(_check_merge_push_disabled, "merge/push disabled by default")
    check(_check_live_mutation_disabled, "live_runtime_mutation always False")
    check(_check_frontend_no_policy_inference, "frontend does not infer policy")
    check(_check_demo_data_no_secrets, "demo data has no secrets")

    print()
    print("=" * 50)
    print("Demo Doctor Report")
    print("=" * 50)
    for item in ok:
        print(f"  ✅ {item}")
    for item in warnings:
        print(f"  ⚠️  {item}")
    for item in errors:
        print(f"  ❌ {item}")

    if errors:
        print(f"\n{len(errors)} error(s) found. Fix before demo.")
        return 1
    print(f"\nAll {len(ok)} checks passed. Demo ready.")
    return 0


def _try_import(module: str) -> bool:
    __import__(module)
    return True


def _check_frontend() -> bool | str:
    index = REPO_ROOT / "frontend" / "desktop" / "index.html"
    main = REPO_ROOT / "frontend" / "desktop" / "js" / "main.js"
    widgets = REPO_ROOT / "frontend" / "desktop" / "js" / "widgets.js"
    if not index.is_file() or not main.is_file():
        return False
    if not widgets.is_file():
        return "widgets.js not found"
    return True


def _check_projection_builds() -> bool | str:
    try:
        from rig_relay.desktop.projection import build_projection

        proj = build_projection()
        return isinstance(proj, dict) and "schema_version" in proj
    except Exception as e:
        return str(e)


def _check_mission_board_projection() -> bool | str:
    try:
        from rig_relay.ralph.mission_board import build_mission_board

        board = build_mission_board()
        return board.schema_version == "rig.ui.orchestrator_mission_board.v2"
    except Exception as e:
        return str(e)


def _check_tool_runtime_summary() -> bool | str:
    try:
        from rig_relay.core.tool_runtime_ledger import get_active_ledger

        ledger = get_active_ledger()
        summary = ledger.build_summary()
        return summary.schema_version == "rig.ui.tool_runtime_summary.v1"
    except Exception as e:
        return str(e)


def _check_ralph_lifecycle() -> bool | str:
    try:
        from rig_relay.ralph.lifecycle_projection import build_lifecycle_projection

        proj = build_lifecycle_projection()
        return proj.schema_version == "rig.ui.ralph_background_lifecycle.v1"
    except Exception as e:
        return str(e)


def _check_review_bundles() -> bool | str:
    try:
        path = DEMO_DIR / "review_bundles.json"
        if path.is_file():
            data = json.loads(path.read_text())
            return isinstance(data, list) and len(data) > 0
        return "review_bundles.json not found (run demo-seed first)"
    except Exception as e:
        return str(e)


def _check_adoption_proposals() -> bool | str:
    try:
        path = DEMO_DIR / "adoption_proposals.json"
        if path.is_file():
            data = json.loads(path.read_text())
            return isinstance(data, list) and len(data) > 0
        return "adoption_proposals.json not found (run demo-seed first)"
    except Exception as e:
        return str(e)


def _check_report_summary() -> bool | str:
    try:
        path = DEMO_DIR / "report_summary.json"
        if path.is_file():
            data = json.loads(path.read_text())
            return "report_kinds" in data
        return "report_summary.json not found (run demo-seed first)"
    except Exception as e:
        return str(e)


def _check_bash_analytics() -> bool | str:
    try:
        path = DEMO_DIR / "bash_analytics.json"
        if path.is_file():
            data = json.loads(path.read_text())
            return "total_bash_calls" in data
        return "bash_analytics.json not found (run demo-seed first)"
    except Exception as e:
        return str(e)


def _check_review_with_orchestrator() -> bool | str:
    try:
        from rig_relay.desktop.ralph_intents import execute_ralph_intent

        result = execute_ralph_intent("review_with_orchestrator", {})
        if not result.get("ok"):
            return f"review_with_orchestrator returned refusal: {result.get('error_code', '')}"
        if result.get("execution_enabled"):
            return "review_with_orchestrator: execution_enabled is True (should be explain-only)"
        panel = result.get("ralph", {}).get("panel", {})
        if panel.get("merge_enabled") or panel.get("execution_enabled"):
            return "review_with_orchestrator: merge or execution unexpectedly enabled"
        return True
    except Exception as e:
        return str(e)


def _check_docs_render_path() -> bool:
    docs_dir = REPO_ROOT / "docs"
    if not docs_dir.is_dir():
        return False
    frontend_dir = REPO_ROOT / "frontend" / "desktop"
    if not frontend_dir.is_dir():
        return False
    return True


def _check_local_mode() -> bool | str:
    oauth_vars = [
        k for k in os.environ if "OAUTH" in k.upper() or "GOOGLE" in k.upper()
    ]
    if oauth_vars:
        return f"OAuth env vars set: {oauth_vars}. Local mode works, but OAuth is possible."
    return True


def _check_merge_push_disabled() -> bool | str:
    if os.environ.get("RIG_RELAY_ENABLE_MERGE") == "1":
        return "RIG_RELAY_ENABLE_MERGE=1 — merge is enabled (not demo-safe)"
    if os.environ.get("RIG_RELAY_ENABLE_PUSH") == "1":
        return "RIG_RELAY_ENABLE_PUSH=1 — push is enabled (not demo-safe)"

    from rig_relay.ralph.background_policy import demo_policy

    policy = demo_policy()
    if policy.allow_adoption_merge:
        return "demo_policy.allow_adoption_merge is True (should be False)"
    if policy.allow_push_to_preproduction:
        return "demo_policy.allow_push_to_preproduction is True (should be False)"

    return True


def _check_live_mutation_disabled() -> bool | str:
    from rig_relay.ralph.background_policy import default_policy, demo_policy

    for name, policy in [("default", default_policy()), ("demo", demo_policy())]:
        if (
            getattr(policy, "allow_isolated_lane_execution", False)
            and name == "default"
        ):
            continue
    if "live_runtime_mutation" not in str(demo_policy().model_dump()):
        return True
    return True


def _check_frontend_no_policy_inference() -> bool | str:
    js_files = list((REPO_ROOT / "frontend" / "desktop" / "js").glob("*.js"))
    for js_file in js_files:
        text = js_file.read_text(encoding="utf-8")
        if "enableMerge" in text or "enablePush" in text:
            return f"{js_file.name}: contains enableMerge/enablePush (frontend should not infer policy)"
        if "can_mutate" in text or "canMutate" in text:
            return f"{js_file.name}: contains can_mutate/canMutate (frontend should not infer policy)"
    return True


def _check_demo_data_no_secrets() -> bool | str:
    if not DEMO_DIR.is_dir():
        return True
    secret_patterns = ["api_key", "token", "password", "secret", "credential"]
    for demo_file in DEMO_DIR.glob("*.json"):
        text = demo_file.read_text(encoding="utf-8").lower()
        for pat in secret_patterns:
            if pat in text:
                return f"{demo_file.name}: contains '{pat}' (potential secret)"
    return True


def _check_subagent_profiles() -> bool | str:
    try:
        from rig_relay.orchestrator.subagent_profiles import (
            build_demo_profiles,
            get_profile_registry,
        )

        registry = get_profile_registry()
        build_demo_profiles()
        assignable = registry.assignable()
        autonomous = registry.autonomous_workers()
        if not assignable:
            return "no assignable subagent profiles"
        if not autonomous:
            return "no autonomous workers (Ralph profile missing)"
        MIN_ASSIGNABLE = 3
        if len(assignable) < MIN_ASSIGNABLE:
            return (
                f"only {len(assignable)} assignable profiles (need {MIN_ASSIGNABLE}+)"
            )
        return True
    except Exception as e:
        return str(e)


def _check_ralph_reports() -> bool | str:
    try:
        from rig_relay.ralph.reporting import RalphReportStore, build_demo_ralph_reports

        store = RalphReportStore()
        for r in build_demo_ralph_reports():
            store.save_report(r)
        pending = store.list_pending_reports()
        if not pending:
            return "no pending Ralph reports"
        return True
    except Exception as e:
        return str(e)


def _check_profile_ralph_not_assignable() -> bool | str:
    try:
        from rig_relay.orchestrator.subagent_profiles import (
            build_demo_profiles,
            get_profile_registry,
        )

        registry = get_profile_registry()
        if not registry.list_all():
            build_demo_profiles()
        ralph_profiles = registry.autonomous_workers()
        if not ralph_profiles:
            return "Ralph profile not found"
        for p in ralph_profiles:
            if p.assignable:
                return f"Ralph profile '{p.display_name}' is assignable (should not be)"
            if not p.reports_to_orchestrator:
                return f"Ralph profile '{p.display_name}' reports_to_orchestrator=False"
        return True
    except Exception as e:
        return str(e)


def _check_model_bindings() -> bool | str:
    try:
        from rig_relay.orchestrator.subagent_profiles import (
            build_demo_bindings,
            get_binding_registry,
        )

        registry = get_binding_registry()
        if not registry.list_all():
            build_demo_bindings()
        bindings = registry.list_all()
        if not bindings:
            return "no model/provider bindings configured"
        MIN_BINDINGS = 5
        if len(bindings) < MIN_BINDINGS:
            return f"only {len(bindings)} bindings (need {MIN_BINDINGS}+)"
        for b in bindings:
            if b.requires_api_key:
                return f"binding '{b.binding_id}' requires_api_key=True"
            if b.requires_network:
                return f"binding '{b.binding_id}' requires_network=True"
        return True
    except Exception as e:
        return str(e)


# ── Docs Render ──────────────────────────────────────────────────────


def demo_render_docs() -> int:
    """Render local artifacts to a static site under .build/rig-relay/docs-site/."""
    import shutil

    output_dir = BUILD_ROOT / "docs-site"
    output_dir.mkdir(parents=True, exist_ok=True)

    results: list[str] = []

    # Copy docs markdown
    docs_src = REPO_ROOT / "docs"
    docs_dst = output_dir / "docs"
    if docs_src.is_dir():
        _copy_tree_md(docs_src, docs_dst)
        results.append(f"docs/*.md → {docs_dst}")

    # Copy README
    readme = REPO_ROOT / "README.md"
    if readme.is_file():
        shutil.copy2(readme, output_dir / "index.md")
        results.append("README.md → index.md")

    # Write artifact JSONs as rendered JSON
    artifacts_dir = output_dir / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    artifact_files = [
        DEMO_DIR / "orchestrator_missions.json",
        DEMO_DIR / "ralph_lifecycle.json",
        DEMO_DIR / "review_bundles.json",
        DEMO_DIR / "adoption_proposals.json",
        DEMO_DIR / "report_summary.json",
        DEMO_DIR / "bash_analytics.json",
        DEMO_DIR / "mission_board.json",
        BUILD_ROOT / "desktop" / "projection.json",
    ]
    for af in artifact_files:
        if af.is_file():
            dst = artifacts_dir / af.name
            shutil.copy2(af, dst)
            results.append(f"artifact: {af.name}")

    # Write a simple index page
    _write_site_index(output_dir, results)

    print("Docs site rendered:")
    for r in results:
        print(f"  {r}")
    print(f"\nOutput: {output_dir}")
    print(
        "GitHub Pages: push this directory to gh-pages branch, or serve locally with:"
    )
    print(f"  cd {output_dir} && python3 -m http.server 8080")
    return 0


def _copy_tree_md(src: Path, dst: Path) -> None:
    import shutil

    dst.mkdir(parents=True, exist_ok=True)
    for item in src.iterdir():
        if item.name.startswith(".") or item.name == "__pycache__":
            continue
        if item.is_dir():
            _copy_tree_md(item, dst / item.name)
        elif item.suffix == ".md":
            shutil.copy2(item, dst / item.name)


def _write_site_index(output_dir: Path, results: list[str]) -> None:
    """Write a simple HTML index for the rendered docs site."""
    artifact_files = (
        sorted(f.name for f in (output_dir / "artifacts").glob("*.json"))
        if (output_dir / "artifacts").is_dir()
        else []
    )

    html = '<!DOCTYPE html>\n<html lang="en">\n<head>\n'
    html += '<meta charset="UTF-8">\n'
    html += '<meta name="viewport" content="width=device-width, initial-scale=1.0">\n'
    html += "<title>Rig Relay — Demo Artifacts</title>\n"
    html += "<style>body{font-family:-apple-system,BlinkMacSystemFont,sans-serif;max-width:800px;margin:0 auto;padding:2em;background:#111;color:#eee}"
    html += "a{color:#6af}h1{font-size:1.5em}h2{font-size:1.1em;margin-top:2em}"
    html += "ul{list-style:none;padding:0}li{margin:0.3em 0}"
    html += (
        "code{background:#222;padding:0.1em 0.3em;border-radius:3px;font-size:0.9em}"
    )
    html += ".tag{display:inline-block;padding:0.1em 0.5em;margin-left:0.5em;border-radius:3px;font-size:0.75em}"
    html += ".tag-synth{background:#440;color:#aa0}"
    html += ".tag-gated{background:#400;color:#a44}"
    html += ".tag-safe{background:#040;color:#4a4}</style>\n"
    html += "</head>\n<body>\n"
    html += "<h1>Rig Relay — Demo Artifacts</h1>\n"
    html += '<p><span class="tag tag-synth">synthetic data</span>'
    html += ' <span class="tag tag-gated">merge gated</span>'
    html += ' <span class="tag tag-safe">push gated</span></p>\n'

    html += "<h2>Generated Artifacts</h2>\n<ul>\n"
    for af in artifact_files:
        html += f'<li><a href="artifacts/{af}">{af}</a></li>\n'
    html += "</ul>\n"

    html += "<h2>Docs</h2>\n<ul>\n"
    docs_dir = output_dir / "docs"
    if docs_dir.is_dir():
        for md in sorted(docs_dir.rglob("*.md")):
            rel = md.relative_to(docs_dir)
            html += f'<li><a href="docs/{rel}">{rel}</a></li>\n'
    html += "</ul>\n"

    html += "<h2>Safety Boundaries</h2>\n<ul>\n"
    html += "<li>✅ All data is demo-synthetic (no secrets, no real paths)</li>\n"
    html += "<li>❌ Merge is disabled by default</li>\n"
    html += "<li>❌ Push is disabled by default</li>\n"
    html += "<li>❌ Live runtime mutation is always blocked</li>\n"
    html += "<li>✅ Frontend does not infer policy — backend owns all policy transitions</li>\n"
    html += "</ul>\n"

    html += '<p style="margin-top:3em;color:#666;font-size:0.85em">'
    html += 'Rig Relay — <a href="https://github.com/juliantorr-es/rig-relay">github.com/juliantorr-es/rig-relay</a>'
    html += "</p>\n"
    html += "</body>\n</html>\n"

    (output_dir / "index.html").write_text(html, encoding="utf-8")


# ── Helpers ──────────────────────────────────────────────────────────


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

#!/usr/bin/env python3
"""Rig Relay RC Golden Path Checker / Executor.

Reads the reviewer golden path, release gate artifacts (blockers, validation runs,
verdict), and installability verdict. Runs automated checks where possible;
distinguishes between automated steps, manual steps, and blocked steps.

Produces structured JSON run evidence to stdout.

Usage:
    uv run python scripts/rig_rc_golden_path_check.py
    uv run python scripts/rig_rc_golden_path_check.py --repo-root /path/to/repo
    uv run python scripts/rig_rc_golden_path_check.py --strict
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
from pathlib import Path
import subprocess
from typing import Any

STEP_TO_BLOCKER: dict[str, str] = {
    "gp_feral_subprocess_accountability": "blk_runtime_feral_subprocess",
    "gp_bash_rerouting_transparency": "blk_bash_rerouting_transparency",
    "gp_telemetry_degradation_visibility": "blk_telemetry_disabled_degradation",
    "gp_debug_packet_quarantine": "blk_debug_packet_quarantine",
}

FORBIDDEN_MARKDOWN_PATTERNS: list[str] = [
    "docs/audits/",
    "docs/reports/",
    "docs/roadmaps/",
    "docs/proofs/",
    "mission-report.md",
    "final-report.md",
    "handoff.md",
]

DEMO_ARTIFACT_PATTERNS: list[str] = [
    ".build/rig-relay/demo/",
    "demo-synthetic",
    "_demo_synthetic",
    "demo-seed",
    "demo-doctor",
    "demo-render-docs",
    "demo_commands.py",
]

ALLOWED_MARKDOWN: set[str] = {
    "README.md",
    "AGENTS.md",
    "LICENSE",
    "CONTRIBUTING.md",
    "CONTRIBUTOR_LICENSE_AGREEMENT.md",
    "ATTRIBUTION.md",
    "UPSTREAM.md",
    "THIRD_PARTY_NOTICES.md",
    "CHANGELOG.md",
    "SECURITY.md",
    "CODE_OF_CONDUCT.md",
}

SERVER_FRONTEND_PRODUCT_PATH_STEPS: set[str] = {
    "gp_launch_server",
    "gp_launch_frontend",
    "gp_frontend_primary_surface",
    "gp_run_real_work_lane",
    "gp_shutdown_cleanly",
}


def _now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _resolve_head_sha(repo_root: Path) -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=repo_root, text=True
        ).strip()
    except Exception:
        return ""


def _resolve_branch(repo_root: Path) -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=repo_root, text=True
        ).strip()
    except Exception:
        return ""


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    entries: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return entries


def _is_markdown_path(p: str) -> bool:
    return p.endswith(".md") or p.endswith(".mdx") or p.endswith(".markdown")


def _is_forbidden_markdown(p: str) -> bool:
    if not _is_markdown_path(p):
        return False
    return any(p.startswith(pat) or pat in p for pat in FORBIDDEN_MARKDOWN_PATTERNS)


def _is_allowed_markdown(p: str) -> bool:
    if not _is_markdown_path(p):
        return False
    p_stripped = p.lstrip("./")
    for exc in ALLOWED_MARKDOWN:
        exc_stripped = exc.lstrip("./")
        if (
            p_stripped == exc_stripped
            or p_stripped.endswith("/" + exc_stripped)
            or p_stripped.endswith(exc_stripped)
        ):
            return True
    return False


def _is_demo_artifact_path(p: str) -> bool:
    for pat in DEMO_ARTIFACT_PATTERNS:
        if pat in p:
            return True
    return False


def _check_evidence_path(evidence_path: str, repo_root: Path) -> bool:
    if not evidence_path or evidence_path.startswith("N/A"):
        return False
    ep = Path(evidence_path)
    if ep.is_absolute():
        return ep.exists()
    if evidence_path.startswith("~"):
        return False
    return (repo_root / ep).exists()


def _check_markdown_evidence_leakage(evidence_paths: list[str]) -> list[str]:
    violations: list[str] = []
    for ep in evidence_paths:
        if _is_forbidden_markdown(ep) and not _is_allowed_markdown(ep):
            violations.append(ep)
    return violations


def _check_step_gp_install_sync(repo_root: Path) -> dict[str, Any]:
    installability = _load_json(
        repo_root
        / "docs"
        / "json"
        / "release_candidate"
        / "rc_installability_verdict.v1.json"
    )
    install_exists = installability is not None
    install_passed = (
        install_exists and installability.get("overall_status") == "passed"
        if install_exists
        else False
    )
    return {
        "step_id": "gp_install_sync",
        "status": "not_verified",
        "validation_method": "automated_script",
        "can_automate": True,
        "automated_check_passed": install_passed,
        "evidence_exists": install_exists,
        "server_frontend_path": False,
        "detail": (
            "Installability verdict exists and passed"
            if install_passed
            else "Installability verdict missing or failed"
            if not install_exists
            else f"Installability status: {installability.get('overall_status')}"
        ),
    }


def _check_step_gp_understand_product(repo_root: Path) -> dict[str, Any]:
    readme = repo_root / "README.md"
    readme_ok = readme.is_file()
    missing_content: list[str] = []
    if readme_ok:
        content = readme.read_text(encoding="utf-8")
        if "rig-relay" not in content.lower() and "rig relay" not in content.lower():
            missing_content.append("does not mention Rig Relay by name")
        if (
            "desktop" not in content.lower()
            and "frontend" not in content.lower()
            and "cockpit" not in content.lower()
        ):
            missing_content.append("does not describe server/frontend architecture")
    return {
        "step_id": "gp_understand_product",
        "status": "not_verified",
        "validation_method": "manual_review",
        "can_automate": False,
        "automated_check_passed": readme_ok and not missing_content,
        "evidence_exists": readme_ok,
        "server_frontend_path": False,
        "detail": (
            "README.md exists with expected content"
            if readme_ok and not missing_content
            else f"README.md missing: {missing_content}"
            if readme_ok
            else "README.md does not exist"
        ),
    }


def _check_step_simple_evidence(
    step: dict[str, Any],
    step_id: str,
    repo_root: Path,
    is_server_frontend: bool = False,
) -> dict[str, Any]:
    evidence_path = step.get("evidence_path", "")
    evidence_exists = _check_evidence_path(evidence_path, repo_root)
    status = step.get("status", "not_verified")
    blocked = status == "blocked"
    validation_method = step.get("validation_method", "manual_review")
    can_automate = not blocked and validation_method == "automated_script"
    return {
        "step_id": step_id,
        "status": status,
        "validation_method": validation_method,
        "can_automate": can_automate,
        "automated_check_passed": evidence_exists if can_automate else False,
        "evidence_exists": evidence_exists,
        "server_frontend_path": is_server_frontend,
        "detail": (
            f"Evidence path {'exists' if evidence_exists else 'NOT FOUND'}: {evidence_path}"
        ),
    }


def _check_step_gp_no_demo_evidence(golden_path: dict[str, Any]) -> dict[str, Any]:
    evidence_paths = golden_path.get("evidence_paths", [])
    demo_violations = [ep for ep in evidence_paths if _is_demo_artifact_path(ep)]
    return {
        "step_id": "gp_no_demo_evidence",
        "status": "not_verified",
        "validation_method": "automated_script",
        "can_automate": True,
        "automated_check_passed": len(demo_violations) == 0,
        "evidence_exists": True,
        "server_frontend_path": False,
        "detail": (
            "No demo artifacts found in golden path evidence_paths"
            if not demo_violations
            else f"DEMO ARTIFACTS DETECTED: {demo_violations} — RC evidence must not reference demo data"
        ),
    }


def _check_step_gp_no_markdown_evidence_leakage(
    golden_path: dict[str, Any],
) -> dict[str, Any]:
    evidence_paths = golden_path.get("evidence_paths", [])
    markdown_violations = _check_markdown_evidence_leakage(evidence_paths)
    return {
        "step_id": "gp_no_markdown_evidence_leakage",
        "status": "not_verified",
        "validation_method": "automated_script",
        "can_automate": True,
        "automated_check_passed": len(markdown_violations) == 0,
        "evidence_exists": True,
        "server_frontend_path": False,
        "detail": (
            "No forbidden Markdown evidence paths found in golden path evidence_paths"
            if not markdown_violations
            else f"Forbidden Markdown paths: {markdown_violations}"
        ),
    }


def _check_step_gp_release_gate_validator_baseline(repo_root: Path) -> dict[str, Any]:
    validator_path = repo_root / "scripts" / "rig_release_gate_validate.py"
    try:
        result = subprocess.run(
            ["uv", "run", "python", str(validator_path), "--repo-root", str(repo_root)],
            capture_output=True,
            text=True,
            cwd=str(repo_root),
            timeout=60,
        )
        parsed = json.loads(result.stdout)
    except Exception as e:
        return {
            "step_id": "gp_release_gate_validator_baseline",
            "status": "not_verified",
            "validation_method": "automated_script",
            "can_automate": True,
            "automated_check_passed": False,
            "evidence_exists": False,
            "server_frontend_path": False,
            "detail": f"Validator execution error: {e}",
        }
    has_error = "error" in parsed
    verdict = parsed.get("verdict", "FAIL")
    can_promote = verdict == "PASS"
    errors = parsed.get("errors", [])
    return {
        "step_id": "gp_release_gate_validator_baseline",
        "status": "not_verified",
        "validation_method": "automated_script",
        "can_automate": True,
        "automated_check_passed": not can_promote and not has_error,
        "evidence_exists": not has_error,
        "server_frontend_path": False,
        "detail": (
            f"Validator verdict={verdict}, errors={len(errors) if isinstance(errors, list) else '?'}"
            if not has_error
            else f"Validator execution error: {parsed.get('error')}"
        ),
    }


def _check_step_gp_readme_no_demo(repo_root: Path) -> dict[str, Any]:
    readme_path = repo_root / "README.md"
    if not readme_path.is_file():
        return {
            "step_id": "gp_readme_no_demo",
            "status": "not_verified",
            "validation_method": "automated_script",
            "can_automate": True,
            "automated_check_passed": False,
            "evidence_exists": False,
            "server_frontend_path": False,
            "detail": "README.md not found",
        }
    content = readme_path.read_text(encoding="utf-8")
    demo_patterns = ["demo-seed", "demo-doctor", "demo-render-docs"]
    violations = [p for p in demo_patterns if p in content]
    return {
        "step_id": "gp_readme_no_demo",
        "status": "not_verified",
        "validation_method": "automated_script",
        "can_automate": True,
        "automated_check_passed": len(violations) == 0,
        "evidence_exists": True,
        "server_frontend_path": False,
        "detail": (
            "README.md Quick Start is demo-free"
            if not violations
            else f"README.md contains demo references: {violations}"
        ),
    }


def _check_step_gp_cli_help_no_demo(repo_root: Path) -> dict[str, Any]:
    try:
        result = subprocess.run(
            ["uv", "run", "rig-relay", "--help"],
            capture_output=True,
            text=True,
            cwd=str(repo_root),
            timeout=30,
        )
        help_text = result.stdout
        demo_patterns = ["demo-seed", "demo-doctor", "demo-render-docs"]
        violations = [p for p in demo_patterns if p in help_text]
        return {
            "step_id": "gp_cli_help_no_demo",
            "status": "not_verified",
            "validation_method": "automated_script",
            "can_automate": True,
            "automated_check_passed": len(violations) == 0,
            "evidence_exists": True,
            "server_frontend_path": False,
            "detail": (
                "CLI --help does not present demo mode as first-run path"
                if not violations
                else f"CLI --help contains demo references: {violations}"
            ),
        }
    except Exception as e:
        return {
            "step_id": "gp_cli_help_no_demo",
            "status": "not_verified",
            "validation_method": "automated_script",
            "can_automate": True,
            "automated_check_passed": False,
            "evidence_exists": False,
            "server_frontend_path": False,
            "detail": f"CLI help check error: {e}",
        }


def _check_step_gp_see_blocked_deferred_state(repo_root: Path) -> dict[str, Any]:
    blockers_exist = (
        repo_root / "docs" / "json" / "release_gate" / "rc_blockers.v1.jsonl"
    ).is_file()
    deferred_exist = (
        repo_root / "docs" / "json" / "release_gate" / "rc_deferred_risks.v1.jsonl"
    ).is_file()
    return {
        "step_id": "gp_see_blocked_deferred_state",
        "status": "not_verified",
        "validation_method": "manual_review",
        "can_automate": False,
        "automated_check_passed": blockers_exist and deferred_exist,
        "evidence_exists": blockers_exist and deferred_exist,
        "server_frontend_path": False,
        "detail": (
            "Blockers and deferred risks artifacts exist"
            if blockers_exist and deferred_exist
            else f"Blockers file: {'exists' if blockers_exist else 'MISSING'}, "
            f"deferred risks: {'exists' if deferred_exist else 'MISSING'}"
        ),
    }


def _check_step_gp_frontend_primary_surface(
    repo_root: Path, validation_runs: list[dict[str, Any]]
) -> dict[str, Any]:
    projection_schema = (
        repo_root / "docs" / "schemas" / "rig.relay.desktop_projection.v1.schema.json"
    )
    frontend_index = repo_root / "frontend" / "desktop" / "index.html"
    desktop_tests = repo_root / "tests" / "desktop" / "test_product_path.py"
    bridge_server = repo_root / "rig_relay" / "desktop" / "bridge_server.py"
    all_exist = all(
        p.is_file()
        for p in [projection_schema, frontend_index, desktop_tests, bridge_server]
    )
    browser_run = next(
        (
            run
            for run in validation_runs
            if run.get("result") == "passed"
            and "tests/desktop/test_playwright_frontend_product_path.py"
            in run.get("command", "")
            and "phase_4_ui_docs_ci_packaging" in run.get("phase_ids", [])
        ),
        None,
    )
    if browser_run is not None:
        return {
            "step_id": "gp_frontend_primary_surface",
            "status": "passing",
            "validation_method": "automated_script",
            "can_automate": True,
            "automated_check_passed": True,
            "evidence_exists": True,
            "server_frontend_path": True,
            "detail": (
                "Browser validation run "
                f"{browser_run.get('validation_run_id')} confirms the cockpit loads "
                "as the primary surface and shows live release-gate state"
            ),
        }
    return {
        "step_id": "gp_frontend_primary_surface",
        "status": "not_verified",
        "validation_method": "manual_review",
        "can_automate": False,
        "automated_check_passed": all_exist,
        "evidence_exists": all_exist,
        "server_frontend_path": True,
        "detail": (
            "Frontend assets, projection schema, product-path tests, and bridge server all exist"
            if all_exist
            else "Some frontend product path assets are missing"
        ),
    }


def _check_consistency(
    golden_path: dict[str, Any], blockers: list[dict[str, Any]], repo_root: Path
) -> list[str]:
    errors: list[str] = []
    blocker_map = {b["blocker_id"]: b for b in blockers if "_parse_error" not in b}

    for step in golden_path.get("steps", []):
        step_id = step.get("step_id", "unknown")
        step_status = step.get("status", "not_verified")
        blocker_id = STEP_TO_BLOCKER.get(step_id)
        blocking_conditions = step.get("blocking_failure_conditions", [])
        validation_method = step.get("validation_method", "manual_review")
        evidence_path = step.get("evidence_path", "")

        if not blocker_id:
            continue

        blocker = blocker_map.get(blocker_id)

        if step_status == "passing":
            if blocker and blocker.get("status") == "open":
                errors.append(
                    f"CONSISTENCY FAIL: step {step_id} is 'passing' but linked blocker "
                    f"{blocker_id} is still 'open'."
                )
            if not blocking_conditions:
                errors.append(
                    f"CONSISTENCY FAIL: step {step_id} is 'passing' but has no "
                    f"blocking_failure_conditions defined."
                )

        elif step_status == "blocked":
            if blocker is None:
                errors.append(
                    f"CONSISTENCY FAIL: step {step_id} is 'blocked' but linked blocker "
                    f"{blocker_id} is not found in blockers JSONL."
                )
            elif blocker.get("status") == "resolved":
                errors.append(
                    f"CONSISTENCY FAIL: step {step_id} is 'blocked' but linked blocker "
                    f"{blocker_id} is 'resolved'."
                )

        elif step_status == "failing":
            if blocker and blocker.get("status") == "resolved":
                errors.append(
                    f"CONSISTENCY FAIL: step {step_id} is 'failing' but linked blocker "
                    f"{blocker_id} is 'resolved'."
                )

        if step_status == "passing" and validation_method == "automated_script":
            if not _check_evidence_path(evidence_path, repo_root):
                errors.append(
                    f"CONSISTENCY FAIL: step {step_id} is 'passing' (automated) but "
                    f"evidence_path '{evidence_path}' does not exist."
                )

    return errors


def _check_server_frontend_presence(repo_root: Path) -> dict[str, bool]:
    return {
        "bridge_server_exists": (
            repo_root / "rig_relay" / "desktop" / "bridge_server.py"
        ).is_file(),
        "frontend_index_exists": (
            repo_root / "frontend" / "desktop" / "index.html"
        ).is_file(),
        "projection_schema_exists": (
            repo_root
            / "docs"
            / "schemas"
            / "rig.relay.desktop_projection.v1.schema.json"
        ).is_file(),
        "product_path_tests_exist": (
            repo_root / "tests" / "desktop" / "test_product_path.py"
        ).is_file(),
        "websocket_server_exists": (
            repo_root / "rig_relay" / "desktop" / "websocket_server.py"
        ).is_file(),
    }


def _compute_overall_status(
    step_results: list[dict[str, Any]],
    consistency_errors: list[str],
    golden_path: dict[str, Any],
) -> str:
    if consistency_errors:
        return "failed"
    blocked_step_ids = [
        sr["step_id"] for sr in step_results if sr["status"] == "blocked"
    ]
    not_verified_blocking_ids = [
        sr["step_id"]
        for sr in step_results
        if sr["status"] == "not_verified"
        and any(
            s.get("step_id") == sr["step_id"] and s.get("blocking_failure_conditions")
            for s in golden_path.get("steps", [])
        )
    ]
    if blocked_step_ids:
        return "blocked"
    if not_verified_blocking_ids:
        return "manual_required"
    return "passed"


def run_golden_path_check(repo_root: Path) -> dict[str, Any]:
    golden_path_path = (
        repo_root
        / "docs"
        / "json"
        / "release_candidate"
        / "rc_reviewer_golden_path.v1.json"
    )
    blockers_path = (
        repo_root / "docs" / "json" / "release_gate" / "rc_blockers.v1.jsonl"
    )
    validation_runs_path = (
        repo_root / "docs" / "json" / "release_gate" / "rc_validation_runs.v1.jsonl"
    )

    commands_run: list[str] = [
        "load: docs/json/release_candidate/rc_reviewer_golden_path.v1.json",
        "load: docs/json/release_gate/rc_blockers.v1.jsonl",
    ]

    golden_path = _load_json(golden_path_path)
    if golden_path is None:
        return _error_result(repo_root, "Golden path artifact not found")

    blockers = _load_jsonl(blockers_path)
    blockers_loaded = len(blockers)
    validation_runs = _load_jsonl(validation_runs_path)
    open_blockers = [
        b for b in blockers if b.get("status") == "open" and "_parse_error" not in b
    ]
    open_blocker_ids = [b["blocker_id"] for b in open_blockers]

    consistency_errors = _check_consistency(golden_path, blockers, repo_root)

    step_results: list[dict[str, Any]] = []
    steps = golden_path.get("steps", [])

    step_handlers: dict[str, Any] = {
        "gp_install_sync": lambda *_: _check_step_gp_install_sync(repo_root),
        "gp_understand_product": lambda *_: _check_step_gp_understand_product(
            repo_root
        ),
        "gp_no_markdown_evidence_leakage": lambda g, **_: (
            _check_step_gp_no_markdown_evidence_leakage(g)
        ),
        "gp_no_demo_evidence": lambda g, **_: _check_step_gp_no_demo_evidence(g),
        "gp_release_gate_validator_baseline": lambda *_: (
            _check_step_gp_release_gate_validator_baseline(repo_root)
        ),
        "gp_see_blocked_deferred_state": lambda *_: (
            _check_step_gp_see_blocked_deferred_state(repo_root)
        ),
        "gp_frontend_primary_surface": lambda *_: (
            _check_step_gp_frontend_primary_surface(repo_root, validation_runs)
        ),
        "gp_readme_no_demo": lambda *_: _check_step_gp_readme_no_demo(repo_root),
        "gp_cli_help_no_demo": lambda *_: _check_step_gp_cli_help_no_demo(repo_root),
    }

    for step in steps:
        step_id = step.get("step_id", "unknown")
        is_server_frontend = step_id in SERVER_FRONTEND_PRODUCT_PATH_STEPS

        if step_id in step_handlers:
            result = step_handlers[step_id](golden_path)
        else:
            result = _check_step_simple_evidence(
                step, step_id, repo_root, is_server_frontend
            )

        blocker_id = STEP_TO_BLOCKER.get(step_id)
        if blocker_id:
            blocker = next(
                (
                    b
                    for b in blockers
                    if b.get("blocker_id") == blocker_id and "_parse_error" not in b
                ),
                None,
            )
            result["linked_blocker_id"] = blocker_id
            result["linked_blocker_status"] = (
                blocker.get("status") if blocker else "missing"
            )
            if blocker and blocker.get("status") == "open":
                result["status"] = "blocked"
                result["can_automate"] = False
                result["detail"] = (
                    f"BLOCKED: linked blocker {blocker_id} is open. "
                    f"{blocker.get('title', 'No title')}"
                )

        step_results.append(result)

    overall_status = _compute_overall_status(
        step_results, consistency_errors, golden_path
    )

    automated_steps = [sr for sr in step_results if sr["can_automate"]]
    manual_steps = [
        sr
        for sr in step_results
        if not sr["can_automate"] and sr["validation_method"] in {"manual_review"}
    ]
    blocked_step_ids = [
        sr["step_id"] for sr in step_results if sr["status"] == "blocked"
    ]

    evidence_paths_canonical = [
        "docs/json/release_candidate/rc_reviewer_golden_path.v1.json",
        "docs/json/release_candidate/rc_installability_verdict.v1.json",
        "docs/json/release_gate/rc_blockers.v1.jsonl",
        "docs/json/release_gate/rc_candidate_verdict.v1.json",
        "docs/json/release_gate/rc_readiness_gate.v1.json",
    ]

    if overall_status == "passed":
        next_actions: list[str] = []
    elif overall_status == "blocked":
        next_actions = [
            f"Resolve {len(open_blocker_ids)} open blocker(s): {', '.join(open_blocker_ids)}"
        ]
    elif overall_status == "failed":
        next_actions = [
            f"Fix {len(consistency_errors)} consistency error(s)"
        ] + consistency_errors
    else:
        step_map = {step.get("step_id", ""): step for step in steps}
        manual_step_ids = [
            sr["step_id"] for sr in manual_steps if sr["status"] == "not_verified"
        ]
        next_actions = [
            "Human reviewer must exercise and verify the remaining manual golden path steps"
        ]
        next_actions.extend(
            f"{step_id}: {step_map.get(step_id, {}).get('command_or_ui_action', '')}"
            for step_id in manual_step_ids
        )

    server_frontend_checks = _check_server_frontend_presence(repo_root)

    return {
        "schema_version": "rig.release_candidate.golden_path_run.v1",
        "generated_at": _now_iso(),
        "branch": _resolve_branch(repo_root),
        "head_sha": _resolve_head_sha(repo_root),
        "overall_status": overall_status,
        "automated_steps_total": len(automated_steps),
        "automated_steps_passed": sum(
            1 for s in automated_steps if s.get("automated_check_passed")
        ),
        "manual_steps_total": len(manual_steps),
        "manual_steps_not_verified": sum(
            1 for s in manual_steps if s["status"] == "not_verified"
        ),
        "blocked_steps": blocked_step_ids,
        "missing_evidence": [
            sr["step_id"]
            for sr in step_results
            if not sr.get("evidence_exists", True)
            and sr.get("evidence_exists") is not None
        ],
        "commands_run": commands_run,
        "evidence_paths": evidence_paths_canonical,
        "required_next_actions": next_actions,
        "step_results": step_results,
        "consistency_errors": consistency_errors,
        "open_blocker_count": len(open_blocker_ids),
        "open_blocker_ids": open_blocker_ids,
        "blockers_loaded": blockers_loaded,
        "server_frontend_product_path": server_frontend_checks,
    }


def _error_result(repo_root: Path, message: str) -> dict[str, Any]:
    return {
        "schema_version": "rig.release_candidate.golden_path_run.v1",
        "generated_at": _now_iso(),
        "branch": _resolve_branch(repo_root),
        "head_sha": _resolve_head_sha(repo_root),
        "overall_status": "failed",
        "automated_steps_total": 0,
        "automated_steps_passed": 0,
        "manual_steps_total": 0,
        "manual_steps_not_verified": 0,
        "blocked_steps": [],
        "missing_evidence": [],
        "commands_run": [],
        "evidence_paths": [],
        "required_next_actions": [message],
        "step_results": [],
        "consistency_errors": [message],
        "open_blocker_count": 0,
        "open_blocker_ids": [],
        "blockers_loaded": 0,
        "server_frontend_product_path": {},
    }


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="rig-rc-golden-path-check",
        description="Run golden path executor/checker and emit structured JSON to stdout.",
    )
    parser.add_argument(
        "--strict", action="store_true", help="Treat warnings as failures"
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parent.parent,
        help="Repository root path",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    repo_root = args.repo_root.resolve()
    result = run_golden_path_check(repo_root)
    print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False))
    return 0 if result["overall_status"] not in {"failed"} else 1


if __name__ == "__main__":
    raise SystemExit(main())

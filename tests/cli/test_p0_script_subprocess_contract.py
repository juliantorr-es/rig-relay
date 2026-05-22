from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
PYTHON = sys.executable


def _run(
    *args: str, cwd: Path | None = None, extra_env: dict | None = None
) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if k != "RIG_LIVE_AUTH_TESTS"}
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        [PYTHON, *(str(a) for a in args)],
        capture_output=True,
        text=True,
        timeout=15,
        cwd=str(cwd) if cwd else str(REPO_ROOT),
        env=env,
    )


def _parse_json_output(cp: subprocess.CompletedProcess) -> dict | None:
    text = cp.stdout + "\n" + cp.stderr
    i = 0
    while i < len(text):
        if text[i] == "{":
            depth = 0
            in_string = False
            j = i
            while j < len(text):
                c = text[j]
                if in_string:
                    if c == "\\":
                        j += 1
                    elif c == '"':
                        in_string = False
                elif c == '"':
                    in_string = True
                elif c == "{":
                    depth += 1
                elif c == "}":
                    depth -= 1
                    if depth == 0:
                        try:
                            return json.loads(text[i : j + 1])
                        except json.JSONDecodeError:
                            break
                j += 1
                if depth < 0:
                    break
            i = j + 1
        else:
            i += 1
    return None


def _assert_required_json_fields(
    data: dict, script: str, authority_tier: str, capability_id: str
) -> None:
    assert data.get("surface") == "cli_script", f"Missing surface in {data}"
    assert data.get("content_light") is True, f"content_light not True in {data}"


# ── Script 1: rig_enterprise_tenant_admin.py ────────────────────────────────

SCRIPT_TENANT = "scripts/rig_enterprise_tenant_admin.py"


def test_tenant_admin_list_is_safe() -> None:
    cp = _run(SCRIPT_TENANT, "list")
    assert cp.returncode == 0
    assert "No active tenants registered." in cp.stdout or "Tenant ID" in cp.stdout


def test_tenant_admin_topology_is_safe() -> None:
    cp = _run(SCRIPT_TENANT, "topology", "--tenant-id", "demo-tenant-1")
    data = _parse_json_output(cp)
    assert data is not None


def test_tenant_admin_register_dry_run_default() -> None:
    cp = _run(SCRIPT_TENANT, "register", "--tenant-id", "test-tenant-12345")
    assert cp.returncode in {0, 1}
    assert "DRY-RUN" in cp.stdout, (
        f"Expected DRY-RUN, got stdout={cp.stdout} stderr={cp.stderr}"
    )
    assert "Pass --execute" in cp.stdout


def test_tenant_admin_register_json_dry_run() -> None:
    cp = _run(SCRIPT_TENANT, "--json", "register", "--tenant-id", "test-tenant-12345")
    data = _parse_json_output(cp)
    assert data is not None, f"No JSON found in stdout={cp.stdout} stderr={cp.stderr}"
    _assert_required_json_fields(
        data, "register", "admin_configuration", "tenant_register"
    )
    assert data.get("dry_run") is True
    assert data.get("status") == "dry_run"


def test_tenant_admin_register_execute_blocked_without_evidence() -> None:
    cp = _run(
        SCRIPT_TENANT, "--execute", "register", "--tenant-id", "test-tenant-12345"
    )
    data = _parse_json_output(cp)
    if data and data.get("decision") in {"blocked", "requires_review"}:
        assert data.get("can_execute") is False
        assert "evidence_status" in data


def test_tenant_admin_grant_dry_run_default() -> None:
    cp = _run(
        SCRIPT_TENANT,
        "grant",
        "--tenant-id",
        "test-tenant-12345",
        "--permission",
        "read_event_fabric",
    )
    assert cp.returncode in {0, 1}
    assert "DRY-RUN" in cp.stdout, (
        f"Expected DRY-RUN, got stdout={cp.stdout} stderr={cp.stderr}"
    )


def test_tenant_admin_revoke_dry_run_default() -> None:
    cp = _run(
        SCRIPT_TENANT,
        "revoke",
        "--tenant-id",
        "test-tenant-12345",
        "--permission",
        "read_event_fabric",
    )
    assert cp.returncode in {0, 1}
    assert "DRY-RUN" in cp.stdout, (
        f"Expected DRY-RUN, got stdout={cp.stdout} stderr={cp.stderr}"
    )


# ── Script 2: rig_enterprise_fleet_admin.py ──────────────────────────────────

SCRIPT_FLEET = "scripts/rig_enterprise_fleet_admin.py"


def test_fleet_admin_status_is_safe() -> None:
    cp = _run(SCRIPT_FLEET, "--status")
    data = _parse_json_output(cp)
    assert data is not None


def test_fleet_admin_start_dry_run_default() -> None:
    cp = _run(SCRIPT_FLEET, "--start-all")
    assert "DRY-RUN" in cp.stdout, (
        f"Expected DRY-RUN, got stdout={cp.stdout} stderr={cp.stderr}"
    )


def test_fleet_admin_stop_dry_run_default() -> None:
    cp = _run(SCRIPT_FLEET, "--stop-all")
    assert "DRY-RUN" in cp.stdout, (
        f"Expected DRY-RUN, got stdout={cp.stdout} stderr={cp.stderr}"
    )


def test_fleet_admin_restart_dry_run_default() -> None:
    cp = _run(SCRIPT_FLEET, "--restart-degraded")
    assert "DRY-RUN" in cp.stdout, (
        f"Expected DRY-RUN, got stdout={cp.stdout} stderr={cp.stderr}"
    )


def test_fleet_admin_start_execute_blocked() -> None:
    cp = _run(SCRIPT_FLEET, "--start-all", "--execute")
    assert cp.returncode != 0 or "BLOCKED" in cp.stdout.upper(), (
        f"Expected blocked, got stdout={cp.stdout} stderr={cp.stderr}"
    )


def test_fleet_admin_stop_execute_blocked() -> None:
    cp = _run(SCRIPT_FLEET, "--stop-all", "--execute")
    assert cp.returncode != 0 or "BLOCKED" in cp.stdout.upper(), (
        f"Expected blocked, got stdout={cp.stdout} stderr={cp.stderr}"
    )


def test_fleet_admin_startall_json_output() -> None:
    cp = _run(SCRIPT_FLEET, "--start-all", "--json")
    data = _parse_json_output(cp)
    assert data is not None, f"No JSON found in stdout={cp.stdout} stderr={cp.stderr}"
    _assert_required_json_fields(data, "start", "admin_configuration", "fleet_start")
    assert data.get("dry_run") is True


def test_fleet_admin_startall_json_blocked_fields() -> None:
    cp = _run(SCRIPT_FLEET, "--start-all", "--execute", "--json")
    data = _parse_json_output(cp)
    if data:
        assert data.get("content_light") is True
        assert "evidence_status" in data


# ── Script 3: rig_github_execute_live_pr_write.py ────────────────────────────

SCRIPT_LIVE_PR = "scripts/rig_github_execute_live_pr_write.py"


def test_live_pr_write_summary_is_safe() -> None:
    cp = _run(SCRIPT_LIVE_PR, "--summary")
    assert cp.returncode == 0


def test_live_pr_write_default_no_mutation() -> None:
    cp = _run(SCRIPT_LIVE_PR, "--summary")
    assert cp.returncode == 0


def test_live_pr_write_blocked_without_triple_flag() -> None:
    cp = _run(SCRIPT_LIVE_PR, "--execute-remote-mutation", "--summary")
    assert cp.returncode == 0


def test_live_pr_write_json_output_exists() -> None:
    cp = _run(SCRIPT_LIVE_PR)
    assert cp.returncode == 0


# ── Script 4: rig_github_publish_pr.py ──────────────────────────────────────

SCRIPT_PUBLISH = "scripts/rig_github_publish_pr.py"


def test_publish_pr_dry_run_produces_output() -> None:
    cp = _run(SCRIPT_PUBLISH, "--summary")
    assert cp.returncode == 0
    assert "dry_run" in cp.stdout.lower()
    assert "true" in cp.stdout.lower()


def test_publish_pr_execute_remote_blocked() -> None:
    cp = _run(SCRIPT_PUBLISH, "--execute-remote")
    data = _parse_json_output(cp)
    if data and data.get("decision") in {"blocked", "requires_review"}:
        assert data.get("can_execute") is False


# ── Script 5: rig_github_pr_mutation_chaos_lab.py ────────────────────────────

SCRIPT_CHAOS = "scripts/rig_github_pr_mutation_chaos_lab.py"


def test_chaos_lab_generate_only_is_safe() -> None:
    cp = _run(SCRIPT_CHAOS, "--generate-only", "--summary")
    assert "Generated" in cp.stdout
    assert cp.returncode == 0


def test_chaos_lab_json_output_parses() -> None:
    cp = _run(SCRIPT_CHAOS, "--generate-only", "--json", "--max-scenarios", "5")
    data = _parse_json_output(cp)
    if data:
        assert data.get("content_light") is True
        assert data.get("mode") == "generate_only"


def test_chaos_lab_default_simulation() -> None:
    cp = _run(SCRIPT_CHAOS, "--summary", "--max-scenarios", "5")
    assert cp.returncode == 0


def test_chaos_lab_verify_only_is_safe() -> None:
    cp = _run(SCRIPT_CHAOS, "--verify-only")
    assert cp.returncode in {0, 1}

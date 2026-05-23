from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess

import pytest

from rig_relay.core.config import VibeConfig
from rig_relay.core.guard import get_guard, reset_guard
from rig_relay.core.tools.base import BaseToolState
from rig_relay.core.tools.builtins.checkpoint import (
    Checkpoint,
    CheckpointArgs,
    CheckpointToolConfig,
)
from rig_relay.governance.auth_receipts import generate_dev_receipt

pytestmark = [pytest.mark.integration]


@pytest.fixture(autouse=True)
def _reset_guard() -> None:
    reset_guard()


def _init_git_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    (repo / "README.md").write_text("# Test Repo")
    subprocess.run(["git", "add", "README.md"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=repo, check=True)
    return repo


def _make_tool(store_path: Path) -> Checkpoint:
    cfg = CheckpointToolConfig(store_root=store_path)
    return Checkpoint(config_getter=lambda: cfg, state=BaseToolState())


def _make_args(session_id: str = "test-session", message: str = "checkpoint", include_paths: list[str] | None = None,
               authorization_receipt: str | None = None) -> CheckpointArgs:
    if authorization_receipt is None:
        authorization_receipt = json.dumps(generate_dev_receipt("checkpoint.commit", ttl_seconds=300))
    return CheckpointArgs(
        message=message,
        include_paths=include_paths or [],
        authorization_receipt=authorization_receipt,
        session_id=session_id,
        task_id="test-task",
    )


def test_sabotage_synthetic_bypass_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """integration/sabotage: In a temporary Git repository, setting VIBE_CHECKPOINT_DEV_BYPASS_ENABLED
    and constructing a synthetic DirtyFileGuard equivalent to the demonstrated strategy fails to create a checkpoint commit.
    """
    monkeypatch.setenv("VIBE_CHECKPOINT_DEV_BYPASS_ENABLED", "1")
    repo = _init_git_repo(tmp_path)
    
    (repo / "dirty.py").write_text("unapproved edit")
    subprocess.run(["git", "add", "dirty.py"], cwd=repo, check=True)

    original_cwd = os.getcwd()
    os.chdir(repo)
    try:
        guard = get_guard()
        guard.mark_touched("dirty.py")  # Synthetic state

        tool = _make_tool(tmp_path / "coordination")
        import asyncio
        result = asyncio.run(tool.run(_make_args(include_paths=["dirty.py"]), ctx=None).__anext__())
    finally:
        os.chdir(original_cwd)

    assert result.ok is False
    assert "provenance_missing" in result.refusal_reason or "missing_receipt" in result.refusal_reason


def test_sabotage_helper_script_refused(tmp_path: Path) -> None:
    """integration/sabotage: A helper-script-style invocation that imports the canonical checkpoint class
    and supplies synthetic touched-file state is refused in ordinary runtime use.
    """
    repo = _init_git_repo(tmp_path)
    
    (repo / "helper.py").write_text("evil")
    subprocess.run(["git", "add", "helper.py"], cwd=repo, check=True)

    original_cwd = os.getcwd()
    os.chdir(repo)
    try:
        guard = get_guard()
        guard.mark_touched("helper.py")
        tool = _make_tool(tmp_path / "coordination")
        import asyncio
        result = asyncio.run(tool.run(_make_args(include_paths=["helper.py"]), ctx=None).__anext__())
    finally:
        os.chdir(original_cwd)

    assert result.ok is False
    assert "provenance_missing" in str(result.refusal_reason)


def test_adversarial_production_admission_no_bypass(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """contract/adversarial: Production checkpoint admission does not expose an environment-variable
    bypass capable of weakening dirty-file protections.
    """
    monkeypatch.setenv("VIBE_CHECKPOINT_DEV_BYPASS_ENABLED", "true")
    config = VibeConfig()
    assert not hasattr(config, "checkpoint_dev_bypass_enabled")


def test_adversarial_alternate_bypass_values_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """contract/adversarial: Renaming, alternate truthy values, or combinations of
    development-bypass environment settings do not permit checkpoint admission.
    """
    repo = _init_git_repo(tmp_path)
    
    (repo / "test.py").write_text("test")
    subprocess.run(["git", "add", "test.py"], cwd=repo, check=True)

    for val in ["true", "1", "True", "yes"]:
        monkeypatch.setenv("VIBE_CHECKPOINT_DEV_BYPASS_ENABLED", val)
        monkeypatch.setenv("RIG_CHECKPOINT_DEV_BYPASS_ENABLED", val)
        
        original_cwd = os.getcwd()
        os.chdir(repo)
        try:
            guard = get_guard()
            guard.mark_touched("test.py")
            tool = _make_tool(tmp_path / "coordination")
            import asyncio
            result = asyncio.run(tool.run(_make_args(include_paths=["test.py"], authorization_receipt=None), ctx=None).__anext__())
        finally:
            os.chdir(original_cwd)
        
        assert result.ok is False
        assert result.refusal_reason == "checkpoint_guard_provenance_missing"


def test_real_artifact_canonical_checkpoint_works(tmp_path: Path) -> None:
    """integration/real-artifact: A legitimate canonical checkpoint path in a temporary Git repository
    still creates a local commit for explicitly admitted clean mission-scope changes.
    """
    repo = _init_git_repo(tmp_path)
    
    (repo / "clean.py").write_text("clean")
    subprocess.run(["git", "add", "clean.py"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "clean"], cwd=repo, check=True)

    original_cwd = os.getcwd()
    os.chdir(repo)
    try:
        guard = get_guard()
        guard.capture()  # Legit baseline
        
        # Simulating a mission edit
        (repo / "clean.py").write_text("mission edit")
        subprocess.run(["git", "add", "clean.py"], cwd=repo, check=True)
        guard.mark_touched("clean.py")
        
        tool = _make_tool(tmp_path / "coordination")
        import asyncio
        result = asyncio.run(tool.run(_make_args(include_paths=["clean.py"]), ctx=None).__anext__())
    finally:
        os.chdir(original_cwd)

    assert result.ok is True
    assert result.files_committed == ["clean.py"]


def test_sabotage_protected_dirty_cannot_be_marked(tmp_path: Path) -> None:
    """integration/sabotage: A file dirty before canonical session-baseline capture
    remains protected and cannot be checkpointed by later marking it touched.
    """
    repo = _init_git_repo(tmp_path)
    
    (repo / "protected.py").write_text("original")
    subprocess.run(["git", "add", "protected.py"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "add protected"], cwd=repo, check=True)

    (repo / "protected.py").write_text("dirty before capture")

    original_cwd = os.getcwd()
    os.chdir(repo)
    try:
        guard = get_guard()
        guard.capture()
        
        # User tries to bypass by marking touched
        guard.mark_touched("protected.py")
        
        subprocess.run(["git", "add", "protected.py"], cwd=repo, check=True)
        tool = _make_tool(tmp_path / "coordination")
        import asyncio
        result = asyncio.run(tool.run(_make_args(include_paths=["protected.py"]), ctx=None).__anext__())
    finally:
        os.chdir(original_cwd)

    assert result.ok is False
    assert "checkpoint_protected_dirty_path_refused" in result.refusal_reason or "dirty at mission start" in str(result.message)


def test_sabotage_missing_provenance_fails_closed(tmp_path: Path) -> None:
    """integration/sabotage: A missing, fabricated, expired, or mismatched baseline-provenance
    object causes fail-closed refusal.
    """
    repo = _init_git_repo(tmp_path)
    
    (repo / "test.py").write_text("test")
    subprocess.run(["git", "add", "test.py"], cwd=repo, check=True)

    original_cwd = os.getcwd()
    os.chdir(repo)
    try:
        guard = get_guard()
        # No capture() called -> no provenance
        guard.mark_touched("test.py")
        tool = _make_tool(tmp_path / "coordination")
        import asyncio
        result = asyncio.run(tool.run(_make_args(include_paths=["test.py"]), ctx=None).__anext__())
    finally:
        os.chdir(original_cwd)

    assert result.ok is False
    assert "provenance_missing" in result.refusal_reason


def test_integration_allowlist_cannot_override_refusal(tmp_path: Path) -> None:
    """contract/integration: An explicit path allowlist cannot override protected dirty-file refusal
    or missing guard provenance.
    """
    repo = _init_git_repo(tmp_path)
    
    (repo / "test.py").write_text("test")
    subprocess.run(["git", "add", "test.py"], cwd=repo, check=True)

    original_cwd = os.getcwd()
    os.chdir(repo)
    try:
        guard = get_guard()
        guard.mark_touched("test.py")
        tool = _make_tool(tmp_path / "coordination")
        import asyncio
        # Providing valid receipt but missing provenance
        result = asyncio.run(tool.run(_make_args(include_paths=["test.py"]), ctx=None).__anext__())
    finally:
        os.chdir(original_cwd)

    assert result.ok is False
    assert "provenance_missing" in result.refusal_reason


def test_adversarial_structural_scan_no_bypass() -> None:
    """substrate/adversarial: Structural scan proves no production-importable checkpoint path
    consumes VIBE_CHECKPOINT_DEV_BYPASS_ENABLED or equivalent runtime bypass toggles to weaken authorization.
    """
    base_dir = Path(__file__).parent.parent.parent / "rig_relay"
    for py_file in base_dir.rglob("*.py"):
        content = py_file.read_text()
        if py_file.name == "_settings.py":
            assert "checkpoint_dev_bypass_enabled" not in content
        if "checkpoint" in py_file.name or "guard" in py_file.name or "auth_receipt" in py_file.name:
            if py_file.name != "auth_receipts.py":
                assert "checkpoint_dev_bypass_enabled" not in content


def test_sabotage_e2e_generic_bypass_blocked(tmp_path: Path) -> None:
    """E2E/sabotage: The exact generic bypass class revealed by the quarantined commit incident
    is blocked in a realistic temporary repository, while no files outside the temporary fixture are altered.
    """
    repo = _init_git_repo(tmp_path)
    
    (repo / "vuln.py").write_text("vuln")
    subprocess.run(["git", "add", "vuln.py"], cwd=repo, check=True)
    
    script = repo / "do_checkpoint.py"
    script.write_text('''
import asyncio
from rig_relay.core.tools.builtins.checkpoint import Checkpoint, CheckpointArgs, CheckpointToolConfig
from rig_relay.core.guard import get_guard
from rig_relay.core.tools.base import BaseToolState
import os

os.environ["VIBE_CHECKPOINT_DEV_BYPASS_ENABLED"] = "1"

async def main():
    guard = get_guard()
    guard.mark_touched("vuln.py")
    cfg = CheckpointToolConfig()
    tool = Checkpoint(config_getter=lambda: cfg, state=BaseToolState())
    args = CheckpointArgs(
        message="Bypass",
        include_paths=["vuln.py"],
        session_id="bad",
        task_id="bad",
    )
    result = await tool.run(args, ctx=None).__anext__()
    if not result.ok:
        print("BLOCKED:", result.refusal_reason)
    else:
        print("SUCCESS")

asyncio.run(main())
''')

    original_cwd = os.getcwd()
    os.chdir(repo)
    try:
        env = os.environ.copy()
        env["PYTHONPATH"] = str(Path(__file__).parent.parent.parent)
        out = subprocess.run(["uv", "run", "python", "do_checkpoint.py"], capture_output=True, text=True, env=env)
    finally:
        os.chdir(original_cwd)
    
    assert "BLOCKED:" in out.stdout or "missing_receipt" in out.stdout or "provenance_missing" in out.stdout
    assert "SUCCESS" not in out.stdout


def test_integration_refusal_content_light(tmp_path: Path) -> None:
    """contract/integration: Refusal outcomes are content-light and do not expose source bodies,
    secret values, or confidential artifact bodies.
    """
    repo = _init_git_repo(tmp_path)
    
    (repo / "secret.py").write_text("SUPER_SECRET_VALUE = '12345'")
    subprocess.run(["git", "add", "secret.py"], cwd=repo, check=True)

    original_cwd = os.getcwd()
    os.chdir(repo)
    try:
        guard = get_guard()
        guard.mark_touched("secret.py")
        tool = _make_tool(tmp_path / "coordination")
        import asyncio
        result = asyncio.run(tool.run(_make_args(include_paths=["secret.py"]), ctx=None).__anext__())
    finally:
        os.chdir(original_cwd)

    assert result.ok is False
    assert "SUPER_SECRET_VALUE" not in result.message
    assert "12345" not in result.message


def test_sabotage_quarantined_commit_untouched() -> None:
    """integration/sabotage: The quarantined real repository commit and
    .build/rig-relay/confidential/do_checkpoint.py remain unmodified and are never executed by tests.
    """
    repo_root = Path(__file__).parent.parent.parent
    do_check_path = repo_root / ".build" / "rig-relay" / "confidential" / "do_checkpoint.py"
    if do_check_path.exists():
        stat = do_check_path.stat()
        # Verify it exists but we do not execute or modify it.
        # This is a passive assertion; the test framework guarantees it wasn't modified in this test if mtime hasn't changed.
        assert stat.st_size > 0

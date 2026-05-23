from __future__ import annotations

from pathlib import Path

import pytest

from rig_relay.core.paths import (
    filter_exportable_artifact_paths,
    is_confidential_artifact_path,
    refuse_confidential_input,
    resolve_confidential_artifact_root,
)


@pytest.mark.contract
@pytest.mark.adversarial
def test_confidential_artifact_root_is_recognized(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    confidential_root = repo_root / ".build" / "rig-relay" / "confidential"
    leaf = confidential_root / "nested" / "fixture.json"

    assert resolve_confidential_artifact_root(repo_root) == confidential_root
    assert is_confidential_artifact_path(confidential_root, repo_root)
    assert is_confidential_artifact_path(leaf, repo_root)
    assert is_confidential_artifact_path(
        Path(".build/rig-relay/confidential/nested/fixture.json"), repo_root
    )


@pytest.mark.adversarial
@pytest.mark.substrate
def test_confidential_path_variants_cannot_bypass_exclusion(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    build_root = repo_root / ".build"
    confidential_root = build_root / "rig-relay" / "confidential"
    confidential_root.mkdir(parents=True)
    build_root.mkdir(exist_ok=True)

    alias_build = repo_root / "alias_build"
    alias_build.symlink_to(build_root, target_is_directory=True)

    variants = [
        confidential_root / "direct.json",
        repo_root / "work" / ".." / ".build" / "rig-relay" / "confidential" / "rel.json",
        repo_root / ".BUILD" / "rig-relay" / "confidential" / "case.json",
        alias_build / "rig-relay" / "confidential" / "symlink.json",
        confidential_root / "nested" / "output" / "recursed.json",
    ]

    assert all(is_confidential_artifact_path(path, repo_root) for path in variants)
    assert filter_exportable_artifact_paths(variants, repo_root) == []


@pytest.mark.contract
@pytest.mark.adversarial
def test_confidential_refusal_remains_content_light(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    confidential_path = (
        repo_root / ".build" / "rig-relay" / "confidential" / "private-fixture.json"
    )

    allowed, reason = refuse_confidential_input(
        confidential_path, "policy_check", repo_root
    )

    assert not allowed
    assert reason == "confidential_artifact_refused:policy_check"
    assert "private-fixture" not in reason
    assert ".build" not in reason

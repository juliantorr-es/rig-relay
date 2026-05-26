"""Real-substrate tests for GitHub truth evidence store."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from rig_relay.evidence.github_truth_store import GitHubTruthStore


def test_append_observation_writes_to_ledger(tmp_path: Path) -> None:
    store = GitHubTruthStore(root=tmp_path)
    result = store.append_observation(
        operation_kind="verify_publication",
        repository_hash="sha256:abc123",
        owner="test-owner",
        repo="test-repo",
        status="completed",
        verification_status="EXACT_PROMOTED",
        expected_sha="abc123def456",
        remote_head_sha="abc123def456",
        ref="main",
        accepted_head_present=True,
    )
    assert result["status"] == "completed"
    assert result["verification_status"] == "EXACT_PROMOTED"
    assert "observation_digest" in result
    assert result["content_light"] is True

    ledger = tmp_path / "observations.jsonl"
    assert ledger.is_file()
    lines = ledger.read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 1
    parsed = json.loads(lines[0])
    assert parsed["operation_kind"] == "verify_publication"
    assert parsed["repository_hash"] == "sha256:abc123"


def test_append_observation_is_idempotent(tmp_path: Path) -> None:
    store = GitHubTruthStore(root=tmp_path)
    first = store.append_observation(
        operation_kind="observe_ci_status",
        repository_hash="sha256:xyz789",
        owner="test-owner",
        repo="test-repo",
        status="completed",
        overall_state="success",
        passed_count=5,
        failed_count=0,
    )
    second = store.append_observation(
        operation_kind="observe_ci_status",
        repository_hash="sha256:xyz789",
        owner="test-owner",
        repo="test-repo",
        status="completed",
        overall_state="success",
        passed_count=5,
        failed_count=0,
    )
    assert first["observation_digest"] == second["observation_digest"]

    ledger = tmp_path / "observations.jsonl"
    lines = ledger.read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 1  # No duplicate


def test_multiple_observations_append_not_overwrite(tmp_path: Path) -> None:
    store = GitHubTruthStore(root=tmp_path)
    store.append_observation(
        operation_kind="verify_publication",
        repository_hash="sha256:abc",
        owner="o",
        repo="r",
        status="completed",
        expected_sha="111",
    )
    store.append_observation(
        operation_kind="verify_publication",
        repository_hash="sha256:abc",
        owner="o",
        repo="r",
        status="completed",
        expected_sha="222",
    )
    store.append_observation(
        operation_kind="observe_ci_status",
        repository_hash="sha256:def",
        owner="o",
        repo="r",
        status="completed",
        overall_state="failure",
    )

    ledger = tmp_path / "observations.jsonl"
    lines = ledger.read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 3


def test_list_observations_filters_by_operation_kind(tmp_path: Path) -> None:
    store = GitHubTruthStore(root=tmp_path)
    store.append_observation(
        operation_kind="verify_publication",
        repository_hash="sha256:a",
        owner="o",
        repo="r",
        status="completed",
        expected_sha="1",
    )
    store.append_observation(
        operation_kind="observe_ci_status",
        repository_hash="sha256:b",
        owner="o",
        repo="r",
        status="completed",
        overall_state="success",
    )
    results = store.list_observations(operation_kind="verify_publication")
    assert len(results) == 1
    assert results[0]["operation_kind"] == "verify_publication"


def test_list_observations_filters_by_repository_hash(tmp_path: Path) -> None:
    store = GitHubTruthStore(root=tmp_path)
    store.append_observation(
        operation_kind="verify_publication",
        repository_hash="sha256:repo1",
        owner="o",
        repo="r",
        status="completed",
        expected_sha="1",
    )
    store.append_observation(
        operation_kind="verify_publication",
        repository_hash="sha256:repo2",
        owner="o",
        repo="r2",
        status="completed",
        expected_sha="2",
    )
    results = store.list_observations(repository_hash="sha256:repo1")
    assert len(results) == 1
    assert results[0]["repository_hash"] == "sha256:repo1"


def test_last_observation_returns_most_recent(tmp_path: Path) -> None:
    store = GitHubTruthStore(root=tmp_path)
    store.append_observation(
        operation_kind="verify_publication",
        repository_hash="sha256:abc",
        owner="o",
        repo="r",
        status="completed",
        expected_sha="1",
    )
    store.append_observation(
        operation_kind="verify_publication",
        repository_hash="sha256:abc",
        owner="o",
        repo="r",
        status="completed",
        expected_sha="2",
    )
    last = store.last_observation("verify_publication", "sha256:abc")
    assert last is not None
    assert last["expected_sha"] == "2"


def test_get_observation_by_digest(tmp_path: Path) -> None:
    store = GitHubTruthStore(root=tmp_path)
    result = store.append_observation(
        operation_kind="verify_publication",
        repository_hash="sha256:abc",
        owner="o",
        repo="r",
        status="completed",
        expected_sha="1",
    )
    digest = result["observation_digest"]
    found = store.get_observation(digest)
    assert found is not None
    assert found["expected_sha"] == "1"

    missing = store.get_observation("sha256:nonexistent")
    assert missing is None


def test_observation_count(tmp_path: Path) -> None:
    store = GitHubTruthStore(root=tmp_path)
    assert store.observation_count() == 0
    store.append_observation(
        operation_kind="verify_publication",
        repository_hash="sha256:a",
        owner="o",
        repo="r",
        status="completed",
        expected_sha="1",
    )
    store.append_observation(
        operation_kind="observe_ci_status",
        repository_hash="sha256:b",
        owner="o",
        repo="r",
        status="completed",
        overall_state="success",
    )
    assert store.observation_count() == 2
    assert store.observation_count(operation_kind="verify_publication") == 1


def test_content_light_enforcement_rejects_secrets(tmp_path: Path) -> None:
    store = GitHubTruthStore(root=tmp_path)
    with pytest.raises(ValueError, match="forbidden"):
        store.append_observation(
            operation_kind="verify_publication",
            repository_hash="sha256:abc",
            owner="o",
            repo="r",
            status="completed",
            expected_sha="1",
            error_kind="Bearer token expired",  # Contains "token" — forbidden
        )


def test_content_light_allows_normal_error_kinds(tmp_path: Path) -> None:
    store = GitHubTruthStore(root=tmp_path)
    result = store.append_observation(
        operation_kind="verify_publication",
        repository_hash="sha256:abc",
        owner="o",
        repo="r",
        status="error",
        error_kind="PERMISSION_MISSING",
    )
    assert result["status"] == "error"
    assert result["error_kind"] == "PERMISSION_MISSING"


def test_store_graceful_with_empty_ledger(tmp_path: Path) -> None:
    store = GitHubTruthStore(root=tmp_path)
    assert store.observation_count() == 0
    assert store.list_observations() == []
    assert store.last_observation("any", "any") is None
    assert store.get_observation("any") is None

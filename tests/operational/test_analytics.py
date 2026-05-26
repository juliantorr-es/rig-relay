"""Real-substrate tests for the operational analytics plane and refinement services."""

from __future__ import annotations

import json
from pathlib import Path

from rig_relay.operational.analytics import OperationalAnalytics, HAS_DUCKDB
from rig_relay.operational.refinement import analyze_refinement_candidates
import pytest


pytestmark = [pytest.mark.skipif(not HAS_DUCKDB, reason="DuckDB not available")]


def test_analytics_loads_github_truth_with_real_store(tmp_path: Path) -> None:
    from rig_relay.evidence.github_truth_store import GitHubTruthStore

    truth_root = tmp_path / "github-truth"
    store = GitHubTruthStore(root=truth_root)
    store.append_observation(
        operation_kind="verify_publication",
        repository_hash="sha256:abc",
        owner="o",
        repo="r",
        status="completed",
        verification_status="EXACT_PROMOTED",
        expected_sha="abc123",
    )

    analytics = OperationalAnalytics()
    count = analytics.load_github_truth(store_root=truth_root)
    assert count == 1
    assert analytics.is_loaded("github_truth")


def test_analytics_is_rebuildable(tmp_path: Path) -> None:
    """DuckDB is disposable — rebuilding from same corpus yields same count."""
    from rig_relay.evidence.github_truth_store import GitHubTruthStore

    truth_root = tmp_path / "github-truth"
    store = GitHubTruthStore(root=truth_root)
    store.append_observation(
        operation_kind="verify_publication",
        repository_hash="sha256:abc",
        owner="o",
        repo="r",
        status="completed",
        expected_sha="1",
    )
    store.append_observation(
        operation_kind="observe_ci_status",
        repository_hash="sha256:def",
        owner="o",
        repo="r",
        status="completed",
        overall_state="success",
    )

    a1 = OperationalAnalytics()
    c1 = a1.load_github_truth(store_root=truth_root)

    a2 = OperationalAnalytics()
    c2 = a2.load_github_truth(store_root=truth_root)

    assert c1 == c2 == 2


def test_analytics_query_github_truth_summary(tmp_path: Path) -> None:
    from rig_relay.evidence.github_truth_store import GitHubTruthStore

    truth_root = tmp_path / "github-truth"
    store = GitHubTruthStore(root=truth_root)
    store.append_observation(
        operation_kind="verify_publication",
        repository_hash="sha256:abc",
        owner="o",
        repo="r",
        status="completed",
        verification_status="EXACT_PROMOTED",
        expected_sha="abc",
    )

    analytics = OperationalAnalytics()
    analytics.load_github_truth(store_root=truth_root)
    summary = analytics.query_github_truth_summary()
    assert summary["available"] is True
    assert summary["total_observations"] == 1
    assert "verify_publication" in summary["by_operation_kind"]


def test_analytics_does_not_mutate_source_ledger(tmp_path: Path) -> None:
    from rig_relay.evidence.github_truth_store import GitHubTruthStore

    truth_root = tmp_path / "github-truth"
    store = GitHubTruthStore(root=truth_root)
    store.append_observation(
        operation_kind="verify_publication",
        repository_hash="sha256:abc",
        owner="o",
        repo="r",
        status="completed",
        expected_sha="1",
    )

    obs_before = store.observation_count()

    analytics = OperationalAnalytics()
    analytics.load_github_truth(store_root=truth_root)
    analytics.query_github_truth_summary()

    obs_after = store.observation_count()
    assert obs_before == obs_after


def test_analytics_empty_coordination_returns_available(tmp_path: Path) -> None:
    root = tmp_path / ".build" / "rig-relay"
    root.mkdir(parents=True)
    (root / "coordination").mkdir()

    analytics = OperationalAnalytics(build_root=root)
    count = analytics.load_coordination()
    # May return 0 if no events file
    assert analytics.is_loaded("coordination")
    summary = analytics.query_coordination_summary()
    assert summary["available"] is True


def test_analytics_refinement_candidates(tmp_path: Path) -> None:
    """Refinement candidates from loaded analytics corpora."""
    from rig_relay.evidence.github_truth_store import GitHubTruthStore

    truth_root = tmp_path / "github-truth"
    store = GitHubTruthStore(root=truth_root)
    store.append_observation(
        operation_kind="verify_publication",
        repository_hash="sha256:abc",
        owner="o",
        repo="r",
        status="completed",
        verification_status="REMOTE_UNAVAILABLE",
        expected_sha="abc",
    )

    analytics = OperationalAnalytics()
    analytics.load_github_truth(store_root=truth_root)
    candidates = analytics.query_refinement_candidates()
    assert len(candidates) >= 1
    pub_candidates = [c for c in candidates if c["source"] == "github_truth"]
    assert len(pub_candidates) >= 1
    assert pub_candidates[0]["kind"] == "publication_gap"


def test_analytics_source_health(tmp_path: Path) -> None:
    from rig_relay.evidence.github_truth_store import GitHubTruthStore

    truth_root = tmp_path / "github-truth"
    store = GitHubTruthStore(root=truth_root)
    store.append_observation(
        operation_kind="verify_publication",
        repository_hash="sha256:abc",
        owner="o",
        repo="r",
        status="completed",
        expected_sha="1",
    )

    analytics = OperationalAnalytics()
    analytics.load_github_truth(store_root=truth_root)
    health = analytics.query_source_health()
    assert health["available"] is True
    assert health["loaded_sources"] >= 1


def test_refinement_analyze_empty_derived_dir(tmp_path: Path) -> None:
    candidates, warnings = analyze_refinement_candidates(tmp_path)
    assert len(candidates) == 0


def test_no_scripts_import_in_operational() -> None:
    import rig_relay.operational.analytics as ana
    import rig_relay.operational.refinement as ref

    for mod in [ana, ref]:
        src = mod.__file__
        if src:
            content = Path(src).read_text(encoding="utf-8")
            assert "from scripts." not in content

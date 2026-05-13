"""Tests for storage lifecycle: audit, compaction, GC."""

from __future__ import annotations

import json
import os
from pathlib import Path
import time

from rig_relay.evidence.storage_lifecycle import compute_storage_summary
from scripts.rig_relay_compact_artifacts import (
    DATASET_QUERIES,
    RAW_PREFIXES,
    _find_compactable_datasets,
    _is_raw_dataset,
)
from scripts.rig_relay_gc_artifacts import (
    DEFAULT_BUDGET as GC_BUDGET,
    RETENTION_RULES,
    _find_gc_candidates,
    _get_budget_key_value,
    _is_active_lease,
    _is_protected,
    _remove_empty_dirs,
)
from scripts.rig_relay_storage_audit import (
    DEFAULT_BUDGET,
    _count_jsonl_rows,
    _count_stale_leases,
    _file_count,
    _find_prune_candidates,
    _find_rollup_candidates,
    _largest_files,
    _size_mb,
    audit_storage,
)

# ── Fixtures ────────────────────────────────────────────────────────────


def _make_temp_build(tmp_path: Path) -> Path:
    """Create a minimal .build/rig-relay/ tree for testing."""
    root = tmp_path / ".build" / "rig-relay"
    (root / "coordination" / "leases" / "paths").mkdir(parents=True)
    (root / "coordination" / "artifacts").mkdir(parents=True)
    (root / "coordination" / "conflicts").mkdir(parents=True)
    (root / "coordination" / "sessions").mkdir(parents=True)
    (root / "coordination" / "tasks").mkdir(parents=True)
    (root / "derived").mkdir(parents=True)
    (root / "desktop").mkdir(parents=True)
    (root / "telemetry-bundles").mkdir(parents=True)
    (root / "drive-uploads").mkdir(parents=True)
    (root / "reports").mkdir(parents=True)
    (root / "cockpit").mkdir(parents=True)
    (root / "chatgpt-bundles").mkdir(parents=True)

    # Touch some test files
    (root / "coordination" / "events.jsonl").write_text(
        json.dumps({"event_name": "test"}), encoding="utf-8"
    )
    (root / "derived" / "test_dataset.jsonl").write_text(
        "\n".join(json.dumps({"id": i}) for i in range(10)), encoding="utf-8"
    )
    (root / "derived" / "rollup_manifest.json").write_text("{}", encoding="utf-8")
    (root / "desktop" / "projection.json").write_text("{}", encoding="utf-8")
    (root / "telemetry-bundles" / "test.zip").write_bytes(b"zip data")
    (root / "telemetry-bundles" / "manifest.json").write_text("{}", encoding="utf-8")
    (root / "drive-uploads" / "receipt.json").write_text("{}", encoding="utf-8")

    return root


def _make_old_file(path: Path, days_ago: int = 100) -> None:
    """Create a file with an old mtime."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("old data", encoding="utf-8")
    old_time = time.time() - (days_ago * 86400)
    os.utime(str(path), (old_time, old_time))


# ── Storage Audit Tests ────────────────────────────────────────────────


class TestSizeMB:
    def test_returns_zero_for_empty_dir(self, tmp_path: Path) -> None:
        d = tmp_path / "empty"
        d.mkdir()
        assert _size_mb(d) == 0.0

    def test_returns_positive_for_file(self, tmp_path: Path) -> None:
        f = tmp_path / "data.bin"
        f.write_bytes(b"x" * 1_048_576)
        assert _size_mb(f) > 0.9


class TestFileCount:
    def test_counts_files_in_directory(self, tmp_path: Path) -> None:
        d = tmp_path / "dir"
        d.mkdir()
        (d / "a.txt").write_text("a")
        (d / "b.txt").write_text("b")
        assert _file_count(d) == 2

    def test_returns_zero_for_empty_dir(self, tmp_path: Path) -> None:
        d = tmp_path / "empty"
        d.mkdir()
        assert _file_count(d) == 0


class TestLargestFiles:
    def test_returns_top_files(self, tmp_path: Path) -> None:
        d = tmp_path / "files"
        d.mkdir()
        (d / "small.txt").write_text("x" * 100)
        (d / "medium.txt").write_text("x" * 1000)
        (d / "large.txt").write_text("x" * 10000)
        top = _largest_files(d, n=2)
        assert len(top) <= 2
        assert top[0]["path"].endswith("large.txt")

    def test_returns_empty_for_missing_dir(self, tmp_path: Path) -> None:
        assert _largest_files(tmp_path / "nonexistent") == []


class TestCountStaleLeases:
    def test_counts_stale_files(self, tmp_path: Path) -> None:
        leases = tmp_path / "leases"
        leases.mkdir(parents=True)
        # Old lease
        _make_old_file(leases / "stale_lease.json", days_ago=10)
        assert _count_stale_leases(leases, stale_hours=24) == 1

    def test_returns_zero_for_missing_dir(self) -> None:
        assert _count_stale_leases(Path("/nonexistent/leases")) == 0


class TestFindRollupCandidates:
    def test_finds_jsonl_without_parquet(self, tmp_path: Path) -> None:
        derived = tmp_path / "derived"
        derived.mkdir()
        (derived / "dataset.jsonl").write_text("{}\n", encoding="utf-8")
        candidates = _find_rollup_candidates(derived)
        assert len(candidates) == 1
        assert not candidates[0]["parquet_exists"]

    def test_marks_existing_parquet(self, tmp_path: Path) -> None:
        derived = tmp_path / "derived"
        derived.mkdir()
        (derived / "dataset.jsonl").write_text("{}\n", encoding="utf-8")
        (derived / "dataset.parquet").write_bytes(b"parquet")
        candidates = _find_rollup_candidates(derived)
        assert len(candidates) == 1
        assert candidates[0]["parquet_exists"]


class TestFindPruneCandidates:
    def test_finds_old_files(self, tmp_path: Path) -> None:
        root = _make_temp_build(tmp_path)
        _make_old_file(root / "desktop" / "old_projection.json", days_ago=50)
        candidates = _find_prune_candidates(root, DEFAULT_BUDGET)
        assert len(candidates) >= 1
        assert any("old_projection" in c["path"] for c in candidates)

    def test_skips_protected_manifests(self, tmp_path: Path) -> None:
        root = _make_temp_build(tmp_path)
        _make_old_file(root / "derived" / "rollup_manifest.json", days_ago=50)
        candidates = _find_prune_candidates(root, DEFAULT_BUDGET)
        assert not any("rollup_manifest" in c["path"] for c in candidates)

    def test_skips_receipts(self, tmp_path: Path) -> None:
        root = _make_temp_build(tmp_path)
        _make_old_file(root / "drive-uploads" / "receipt_old.json", days_ago=50)
        candidates = _find_prune_candidates(root, DEFAULT_BUDGET)
        assert not any("receipt" in c["path"] for c in candidates)


class TestAuditStorage:
    def test_returns_expected_structure(self, tmp_path: Path) -> None:
        root = _make_temp_build(tmp_path)
        result = audit_storage(root=root, budget=DEFAULT_BUDGET)
        assert result["schema_version"] == "rig.relay.storage_audit.v1"
        assert "categories" in result
        assert "budget" in result
        assert "recommendations" in result
        assert isinstance(result["total_size_mb"], float)
        assert result["total_file_count"] > 0

    def test_status_is_ok_for_small_build(self, tmp_path: Path) -> None:
        root = _make_temp_build(tmp_path)
        result = audit_storage(root=root, budget=DEFAULT_BUDGET)
        assert result["budget"]["status"] == "ok"

    def test_fleet_blocked_when_over_budget(self, tmp_path: Path) -> None:
        root = _make_temp_build(tmp_path)
        tiny_budget = dict(DEFAULT_BUDGET)
        tiny_budget["refuse_fleet_over_mb"] = 0
        result = audit_storage(root=root, budget=tiny_budget)
        assert result["budget"]["status"] == "fleet_blocked"


# ── Compaction Tests ────────────────────────────────────────────────────


class TestIsRawDataset:
    def test_detects_raw_prefixes(self) -> None:
        assert _is_raw_dataset("raw_events")
        assert _is_raw_dataset("observability_20260513")

    def test_allows_derived_datasets(self) -> None:
        assert not _is_raw_dataset("cross_session_coordination_dataset")
        assert not _is_raw_dataset("tool_failure_patterns_dataset")


class TestFindCompactableDatasets:
    def test_finds_known_datasets(self, tmp_path: Path) -> None:
        derived = tmp_path / "derived"
        derived.mkdir()
        for name in DATASET_QUERIES:
            (derived / f"{name}.jsonl").write_text("{}\n", encoding="utf-8")
        datasets = _find_compactable_datasets(derived)
        assert len(datasets) == len(DATASET_QUERIES)

    def test_skips_unknown_datasets(self, tmp_path: Path) -> None:
        derived = tmp_path / "derived"
        derived.mkdir()
        (derived / "unknown_dataset.jsonl").write_text("{}\n", encoding="utf-8")
        datasets = _find_compactable_datasets(derived)
        assert len(datasets) == 0

    def test_skips_raw_datasets(self, tmp_path: Path) -> None:
        derived = tmp_path / "derived"
        derived.mkdir()
        for prefix in RAW_PREFIXES:
            (derived / f"{prefix}_data.jsonl").write_text("{}\n", encoding="utf-8")
        datasets = _find_compactable_datasets(derived)
        assert len(datasets) == 0

    def test_returns_empty_for_missing_dir(self, tmp_path: Path) -> None:
        assert _find_compactable_datasets(tmp_path / "nonexistent") == []


class TestDatasetQueries:
    """Verify all dataset queries have matching query definitions."""

    def test_all_queries_have_valid_format(self) -> None:
        for name, query in DATASET_QUERIES.items():
            assert "{source}" in query, (
                f"Query for {name} missing {{source}} placeholder"
            )
            assert query.strip().startswith("SELECT"), (
                f"Query for {name} must start with SELECT"
            )


class TestCountJsonlRows:
    def test_counts_lines(self, tmp_path: Path) -> None:
        f = tmp_path / "data.jsonl"
        f.write_text("\n".join(["{}", "{}", "{}"]), encoding="utf-8")
        assert _count_jsonl_rows(f) == 3

    def test_handles_empty_file(self, tmp_path: Path) -> None:
        f = tmp_path / "empty.jsonl"
        f.write_text("", encoding="utf-8")
        assert _count_jsonl_rows(f) == 0

    def test_handles_missing_file(self) -> None:
        assert _count_jsonl_rows(Path("/nonexistent/file.jsonl")) == 0


# ── GC Tests ────────────────────────────────────────────────────────────


class TestIsProtected:
    def test_detects_rollup_manifest(self) -> None:
        assert _is_protected(Path("rollup_manifest.json"))

    def test_detects_export_manifest(self) -> None:
        assert _is_protected(Path("export_manifest.json"))

    def test_detects_receipt(self) -> None:
        assert _is_protected(Path("upload_receipt.json"))

    def test_detects_convergence_report(self) -> None:
        assert _is_protected(Path("parent_convergence_report.json"))

    def test_allows_regular_files(self) -> None:
        assert not _is_protected(Path("events.jsonl"))
        assert not _is_protected(Path("dataset.jsonl"))
        assert not _is_protected(Path("projection.json"))


class TestIsActiveLease:
    def test_non_lease_file_is_not_active(self, tmp_path: Path) -> None:
        f = tmp_path / "data.json"
        f.write_text("{}")
        assert not _is_active_lease(f)

    def test_recent_lease_is_active(self, tmp_path: Path) -> None:
        f = tmp_path / "lease_active.json"
        f.write_text("{}")
        assert _is_active_lease(f, stale_hours=24)

    def test_old_lease_is_not_active(self, tmp_path: Path) -> None:
        f = tmp_path / "lease_stale.json"
        _make_old_file(f, days_ago=10)
        assert not _is_active_lease(f, stale_hours=24)


class TestGetBudgetKeyValue:
    def test_returns_budget_value(self) -> None:
        budget = {"derived_jsonl_days": 30}
        assert _get_budget_key_value(budget, "derived_jsonl_days") == 30

    def test_converts_stale_lease_hours(self) -> None:
        budget = {"stale_leases_hours": 48}
        assert _get_budget_key_value(budget, "stale_leases_hours") == 2

    def test_uses_default_for_missing_key(self) -> None:
        assert _get_budget_key_value({}, "nonexistent_key") == 30


class TestFindGCCandidates:
    def test_finds_stale_leases(self, tmp_path: Path) -> None:
        root = tmp_path / "build"
        leases = root / "coordination" / "leases" / "paths"
        leases.mkdir(parents=True)
        _make_old_file(leases / "stale_lease.json", days_ago=10)
        (leases / "active_lease.json").write_text("{}")
        candidates = _find_gc_candidates(root, GC_BUDGET)
        assert len(candidates) >= 1
        assert any("stale_lease" in c["path"] for c in candidates)
        # Active lease should not be a candidate
        assert not any("active_lease" in c["path"] for c in candidates)

    def test_skips_protected_files(self, tmp_path: Path) -> None:
        root = tmp_path / "build"
        derived = root / "derived"
        derived.mkdir(parents=True)
        _make_old_file(derived / "rollup_manifest.json", days_ago=50)
        candidates = _find_gc_candidates(root, GC_BUDGET)
        assert not any("rollup_manifest" in c["path"] for c in candidates)

    def test_returns_empty_for_clean_build(self, tmp_path: Path) -> None:
        root = tmp_path / "build"
        (root / "coordination" / "leases" / "paths").mkdir(parents=True)
        (root / "derived").mkdir()
        # All recent files
        (root / "derived" / "data.jsonl").write_text("{}\n", encoding="utf-8")
        candidates = _find_gc_candidates(root, GC_BUDGET)
        assert len(candidates) == 0


class TestRetentionRules:
    """Verify retention rules cover all expected categories."""

    def test_rules_have_valid_structure(self) -> None:
        for subdir, budget_key, allowed_exts, description in RETENTION_RULES:
            assert isinstance(subdir, str)
            assert isinstance(budget_key, str)
            assert isinstance(description, str)
            if allowed_exts is not None:
                assert isinstance(allowed_exts, list)


class TestRemoveEmptyDirs:
    def test_removes_empty_dirs(self, tmp_path: Path) -> None:
        d = tmp_path / "a" / "b" / "c"
        d.mkdir(parents=True)
        _remove_empty_dirs(tmp_path)
        # The empty nested dirs should be removed
        remaining = list(tmp_path.rglob("*"))
        assert len(remaining) == 0


# ── compute_storage_summary Tests ────────────────────────────────────────


class TestComputeStorageSummary:
    """Tests for the reusable storage lifecycle helper."""

    def test_returns_dict_with_keys(self, tmp_path: Path) -> None:
        root = _make_temp_build(tmp_path)
        result = compute_storage_summary(build_root=root)
        assert isinstance(result, dict)
        assert "budget_status" in result
        assert "total_size_bytes" in result
        assert "total_size_mb" in result
        assert "category_count" in result
        assert "largest_category" in result
        assert "rollup_candidate_count" in result
        assert "prune_candidate_count" in result
        assert "stale_lease_count" in result
        assert "recommendations" in result

    def test_returns_ok_for_small_build(self, tmp_path: Path) -> None:
        root = _make_temp_build(tmp_path)
        result = compute_storage_summary(build_root=root)
        assert result["budget_status"] == "ok"

    def test_handles_missing_root(self, tmp_path: Path) -> None:
        missing = tmp_path / "nonexistent"
        result = compute_storage_summary(build_root=missing)
        assert result["budget_status"] == "unknown"
        assert result["total_size_bytes"] == 0
        assert result["warnings"]

    def test_largest_category_returns_name(self, tmp_path: Path) -> None:
        root = _make_temp_build(tmp_path)
        result = compute_storage_summary(build_root=root)
        assert isinstance(result["largest_category"], str)

    def test_rollup_candidates_is_integer(self, tmp_path: Path) -> None:
        root = _make_temp_build(tmp_path)
        result = compute_storage_summary(build_root=root)
        assert isinstance(result["rollup_candidate_count"], int)
        assert result["rollup_candidate_count"] >= 0

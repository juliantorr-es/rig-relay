"""Tests for validation cache — caching, fingerprints, key computation, reuse policy."""

from __future__ import annotations

from pathlib import Path

import pytest

from rig_relay.evidence.validation_cache import (
    CACHE_POLICY_DISABLED,
    CACHE_POLICY_ENABLED,
    CACHE_POLICY_FORCE_RERUN,
    CACHE_STATUS_DISABLED,
    CACHE_STATUS_HIT,
    CACHE_STATUS_MISS_FAILED_REUSE_DISABLED,
    CACHE_STATUS_MISS_FORCE_RERUN,
    CACHE_STATUS_MISS_MISSING_RECORD,
    ValidationCacheRecord,
    ValidationCacheStore,
    compute_cache_key,
    compute_input_fingerprint,
    decide_cache_eligibility,
)


class TestValidationCacheStore:
    """File-backed cache store tests."""

    def test_empty_lookup_returns_miss(self, tmp_path: Path) -> None:
        store = ValidationCacheStore(tmp_path / "cache")
        result = store.lookup("sha256:nonexistent")
        assert result.cache_status == CACHE_STATUS_MISS_MISSING_RECORD
        assert result.cache_key == "sha256:nonexistent"

    def test_store_then_lookup_hit(self, tmp_path: Path) -> None:
        store = ValidationCacheStore(tmp_path / "cache")
        record = ValidationCacheRecord(
            cache_key="sha256:testkey",
            check_id="ruff_check",
            command_kind="ruff",
            command_fingerprint="fp123",
            input_fingerprint="input456",
            status="passed",
            stdout_bytes=100,
            stderr_bytes=0,
        )
        store.store(record)

        result = store.lookup("sha256:testkey")
        assert result.cache_status == CACHE_STATUS_HIT
        assert result.record is not None
        assert result.record.status == "passed"

    def test_store_then_lookup_second_identical_hit(self, tmp_path: Path) -> None:
        store = ValidationCacheStore(tmp_path / "cache")
        record = ValidationCacheRecord(
            cache_key="sha256:dupkey",
            check_id="pytest_run",
            command_kind="pytest",
            command_fingerprint="fp",
            input_fingerprint="inp",
            status="passed",
            stdout_bytes=50,
            stderr_bytes=0,
        )
        store.store(record)

        first = store.lookup("sha256:dupkey")
        second = store.lookup("sha256:dupkey")
        assert first.cache_status == CACHE_STATUS_HIT
        assert second.cache_status == CACHE_STATUS_HIT
        assert first.record is not None
        assert second.record is not None
        assert first.record.status == second.record.status

    def test_delete_removes_record(self, tmp_path: Path) -> None:
        store = ValidationCacheStore(tmp_path / "cache")
        record = ValidationCacheRecord(
            cache_key="sha256:delkey",
            check_id="c1",
            command_kind="ruff",
            command_fingerprint="f",
            input_fingerprint="i",
            status="passed",
            stdout_bytes=10,
            stderr_bytes=0,
        )
        store.store(record)
        assert store.lookup("sha256:delkey").cache_status == CACHE_STATUS_HIT

        store.delete("sha256:delkey")
        result = store.lookup("sha256:delkey")
        assert result.cache_status == CACHE_STATUS_MISS_MISSING_RECORD

    def test_clear_all_removes_all(self, tmp_path: Path) -> None:
        store = ValidationCacheStore(tmp_path / "cache")
        for i in range(3):
            record = ValidationCacheRecord(
                cache_key=f"sha256:key{i}",
                check_id=f"c{i}",
                command_kind="pytest",
                command_fingerprint=f"fp{i}",
                input_fingerprint=f"inp{i}",
                status="passed",
                stdout_bytes=10,
                stderr_bytes=0,
            )
            store.store(record)

        assert store.clear_all() == 3
        for i in range(3):
            r = store.lookup(f"sha256:key{i}")
            assert r.cache_status == CACHE_STATUS_MISS_MISSING_RECORD

    def test_corrupt_file_returns_miss(self, tmp_path: Path) -> None:
        store = ValidationCacheStore(tmp_path / "cache")
        record = ValidationCacheRecord(
            cache_key="sha256:corrupt",
            check_id="c1",
            command_kind="pytest",
            command_fingerprint="f",
            input_fingerprint="i",
            status="passed",
            stdout_bytes=10,
            stderr_bytes=0,
        )
        store.store(record)

        # Corrupt the file
        path = store._record_path("sha256:corrupt")
        path.write_text("{bad json}", encoding="utf-8")

        result = store.lookup("sha256:corrupt")
        assert result.cache_status == CACHE_STATUS_MISS_MISSING_RECORD
        assert result.error is not None
        assert "corrupt" in result.error

    def test_different_cache_root_isolated(self, tmp_path: Path) -> None:
        root1 = tmp_path / "cache1"
        root2 = tmp_path / "cache2"
        store1 = ValidationCacheStore(root1)
        store2 = ValidationCacheStore(root2)

        record = ValidationCacheRecord(
            cache_key="sha256:iso",
            check_id="c1",
            command_kind="pytest",
            command_fingerprint="f",
            input_fingerprint="i",
            status="passed",
            stdout_bytes=10,
            stderr_bytes=0,
        )
        store1.store(record)

        result1 = store1.lookup("sha256:iso")
        result2 = store2.lookup("sha256:iso")
        assert result1.cache_status == CACHE_STATUS_HIT
        assert result2.cache_status == CACHE_STATUS_MISS_MISSING_RECORD


class TestComputeInputFingerprint:
    def test_basic_fingerprint_is_deterministic(self, tmp_path: Path) -> None:
        fp1, _files1 = compute_input_fingerprint(str(tmp_path), "cmd_fp", "pytest")
        fp2, _files2 = compute_input_fingerprint(str(tmp_path), "cmd_fp", "pytest")
        assert fp1 == fp2

    def test_different_command_fp_differs(self, tmp_path: Path) -> None:
        fp1, _ = compute_input_fingerprint(str(tmp_path), "fp_a", "pytest")
        fp2, _ = compute_input_fingerprint(str(tmp_path), "fp_b", "pytest")
        assert fp1 != fp2

    def test_pyproject_toml_change_invalidates(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text("[tool]\nkey=1", encoding="utf-8")
        fp1, files1 = compute_input_fingerprint(str(tmp_path), "cmd_fp", "pytest")
        assert "pyproject.toml" in files1

        (tmp_path / "pyproject.toml").write_text("[tool]\nkey=2", encoding="utf-8")
        fp2, _ = compute_input_fingerprint(str(tmp_path), "cmd_fp", "pytest")
        assert fp1 != fp2

    def test_uv_lock_change_invalidates(self, tmp_path: Path) -> None:
        (tmp_path / "uv.lock").write_text("lock v1", encoding="utf-8")
        fp1, _ = compute_input_fingerprint(str(tmp_path), "cmd_fp", "pytest")

        (tmp_path / "uv.lock").write_text("lock v2", encoding="utf-8")
        fp2, _ = compute_input_fingerprint(str(tmp_path), "cmd_fp", "pytest")
        assert fp1 != fp2

    def test_schema_kind_fingerprints_schemas(self, tmp_path: Path) -> None:
        schema_dir = tmp_path / "docs" / "schemas"
        schema_dir.mkdir(parents=True)
        (schema_dir / "test.v1.schema.json").write_text(
            '{"type": "object"}', encoding="utf-8"
        )

        fp, files = compute_input_fingerprint(str(tmp_path), "schema_fp", "schema")
        # Should contain schema file fingerprints
        schema_files = [k for k in files if "docs/schemas" in k]
        assert len(schema_files) >= 1

    def test_schema_kind_ignores_when_no_schemas(self, tmp_path: Path) -> None:
        fp, files = compute_input_fingerprint(str(tmp_path), "schema_fp", "schema")
        schema_files = [k for k in files if "docs/schemas" in k]
        assert len(schema_files) == 0


class TestComputeCacheKey:
    def test_deterministic(self) -> None:
        k1 = compute_cache_key("c1", "pytest", "fp", "inp", "/tmp", "/repo")
        k2 = compute_cache_key("c1", "pytest", "fp", "inp", "/tmp", "/repo")
        assert k1 == k2

    def test_different_check_id_differs(self) -> None:
        k1 = compute_cache_key("c1", "pytest", "fp", "inp", "/tmp", "/repo")
        k2 = compute_cache_key("c2", "pytest", "fp", "inp", "/tmp", "/repo")
        assert k1 != k2

    def test_different_command_kind_differs(self) -> None:
        k1 = compute_cache_key("c1", "pytest", "fp", "inp", "/tmp", "/repo")
        k2 = compute_cache_key("c1", "ruff", "fp", "inp", "/tmp", "/repo")
        assert k1 != k2

    def test_different_cwd_differs(self) -> None:
        k1 = compute_cache_key("c1", "pytest", "fp", "inp", "/a", "/repo")
        k2 = compute_cache_key("c1", "pytest", "fp", "inp", "/b", "/repo")
        assert k1 != k2

    def test_different_input_fp_differs(self) -> None:
        k1 = compute_cache_key("c1", "pytest", "fp", "inp_a", "/tmp", "/repo")
        k2 = compute_cache_key("c1", "pytest", "fp", "inp_b", "/tmp", "/repo")
        assert k1 != k2

    def test_different_repo_root_differs(self) -> None:
        k1 = compute_cache_key("c1", "pytest", "fp", "inp", "/tmp", "/repo_a")
        k2 = compute_cache_key("c1", "pytest", "fp", "inp", "/tmp", "/repo_b")
        assert k1 != k2

    def test_starts_with_sha256(self) -> None:
        k = compute_cache_key("c1", "pytest", "fp", "inp", "/tmp", "/repo")
        assert k.startswith("sha256:")
        assert len(k) == 64 + 7  # sha256: + 64 hex chars


class TestDecideCacheEligibility:
    def test_disabled_policy_returns_disabled(self, tmp_path: Path) -> None:
        store = ValidationCacheStore(tmp_path / "c")
        record = ValidationCacheRecord(
            cache_key="sha256:k",
            check_id="c1",
            command_kind="pytest",
            command_fingerprint="f",
            input_fingerprint="i",
            status="passed",
            stdout_bytes=10,
            stderr_bytes=0,
        )
        store.store(record)
        lookup = store.lookup("sha256:k")
        status, reason = decide_cache_eligibility(CACHE_POLICY_DISABLED, lookup, False)
        assert status == CACHE_STATUS_DISABLED
        assert reason is None

    def test_force_rerun_bypasses_cache(self, tmp_path: Path) -> None:
        store = ValidationCacheStore(tmp_path / "c")
        record = ValidationCacheRecord(
            cache_key="sha256:k",
            check_id="c1",
            command_kind="pytest",
            command_fingerprint="f",
            input_fingerprint="i",
            status="passed",
            stdout_bytes=10,
            stderr_bytes=0,
        )
        store.store(record)
        lookup = store.lookup("sha256:k")
        status, reason = decide_cache_eligibility(
            CACHE_POLICY_FORCE_RERUN, lookup, False
        )
        assert status == CACHE_STATUS_MISS_FORCE_RERUN

    def test_passed_result_reused_by_default(self, tmp_path: Path) -> None:
        store = ValidationCacheStore(tmp_path / "c")
        record = ValidationCacheRecord(
            cache_key="sha256:k",
            check_id="c1",
            command_kind="pytest",
            command_fingerprint="f",
            input_fingerprint="i",
            status="passed",
            stdout_bytes=10,
            stderr_bytes=0,
        )
        store.store(record)
        lookup = store.lookup("sha256:k")
        status, _reason = decide_cache_eligibility(CACHE_POLICY_ENABLED, lookup, False)
        assert status == CACHE_STATUS_HIT

    def test_failed_result_not_reused_by_default(self, tmp_path: Path) -> None:
        store = ValidationCacheStore(tmp_path / "c")
        record = ValidationCacheRecord(
            cache_key="sha256:k",
            check_id="c1",
            command_kind="pytest",
            command_fingerprint="f",
            input_fingerprint="i",
            status="failed",
            stdout_bytes=10,
            stderr_bytes=0,
        )
        store.store(record)
        lookup = store.lookup("sha256:k")
        status, _reason = decide_cache_eligibility(CACHE_POLICY_ENABLED, lookup, False)
        assert status == CACHE_STATUS_MISS_FAILED_REUSE_DISABLED

    def test_failed_result_reused_when_allowed(self, tmp_path: Path) -> None:
        store = ValidationCacheStore(tmp_path / "c")
        record = ValidationCacheRecord(
            cache_key="sha256:k",
            check_id="c1",
            command_kind="pytest",
            command_fingerprint="f",
            input_fingerprint="i",
            status="failed",
            stdout_bytes=10,
            stderr_bytes=0,
        )
        store.store(record)
        lookup = store.lookup("sha256:k")
        status, _reason = decide_cache_eligibility(CACHE_POLICY_ENABLED, lookup, True)
        assert status == CACHE_STATUS_HIT

    def test_missing_record_returns_miss(self) -> None:
        from rig_relay.evidence.validation_cache import ValidationCacheLookupResult

        lookup = ValidationCacheLookupResult(
            cache_status=CACHE_STATUS_MISS_MISSING_RECORD,
            cache_key="sha256:nonexistent",
        )
        status, _ = decide_cache_eligibility(CACHE_POLICY_ENABLED, lookup, False)
        assert status == CACHE_STATUS_MISS_MISSING_RECORD

    def test_none_record_returns_miss(self) -> None:
        from rig_relay.evidence.validation_cache import ValidationCacheLookupResult

        lookup = ValidationCacheLookupResult(
            cache_status=CACHE_STATUS_HIT, cache_key="sha256:k", record=None
        )
        status, _ = decide_cache_eligibility(CACHE_POLICY_ENABLED, lookup, False)
        assert status == CACHE_STATUS_MISS_MISSING_RECORD


class TestValidationCacheRecord:
    def test_record_sha256_is_deterministic(self) -> None:
        r1 = ValidationCacheRecord(
            cache_key="sha256:k",
            check_id="c1",
            command_kind="pytest",
            command_fingerprint="f",
            input_fingerprint="i",
            status="passed",
            stdout_bytes=10,
            stderr_bytes=0,
        )
        r2 = ValidationCacheRecord(
            cache_key="sha256:k",
            check_id="c1",
            command_kind="pytest",
            command_fingerprint="f",
            input_fingerprint="i",
            status="passed",
            stdout_bytes=10,
            stderr_bytes=0,
        )
        assert r1.record_sha256() == r2.record_sha256()

    def test_model_rejects_extra_fields(self) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            ValidationCacheRecord.model_validate({
                "cache_key": "k",
                "check_id": "c1",
                "command_kind": "pytest",
                "command_fingerprint": "f",
                "input_fingerprint": "i",
                "status": "passed",
                "stdout_bytes": 10,
                "stderr_bytes": 0,
                "raw_output": "nope",
            })

    def test_is_passed_returns_true(self) -> None:
        r = ValidationCacheRecord(
            cache_key="k",
            check_id="c1",
            command_kind="pytest",
            command_fingerprint="f",
            input_fingerprint="i",
            status="passed",
            stdout_bytes=10,
            stderr_bytes=0,
        )
        assert r.is_passed()

    def test_is_passed_returns_false_for_failed(self) -> None:
        r = ValidationCacheRecord(
            cache_key="k",
            check_id="c1",
            command_kind="pytest",
            command_fingerprint="f",
            input_fingerprint="i",
            status="failed",
            stdout_bytes=10,
            stderr_bytes=0,
        )
        assert not r.is_passed()

    def test_no_forbidden_raw_fields(self) -> None:
        r = ValidationCacheRecord(
            cache_key="k",
            check_id="c1",
            command_kind="pytest",
            command_fingerprint="f",
            input_fingerprint="i",
            status="passed",
            stdout_bytes=10,
            stderr_bytes=0,
        )
        dumped = r.model_dump(mode="json")
        forbidden = (
            "content",
            "diff",
            "patch",
            "prompt",
            "secret",
            "argv",
            "raw_output",
            "snippet",
        )
        for key in dumped:
            for f in forbidden:
                assert f not in key.lower()

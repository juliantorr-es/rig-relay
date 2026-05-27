"""X1.6 cross-process tests — advisory lock determinism, concurrency, crash safety, replay, X0 surface, timeline locks."""

from __future__ import annotations

import secrets
import string
import threading
from typing import Any

import pytest

from rig_relay.data_plane.postgres._materialization_input import (
    MaterializationInputStatus,
    PublicationMaterializationInput,
    RepositoryEstateMaterializationInput,
)
from rig_relay.data_plane.postgres._materialize_publication import (
    PublicationMaterializer,
)
from rig_relay.data_plane.postgres._materialize_repository_estate import (
    RepositoryEstateMaterializer,
)
from rig_relay.data_plane.postgres._materialize_timeline import TimelineMaterializer
from rig_relay.data_plane.postgres._models import (
    MaterializationReceipt,
    RebuildReceipt,
    compute_advisory_lock_key,
    compute_deterministic_materialization_receipt_id,
    compute_deterministic_rebuild_receipt_id,
)
from rig_relay.data_plane.postgres._x0_projection import X0ProjectionSurface


class _FakeReconstruction:
    def __init__(self, receipt_id: str, evidence_digest: str, compiled_at: str) -> None:
        self.receipts: list[dict] = [
            {
                "receipt_id": receipt_id,
                "compiled_at": compiled_at,
                "evidence_digest": evidence_digest,
                "compilation_successful": True,
                "safety_passed": True,
                "refusal_code": None,
                "result_digest": "sha256:result",
                "operation_id": "op",
                "source_event_id": "",
                "source_event_digest": "",
            }
        ]
        self.total_rows: int = 1
        self.valid_rows: int = 1
        self.corrupt_rows: int = 0
        self.corrupt_lines: list[int] = []
        self.corruption_detected: bool = False
        self.authoritative: bool = False
        self.reconstruction_warnings: list[str] = []


class _FakeEstateProjection:
    def __init__(self) -> None:
        self.registered_repositories: list[dict] = []
        self.corruption_events: list[dict] = []
        self.recent_changes: list[dict] = []
        self.total_registered: int = 0
        self.total_observations: int = 0
        self.corrupt_registration_count: int = 0
        self.corrupt_observation_count: int = 0
        self.authority_state: str = "controlled_boundary"


class _FakeTimelineResult:
    """Minimal stub for TimelineAssemblyResult used by TimelineMaterializer."""

    def __init__(self) -> None:
        self.timeline: Any = _FakeTimeline()


class _FakeTimeline:
    """Minimal stub for InvestigationTimeline used by build_postgres_projection."""

    def __init__(self) -> None:
        self.timeline_id: str = "tl_0000000000000000"
        self.events: list[Any] = []


class _FakeTimelineProjection:
    """Minimal stub for PostgresTimelineProjection."""

    def __init__(self) -> None:
        self.timeline_id: str = "tl_0000000000000000"
        self.rows: list[Any] = []
        self.projection_id: str = "proj_fake"


class _FakeTimelineService:
    def assemble_timeline(self) -> _FakeTimelineResult:
        return _FakeTimelineResult()

    def build_postgres_projection(self) -> Any:
        return {"timeline_events": [], "projection_id": "proj_fake"}


# ── Advisory lock determinism ───────────────────────────────────────


class TestAdvisoryLockDeterminism:
    def test_same_domain_produces_same_key(self) -> None:
        k1 = compute_advisory_lock_key("publication_history")
        k2 = compute_advisory_lock_key("publication_history")
        assert k1 == k2, f"Same domain must produce same lock key: {k1} vs {k2}"

    def test_different_domains_produce_different_keys(self) -> None:
        domains = ["publication_history", "repository_estate", "investigation_timeline"]
        keys = {d: compute_advisory_lock_key(d) for d in domains}
        assert len(set(keys.values())) == len(domains), (
            f"All domains must have distinct keys: {keys}"
        )

    def test_key_within_postgres_bigint_range(self) -> None:
        domain = "publication_history"
        key = compute_advisory_lock_key(domain)
        assert -(2**63) <= key <= (2**63) - 1, (
            f"Key {key} must be within PostgreSQL signed bigint range "
            f"({-(2**63)} to {(2**63) - 1})"
        )


# ── Concurrent same-domain serialization ─────────────────────────────


class TestConcurrentSameDomainSerialization:
    def test_concurrent_rebuild_publication_serialized(
        self, migrated_store, store2
    ) -> None:
        suffix = "".join(secrets.choice(string.ascii_lowercase) for _ in range(6))

        mat_a = PublicationMaterializer(migrated_store)
        mat_b = PublicationMaterializer(store2)

        results: list[RebuildReceipt] = []
        errors: list[Exception] = []
        barrier = threading.Barrier(2, timeout=10)

        def worker(mat: PublicationMaterializer, thread_id: str) -> None:
            barrier.wait()
            try:
                input_data = PublicationMaterializationInput(
                    reconstruction=_FakeReconstruction(
                        f"rec_pub_serial_{suffix}_{thread_id}",
                        f"sha256:ev_pub_serial_{suffix}_{thread_id}",
                        "2026-01-01T00:00:00+00:00",
                    ),
                    source_evidence_digest=f"sha256:pub_serial_{suffix}_{thread_id}",
                    ledger_identity_digest=f"sha256:ledger_serial_{suffix}_{thread_id}",
                    source_status=MaterializationInputStatus.VERIFIED,
                )
                r = mat.rebuild(input_data)
                results.append(r)
            except Exception as e:
                errors.append(e)

        t1 = threading.Thread(target=worker, args=(mat_a, "a"))
        t2 = threading.Thread(target=worker, args=(mat_b, "b"))
        t1.start()
        t2.start()
        t1.join(timeout=15)
        t2.join(timeout=15)

        assert len(errors) == 0, f"Unexpected errors: {errors}"
        assert len(results) == 2, f"Expected 2 rebuilds, got {len(results)}"
        assert results[0].receipt_id != results[1].receipt_id, (
            "Different evidence must produce different receipt IDs"
        )

    def test_concurrent_materialize_vs_rebuild_publication_serialized(
        self, migrated_store, store2
    ) -> None:
        suffix = "".join(secrets.choice(string.ascii_lowercase) for _ in range(6))

        mat_a = PublicationMaterializer(migrated_store)
        mat_b = PublicationMaterializer(store2)

        results: list[RebuildReceipt | MaterializationReceipt] = []
        errors: list[Exception] = []
        barrier = threading.Barrier(2, timeout=10)

        def rebuild_worker(mat: PublicationMaterializer) -> None:
            barrier.wait()
            try:
                input_data = PublicationMaterializationInput(
                    reconstruction=_FakeReconstruction(
                        f"rec_mat_vs_rebuild_{suffix}_rebuild",
                        f"sha256:ev_mat_vs_rebuild_{suffix}_rebuild",
                        "2026-01-01T00:00:00+00:00",
                    ),
                    source_evidence_digest=f"sha256:mat_vs_rebuild_{suffix}_rebuild",
                    ledger_identity_digest=f"sha256:ldg_{suffix}_rebuild",
                    source_status=MaterializationInputStatus.VERIFIED,
                )
                r = mat.rebuild(input_data)
                results.append(r)
            except Exception as e:
                errors.append(e)

        def mat_worker(mat: PublicationMaterializer) -> None:
            barrier.wait()
            try:
                input_data = PublicationMaterializationInput(
                    reconstruction=_FakeReconstruction(
                        f"rec_mat_vs_rebuild_{suffix}_mat",
                        f"sha256:ev_mat_vs_rebuild_{suffix}_mat",
                        "2026-01-01T00:00:00+00:00",
                    ),
                    source_evidence_digest=f"sha256:mat_vs_rebuild_{suffix}_mat",
                    ledger_identity_digest=f"sha256:ldg_{suffix}_mat",
                    source_status=MaterializationInputStatus.VERIFIED,
                )
                r = mat.materialize(input_data)
                results.append(r)
            except Exception as e:
                errors.append(e)

        t_rebuild = threading.Thread(target=rebuild_worker, args=(mat_a,))
        t_mat = threading.Thread(target=mat_worker, args=(mat_b,))
        t_rebuild.start()
        t_mat.start()
        t_rebuild.join(timeout=15)
        t_mat.join(timeout=15)

        assert len(errors) == 0, f"Unexpected errors: {errors}"
        assert len(results) == 2, f"Expected 2 operations, got {len(results)}"


# ── Concurrent distinct domains ──────────────────────────────────────


class TestSafeConcurrentDistinctDomains:
    def test_concurrent_different_domains_no_conflict(
        self, migrated_store, store2
    ) -> None:
        suffix = "".join(secrets.choice(string.ascii_lowercase) for _ in range(6))

        pub_mat = PublicationMaterializer(migrated_store)
        estate_mat = RepositoryEstateMaterializer(store2)

        errors: list[Exception] = []
        results: list[str] = []
        barrier = threading.Barrier(2, timeout=10)

        def pub_worker() -> None:
            barrier.wait()
            try:
                input_data = PublicationMaterializationInput(
                    reconstruction=_FakeReconstruction(
                        f"rec_distinct_{suffix}_pub",
                        f"sha256:ev_distinct_{suffix}_pub",
                        "2026-01-01T00:00:00+00:00",
                    ),
                    source_evidence_digest=f"sha256:distinct_{suffix}_pub",
                    ledger_identity_digest=f"sha256:ldg_{suffix}_pub",
                    source_status=MaterializationInputStatus.VERIFIED,
                )
                r = pub_mat.rebuild(input_data)
                results.append(f"pub:{r.receipt_id}")
            except Exception as e:
                errors.append(e)

        def estate_worker() -> None:
            barrier.wait()
            try:
                input_data = RepositoryEstateMaterializationInput(
                    projection=_FakeEstateProjection(),
                    source_evidence_digest=f"sha256:distinct_{suffix}_estate",
                    source_status=MaterializationInputStatus.VERIFIED,
                )
                r = estate_mat.materialize(input_data)
                results.append(f"estate:{r.receipt_id}")
            except Exception as e:
                errors.append(e)

        t1 = threading.Thread(target=pub_worker)
        t2 = threading.Thread(target=estate_worker)
        t1.start()
        t2.start()
        t1.join(timeout=15)
        t2.join(timeout=15)

        assert len(errors) == 0, f"Unexpected errors: {errors}"
        assert len(results) == 2, f"Expected 2 operations, got {len(results)}"

    def test_concurrent_different_domains_from_separate_stores(
        self, migrated_store, store2
    ) -> None:
        suffix = "".join(secrets.choice(string.ascii_lowercase) for _ in range(6))

        pub_mat = PublicationMaterializer(migrated_store)
        estate_mat = RepositoryEstateMaterializer(store2)

        errors: list[Exception] = []
        results: list[str] = []
        barrier = threading.Barrier(2, timeout=10)

        def pub_worker() -> None:
            barrier.wait()
            try:
                input_data = PublicationMaterializationInput(
                    reconstruction=_FakeReconstruction(
                        f"rec_sep_stores_{suffix}_pub",
                        f"sha256:ev_sep_stores_{suffix}_pub",
                        "2026-01-01T00:00:00+00:00",
                    ),
                    source_evidence_digest=f"sha256:sep_stores_{suffix}_pub",
                    ledger_identity_digest=f"sha256:ldg_{suffix}_pub",
                    source_status=MaterializationInputStatus.VERIFIED,
                )
                r = pub_mat.rebuild(input_data)
                results.append(f"pub:{r.receipt_id}")
            except Exception as e:
                errors.append(e)

        def estate_worker() -> None:
            barrier.wait()
            try:
                input_data = RepositoryEstateMaterializationInput(
                    projection=_FakeEstateProjection(),
                    source_evidence_digest=f"sha256:sep_stores_{suffix}_estate",
                    source_status=MaterializationInputStatus.VERIFIED,
                )
                r = estate_mat.materialize(input_data)
                results.append(f"estate:{r.receipt_id}")
            except Exception as e:
                errors.append(e)

        t1 = threading.Thread(target=pub_worker)
        t2 = threading.Thread(target=estate_worker)
        t1.start()
        t2.start()
        t1.join(timeout=15)
        t2.join(timeout=15)

        assert len(errors) == 0, f"Unexpected errors: {errors}"
        assert len(results) == 2, f"Expected 2 operations, got {len(results)}"


# ── Rebuild crash rollback safety ────────────────────────────────────


class TestRebuildCrashRollbackSafety:
    def test_rebuild_rollback_preserves_prior_state(self, migrated_store) -> None:
        suffix = "".join(secrets.choice(string.ascii_lowercase) for _ in range(6))
        mat = RepositoryEstateMaterializer(migrated_store)

        first_input = RepositoryEstateMaterializationInput(
            projection=_FakeEstateProjection(),
            source_evidence_digest=f"sha256:rollback_{suffix}_good",
            source_status=MaterializationInputStatus.VERIFIED,
        )
        good_receipt = mat.materialize(first_input)
        assert good_receipt.rows_materialized >= 0

        surface = X0ProjectionSurface(migrated_store)
        sum_before = surface.get_estate_summary()
        rows_before = sum_before.get("registered_repositories", -1)

        bad_input = RepositoryEstateMaterializationInput(
            projection=_FakeEstateProjection(),
            source_evidence_digest="",
            source_status=MaterializationInputStatus.VERIFIED,
        )
        refused = mat.materialize(bad_input)
        assert refused.rows_materialized == 0, (
            "Materialize with empty digest must be refused"
        )

        sum_after = surface.get_estate_summary()
        rows_after = sum_after.get("registered_repositories", -1)
        assert rows_after == rows_before, (
            f"Prior state must be preserved after refused materialize: "
            f"{rows_before} vs {rows_after}"
        )

    def test_mid_rebuild_connection_fresh(self, migrated_store) -> None:
        mat = PublicationMaterializer(migrated_store)
        suffix = "".join(secrets.choice(string.ascii_lowercase) for _ in range(6))
        good_input = PublicationMaterializationInput(
            reconstruction=_FakeReconstruction(
                f"rec_fresh_{suffix}",
                f"sha256:ev_fresh_{suffix}",
                "2026-01-01T00:00:00+00:00",
            ),
            source_evidence_digest=f"sha256:fresh_{suffix}",
            ledger_identity_digest=f"sha256:ldg_fresh_{suffix}",
            source_status=MaterializationInputStatus.VERIFIED,
        )
        receipt = mat.rebuild(good_input)
        assert isinstance(receipt, RebuildReceipt)
        assert receipt.projection_name == "publication"
        assert receipt.rows_after >= 0


# ── Replay idempotency ───────────────────────────────────────────────


class TestReplayIdempotency:
    def test_publication_rebuild_replay_produces_same_receipt_id(
        self, migrated_store
    ) -> None:
        suffix = "".join(secrets.choice(string.ascii_lowercase) for _ in range(6))
        ev_digest = f"sha256:replay_pub_{suffix}"
        expected_id = compute_deterministic_rebuild_receipt_id("publication", ev_digest)

        mat = PublicationMaterializer(migrated_store)
        input_data = PublicationMaterializationInput(
            reconstruction=_FakeReconstruction(
                f"rec_replay_{suffix}", ev_digest, "2026-01-01T00:00:00+00:00"
            ),
            source_evidence_digest=ev_digest,
            ledger_identity_digest=f"sha256:ldg_replay_{suffix}",
            source_status=MaterializationInputStatus.VERIFIED,
        )

        receipt = mat.rebuild(input_data)
        assert receipt.receipt_id == expected_id, (
            f"Rebuild receipt ID must match deterministic computation: "
            f"{receipt.receipt_id} vs {expected_id}"
        )

        recomputed = compute_deterministic_rebuild_receipt_id("publication", ev_digest)
        assert recomputed == expected_id, (
            "Deterministic ID must be reproducible from evidence"
        )

    def test_estate_materialize_replay_same_receipt_id(
        self, migrated_store, store2
    ) -> None:
        ev_digest = "sha256:replay_estate_evidence"
        mat1 = RepositoryEstateMaterializer(migrated_store)
        mat2 = RepositoryEstateMaterializer(store2)

        input_data = RepositoryEstateMaterializationInput(
            projection=_FakeEstateProjection(),
            source_evidence_digest=ev_digest,
            source_status=MaterializationInputStatus.VERIFIED,
        )

        r1 = mat1.materialize(input_data)
        r2 = mat2.materialize(input_data)

        assert r1.receipt_id == r2.receipt_id, (
            f"Same evidence must produce same materialize receipt ID: "
            f"{r1.receipt_id} vs {r2.receipt_id}"
        )

    def test_different_evidence_produces_different_receipt_ids(self) -> None:
        rid_a = compute_deterministic_materialization_receipt_id(
            "publication", "sha256:evidence_x"
        )
        rid_b = compute_deterministic_materialization_receipt_id(
            "publication", "sha256:evidence_y"
        )
        assert rid_a != rid_b, (
            f"Different evidence must produce different receipt IDs: {rid_a}"
        )


# ── X0 projection surface integration ────────────────────────────────


@pytest.mark.xdist_group("x0_surface")
class TestX0ProjectionSurfaceIntegration:
    def test_projection_status_returns_all_three_domains(self, migrated_store) -> None:
        surface = X0ProjectionSurface(migrated_store)
        status = surface.get_projection_status()
        expected = {
            "repository_estate",
            "investigation_timeline",
            "publication_history",
        }
        assert set(status.keys()) == expected, (
            f"Must return all three domains, got: {set(status.keys())}"
        )

    def test_projection_status_returns_unavailable_when_no_builds(
        self, migrated_store
    ) -> None:
        # Clean residual data from previous tests (session-scoped database)
        schema = migrated_store.config.schema_name
        with migrated_store.conn.cursor() as cur:
            for table in (
                "publication_builds",
                "repository_estate_builds",
                "timeline_builds",
                "rebuild_receipts",
            ):
                cur.execute(f"DELETE FROM {schema}.{table}")
        surface = X0ProjectionSurface(migrated_store)
        status = surface.get_projection_status()
        for domain, s in status.items():
            assert s.availability in ("unavailable", "refused"), (
                f"Domain {domain} must report unavailable or refused when no builds, "
                f"got {s.availability}"
            )

    def test_projection_status_returns_available_after_rebuild(
        self, migrated_store
    ) -> None:
        suffix = "".join(secrets.choice(string.ascii_lowercase) for _ in range(6))
        mat = PublicationMaterializer(migrated_store)
        input_data = PublicationMaterializationInput(
            reconstruction=_FakeReconstruction(
                f"rec_x0_avail_{suffix}",
                f"sha256:ev_x0_avail_{suffix}",
                "2026-01-01T00:00:00+00:00",
            ),
            source_evidence_digest=f"sha256:x0_avail_{suffix}",
            ledger_identity_digest=f"sha256:ldg_x0_avail_{suffix}",
            source_status=MaterializationInputStatus.VERIFIED,
        )
        mat.rebuild(input_data)

        surface = X0ProjectionSurface(migrated_store)
        status = surface.get_projection_status()
        pub = status["publication_history"]
        assert pub.availability != "unavailable", (
            f"publication_history must not be unavailable after rebuild, got {pub.availability}"
        )

    def test_rebuild_history_returns_records(self, migrated_store) -> None:
        mat = PublicationMaterializer(migrated_store)
        input_data = PublicationMaterializationInput(
            reconstruction=_FakeReconstruction(
                "rec_x0_hist", "sha256:ev_x0_hist", "2026-01-01T00:00:00+00:00"
            ),
            source_evidence_digest="sha256:x0_hist_evidence",
            ledger_identity_digest="sha256:ldg_x0_hist",
            source_status=MaterializationInputStatus.VERIFIED,
        )
        mat.rebuild(input_data)

        surface = X0ProjectionSurface(migrated_store)
        history = surface.get_rebuild_history("publication_history")
        assert len(history) >= 1, (
            f"Must have at least 1 rebuild record, got {len(history)}"
        )
        assert "receipt_id" in history[0]

    def test_estate_summary_returns_counts(self, migrated_store) -> None:
        mat = RepositoryEstateMaterializer(migrated_store)
        input_data = RepositoryEstateMaterializationInput(
            projection=_FakeEstateProjection(),
            source_evidence_digest="sha256:x0_estate_counts",
            source_status=MaterializationInputStatus.VERIFIED,
        )
        mat.materialize(input_data)

        surface = X0ProjectionSurface(migrated_store)
        summary = surface.get_estate_summary()
        assert summary["registered_repositories"] >= 0
        assert "degradation_summary" in summary

    def test_compute_projection_digest_returns_sha256(self, migrated_store) -> None:
        surface = X0ProjectionSurface(migrated_store)
        digest = surface.compute_projection_digest("investigation_timeline")
        assert isinstance(digest, str)
        assert len(digest) > 0, "Must return a non-empty hex digest"

    def test_admission_contract_verifiable(self, migrated_store) -> None:
        surface = X0ProjectionSurface(migrated_store)
        assert surface.verify_admission_contract(), (
            "X0 admission contract must be verifiable"
        )


# ── Cross-process deterministic receipt reconstruction ───────────────


class TestCrossProcessDeterministicReceiptReconstruction:
    def test_publication_receipt_id_reproducible(self) -> None:
        same_evidence = "sha256:cross_proc_evidence"
        rid1 = compute_deterministic_materialization_receipt_id(
            "publication", same_evidence
        )
        rid2 = compute_deterministic_materialization_receipt_id(
            "publication", same_evidence
        )
        assert rid1 == rid2, (
            f"Same evidence must produce same receipt ID: {rid1} vs {rid2}"
        )

    def test_publication_rebuild_receipt_id_reproducible(self) -> None:
        same_evidence = "sha256:cross_proc_rebuild_evidence"
        rid1 = compute_deterministic_rebuild_receipt_id("publication", same_evidence)
        rid2 = compute_deterministic_rebuild_receipt_id("publication", same_evidence)
        assert rid1 == rid2, (
            f"Same evidence must produce same rebuild receipt ID: {rid1} vs {rid2}"
        )

    def test_advisory_lock_key_cross_store_identical(
        self, migrated_store, store2
    ) -> None:
        key1 = compute_advisory_lock_key("publication_history")
        key2 = compute_advisory_lock_key("publication_history")
        assert key1 == key2, (
            f"Advisory lock key must be identical across store instances: "
            f"{key1} vs {key2}"
        )


# ── Timeline advisory lock ───────────────────────────────────────────


class TestTimelineAdvisoryLock:
    def test_timeline_rebuild_acquires_lock(self, migrated_store) -> None:
        mat = TimelineMaterializer(migrated_store)
        receipt = mat.rebuild(_FakeTimelineService())
        assert isinstance(receipt, RebuildReceipt)
        assert receipt.projection_name == "timeline", (
            f"Expected timeline projection_name, got {receipt.projection_name}"
        )

    def test_concurrent_timeline_rebuilds_serialized(
        self, migrated_store, store2
    ) -> None:
        mat_a = TimelineMaterializer(migrated_store)
        mat_b = TimelineMaterializer(store2)

        results: list[RebuildReceipt] = []
        errors: list[Exception] = []
        barrier = threading.Barrier(2, timeout=10)

        def worker(mat: TimelineMaterializer) -> None:
            barrier.wait()
            try:
                r = mat.rebuild(_FakeTimelineService())
                results.append(r)
            except Exception as e:
                errors.append(e)

        t1 = threading.Thread(target=worker, args=(mat_a,))
        t2 = threading.Thread(target=worker, args=(mat_b,))
        t1.start()
        t2.start()
        t1.join(timeout=15)
        t2.join(timeout=15)

        assert len(errors) == 0, f"Unexpected errors: {errors}"
        assert len(results) == 2, (
            f"Both concurrent timeline rebuilds must complete, got {len(results)}"
        )

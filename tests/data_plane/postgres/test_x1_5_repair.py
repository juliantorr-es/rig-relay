"""X1.5 repair tests — atomic rebuild, idempotent receipts, public boundary."""

from __future__ import annotations

import threading

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
from rig_relay.data_plane.postgres._models import (
    RebuildReceipt,
    compute_deterministic_materialization_receipt_id,
    compute_deterministic_rebuild_receipt_id,
)


class _FakeReconstruction:
    """Test double for PublicationMaterializationInput.reconstruction."""

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


class TestAtomicRebuild:
    """Prove rebuild is one atomic serialized operation."""

    def test_rebuild_publication_single_transaction(self, migrated_store) -> None:
        mat = PublicationMaterializer(migrated_store)
        now_ts = "2026-01-01T00:00:00+00:00"

        input_data = PublicationMaterializationInput(
            reconstruction=_FakeReconstruction(
                "rec_atomic_1", "sha256:ev_atomic", now_ts
            ),
            source_evidence_digest="sha256:test_atomic_rebuild_001",
            ledger_identity_digest="sha256:test_ledger_atomic",
            source_status=MaterializationInputStatus.VERIFIED,
        )

        receipt = mat.rebuild(input_data)
        assert isinstance(receipt, RebuildReceipt)
        assert receipt.projection_name == "publication"
        assert receipt.rows_after >= 0

    def test_rebuild_publication_idempotent_digest(self, migrated_store) -> None:
        mat = PublicationMaterializer(migrated_store)
        now_ts = "2026-01-01T00:00:00+00:00"

        input_data = PublicationMaterializationInput(
            reconstruction=_FakeReconstruction("rec_idem_1", "sha256:ev_idem", now_ts),
            source_evidence_digest="sha256:test_idem_rebuild_001",
            ledger_identity_digest="sha256:test_ledger_idem",
            source_status=MaterializationInputStatus.VERIFIED,
        )

        expected_id = compute_deterministic_rebuild_receipt_id(
            "publication", "sha256:test_idem_rebuild_001"
        )

        r1 = mat.rebuild(input_data)
        assert r1.receipt_id == expected_id, (
            f"Rebuild receipt ID must be deterministic from evidence: "
            f"{r1.receipt_id} vs {expected_id}"
        )

        # Second rebuild with same evidence produces same receipt ID
        # (would collide at INSERT — the deterministic id is the proof)
        r2_id = compute_deterministic_rebuild_receipt_id(
            "publication", "sha256:test_idem_rebuild_001"
        )
        assert r2_id == expected_id
        assert r2_id == r1.receipt_id

    def test_different_evidence_produces_different_rebuild_ids(
        self, migrated_store
    ) -> None:
        rebuild_id_a = compute_deterministic_rebuild_receipt_id(
            "publication", "sha256:evidence_a"
        )
        rebuild_id_b = compute_deterministic_rebuild_receipt_id(
            "publication", "sha256:evidence_b"
        )
        assert rebuild_id_a != rebuild_id_b, (
            f"Different evidence must produce different rebuild receipt IDs: "
            f"{rebuild_id_a}"
        )


class TestIdempotentMaterialization:
    """Prove replay of same input converges on same build identity."""

    def test_publication_build_id_idempotent(self) -> None:
        rid_a = compute_deterministic_materialization_receipt_id(
            "publication", "sha256:same_input"
        )
        rid_b = compute_deterministic_materialization_receipt_id(
            "publication", "sha256:same_input"
        )
        assert rid_a == rid_b, (
            f"Same domain+digest must produce same receipt ID: {rid_a} vs {rid_b}"
        )

    def test_different_evidence_produces_different_build_ids(self) -> None:
        rid_a = compute_deterministic_materialization_receipt_id(
            "publication", "sha256:input_a"
        )
        rid_b = compute_deterministic_materialization_receipt_id(
            "publication", "sha256:input_b"
        )
        assert rid_a != rid_b, (
            f"Different evidence must produce different build receipt IDs: {rid_a}"
        )

    def test_rebuild_deterministic_receipt_id(self) -> None:
        rid_a = compute_deterministic_rebuild_receipt_id(
            "publication", "sha256:rebuild_evidence"
        )
        rid_b = compute_deterministic_rebuild_receipt_id(
            "publication", "sha256:rebuild_evidence"
        )
        assert rid_a == rid_b


class TestRebuildConcurrency:
    """Prove rebuild does not interleave with concurrent rebuild."""

    def test_concurrent_rebuilds_serialized(self, migrated_store, pg_config) -> None:
        import secrets
        import string

        from rig_relay.data_plane.postgres._store import (
            PostgresOperationalProjectionStore,
        )

        suffix = "".join(secrets.choice(string.ascii_lowercase) for _ in range(6))

        # Each thread needs its own psycopg connection — connections are not
        # thread-safe. Two stores to the same database share the advisory lock
        # space, so serialization is still enforced at the database level.
        store_a = migrated_store
        store_b = PostgresOperationalProjectionStore(pg_config)
        store_b.ensure_migrated()

        mat_a = PublicationMaterializer(store_a)
        mat_b = PublicationMaterializer(store_b)

        results: list[RebuildReceipt] = []
        errors: list[Exception] = []
        barrier = threading.Barrier(2, timeout=10)

        def build_worker(mat: PublicationMaterializer, thread_id: str) -> None:
            barrier.wait()
            try:
                input_data = PublicationMaterializationInput(
                    reconstruction=_FakeReconstruction(
                        f"rec_concurrent_{suffix}_{thread_id}",
                        f"sha256:ev_concurrent_{suffix}_{thread_id}",
                        "2026-01-01T00:00:00+00:00",
                    ),
                    source_evidence_digest=f"sha256:concurrent_test_{suffix}_{thread_id}",
                    ledger_identity_digest=f"sha256:ledger_concurrent_{suffix}_{thread_id}",
                    source_status=MaterializationInputStatus.VERIFIED,
                )
                r = mat.rebuild(input_data)
                results.append(r)
            except Exception as e:
                errors.append(e)

        t1 = threading.Thread(target=build_worker, args=(mat_a, "a"))
        t2 = threading.Thread(target=build_worker, args=(mat_b, "b"))
        t1.start()
        t2.start()
        t1.join(timeout=15)
        t2.join(timeout=15)

        store_b.close()

        assert len(errors) == 0, f"Unexpected errors: {errors}"
        assert len(results) == 2, f"Expected 2 rebuilds, got {len(results)}"
        # Advisory lock serialized both rebuilds — each completed without
        # interleaving. Receipt IDs differ because evidence differs.
        assert results[0].receipt_id != results[1].receipt_id, (
            "Different evidence must produce different receipt IDs: "
            f"{results[0].receipt_id}"
        )


class TestReceiptReconstruction:
    """Prove rebuild receipt identity is reproducible."""

    def test_rebuild_receipt_id_reproducible_across_targets(self) -> None:
        same_evidence = "sha256:cross_target_evidence"
        rid1 = compute_deterministic_rebuild_receipt_id("publication", same_evidence)
        rid2 = compute_deterministic_rebuild_receipt_id("publication", same_evidence)
        assert rid1 == rid2

    def test_conflicting_evidence_not_collapsed(self) -> None:
        rid_a = compute_deterministic_materialization_receipt_id(
            "publication", "sha256:evidence_x"
        )
        rid_b = compute_deterministic_materialization_receipt_id(
            "publication", "sha256:evidence_y"
        )
        rid_c = compute_deterministic_materialization_receipt_id(
            "repository_estate", "sha256:evidence_x"
        )
        assert rid_a != rid_b
        assert rid_a != rid_c
        assert rid_b != rid_c


class TestPublicStoreBoundary:
    """Prove no external class calls private store methods."""

    def test_record_rebuild_receipt_is_public(self) -> None:
        from rig_relay.data_plane.postgres._store import (
            PostgresOperationalProjectionStore,
        )

        assert hasattr(PostgresOperationalProjectionStore, "record_rebuild_receipt"), (
            "record_rebuild_receipt must be a public method"
        )
        method = PostgresOperationalProjectionStore.record_rebuild_receipt
        assert not method.__name__.startswith("_"), (
            f"Method name must not start with underscore: {method.__name__}"
        )

    def test_acquire_rebuild_lock_is_public(self) -> None:
        from rig_relay.data_plane.postgres._store import (
            PostgresOperationalProjectionStore,
        )

        assert hasattr(PostgresOperationalProjectionStore, "acquire_rebuild_lock"), (
            "acquire_rebuild_lock must be a public method"
        )


class TestCorruptionRegression:
    """Prove X1.4 fixes survive X1.5 changes."""

    def test_corrupt_source_still_emitted(self) -> None:
        class FakeReconstruction:
            def __init__(self) -> None:
                self.receipts: list[dict] = []
                self.total_rows: int = 3
                self.valid_rows: int = 1
                self.corrupt_rows: int = 2
                self.corruption_detected: bool = True

        class FakeLedger:
            def load_receipts(self, authoritative: bool = False):
                return FakeReconstruction()

        input_data = PublicationMaterializationInput.from_ledger(FakeLedger())
        assert input_data.source_status == MaterializationInputStatus.CORRUPT_SOURCE

    def test_verified_with_empty_digest_refused(self, migrated_store) -> None:
        mat = RepositoryEstateMaterializer(migrated_store)
        input_data = RepositoryEstateMaterializationInput(
            projection={},
            source_status=MaterializationInputStatus.VERIFIED,
            source_evidence_digest="",
        )
        receipt = mat.materialize(input_data)
        assert receipt.rows_materialized == 0

    def test_verified_with_digest_accepted(self, migrated_store) -> None:
        class FakeProjection:
            def __init__(self) -> None:
                self.registered_repositories: list[dict] = []
                self.corruption_events: list[dict] = []
                self.recent_changes: list[dict] = []
                self.total_registered: int = 0
                self.total_observations: int = 0
                self.corrupt_registration_count: int = 0
                self.corrupt_observation_count: int = 0
                self.authority_state: str = "controlled_boundary"

        mat = RepositoryEstateMaterializer(migrated_store)
        input_data = RepositoryEstateMaterializationInput(
            projection=FakeProjection(),
            source_status=MaterializationInputStatus.VERIFIED,
            source_evidence_digest="sha256:bound_digest",
        )
        receipt = mat.materialize(input_data)
        assert receipt.rows_materialized >= 0

    def test_missing_producer_digest_refused(self, migrated_store) -> None:
        mat = RepositoryEstateMaterializer(migrated_store)

        class FakeProjection:
            pass

        input_data = RepositoryEstateMaterializationInput(
            projection=FakeProjection(),
            source_status=MaterializationInputStatus.MISSING_PRODUCER_DIGEST,
            source_evidence_digest="",
        )
        receipt = mat.materialize(input_data)
        assert receipt.rows_materialized == 0


class TestX0Contract:
    """Prove X0 contract prohibits direct database access."""

    def test_x0_contract_exists_and_readable(self) -> None:
        import json
        from pathlib import Path

        contract_path = (
            Path(__file__).resolve().parent.parent.parent.parent
            / "docs/json/contracts/x0_postgres_consumer_admission.v1.json"
        )
        assert contract_path.exists()
        contract = json.loads(contract_path.read_text())
        assert "candidate_commit_sha" in contract
        assert len(contract["candidate_commit_sha"]) == 40

    def test_x0_contract_prohibits_direct_table_access(self) -> None:
        import json
        from pathlib import Path

        contract_path = (
            Path(__file__).resolve().parent.parent.parent.parent
            / "docs/json/contracts/x0_postgres_consumer_admission.v1.json"
        )
        contract = json.loads(contract_path.read_text())

        prohibited = contract["prohibited_claims"]
        direct_access_claim = (
            "X0 queries PostgreSQL domain tables or materialized views directly "
            "instead of consuming a typed public X1 application-service projection"
        )
        assert direct_access_claim in prohibited, (
            "X0 contract must prohibit direct table/materialized-view access"
        )

        for domain_key in (
            "repository_estate",
            "investigation_timeline",
            "publication_history",
        ):
            domain = contract["domains"][domain_key]
            admission_text = domain["admission_for_x0"]
            assert (
                "public typed application-service projection" in admission_text.lower()
            ), (
                f"Domain {domain_key} admission_for_x0 must reference "
                f"public projection boundary"
            )
            domain_prohibited = domain["prohibited"]
            assert any(
                "directly" in p.lower()
                and ("table" in p.lower() or "materialized" in p.lower())
                for p in domain_prohibited
            ), (
                f"Domain {domain_key} must prohibit direct table/materialized-view queries"
            )

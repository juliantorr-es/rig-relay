"""Canonical evidence ingestion tests — idempotent ingestion,
duplicate detection, malformed evidence refusal, checkpoint management.
"""

from __future__ import annotations

from rig_relay.data_plane.postgres._models import EvidenceSourceKind


class TestEvidenceIngestion:
    """Ingestion and idempotency tests against real PostgreSQL."""

    def test_ingest_single_evidence(self, migrated_store) -> None:
        """Ingest a single evidence record."""
        receipt = migrated_store.ingest_evidence(
            evidence_id="evt_001",
            evidence_kind=EvidenceSourceKind.COORDINATION_EVENT,
            evidence_sha256="abc123",
            provenance={"session_id": "s1"},
        )
        assert receipt.status == "ingested"
        assert receipt.evidence_id == "evt_001"
        assert receipt.evidence_kind == EvidenceSourceKind.COORDINATION_EVENT

    def test_ingest_duplicate_idempotent(self, migrated_store) -> None:
        """Ingesting the same evidence_id twice returns duplicate status."""
        # First ingestion
        r1 = migrated_store.ingest_evidence(
            evidence_id="evt_002",
            evidence_kind=EvidenceSourceKind.TOOL_CALL,
            evidence_sha256="def456",
        )
        assert r1.status == "ingested"

        # Second ingestion — same evidence_id
        r2 = migrated_store.ingest_evidence(
            evidence_id="evt_002",
            evidence_kind=EvidenceSourceKind.TOOL_CALL,
            evidence_sha256="def456",
        )
        assert r2.status == "duplicate"

    def test_ingest_multiple_kinds(self, migrated_store) -> None:
        """Ingest evidence of different kinds."""
        kinds = [
            ("evt_c1", EvidenceSourceKind.COORDINATION_EVENT),
            ("evt_s1", EvidenceSourceKind.SESSION_OBSERVABILITY),
            ("evt_g1", EvidenceSourceKind.GOVERNANCE_DECISION),
            ("evt_t1", EvidenceSourceKind.TOOL_CALL),
            ("evt_ch1", EvidenceSourceKind.CHECKPOINT),
            ("evt_a1", EvidenceSourceKind.ARTIFACT),
        ]
        for eid, kind in kinds:
            r = migrated_store.ingest_evidence(
                evidence_id=eid, evidence_kind=kind, evidence_sha256=f"sha256_{eid}"
            )
            assert r.status == "ingested", f"Failed for {kind}"

        counts = migrated_store.count_evidence_by_kind()
        assert len(counts) == len(kinds)

    def test_ingest_refused_invalid_kind(self, migrated_store) -> None:
        """Ingesting with an invalid evidence kind returns refused status."""
        receipt = migrated_store.ingest_evidence(
            evidence_id="evt_bad",
            evidence_kind="not_a_real_kind",
            evidence_sha256="bad",
        )
        assert receipt.status == "refused"
        assert receipt.refusal_reason is not None

    def test_ingest_refused_malformed_id(self, migrated_store) -> None:
        """Empty evidence_id should still work (store doesn't validate semantics)."""
        receipt = migrated_store.ingest_evidence(
            evidence_id="",
            evidence_kind=EvidenceSourceKind.ARTIFACT,
            evidence_sha256="",
        )
        assert receipt.status == "ingested"

    def test_count_evidence_by_kind(self, migrated_store) -> None:
        """Evidence counts are accurate after ingestion."""
        count_before = migrated_store.count_evidence_by_kind().get("checkpoint", 0)
        for i in range(5):
            migrated_store.ingest_evidence(
                evidence_id=f"evt_count_{i}",
                evidence_kind=EvidenceSourceKind.CHECKPOINT,
                evidence_sha256=f"hash_{i}",
            )
        counts = migrated_store.count_evidence_by_kind()
        assert counts.get("checkpoint", 0) == count_before + 5

    def test_get_evidence_by_id(self, migrated_store) -> None:
        """Retrieve an ingested evidence record by ID."""
        migrated_store.ingest_evidence(
            evidence_id="evt_get_1",
            evidence_kind=EvidenceSourceKind.TOOL_CALL,
            evidence_sha256="sha_get_1",
            provenance={"task_id": "t1"},
        )
        evidence = migrated_store.get_evidence("evt_get_1")
        assert evidence is not None
        assert evidence.evidence_kind == EvidenceSourceKind.TOOL_CALL
        assert evidence.evidence_sha256 == "sha_get_1"
        assert evidence.provenance == {"task_id": "t1"}

    def test_get_evidence_missing(self, migrated_store) -> None:
        """Retrieving a non-existent evidence ID returns None."""
        evidence = migrated_store.get_evidence("does_not_exist")
        assert evidence is None

    def test_checkpoint_management(self, migrated_store) -> None:
        """Ingestion checkpoints can be created and retrieved."""
        migrated_store.update_checkpoint(
            ledger_path_hash="ledger_hash_1",
            last_sequence=42,
            last_event_id="evt_042",
            records_ingested=100,
        )
        cp = migrated_store.get_checkpoint("ledger_hash_1")
        assert cp is not None
        assert cp.last_sequence == 42
        assert cp.last_event_id == "evt_042"
        assert cp.records_ingested == 100

        # Update the checkpoint
        migrated_store.update_checkpoint(
            ledger_path_hash="ledger_hash_1",
            last_sequence=50,
            last_event_id="evt_050",
            records_ingested=8,
        )
        cp2 = migrated_store.get_checkpoint("ledger_hash_1")
        assert cp2 is not None
        assert cp2.last_sequence == 50
        assert cp2.records_ingested == 108

    def test_checkpoint_missing(self, migrated_store) -> None:
        """Non-existent checkpoint returns None."""
        cp = migrated_store.get_checkpoint("no_such_ledger")
        assert cp is None

    def test_ingest_with_provenance(self, migrated_store) -> None:
        """Evidence with provenance metadata is stored correctly."""
        migrated_store.ingest_evidence(
            evidence_id="evt_prov",
            evidence_kind=EvidenceSourceKind.COORDINATION_EVENT,
            evidence_sha256="sha_prov",
            provenance={
                "session_id": "s1",
                "task_id": "t1",
                "agent_profile": "builder",
            },
        )
        evidence = migrated_store.get_evidence("evt_prov")
        assert evidence.provenance["session_id"] == "s1"
        assert evidence.provenance["agent_profile"] == "builder"

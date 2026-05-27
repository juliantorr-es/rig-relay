"""Projection rebuild tests — deterministic rebuild from canonical evidence."""

from __future__ import annotations

from rig_relay.data_plane.postgres._models import EvidenceSourceKind


class TestRebuild:
    """Rebuild tests against real PostgreSQL."""

    def test_clear_projection_data(self, migrated_store) -> None:
        """Clear removes evidence and projection data but preserves schema."""
        # Ingest some evidence
        for i in range(3):
            migrated_store.ingest_evidence(
                evidence_id=f"evt_clear_{i}",
                evidence_kind=EvidenceSourceKind.CHECKPOINT,
                evidence_sha256=f"hash_clear_{i}",
            )

        counts_before = sum(migrated_store.count_evidence_by_kind().values())
        assert counts_before >= 3

        deleted = migrated_store.clear_projection_data()
        assert deleted >= 3

        counts_after = sum(migrated_store.count_evidence_by_kind().values())
        assert counts_after == 0

        # Schema version should still exist
        version, _ = migrated_store._get_schema_version()
        assert version >= 1

    def test_rebuild_deterministic(self, migrated_store) -> None:
        """Rebuild from the same evidence sources produces the same row counts.

        Rebuild clears all data and re-ingests exactly the provided sources.
        After rebuild, evidence count must equal the source count.
        """
        sources = [
            {
                "evidence_id": "evt_rb_1",
                "evidence_kind": EvidenceSourceKind.COORDINATION_EVENT,
                "evidence_sha256": "sha_rb_1",
                "provenance": {"session_id": "s1"},
            },
            {
                "evidence_id": "evt_rb_2",
                "evidence_kind": EvidenceSourceKind.TOOL_CALL,
                "evidence_sha256": "sha_rb_2",
                "provenance": {"session_id": "s1"},
            },
            {
                "evidence_id": "evt_rb_3",
                "evidence_kind": EvidenceSourceKind.CHECKPOINT,
                "evidence_sha256": "sha_rb_3",
                "provenance": {"session_id": "s2"},
            },
        ]

        # Rebuild from evidence sources
        from rig_relay.data_plane.postgres._models import EvidenceSource

        evidence_objects = []
        for src in sources:
            evidence_objects.append(
                EvidenceSource(
                    evidence_id=src["evidence_id"],
                    evidence_kind=src["evidence_kind"],
                    evidence_sha256=src["evidence_sha256"],
                    provenance=src.get("provenance", {}),
                )
            )

        receipt = migrated_store.rebuild_from_evidence(
            projection_name="test_projection", evidence_sources=evidence_objects
        )

        assert receipt.rows_after == 3
        # After rebuild, only the provided sources should exist
        counts = migrated_store.count_evidence_by_kind()
        total = sum(counts.values())
        assert total == 3

    def test_rebuild_preserves_schema(self, migrated_store) -> None:
        """Rebuild does not damage schema authority tables."""
        version_before, _ = migrated_store._get_schema_version()

        migrated_store.rebuild_from_evidence(
            projection_name="schema_test", evidence_sources=[]
        )

        version_after, _ = migrated_store._get_schema_version()
        assert version_after == version_before

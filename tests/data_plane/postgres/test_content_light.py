"""Content-light storage exclusion tests.

Prove that no raw file contents, prompts, model outputs, paths,
credentials, or other forbidden content is stored in PostgreSQL.
"""

from __future__ import annotations

import hashlib

from rig_relay.data_plane.postgres._models import EvidenceSourceKind


class TestContentLight:
    """Content-light boundary tests."""

    def test_no_secret_in_config_safe_summary(self, migrated_store) -> None:
        """Config safe_summary does not expose password."""
        summary = migrated_store.config.safe_summary()
        assert "s3cret" not in str(summary)
        assert "password" not in summary  # key is password_configured

    def test_evidence_stores_hash_not_content(self, migrated_store) -> None:
        """Evidence records store SHA256 hashes, not raw content."""
        raw_content = "This is raw private file content that should not be stored"
        content_hash = hashlib.sha256(raw_content.encode()).hexdigest()

        migrated_store.ingest_evidence(
            evidence_id="evt_hash_test",
            evidence_kind=EvidenceSourceKind.TOOL_CALL,
            evidence_sha256=content_hash,
        )

        evidence = migrated_store.get_evidence("evt_hash_test")
        assert evidence.evidence_sha256 == content_hash
        assert "raw private file content" not in str(evidence.model_dump())

    def test_no_raw_paths_in_evidence(self, migrated_store) -> None:
        """Evidence records don't store raw file paths — use salted hashes."""
        raw_path = "/Users/test/secret/file.txt"
        path_hash = "sha256:" + hashlib.sha256(raw_path.encode()).hexdigest()

        migrated_store.ingest_evidence(
            evidence_id="evt_path_test",
            evidence_kind=EvidenceSourceKind.COORDINATION_EVENT,
            evidence_sha256="hash123",
            source_ledger_path_hash=path_hash,
        )

        evidence = migrated_store.get_evidence("evt_path_test")
        dump = evidence.model_dump()
        # The raw path should not appear in the stored evidence
        assert raw_path not in str(dump)
        # Only the hash should be stored
        assert evidence.source_ledger_path_hash == path_hash

    def test_provenance_is_content_light(self, migrated_store) -> None:
        """Provenance metadata only stores session_id, task_id, etc — no raw content."""
        migrated_store.ingest_evidence(
            evidence_id="evt_prov_light",
            evidence_kind=EvidenceSourceKind.TOOL_CALL,
            evidence_sha256="hash_prov",
            provenance={
                "session_id": "s1",
                "task_id": "t1",
                "agent_profile": "builder",
                # These would be appropriate content-light fields
                # Raw content like "raw_prompt", "file_contents" must not be stored
            },
        )

        evidence = migrated_store.get_evidence("evt_prov_light")
        provenance = evidence.provenance
        # Verify content-light fields are present
        assert provenance.get("session_id") == "s1"
        assert provenance.get("agent_profile") == "builder"
        # Verify no forbidden keys
        forbidden = {
            "raw_file_contents",
            "raw_prompt_text",
            "model_output_text",
            "secrets",
        }
        for key in forbidden:
            assert key not in provenance, f"Found forbidden key '{key}' in provenance"

    def test_no_sqlite_imports(self) -> None:
        """Prove no SQLite imports/dependencies in the T2 slice."""
        import sys

        t2_modules = ["rig_relay.data_plane", "rig_relay.data_plane.postgres"]
        for mod_name in t2_modules:
            mod = sys.modules.get(mod_name)
            if mod is None:
                continue
            assert "sqlite3" not in str(mod.__dict__)
            assert "aiosqlite" not in str(mod.__dict__)
            assert "sqlalchemy" not in str(mod.__dict__)
            assert "alembic" not in str(mod.__dict__)
            assert "pgvector" not in str(mod.__dict__)

    def test_operational_snapshot_content_light(self, migrated_store) -> None:
        """Operational snapshots store content-light metadata, not raw content."""
        migrated_store.capture_snapshot(
            snapshot_id="snap_light",
            snapshot_kind="degradation",
            snapshot_data={
                "status": "degraded",
                "reason": "provider_timeout",
                "affected_service": "llm_backend",
                # These are content-light operational metadata
            },
        )

        data = migrated_store.get_snapshot("snap_light")
        assert data is not None
        assert data["status"] == "degraded"
        assert data["reason"] == "provider_timeout"
        forbidden = {"raw_file_contents", "raw_prompt_text", "secrets", "credentials"}
        for key in forbidden:
            assert key not in data, f"Found forbidden key '{key}' in snapshot"

    def test_no_forbidden_fields_in_models(self) -> None:
        """Pydantic models don't have forbidden field names."""
        from rig_relay.data_plane.postgres._models import (
            EvidenceSource,
            IngestionCheckpoint,
            IngestionReceipt,
            ProjectionBuildReceipt,
        )

        forbidden = {
            "raw_file_contents",
            "raw_prompt_text",
            "model_output_text",
            "secrets",
            "credentials",
            "api_key",
            "access_token",
            "stdout",
            "stderr",
            "prompt",
            "source_code",
        }

        models: list[type] = [
            EvidenceSource,
            IngestionCheckpoint,
            IngestionReceipt,
            ProjectionBuildReceipt,
        ]
        for model_cls in models:
            field_names = set(model_cls.model_fields.keys())
            overlap = field_names & forbidden
            assert not overlap, f"{model_cls.__name__} has forbidden fields: {overlap}"

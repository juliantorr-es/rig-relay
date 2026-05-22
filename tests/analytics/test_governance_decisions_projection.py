from __future__ import annotations

from pathlib import Path
import tempfile

import pytest

from rig_relay.analytics.governance_decisions_projection import (
    HAS_DUCKDB,
    build_governance_decisions_projection,
    query_governance_decisions,
)
from rig_relay.evidence.receipt_envelope import (
    ReceiptActor,
    ReceiptActorKind,
    ReceiptDecision,
    ReceiptEnvelope,
    ReceiptSubject,
    ReceiptSubjectKind,
    build_receipt_envelope,
)
from rig_relay.evidence.receipt_store import FilesystemReceiptStore


def _make_envelope(
    envelope_id: str = "env-test-001",
    receipt_kind: str = "governance_decision",
    surface: str = "agent_loop",
    authority_tier: str = "local_mutation",
    capability_id: str = "rig.write_file",
    governance_decision_id: str = "gd-abc123def456",
    decision_status: str = "blocked",
    content_light_classification: str = "public_safe",
    session_id: str | None = "session-001",
    request_id: str | None = None,
) -> ReceiptEnvelope:
    actor = ReceiptActor(
        actor_id="test_actor",
        actor_kind=ReceiptActorKind.RUNTIME,
        display_name="Test",
        is_human=False,
        is_authoritative=True,
    )
    subject = ReceiptSubject(
        subject_id="write_file",
        subject_kind=ReceiptSubjectKind.TOOL_INVOCATION,
        session_id=session_id,
    )
    decision = ReceiptDecision(
        decision=decision_status,
        gate="test_gate",
        governance_decision_id=governance_decision_id,
        surface=surface,
        authority_tier=authority_tier,
        capability_id=capability_id,
        content_light_classification=content_light_classification,
    )
    return ReceiptEnvelope(
        envelope_id=envelope_id,
        receipt_kind=receipt_kind,
        request_id=request_id,
        actor=actor,
        subject=subject,
        decision=decision,
        created_at="2026-05-21T00:00:00Z",
    )


@pytest.mark.skipif(not HAS_DUCKDB, reason="DuckDB not available")
class TestBuildGovernanceDecisionsProjection:
    def test_build_from_enriched_manifest_and_envelopes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = FilesystemReceiptStore(Path(tmp))
            store.append(
                _make_envelope(envelope_id="env-a", governance_decision_id="gd-a")
            )
            store.append(
                _make_envelope(
                    envelope_id="env-b", governance_decision_id="gd-b", surface="mcp"
                )
            )

            projection = build_governance_decisions_projection(Path(tmp))

            assert projection["status"] == "ok"
            assert projection["valid_record_count"] == 2
            assert projection["manifest_row_count"] == 2
            assert projection["content_light"] is True
            assert projection["mutation_authority"] is False
            assert projection["read_side_only"] is True
            assert projection["raw_payloads_exposed"] is False
            assert projection["rebuildable"] is True

    def test_count_matches_valid_manifest_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = FilesystemReceiptStore(Path(tmp))
            store.append(_make_envelope(envelope_id="env-1"))
            store.append(_make_envelope(envelope_id="env-2"))
            store.append(_make_envelope(envelope_id="env-3"))

            projection = build_governance_decisions_projection(Path(tmp))
            assert projection["valid_record_count"] == 3
            assert projection["manifest_row_count"] == 3

    def test_query_by_governance_decision_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = FilesystemReceiptStore(Path(tmp))
            store.append(
                _make_envelope(
                    envelope_id="env-find", governance_decision_id="gd-target"
                )
            )

            result = query_governance_decisions(
                Path(tmp),
                "SELECT governance_decision_id FROM governance_decisions WHERE governance_decision_id = 'gd-target'",
            )
            assert len(result) == 1
            assert result[0]["governance_decision_id"] == "gd-target"

    def test_query_by_surface(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = FilesystemReceiptStore(Path(tmp))
            store.append(_make_envelope(envelope_id="env-mcp", surface="mcp"))
            store.append(_make_envelope(envelope_id="env-cli", surface="cli"))

            result = query_governance_decisions(
                Path(tmp),
                "SELECT surface, COUNT(*) as cnt FROM governance_decisions WHERE surface = 'mcp' GROUP BY surface",
            )
            assert len(result) == 1
            assert result[0]["surface"] == "mcp"

    def test_query_by_authority_tier(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = FilesystemReceiptStore(Path(tmp))
            store.append(
                _make_envelope(envelope_id="env-tier", authority_tier="remote_mutation")
            )
            store.append(
                _make_envelope(envelope_id="env-local", authority_tier="local_mutation")
            )

            result = query_governance_decisions(
                Path(tmp),
                "SELECT authority_tier, COUNT(*) as cnt FROM governance_decisions WHERE authority_tier = 'remote_mutation' GROUP BY authority_tier",
            )
            assert len(result) == 1
            assert result[0]["authority_tier"] == "remote_mutation"

    def test_query_by_capability_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = FilesystemReceiptStore(Path(tmp))
            store.append(
                _make_envelope(
                    envelope_id="env-cap", capability_id="rig.search_evidence"
                )
            )

            result = query_governance_decisions(
                Path(tmp),
                "SELECT capability_id FROM governance_decisions WHERE capability_id = 'rig.search_evidence'",
            )
            assert len(result) == 1

    def test_query_by_decision_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = FilesystemReceiptStore(Path(tmp))
            store.append(
                _make_envelope(envelope_id="env-blocked", decision_status="blocked")
            )
            store.append(
                _make_envelope(envelope_id="env-allowed", decision_status="allowed")
            )

            result = query_governance_decisions(
                Path(tmp),
                "SELECT decision_status, COUNT(*) as cnt FROM governance_decisions WHERE decision_status = 'blocked' GROUP BY decision_status",
            )
            assert len(result) == 1
            assert result[0]["decision_status"] == "blocked"

    def test_projection_includes_surface_status_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = FilesystemReceiptStore(Path(tmp))
            store.append(_make_envelope(envelope_id="env-a", surface="mcp"))
            store.append(_make_envelope(envelope_id="env-b", surface="mcp"))

            projection = build_governance_decisions_projection(Path(tmp))
            assert "query_results" in projection
            assert "surface_status_summary" in projection["query_results"]

    def test_projection_includes_authority_tier_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = FilesystemReceiptStore(Path(tmp))
            store.append(_make_envelope(envelope_id="env-1"))

            projection = build_governance_decisions_projection(Path(tmp))
            assert "query_results" in projection
            assert "authority_tier_summary" in projection["query_results"]

    def test_content_light_classification_present_in_row(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = FilesystemReceiptStore(Path(tmp))
            store.append(
                _make_envelope(
                    envelope_id="env-cc", content_light_classification="public_safe"
                )
            )

            result = query_governance_decisions(
                Path(tmp),
                "SELECT content_light_classification FROM governance_decisions WHERE envelope_id = 'env-cc'",
            )
            assert len(result) == 1
            assert result[0].get("content_light_classification") == "public_safe"

    def test_old_manifest_rows_are_tolerated(self) -> None:
        import json

        with tempfile.TemporaryDirectory() as tmp:
            store = FilesystemReceiptStore(Path(tmp))
            old_line = json.dumps({
                "envelope_id": "env-old",
                "receipt_kind": "governance_decision",
                "session_id": None,
                "created_at": "2026-01-01T00:00:00Z",
            })
            with (Path(tmp) / "manifest.jsonl").open("a") as f:
                f.write(old_line + "\n")

            env_old = build_receipt_envelope(
                envelope_id="env-old",
                receipt_kind="governance_decision",
                actor=ReceiptActor(actor_id="a", actor_kind=ReceiptActorKind.RUNTIME),
                subject=ReceiptSubject(
                    subject_id="s", subject_kind=ReceiptSubjectKind.TOOL_INVOCATION
                ),
                decision=None,
                created_at="2026-01-01T00:00:00Z",
            )
            path = store._envelope_path("env-old")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(env_old.model_dump(mode="json"), sort_keys=True),
                encoding="utf-8",
            )

            store.append(_make_envelope(envelope_id="env-new"))

            projection = build_governance_decisions_projection(Path(tmp))
            assert projection["valid_record_count"] >= 1

    def test_projection_rebuild_is_deterministic_for_counts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = FilesystemReceiptStore(Path(tmp))
            store.append(_make_envelope(envelope_id="env-a"))
            store.append(_make_envelope(envelope_id="env-b"))
            store.append(_make_envelope(envelope_id="env-c"))

            p1 = build_governance_decisions_projection(Path(tmp))
            p2 = build_governance_decisions_projection(Path(tmp))

            assert p1["valid_record_count"] == p2["valid_record_count"]
            assert p1["manifest_row_count"] == p2["manifest_row_count"]
            assert p1["manifest_row_count"] == 3


@pytest.mark.skipif(not HAS_DUCKDB, reason="DuckDB not available")
class TestProjectionDiagnostics:
    def test_corrupted_manifest_line_recorded(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with (Path(tmp) / "manifest.jsonl").open("a") as f:
                f.write("not json\n")

            store = FilesystemReceiptStore(Path(tmp))
            store.append(_make_envelope(envelope_id="env-ok"))

            projection = build_governance_decisions_projection(Path(tmp))
            assert projection["corrupted_manifest_line_count"] >= 1
            assert projection["valid_record_count"] == 1

    def test_missing_shard_recorded(self) -> None:
        import json

        with tempfile.TemporaryDirectory() as tmp:
            manifest_line = json.dumps({
                "envelope_id": "env-missing",
                "receipt_kind": "governance_decision",
                "session_id": None,
                "created_at": "2026-01-01T00:00:00Z",
            })
            with (Path(tmp) / "manifest.jsonl").open("a") as f:
                f.write(manifest_line + "\n")

            projection = build_governance_decisions_projection(Path(tmp))
            assert projection["missing_shard_count"] >= 1
            assert projection["valid_record_count"] == 0

    def test_orphaned_shard_recorded(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = FilesystemReceiptStore(Path(tmp))
            env = _make_envelope(envelope_id="env-orphan")
            shard_path = store._envelope_path("env-orphan")
            shard_path.parent.mkdir(parents=True, exist_ok=True)
            import json

            shard_path.write_text(
                json.dumps(env.model_dump(mode="json"), sort_keys=True),
                encoding="utf-8",
            )
            store.append(_make_envelope(envelope_id="env-valid"))

            projection = build_governance_decisions_projection(Path(tmp))
            assert projection["orphaned_shard_count"] >= 1


@pytest.mark.skipif(not HAS_DUCKDB, reason="DuckDB not available")
class TestSourceOfTruthGuarantee:
    def test_projection_is_rebuildable_from_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = FilesystemReceiptStore(Path(tmp))
            store.append(_make_envelope(envelope_id="env-truth"))

            p1 = build_governance_decisions_projection(Path(tmp))
            assert p1["rebuildable"] is True
            assert p1["source_manifest_sha256"]

    def test_projection_declares_non_mutation_authority(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = FilesystemReceiptStore(Path(tmp))
            store.append(_make_envelope(envelope_id="env-sot"))

            projection = build_governance_decisions_projection(Path(tmp))
            assert projection["mutation_authority"] is False
            assert projection["read_side_only"] is True
            assert projection["raw_payloads_exposed"] is False

    def test_projection_writes_to_derived_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = FilesystemReceiptStore(Path(tmp))
            store.append(_make_envelope(envelope_id="env-out"))

            derived = Path(tmp) / "derived"
            projection = build_governance_decisions_projection(
                Path(tmp), derived_dir=derived
            )

            assert "output_path" in projection
            out_file = Path(str(projection["output_path"]))
            assert out_file.is_file()
            import json

            data = json.loads(out_file.read_text(encoding="utf-8"))
            assert data["status"] == "ok"
            assert data["valid_record_count"] == 1


class TestDuckDBUnavailable:
    def test_projection_handles_missing_duckdb_gracefully(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = FilesystemReceiptStore(Path(tmp))
            store.append(_make_envelope(envelope_id="env-no-db"))

            projection = build_governance_decisions_projection(Path(tmp))

            if not HAS_DUCKDB:
                assert projection["status"] == "duckdb_not_available"

    def test_query_returns_empty_when_duckdb_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = query_governance_decisions(Path(tmp), "SELECT 1")
            if not HAS_DUCKDB:
                assert result == []

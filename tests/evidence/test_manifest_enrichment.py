from __future__ import annotations

import json
from pathlib import Path
import tempfile

from rig_relay.evidence.receipt_envelope import (
    ReceiptActor,
    ReceiptActorKind,
    ReceiptDecision,
    ReceiptEnvelope,
    ReceiptSubject,
    ReceiptSubjectKind,
    build_receipt_envelope,
)
from rig_relay.evidence.receipt_store import FilesystemReceiptStore, ManifestDiagnostic


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
    request_id: str | None = "req-001",
) -> ReceiptEnvelope:
    actor = ReceiptActor(
        actor_id="test_actor",
        actor_kind=ReceiptActorKind.RUNTIME,
        display_name="Test Actor",
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


class TestManifestEnrichment:
    def test_manifest_row_includes_governance_decision_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = FilesystemReceiptStore(Path(tmp))
            env = _make_envelope(governance_decision_id="gd-test123")
            store.append(env)

            rows = store.iter_manifest_rows()
            assert len(rows) == 1
            assert rows[0].get("governance_decision_id") == "gd-test123"

    def test_manifest_row_includes_surface(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = FilesystemReceiptStore(Path(tmp))
            env = _make_envelope(surface="mcp")
            store.append(env)

            rows = store.iter_manifest_rows()
            assert rows[0].get("surface") == "mcp"

    def test_manifest_row_includes_authority_tier(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = FilesystemReceiptStore(Path(tmp))
            env = _make_envelope(authority_tier="remote_mutation")
            store.append(env)

            rows = store.iter_manifest_rows()
            assert rows[0].get("authority_tier") == "remote_mutation"

    def test_manifest_row_includes_capability_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = FilesystemReceiptStore(Path(tmp))
            env = _make_envelope(capability_id="rig.search_evidence")
            store.append(env)

            rows = store.iter_manifest_rows()
            assert rows[0].get("capability_id") == "rig.search_evidence"

    def test_manifest_row_includes_decision_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = FilesystemReceiptStore(Path(tmp))
            env = _make_envelope(decision_status="blocked")
            store.append(env)

            rows = store.iter_manifest_rows()
            assert rows[0].get("decision_status") == "blocked"

    def test_manifest_row_includes_content_light_classification(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = FilesystemReceiptStore(Path(tmp))
            env = _make_envelope(content_light_classification="public_safe")
            store.append(env)

            rows = store.iter_manifest_rows()
            assert rows[0].get("content_light_classification") == "public_safe"

    def test_manifest_row_includes_schema_version(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = FilesystemReceiptStore(Path(tmp))
            env = _make_envelope()
            store.append(env)

            rows = store.iter_manifest_rows()
            assert rows[0].get("schema_version") == "rig.relay.receipt_envelope.v1"

    def test_manifest_row_includes_session_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = FilesystemReceiptStore(Path(tmp))
            env = _make_envelope(session_id="my-session")
            store.append(env)

            rows = store.iter_manifest_rows()
            assert rows[0].get("session_id") == "my-session"

    def test_envelope_without_decision_writes_minimal_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = FilesystemReceiptStore(Path(tmp))
            env = build_receipt_envelope(
                receipt_kind="test",
                actor=ReceiptActor(actor_id="a", actor_kind=ReceiptActorKind.RUNTIME),
                subject=ReceiptSubject(
                    subject_id="s", subject_kind=ReceiptSubjectKind.TOOL_INVOCATION
                ),
                decision=None,
            )
            store.append(env)

            rows = store.iter_manifest_rows()
            assert len(rows) == 1
            assert "envelope_id" in rows[0]
            assert (
                "governance_decision_id" not in rows[0]
                or rows[0].get("governance_decision_id") is None
            )


class TestBackwardCompatibility:
    def test_old_manifest_row_without_new_fields_is_readable(self) -> None:
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

            env_without_decision = build_receipt_envelope(
                receipt_kind="new",
                actor=ReceiptActor(actor_id="a", actor_kind=ReceiptActorKind.RUNTIME),
                subject=ReceiptSubject(
                    subject_id="s", subject_kind=ReceiptSubjectKind.TOOL_INVOCATION
                ),
                decision=None,
            )
            store.append(env_without_decision)

            rows = store.iter_manifest_rows()
            assert len(rows) == 2
            first = rows[0]
            assert first["envelope_id"] == "env-old"
            assert (
                "governance_decision_id" not in first
                or first.get("governance_decision_id") is None
            )
            assert "surface" not in first or first.get("surface") is None

    def test_manifest_with_only_old_rows_still_lists(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = FilesystemReceiptStore(Path(tmp))
            env_simple = build_receipt_envelope(
                envelope_id="simple-1",
                receipt_kind="test",
                actor=ReceiptActor(actor_id="a", actor_kind=ReceiptActorKind.RUNTIME),
                subject=ReceiptSubject(
                    subject_id="s", subject_kind=ReceiptSubjectKind.TOOL_INVOCATION
                ),
                decision=None,
                created_at="2026-01-01T00:00:00Z",
            )
            store.append(env_simple)

            results = store.list()
            assert len(results) == 1
            assert results[0].envelope_id == "simple-1"


class TestLookupHelpers:
    def test_find_by_decision_id_locates_envelope(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = FilesystemReceiptStore(Path(tmp))
            env = _make_envelope(
                envelope_id="env-a", governance_decision_id="gd-find-me"
            )
            store.append(env)

            results = store.find_by_decision_id("gd-find-me")
            assert len(results) == 1
            assert results[0].envelope_id == "env-a"

    def test_find_by_decision_id_returns_empty_for_nonexistent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = FilesystemReceiptStore(Path(tmp))
            env = _make_envelope(governance_decision_id="gd-other")
            store.append(env)

            results = store.find_by_decision_id("gd-nonexistent")
            assert len(results) == 0

    def test_find_by_surface_locates_correct_envelopes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = FilesystemReceiptStore(Path(tmp))
            store.append(_make_envelope(envelope_id="env-mcp", surface="mcp"))
            store.append(_make_envelope(envelope_id="env-cli", surface="cli"))

            results = store.find_by_surface("mcp")
            assert len(results) == 1
            assert results[0].envelope_id == "env-mcp"

    def test_find_by_capability_id_locates_envelope(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = FilesystemReceiptStore(Path(tmp))
            env = _make_envelope(envelope_id="env-cap", capability_id="rig.write_file")
            store.append(env)

            results = store.find_by_capability_id("rig.write_file")
            assert len(results) == 1
            assert results[0].envelope_id == "env-cap"

    def test_find_by_authority_tier_locates_envelope(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = FilesystemReceiptStore(Path(tmp))
            env = _make_envelope(
                envelope_id="env-tier", authority_tier="remote_mutation"
            )
            store.append(env)

            results = store.find_by_authority_tier("remote_mutation")
            assert len(results) == 1
            assert results[0].envelope_id == "env-tier"

    def test_find_by_surface_with_old_row_gracefully_skips(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = FilesystemReceiptStore(Path(tmp))
            old_line = json.dumps({
                "envelope_id": "env-old-no-surface",
                "receipt_kind": "old",
                "session_id": None,
                "created_at": "2026-01-01T00:00:00Z",
            })
            with (Path(tmp) / "manifest.jsonl").open("a") as f:
                f.write(old_line + "\n")

            env_old = build_receipt_envelope(
                envelope_id="env-old-no-surface",
                receipt_kind="old",
                actor=ReceiptActor(actor_id="a", actor_kind=ReceiptActorKind.RUNTIME),
                subject=ReceiptSubject(
                    subject_id="s", subject_kind=ReceiptSubjectKind.TOOL_INVOCATION
                ),
                decision=None,
                created_at="2026-01-01T00:00:00Z",
            )
            store_old = FilesystemReceiptStore(Path(tmp))
            store_old.append(env_old)

            results = store_old.find_by_surface("mcp")
            assert len(results) == 0


class TestReceiptEnvelopeRequestId:
    def test_request_id_present_on_envelope(self) -> None:
        env = _make_envelope(request_id="req-abc")
        assert env.request_id == "req-abc"

    def test_request_id_optional_defaults_to_none(self) -> None:
        env = build_receipt_envelope(
            receipt_kind="test",
            actor=ReceiptActor(actor_id="a", actor_kind=ReceiptActorKind.RUNTIME),
            subject=ReceiptSubject(
                subject_id="s", subject_kind=ReceiptSubjectKind.TOOL_INVOCATION
            ),
            decision=None,
        )
        assert env.request_id is None

    def test_request_id_survives_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = FilesystemReceiptStore(Path(tmp))
            env = _make_envelope(request_id="req-roundtrip", envelope_id="env-rt")
            store.append(env)

            retrieved = store.get("env-rt")
            assert retrieved is not None
            assert retrieved.request_id == "req-roundtrip"


class TestOrphanCorruptionDiagnostics:
    def test_clean_store_has_no_diagnostics(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = FilesystemReceiptStore(Path(tmp))
            env = _make_envelope()
            store.append(env)

            diags = store.diagnose()
            assert len(diags) == 0

    def test_corrupted_shard_is_detected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = FilesystemReceiptStore(Path(tmp))
            env = _make_envelope(envelope_id="env-corrupt")
            shard_path = store._envelope_path("env-corrupt")
            shard_path.parent.mkdir(parents=True, exist_ok=True)
            shard_path.write_text("not valid json", encoding="utf-8")

            manifest_line = json.dumps({
                "envelope_id": "env-corrupt",
                "receipt_kind": "governance_decision",
                "session_id": None,
                "created_at": "2026-01-01T00:00:00Z",
            })
            with (Path(tmp) / "manifest.jsonl").open("a") as f:
                f.write(manifest_line + "\n")

            diags = store.diagnose()
            corrupted = [d for d in diags if d.kind == "corrupted_shard"]
            assert len(corrupted) >= 1
            assert corrupted[0].envelope_id == "env-corrupt"

    def test_orphaned_shard_is_detected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = FilesystemReceiptStore(Path(tmp))
            shard_path = store._envelope_path("env-orphan")
            shard_path.parent.mkdir(parents=True, exist_ok=True)
            env_data = _make_envelope(envelope_id="env-orphan")
            shard_path.write_text(
                json.dumps(env_data.model_dump(mode="json"), sort_keys=True),
                encoding="utf-8",
            )

            diags = store.diagnose()
            orphans = [d for d in diags if d.kind == "orphaned_shard"]
            assert len(orphans) >= 1
            assert orphans[0].envelope_id == "env-orphan"

    def test_missing_shard_is_detected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = FilesystemReceiptStore(Path(tmp))
            manifest_line = json.dumps({
                "envelope_id": "env-missing-shard",
                "receipt_kind": "governance_decision",
                "session_id": None,
                "created_at": "2026-01-01T00:00:00Z",
            })
            with (Path(tmp) / "manifest.jsonl").open("a") as f:
                f.write(manifest_line + "\n")

            diags = store.diagnose()
            missing = [d for d in diags if d.kind == "missing_shard"]
            assert len(missing) >= 1
            assert missing[0].envelope_id == "env-missing-shard"

    def test_manifest_diagnostic_to_dict(self) -> None:
        d = ManifestDiagnostic(
            kind="corrupted_shard",
            envelope_id="env-1",
            manifest_line=5,
            reason="JSON decode failure",
        )
        dct = d.to_dict()
        assert dct["kind"] == "corrupted_shard"
        assert dct["envelope_id"] == "env-1"
        assert dct["manifest_line"] == 5
        assert "JSON decode" in str(dct["reason"])

    def test_corrupted_manifest_line_is_detected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = FilesystemReceiptStore(Path(tmp))
            with (Path(tmp) / "manifest.jsonl").open("a") as f:
                f.write("this is not json\n")

            diags = store.diagnose()
            corrupted = [d for d in diags if d.kind == "corrupted_manifest_line"]
            assert len(corrupted) >= 1

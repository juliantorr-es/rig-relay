from __future__ import annotations

import json
from pathlib import Path

from jsonschema import ValidationError, validate
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
READINESS_PATH = (
    REPO_ROOT
    / "docs"
    / "json"
    / "governance"
    / "frontend_bridge_backend_v1_readiness.v1.json"
)
PAGE_SCHEMA_PATH = (
    REPO_ROOT / "docs" / "schemas" / "rig.documentation.page.v1.schema.json"
)


def _page_schema() -> dict:
    return json.loads(PAGE_SCHEMA_PATH.read_text(encoding="utf-8"))


@pytest.mark.real_artifact
class TestFrontendBridgeBackendV1Convergence:
    def test_readiness_artifact_exists(self) -> None:
        assert READINESS_PATH.exists(), (
            f"Readiness artifact not found at {READINESS_PATH}"
        )
        assert READINESS_PATH.is_file()

    def test_readiness_artifact_is_valid_json(self) -> None:
        raw = READINESS_PATH.read_text(encoding="utf-8")
        data = json.loads(raw)
        assert isinstance(data, dict)

    def test_readiness_artifact_schema_version_matches_conventions(self) -> None:
        data = json.loads(READINESS_PATH.read_text(encoding="utf-8"))
        assert data.get("schema_version") == "rig.documentation.page.v1", (
            f"Expected schema_version 'rig.documentation.page.v1', "
            f"got {data.get('schema_version')!r}"
        )

    def test_readiness_artifact_validates_against_page_schema(self) -> None:
        data = json.loads(READINESS_PATH.read_text(encoding="utf-8"))
        schema = _page_schema()
        try:
            validate(instance=data, schema=schema)
        except ValidationError as e:
            pytest.fail(f"Readiness artifact fails schema validation: {e}")

    def test_readiness_artifact_document_id_is_convention_compliant(self) -> None:
        data = json.loads(READINESS_PATH.read_text(encoding="utf-8"))
        doc_id = data.get("document_id", "")
        assert doc_id == "frontend-bridge-backend-v1-readiness", (
            f"Unexpected document_id: {doc_id!r}"
        )

    def test_readiness_artifact_has_required_sections(self) -> None:
        data = json.loads(READINESS_PATH.read_text(encoding="utf-8"))
        sections = data.get("sections", [])
        assert isinstance(sections, list)
        assert len(sections) > 0

        block_ids = {s.get("block_id") for s in sections}
        required_blocks = {"table-proofs", "table-deferred", "list-boundaries"}
        missing = required_blocks - block_ids
        assert not missing, f"Missing required section blocks: {missing}"

    def test_readiness_artifact_contains_all_four_schemas(self) -> None:
        data = json.loads(READINESS_PATH.read_text(encoding="utf-8"))
        sections_str = json.dumps(data.get("sections", []))
        assert "rig.relay.frontend_intent.v1" in sections_str
        assert "rig.relay.bridge_envelope.v1" in sections_str
        assert "rig.relay.backend_projection_patch.v1" in sections_str
        assert "rig.relay.bridge_lifecycle_event.v1" in sections_str

    def test_readiness_artifact_contains_all_implementation_files(self) -> None:
        data = json.loads(READINESS_PATH.read_text(encoding="utf-8"))
        sections_str = json.dumps(data.get("sections", []))
        impl_files = [
            "bridge_protocol.py",
            "bridge_refusals.py",
            "bridge_lifecycle_trace.py",
            "websocket_server.py",
            "intents.py",
            "projection.py",
        ]
        for f in impl_files:
            assert f in sections_str, f"Missing implementation file reference: {f}"

    def test_readiness_artifact_contains_all_frontend_files(self) -> None:
        data = json.loads(READINESS_PATH.read_text(encoding="utf-8"))
        sections_str = json.dumps(data.get("sections", []))
        frontend_files = ["projection.js", "envelope.js", "client.js"]
        for f in frontend_files:
            assert f in sections_str, f"Missing frontend file reference: {f}"

    def test_readiness_artifact_contains_all_eight_proofs(self) -> None:
        data = json.loads(READINESS_PATH.read_text(encoding="utf-8"))
        sections_str = json.dumps(data.get("sections", []))
        proofs = [
            "Trace propagation proof",
            "Refusal proof",
            "Lifecycle persistence proof",
            "Concurrency proof",
            "Thread-safety proof",
            "Progressive rendering proof",
            "Resource budget proof",
            "Content-light proof",
        ]
        for p in proofs:
            assert p in sections_str, f"Missing proof: {p}"

    def test_readiness_artifact_contains_deferred_seams(self) -> None:
        data = json.loads(READINESS_PATH.read_text(encoding="utf-8"))
        sections_str = json.dumps(data.get("sections", []))
        deferred_seams = [
            "WebSocketStream backpressure",
            "E2E browser tests",
            "Lifecycle file rotation",
            "External network budget",
        ]
        for s in deferred_seams:
            assert s in sections_str, f"Missing deferred seam: {s}"

    def test_readiness_artifact_contains_claim_boundaries(self) -> None:
        data = json.loads(READINESS_PATH.read_text(encoding="utf-8"))
        sections_str = json.dumps(data.get("sections", []))
        boundaries = [
            "GitHub provider",
            "Coordination store",
            "Release gate",
            "CI evidence",
            "OTel",
            "MCP",
            "ACP",
            "A2A",
            "SDK",
        ]
        for b in boundaries:
            assert b.lower() in sections_str.lower(), f"Missing claim boundary: {b}"

    def test_readiness_artifact_has_cpu_budget_section(self) -> None:
        data = json.loads(READINESS_PATH.read_text(encoding="utf-8"))
        sections_str = json.dumps(data.get("sections", []))
        assert "CPU Budget" in sections_str
        assert "counts" in sections_str
        assert "wall-clock" in sections_str
        assert "queue caps" in sections_str.lower()
        assert "coalesce" in sections_str.lower()

    def test_readiness_artifact_status_is_active(self) -> None:
        data = json.loads(READINESS_PATH.read_text(encoding="utf-8"))
        assert data.get("status") == "active"

    def test_readiness_artifact_has_toc_enabled(self) -> None:
        data = json.loads(READINESS_PATH.read_text(encoding="utf-8"))
        render = data.get("render", {})
        assert render.get("toc") is True
        assert render.get("search_index") is True

    def test_readiness_artifact_is_not_empty(self) -> None:
        raw = READINESS_PATH.read_text(encoding="utf-8")
        assert len(raw) > 1000, f"Expected substantial content, got {len(raw)} bytes"

    def test_readiness_artifact_no_raw_paths_or_secrets(self) -> None:
        raw = READINESS_PATH.read_text(encoding="utf-8")
        assert "/Users/" not in raw
        assert "/home/" not in raw
        assert "password" not in raw.lower()
        assert "secret_key" not in raw.lower()
        assert "api_key" not in raw.lower()

    def test_schema_in_governance_dir_follows_naming_convention(self) -> None:
        """All governance JSON files must follow *.{version}.json naming."""
        gov_dir = REPO_ROOT / "docs" / "json" / "governance"
        for path in gov_dir.glob("*.json"):
            name = path.name
            assert ".v1.json" in name or ".v2.json" in name, (
                f"Governance file {name} does not follow {'.v<N>.json'} naming"
            )

    def test_v1_convergence_cpu_budget_test_exists(self) -> None:
        cpu_budget_test = REPO_ROOT / "tests" / "desktop" / "test_cpu_budget.py"
        assert cpu_budget_test.exists(), "CPU budget test file not found"
        content = cpu_budget_test.read_text(encoding="utf-8")
        assert "CPU budget" in content or "coalesce" in content.lower()
        assert "MAX_PER_CONNECTION_QUEUE" in content

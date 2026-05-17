from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
VOCAB_PATH = REPO_ROOT / "docs" / "json" / "tracing" / "correlation_vocabulary.v1.json"
SCHEMA_PATH = (
    REPO_ROOT / "docs" / "schemas" / "rig.tracing.correlation_vocabulary.v1.schema.json"
)

REQUIRED_FIELDS = [
    "trace_id",
    "handshake_id",
    "frontend_session_id",
    "connection_id",
    "session_id",
    "tool_batch_id",
    "tool_call_id",
    "schema_id",
    "document_id",
    "event_sequence",
]

REQUIRED_FIELD_ATTRIBUTES = [
    "owner_component",
    "propagation_rules",
    "safe_to_log_classification",
]


@pytest.fixture
def vocab() -> dict:
    return json.loads(VOCAB_PATH.read_text(encoding="utf-8"))


@pytest.fixture
def vocab_fields(vocab: dict) -> dict[str, dict]:
    return {f["field_name"]: f for f in vocab["fields"]}


class TestCorrelationVocabularyExists:
    def test_vocabulary_json_exists(self) -> None:
        assert VOCAB_PATH.exists(), f"Missing {VOCAB_PATH}"

    def test_vocabulary_json_parses(self, vocab: dict) -> None:
        assert vocab["schema_version"] == "rig.tracing.correlation_vocabulary.v1"
        assert "fields" in vocab
        assert isinstance(vocab["fields"], list)
        assert len(vocab["fields"]) > 0

    def test_vocabulary_schema_exists(self) -> None:
        assert SCHEMA_PATH.exists(), f"Missing {SCHEMA_PATH}"


class TestRequiredFields:
    @pytest.mark.parametrize("field_name", REQUIRED_FIELDS)
    def test_required_field_present(
        self, vocab_fields: dict[str, dict], field_name: str
    ) -> None:
        assert field_name in vocab_fields, (
            f"Required field '{field_name}' missing from correlation vocabulary"
        )


class TestFieldAttributes:
    def test_every_field_has_owner(self, vocab: dict) -> None:
        for field in vocab["fields"]:
            assert field.get("owner_component"), (
                f"Field '{field['field_name']}' missing owner_component"
            )

    def test_every_field_has_propagation_rules(self, vocab: dict) -> None:
        for field in vocab["fields"]:
            assert field.get("propagation_rules"), (
                f"Field '{field['field_name']}' missing propagation_rules"
            )

    def test_every_field_has_safe_to_log_classification(self, vocab: dict) -> None:
        valid = {"safe", "safe_hashed_only", "restricted", "never"}
        for field in vocab["fields"]:
            classification = field.get("safe_to_log_classification")
            assert classification, (
                f"Field '{field['field_name']}' missing safe_to_log_classification"
            )
            assert classification in valid, (
                f"Field '{field['field_name']}' has invalid classification: {classification}"
            )

    def test_every_field_has_implementation_status(self, vocab: dict) -> None:
        valid = {"implemented", "partial", "missing", "planned"}
        for field in vocab["fields"]:
            status = field.get("current_implementation_status")
            assert status, (
                f"Field '{field['field_name']}' missing current_implementation_status"
            )
            assert status in valid, (
                f"Field '{field['field_name']}' invalid status: {status}"
            )


class TestFieldSemantics:
    def test_handshake_id_owner_is_backend(self, vocab_fields: dict[str, dict]) -> None:
        field = vocab_fields["handshake_id"]
        assert (
            "bridge_server" in field["owner_component"].lower()
            or "correlation" in field["owner_component"].lower()
        )

    def test_frontend_session_id_not_same_as_handshake_id(
        self, vocab_fields: dict[str, dict]
    ) -> None:
        hs = vocab_fields["handshake_id"]
        fs = vocab_fields["frontend_session_id"]
        assert fs["owner_component"] != hs["owner_component"]
        forbidden = fs.get("forbidden_values", [])
        assert "handshake_id value" in forbidden or "auth token value" in forbidden

    def test_trace_id_is_required(self, vocab_fields: dict[str, dict]) -> None:
        assert vocab_fields["trace_id"]["required_optional"] == "required"

    def test_trace_id_is_safe(self, vocab_fields: dict[str, dict]) -> None:
        assert vocab_fields["trace_id"]["safe_to_log_classification"] == "safe"

    def test_wall_time_is_required(self, vocab_fields: dict[str, dict]) -> None:
        assert vocab_fields["wall_time"]["required_optional"] == "required"

    def test_no_field_has_token_in_forbidden_values(
        self, vocab_fields: dict[str, dict]
    ) -> None:
        for name, field in vocab_fields.items():
            forbidden = field.get("forbidden_values", [])
            for fv in forbidden:
                is_auth_token = "auth token" in str(fv).lower()
                if is_auth_token:
                    assert name == "frontend_session_id", (
                        f"Field '{name}' lists auth token in forbidden_values — only frontend_session_id may"
                    )

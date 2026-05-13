"""Tests for MCP Night demo fixtures — schema validation, redaction, content-light."""

from __future__ import annotations

import json
from pathlib import Path
from typing import ClassVar

import jsonschema

from rig_relay.evidence.redaction import assert_remote_safe, classify_shareable_field

DEMO_FIXTURES_DIR = (
    Path(__file__).resolve().parent.parent.parent / "docs" / "demo" / "fixtures"
)
SCHEMAS_DIR = Path(__file__).resolve().parent.parent.parent / "docs" / "schemas"

OBSERVATION_FIXTURE = DEMO_FIXTURES_DIR / "model-observation-demo.json"
RANKING_FIXTURE = DEMO_FIXTURES_DIR / "provider-ranking-demo.json"

OBSERVATION_SCHEMA = SCHEMAS_DIR / "rig.relay.model_observation.v1.schema.json"
RANKING_SCHEMA = SCHEMAS_DIR / "rig.relay.provider_ranking_snapshot.v1.schema.json"


def _load_json(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


class TestDemoFixturesExist:
    def test_observation_fixture_exists(self) -> None:
        assert OBSERVATION_FIXTURE.is_file(), (
            f"Missing observation fixture: {OBSERVATION_FIXTURE}"
        )

    def test_ranking_fixture_exists(self) -> None:
        assert RANKING_FIXTURE.is_file(), f"Missing ranking fixture: {RANKING_FIXTURE}"


class TestObservationSchemaValidation:
    def test_demo_observation_validates(self) -> None:
        data = _load_json(OBSERVATION_FIXTURE)
        schema = _load_json(OBSERVATION_SCHEMA)
        jsonschema.validate(data, schema)

    def test_demo_observation_has_content_light_guarantee(self) -> None:
        data = _load_json(OBSERVATION_FIXTURE)
        assert data.get("content_light_guarantee") is True

    def test_demo_observation_required_fields_present(self) -> None:
        data = _load_json(OBSERVATION_FIXTURE)
        for field in (
            "schema_version",
            "observation_id",
            "created_at",
            "task_kind",
            "task_fingerprint",
            "provider_kind",
            "provider_name",
            "model_id",
            "backend",
            "tool_call_count",
            "tool_success_count",
            "validation_status",
            "user_outcome",
            "content_light_guarantee",
        ):
            assert field in data, f"Missing required field: {field}"

    def test_demo_observation_has_correct_schema_version(self) -> None:
        data = _load_json(OBSERVATION_FIXTURE)
        assert data["schema_version"] == "rig.relay.model_observation.v1"


class TestRankingSchemaValidation:
    def test_demo_ranking_validates(self) -> None:
        data = _load_json(RANKING_FIXTURE)
        schema = _load_json(RANKING_SCHEMA)
        jsonschema.validate(data, schema)

    def test_demo_ranking_has_low_confidence_warning(self) -> None:
        data = _load_json(RANKING_FIXTURE)
        assert data["confidence_level"] == "low"
        warnings = data.get("warnings", [])
        assert len(warnings) > 0
        assert any("Low sample count" in w for w in warnings)

    def test_demo_ranking_has_required_fields(self) -> None:
        data = _load_json(RANKING_FIXTURE)
        for field in (
            "schema_version",
            "ranking_id",
            "created_at",
            "task_kind",
            "sample_count",
            "provider_scores",
            "model_scores",
            "confidence_level",
        ):
            assert field in data, f"Missing required field: {field}"

    def test_demo_ranking_has_correct_schema_version(self) -> None:
        data = _load_json(RANKING_FIXTURE)
        assert data["schema_version"] == "rig.relay.provider_ranking_snapshot.v1"

    def test_demo_ranking_scores_within_range(self) -> None:
        data = _load_json(RANKING_FIXTURE)
        for entry in data.get("provider_scores", []):
            score = entry.get("overall_score", 0)
            assert 0.0 <= score <= 1.0, f"Score {score} out of range"
        for entry in data.get("model_scores", []):
            score = entry.get("overall_score", 0)
            assert 0.0 <= score <= 1.0, f"Score {score} out of range"


class TestRedactionIntegration:
    def test_demo_observation_safe_for_remote(self) -> None:
        data = _load_json(OBSERVATION_FIXTURE)
        safe = assert_remote_safe(data)
        assert safe["content_light_guarantee"]


class TestNoForbiddenContent:
    """Verify fixture contains no forbidden fields or values."""

    FORBIDDEN_KEYS: ClassVar[set[str]] = {
        "raw_prompt",
        "prompt",
        "raw_model_output",
        "model_output",
        "source_code",
        "diff",
        "stdout",
        "stderr",
        "api_key",
        "access_token",
        "refresh_token",
        "private_path",
    }

    def _check_forbidden_keys(self, data: dict, path: str = "") -> list[str]:
        violations: list[str] = []
        for key, value in data.items():
            full_key = f"{path}.{key}" if path else key
            if key in self.FORBIDDEN_KEYS:
                violations.append(f"{full_key}: forbidden key")
            if isinstance(value, dict):
                violations.extend(self._check_forbidden_keys(value, full_key))
            if isinstance(value, list):
                for i, item in enumerate(value):
                    if isinstance(item, dict):
                        violations.extend(
                            self._check_forbidden_keys(item, f"{full_key}[{i}]")
                        )
        return violations

    def test_observation_no_forbidden_fields(self) -> None:
        data = _load_json(OBSERVATION_FIXTURE)
        violations = self._check_forbidden_keys(data)
        assert len(violations) == 0, f"Forbidden fields found: {violations}"

    def test_ranking_no_forbidden_fields(self) -> None:
        data = _load_json(RANKING_FIXTURE)
        violations = self._check_forbidden_keys(data)
        assert len(violations) == 0, f"Forbidden fields found: {violations}"

    def test_observation_redaction_classifies_bare_prompt_as_forbid(self) -> None:
        result = classify_shareable_field("raw_prompt", "some text")
        assert result == "forbid"

    def test_observation_redaction_classifies_bare_output_as_forbid(self) -> None:
        result = classify_shareable_field("model_output", "output")
        assert result == "forbid"


class TestDemoGuide:
    """Verify demo guide references are consistent."""

    GUIDE_PATH = (
        Path(__file__).resolve().parent.parent.parent
        / "docs"
        / "demo"
        / "mcp-night-development-harness-demo.md"
    )

    def test_demo_guide_exists(self) -> None:
        assert self.GUIDE_PATH.is_file()

    def test_demo_guide_includes_trust_line(self) -> None:
        text = self.GUIDE_PATH.read_text(encoding="utf-8")
        assert "no raw prompts" in text.lower()
        assert "no raw model outputs" in text.lower()
        assert "no source code" in text.lower()
        assert "no secrets" in text.lower()

    def test_demo_guide_mentions_no_protected_controls(self) -> None:
        text = self.GUIDE_PATH.read_text(encoding="utf-8")
        assert "bash" in text
        assert "write_file" in text
        # Should note they are absent
        assert "absent" in text.lower()

    def test_demo_guide_mentions_observation_fixture(self) -> None:
        text = self.GUIDE_PATH.read_text(encoding="utf-8")
        assert "model-observation-demo.json" in text

    def test_demo_guide_mentions_ranking_fixture(self) -> None:
        text = self.GUIDE_PATH.read_text(encoding="utf-8")
        assert "provider-ranking-demo.json" in text


class TestSchemaFiles:
    def test_schema_files_exist(self) -> None:
        assert OBSERVATION_SCHEMA.is_file()
        assert RANKING_SCHEMA.is_file()

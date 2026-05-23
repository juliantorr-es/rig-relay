"""Red-first tests for schema validator strict mode.

Production validate_schema(strict=True) at scripts/rig_relay_validate_schemas.py:96
correctly uses jsonschema.Draft7Validator.check_schema(), but strict=True has
ZERO test coverage in tests/coordination/test_schema_validation.py.

Wave C from docs/json/audits/test_suite_fake_green_audit.v1.json.
"""

from __future__ import annotations

import json
from pathlib import Path

from scripts.rig_relay_validate_schemas import validate_all_schemas, validate_schema

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SCHEMA_DIR = REPO_ROOT / "docs" / "schemas"


class TestStrictModeNotExercised:
    """RED-FIRST: Prove that strict mode has no test coverage.

    The existing tests never call validate_schema(..., strict=True).
    """

    def test_strict_valid_schema_passes(self, tmp_path: Path) -> None:
        s = tmp_path / "valid.schema.json"
        s.write_text(
            json.dumps({
                "$schema": "http://json-schema.org/draft-07/schema#",
                "type": "object",
                "properties": {"name": {"type": "string"}},
            })
        )
        is_valid, errors = validate_schema(s, strict=True)
        assert is_valid, f"Valid schema should pass strict validation: {errors}"

    def test_strict_malformed_schema_fails(self, tmp_path: Path) -> None:
        s = tmp_path / "malformed.schema.json"
        s.write_text(
            json.dumps({
                "$schema": "http://json-schema.org/draft-07/schema#",
                "type": "not_a_real_type",
            })
        )
        is_valid, errors = validate_schema(s, strict=True)
        assert not is_valid, (
            f"Malformed schema with invalid type should fail strict validation. "
            f"Got is_valid={is_valid}, errors={errors}"
        )

    def test_strict_empty_schema_is_technically_valid(self, tmp_path: Path) -> None:
        """Empty schema {} is valid per Draft 7 metaschema — matches everything."""
        s = tmp_path / "empty.schema.json"
        s.write_text(json.dumps({}))
        is_valid, errors = validate_schema(s, strict=True)
        assert is_valid, (
            f"Empty schema {{}} is technically valid per Draft 7. "
            f"Got is_valid={is_valid}, errors={errors}"
        )

    def test_strict_validates_draft7_types(self, tmp_path: Path) -> None:
        s = tmp_path / "int.schema.json"
        s.write_text(
            json.dumps({
                "$schema": "http://json-schema.org/draft-07/schema#",
                "type": "integer",
            })
        )
        is_valid, errors = validate_schema(s, strict=True)
        assert is_valid, f"Valid integer schema should pass: {errors}"

    def test_strict_rejects_invalid_draft_ref(self, tmp_path: Path) -> None:
        s = tmp_path / "bad-draft.schema.json"
        s.write_text(
            json.dumps({
                "$schema": "http://json-schema.org/draft-99/schema#",
                "type": "object",
            })
        )
        is_valid, errors = validate_schema(s, strict=True)
        assert not is_valid, (
            f"Invalid $schema draft should fail. Got is_valid={is_valid}, errors={errors}"
        )

    def test_strict_validates_real_schema_inventory(self) -> None:
        """RED-FIRST: strict validation over actual docs/schemas/ inventory.

        This ensures check_schema() validates ALL existing canonical schemas
        against the Draft 7 metaschema.
        """
        all_valid, all_errors, total, failed = validate_all_schemas(
            SCHEMA_DIR, strict=True
        )
        assert total >= 30, f"Expected at least 30 schemas, got {total}"
        assert all_valid, (
            f"Strict metaschema validation failed for {failed}/{total} schemas:\n"
            + "\n".join(all_errors[:20])
        )
        assert failed == 0, f"Expected 0 strict-validation failures, got {failed}"

    def test_strict_mode_catches_metaschema_violations(self, tmp_path: Path) -> None:
        """Prove strict mode catches things non-strict mode doesn't.

        Non-strict mode only checks JSON parseability and Python token contamination.
        Strict mode must validate against the Draft 7 metaschema via check_schema().
        """
        invalid_but_parseable = {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "type": "object",
            "properties": "not_an_object",  # properties must be an object
        }
        s = tmp_path / "bad-properties.schema.json"
        s.write_text(json.dumps(invalid_but_parseable))

        non_strict_valid, _ = validate_schema(s, strict=False)
        strict_valid, strict_errors = validate_schema(s, strict=True)

        assert non_strict_valid, "Non-strict should pass for valid JSON"
        assert not strict_valid, (
            "RED: Strict mode should reject 'properties' that is not an object. "
            f"Got is_valid={strict_valid}, errors={strict_errors}"
        )

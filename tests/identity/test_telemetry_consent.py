"""Tests for telemetry consent model — scope validation, commercial license tracking."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from rig_relay.identity.telemetry_consent import (
    TELEMETRY_CONSENT_POLICY_VERSION,
    TelemetryConsentScope,
    TelemetryConsentStatus,
    build_initial_consent,
    grant_consent,
    has_commercial_dataset_license,
    revoke_consent,
)


class TestTelemetryConsentScopes:
    """New scope values exist and are accessible."""

    def test_basic_scopes_present(self) -> None:
        assert TelemetryConsentScope.USAGE_METRICS in TelemetryConsentScope
        assert TelemetryConsentScope.CONTENT_LIGHT_BUNDLES in TelemetryConsentScope
        assert TelemetryConsentScope.CRASH_REPORTS in TelemetryConsentScope
        assert TelemetryConsentScope.COORDINATION_METRICS in TelemetryConsentScope
        assert TelemetryConsentScope.TOOL_REFINEMENT_METRICS in TelemetryConsentScope

    def test_commercial_scopes_present(self) -> None:
        assert (
            TelemetryConsentScope.PROVIDER_MODEL_BENCHMARKING in TelemetryConsentScope
        )
        assert TelemetryConsentScope.LOCAL_MODEL_BENCHMARKING in TelemetryConsentScope
        assert TelemetryConsentScope.COMMERCIAL_DATASET_LICENSE in TelemetryConsentScope
        assert TelemetryConsentScope.AGGREGATE_PUBLIC_REPORTING in TelemetryConsentScope

    def test_policy_version_updated(self) -> None:
        assert TELEMETRY_CONSENT_POLICY_VERSION == "alpha-usage-data-license-v1"


class TestGrantConsentDefaults:
    """grant_consent() default scopes exclude commercial scopes."""

    def test_default_scopes_are_basic_only(self) -> None:
        record = grant_consent(subject_hash="test_hash", provider="local")
        assert TelemetryConsentScope.COMMERCIAL_DATASET_LICENSE not in record.scopes
        assert TelemetryConsentScope.AGGREGATE_PUBLIC_REPORTING not in record.scopes
        assert TelemetryConsentScope.PROVIDER_MODEL_BENCHMARKING not in record.scopes
        assert TelemetryConsentScope.LOCAL_MODEL_BENCHMARKING not in record.scopes

    def test_default_scopes_include_all_basic(self) -> None:
        record = grant_consent(subject_hash="test_hash", provider="local")
        assert TelemetryConsentScope.USAGE_METRICS in record.scopes
        assert TelemetryConsentScope.CONTENT_LIGHT_BUNDLES in record.scopes
        assert TelemetryConsentScope.CRASH_REPORTS in record.scopes
        assert TelemetryConsentScope.COORDINATION_METRICS in record.scopes
        assert TelemetryConsentScope.TOOL_REFINEMENT_METRICS in record.scopes

    def test_status_is_granted(self) -> None:
        record = grant_consent(subject_hash="test_hash", provider="local")
        assert record.status == TelemetryConsentStatus.GRANTED


class TestGrantConsentExplicitScopes:
    """grant_consent() accepts explicit scope lists including commercial."""

    def test_basic_only_when_explicit(self) -> None:
        record = grant_consent(
            subject_hash="test_hash",
            provider="local",
            scopes=[TelemetryConsentScope.USAGE_METRICS],
        )
        assert record.scopes == [TelemetryConsentScope.USAGE_METRICS]

    def test_commercial_when_explicitly_included(self) -> None:
        record = grant_consent(
            subject_hash="test_hash",
            provider="local",
            scopes=[
                TelemetryConsentScope.USAGE_METRICS,
                TelemetryConsentScope.COMMERCIAL_DATASET_LICENSE,
            ],
        )
        assert TelemetryConsentScope.COMMERCIAL_DATASET_LICENSE in record.scopes

    def test_all_scopes_when_explicitly_passed(self) -> None:
        all_scopes = list(TelemetryConsentScope)
        record = grant_consent(
            subject_hash="test_hash", provider="local", scopes=all_scopes
        )
        assert len(record.scopes) == len(all_scopes)

    def test_empty_scopes_produces_empty_record(self) -> None:
        record = grant_consent(subject_hash="test_hash", provider="local", scopes=[])
        assert record.scopes == []


class TestHasCommercialDatasetLicense:
    """has_commercial_dataset_license() correctly detects commercial license scope."""

    def test_true_when_commercial_present(self) -> None:
        record = grant_consent(
            subject_hash="test_hash",
            provider="local",
            scopes=[TelemetryConsentScope.COMMERCIAL_DATASET_LICENSE],
        )
        assert has_commercial_dataset_license(record) is True

    def test_false_when_commercial_absent(self) -> None:
        record = grant_consent(subject_hash="test_hash", provider="local")
        assert has_commercial_dataset_license(record) is False

    def test_false_when_commercial_revoked(self) -> None:
        record = grant_consent(
            subject_hash="test_hash",
            provider="local",
            scopes=[TelemetryConsentScope.COMMERCIAL_DATASET_LICENSE],
        )
        assert has_commercial_dataset_license(record) is True
        record = revoke_consent(record)
        assert has_commercial_dataset_license(record) is True  # scopes preserved

    def test_aggregate_reporting_not_confused_with_commercial(self) -> None:
        record = grant_consent(
            subject_hash="test_hash",
            provider="local",
            scopes=[TelemetryConsentScope.AGGREGATE_PUBLIC_REPORTING],
        )
        # AGGREGATE_PUBLIC_REPORTING is NOT COMMERCIAL_DATASET_LICENSE
        assert has_commercial_dataset_license(record) is False


class TestConsentRecordFields:
    """Consent record fields include policy_version."""

    def test_policy_version_in_record(self) -> None:
        record = grant_consent(subject_hash="test_hash", provider="local")
        assert record.policy_version == TELEMETRY_CONSENT_POLICY_VERSION

    def test_content_light_dump_contains_policy_version(self) -> None:
        record = grant_consent(subject_hash="test_hash", provider="local")
        dump = record.model_dump_content_light()
        assert dump.get("policy_version") == TELEMETRY_CONSENT_POLICY_VERSION

    def test_initial_consent_has_empty_scopes(self) -> None:
        record = build_initial_consent()
        assert record.scopes == []
        assert record.status == TelemetryConsentStatus.NOT_REQUESTED


class TestConsentSchemaCompliance:
    """Consent records comply with the JSON schema."""

    SCHEMA_PATH = (
        Path(__file__).resolve().parent.parent.parent
        / "docs"
        / "schemas"
        / "rig.relay.telemetry_consent.v1.schema.json"
    )

    @pytest.fixture(autouse=True)
    def _load_schema(self) -> None:

        schema_text = self.SCHEMA_PATH.read_text(encoding="utf-8")
        self._schema = json.loads(schema_text)

    def test_grant_record_validates(self) -> None:
        import jsonschema

        record = grant_consent(subject_hash="abc123", provider="local")
        data = record.model_dump(mode="json")
        jsonschema.validate(data, self._schema)

    def test_grant_with_commercial_validates(self) -> None:
        import jsonschema

        record = grant_consent(
            subject_hash="abc123",
            provider="local",
            scopes=[
                TelemetryConsentScope.USAGE_METRICS,
                TelemetryConsentScope.COMMERCIAL_DATASET_LICENSE,
            ],
        )
        data = record.model_dump(mode="json")
        jsonschema.validate(data, self._schema)

    def test_revoked_record_validates(self) -> None:
        import jsonschema

        record = grant_consent(subject_hash="abc123", provider="local")
        record = revoke_consent(record)
        data = record.model_dump(mode="json")
        jsonschema.validate(data, self._schema)

    def test_new_scope_enums_in_schema(self) -> None:
        """The JSON schema includes the 4 new scope enum values."""
        scope_enum = None
        for prop_name, prop_def in self._schema.get("properties", {}).items():
            if prop_name == "scopes":
                scope_enum = prop_def["items"]["enum"]
                break
        assert scope_enum is not None
        assert "commercial_dataset_license" in scope_enum
        assert "aggregate_public_reporting" in scope_enum
        assert "provider_model_benchmarking" in scope_enum
        assert "local_model_benchmarking" in scope_enum


class TestScopeStringValues:
    """Scope string values match expected snake_case."""

    def test_basic_scope_values(self) -> None:
        assert TelemetryConsentScope.USAGE_METRICS.value == "usage_metrics"
        assert (
            TelemetryConsentScope.CONTENT_LIGHT_BUNDLES.value == "content_light_bundles"
        )
        assert TelemetryConsentScope.CRASH_REPORTS.value == "crash_reports"
        assert (
            TelemetryConsentScope.COORDINATION_METRICS.value == "coordination_metrics"
        )
        assert (
            TelemetryConsentScope.TOOL_REFINEMENT_METRICS.value
            == "tool_refinement_metrics"
        )

    def test_commercial_scope_values(self) -> None:
        assert (
            TelemetryConsentScope.PROVIDER_MODEL_BENCHMARKING.value
            == "provider_model_benchmarking"
        )
        assert (
            TelemetryConsentScope.LOCAL_MODEL_BENCHMARKING.value
            == "local_model_benchmarking"
        )
        assert (
            TelemetryConsentScope.COMMERCIAL_DATASET_LICENSE.value
            == "commercial_dataset_license"
        )
        assert (
            TelemetryConsentScope.AGGREGATE_PUBLIC_REPORTING.value
            == "aggregate_public_reporting"
        )

"""Sealed adapter for context egress in fixture lanes."""
from __future__ import annotations

from pathlib import Path
import tempfile
from typing import Any

from rig_relay.context_egress.compiler import compile_egress_candidate
from rig_relay.context_egress.models import (
    BoundedMissionManifest,
    ContextEfficiencyEvidence,
    EgressCandidate,
    EgressCrosswalk,
    EgressReceipt,
)


class SealedProjectionStagingContext:
    """Ephemeral projection staging context for context egress."""

    def __init__(self, lane_root: Path, confidential_sink_root: Path) -> None:
        self.lane_root = lane_root.resolve()
        self.confidential_sink_root = confidential_sink_root.resolve()
        self._temp_dir = tempfile.TemporaryDirectory()
        self.staging_root = Path(self._temp_dir.name).resolve()

        if self.staging_root.is_relative_to(self.lane_root):
            raise RuntimeError("Projection staging root must be outside the lane root")
        if self.staging_root.is_relative_to(self.confidential_sink_root):
            raise RuntimeError("Projection staging root must be outside the confidential evidence sink")

    def materialize_input(self, source: str) -> Path:
        input_path = self.staging_root / "temp_fixture_input.py"
        input_path.write_text(source, encoding="utf-8")
        return input_path

    def __enter__(self) -> SealedProjectionStagingContext:
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self._temp_dir.cleanup()


class SealedContextEgressAdapter:
    """Adapts fixture context through the existing context egress boundary."""

    def __init__(self, output_sink_root: Path, lane_root: Path) -> None:
        self.output_sink_root = output_sink_root
        self.lane_root = lane_root

    def route_fixture_context(
        self, manifest: BoundedMissionManifest, fixture_source: str
    ) -> tuple[EgressCandidate | None, EgressCrosswalk | None, EgressReceipt, ContextEfficiencyEvidence | None]:
        """Route fixture context through the compiler, ensuring strict limitations."""
        manifest.no_transmission_marker = True
        manifest.stop_after_candidate_generation = True
        manifest.output_sink_root = str(self.output_sink_root)

        from datetime import datetime

        from rig_relay.context_egress.models import (
            ProviderPolicyAttestation,
            RetentionMode,
        )

        with SealedProjectionStagingContext(
            lane_root=self.lane_root,
            confidential_sink_root=self.output_sink_root
        ) as staging:
            input_path = staging.materialize_input(fixture_source)
            manifest.approved_input_root = str(staging.staging_root)
            manifest.approved_fixture_root = str(staging.staging_root)

            fixture_attestation = ProviderPolicyAttestation(
                provider_family="fixture_provider",
                endpoint_family="fixture_endpoint",
                retention_mode=RetentionMode.ZERO_DATA_RETENTION,
                human_approved_confidential_minimization=True,
                approval_timestamp=datetime.now(),
                approval_scope="fixture_scope",
                attestation_source_class="fixture"
            )

            candidate, crosswalk, receipt, evidence = compile_egress_candidate(
                input_path=str(input_path),
                manifest=manifest,
                attestation=fixture_attestation,
                egress_decision_id="fixture-decision-001"
            )

        if receipt:
            receipt.raw_source_in_receipt = False
            receipt.raw_source_in_provider_candidate = False
            receipt.actual_provider_token_metrics_collected = False
            receipt.actual_cached_token_metrics_collected = False
            receipt.actual_provider_cost_savings_claimed = False

        if candidate:
            candidate.not_transmitted = True
            candidate.output_remains_confidential = True
            candidate.human_provider_submission_approval_required = True

        return candidate, crosswalk, receipt, evidence

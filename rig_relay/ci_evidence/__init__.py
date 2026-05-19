"""CI Evidence Surface v1 — public API.

Produces schema-governed CI run, job, artifact index, and verdict evidence
artifacts under .build/rig-relay/evidence/. Works in GitHub Actions,
Codespaces/lab, and local execution.

Usage:
    from rig_relay.ci_evidence import produce_ci_evidence
    result = produce_ci_evidence()

    from rig_relay.ci_evidence import validate_ci_evidence_surface
    verdict = validate_ci_evidence_surface(run_id="<run_id>")

    from rig_relay.ci_evidence import classify_runner_environment
    runner = classify_runner_environment(os.environ)
"""

from __future__ import annotations

from rig_relay.ci_evidence._producer import (
    CIVerdict,
    RunContext,
    classify_release_context,
    classify_runner_environment,
    collect_artifact_index,
    compute_sha256,
    detect_run_context,
    index_artifacts,
    load_ci_verdict,
    produce_ci_evidence,
    validate_ci_evidence,
    validate_ci_evidence_surface,
    write_ci_event,
)

__all__ = [
    "CIVerdict",
    "RunContext",
    "classify_release_context",
    "classify_runner_environment",
    "collect_artifact_index",
    "compute_sha256",
    "detect_run_context",
    "index_artifacts",
    "load_ci_verdict",
    "produce_ci_evidence",
    "validate_ci_evidence",
    "validate_ci_evidence_surface",
    "write_ci_event",
]

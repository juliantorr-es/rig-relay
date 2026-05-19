"""CI Evidence Surface v1 — public API.

Produces schema-governed CI run, job, artifact index, and verdict evidence
artifacts under .build/rig-relay/ci/<run_id>/. Works in GitHub Actions,
Codespaces/lab, and local execution.

Usage:
    from rig_relay.ci_evidence import produce_ci_evidence
    result = produce_ci_evidence()

    from rig_relay.ci_evidence import validate_ci_evidence
    verdict = validate_ci_evidence(run_id="<run_id>")
"""

from __future__ import annotations

from rig_relay.ci_evidence._producer import (
    CIVerdict,
    RunContext,
    detect_run_context,
    index_artifacts,
    produce_ci_evidence,
    validate_ci_evidence,
)

__all__ = [
    "CIVerdict",
    "RunContext",
    "detect_run_context",
    "index_artifacts",
    "produce_ci_evidence",
    "validate_ci_evidence",
]

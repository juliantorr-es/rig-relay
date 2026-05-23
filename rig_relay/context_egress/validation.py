from __future__ import annotations

import json
from pathlib import Path

from rig_relay.core.paths._confidential_artifacts import (
    resolve_confidential_artifact_root,
)


def write_validation_report(
    report_data: dict, egress_decision_id: str, repo_root: Path | None = None
) -> None:
    """Writes the local fixture-validation report for the context egress compiler token efficiency addendum.
    Never scans real repository content; only accepts structured fixture-run evidence.
    """
    base_dir = (
        resolve_confidential_artifact_root(repo_root)
        / "context_egress"
        / egress_decision_id
    )
    base_dir.mkdir(parents=True, exist_ok=True)
    report_path = (
        base_dir / "context_egress_token_efficiency_addendum_v1_validation.json"
    )
    report_path.write_text(json.dumps(report_data, indent=2))

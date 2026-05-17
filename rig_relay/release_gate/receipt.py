"""Release Evidence Gate — canonical JSON receipt serialization.

Produces a deterministic JSON receipt from a GateResult. Every field ordering
is explicit (no dict key randomization). All values are JSON-safe primitives.
"""

from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path

from rig_relay.release_gate.models import GateResult


def serialize_gate_result(result: GateResult) -> str:
    receipt = _build_receipt_dict(result)
    return json.dumps(receipt, indent=2, sort_keys=False, ensure_ascii=False)


def write_receipt(result: GateResult, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(serialize_gate_result(result) + "\n", encoding="utf-8")
    return path


def _build_receipt_dict(result: GateResult) -> dict[str, object]:
    return {
        "schema_version": result.schema_version,
        "gate_id": result.gate_id,
        "repository": result.repository,
        "head_sha": result.head_sha,
        "branch": result.branch,
        "generated_at": result.generated_at,
        "overall_status": str(result.overall_status),
        "summary": asdict(result.summary),
        "checks": result.checks,
        "findings": result.findings,
        "artifacts": result.artifacts,
        "policy": result.policy,
    }

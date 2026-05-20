from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from rig_relay.enterprise.policy_engine import PolicyEngine, PolicyEvaluation

_ATTESTATION_KEY_MATERIAL = b"rig-relay-enterprise-attestation-v1-hkdf-salt"
_KDF_KEY_LENGTH = 32


def _canonicalize_evaluation(
    evaluation: PolicyEvaluation, engine: PolicyEngine
) -> bytes:
    data = engine.to_json(evaluation)
    return json.dumps(data, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _derive_signing_key(evaluation_bytes: bytes) -> bytes:
    info_bytes = (
        evaluation_bytes[:_KDF_KEY_LENGTH]
        if len(evaluation_bytes) >= _KDF_KEY_LENGTH
        else evaluation_bytes
    )
    hkdf = HKDF(
        algorithm=hashes.SHA256(),
        length=_KDF_KEY_LENGTH,
        salt=_ATTESTATION_KEY_MATERIAL,
        info=info_bytes,
    )
    return hkdf.derive(evaluation_bytes)


def _compute_signature(
    evaluation: PolicyEvaluation, engine: PolicyEngine, operator_id: str, signed_at: str
) -> str:
    canonical = _canonicalize_evaluation(evaluation, engine)
    key = _derive_signing_key(canonical)

    sign_data = canonical + operator_id.encode("utf-8") + signed_at.encode("utf-8")
    h = hashlib.sha256(key + sign_data)
    return h.hexdigest()


def _compute_evaluation_hash(evaluation: PolicyEvaluation, engine: PolicyEngine) -> str:
    canonical = _canonicalize_evaluation(evaluation, engine)
    return hashlib.sha256(canonical).hexdigest()


@dataclass(slots=True)
class Attestation:
    attestation_id: str
    policy_evaluation_id: str
    signed_by: str
    signed_at: str
    signature_hash: str
    acknowledged_gates: list[str]
    acknowledged_checks: list[str]
    content_light: bool = True


def sign_attestation(
    evaluation: PolicyEvaluation, operator_id: str, engine: PolicyEngine | None = None
) -> Attestation:
    eng = engine if engine is not None else PolicyEngine()
    evaluation_hash = _compute_evaluation_hash(evaluation, eng)
    signed_at = datetime.now(UTC).isoformat()
    signature = _compute_signature(evaluation, eng, operator_id, signed_at)

    acknowledged_gates = [r.gate_id for r in evaluation.gates if r.passed]
    acknowledged_checks = evaluation.operator_acknowledgements_required

    return Attestation(
        attestation_id=f"attest-{evaluation_hash[:12]}",
        policy_evaluation_id=evaluation_hash,
        signed_by=operator_id,
        signed_at=signed_at,
        signature_hash=signature,
        acknowledged_gates=acknowledged_gates,
        acknowledged_checks=acknowledged_checks,
        content_light=True,
    )


def verify_attestation(
    attestation: Attestation,
    evaluation: PolicyEvaluation,
    engine: PolicyEngine | None = None,
) -> bool:
    eng = engine if engine is not None else PolicyEngine()

    computed_hash = _compute_evaluation_hash(evaluation, eng)
    if attestation.policy_evaluation_id != computed_hash:
        return False

    computed_sig = _compute_signature(
        evaluation, eng, attestation.signed_by, attestation.signed_at
    )
    return computed_sig == attestation.signature_hash


def attestation_to_json(attestation: Attestation) -> dict[str, Any]:
    return {
        "schema_version": "rig.enterprise.attestation.v1",
        "attestation_id": attestation.attestation_id,
        "policy_evaluation_id": attestation.policy_evaluation_id,
        "signed_by": attestation.signed_by,
        "signed_at": attestation.signed_at,
        "signature_hash": attestation.signature_hash,
        "acknowledged_gates": attestation.acknowledged_gates,
        "acknowledged_checks": attestation.acknowledged_checks,
        "content_light": attestation.content_light,
    }


def attestation_from_json(data: dict[str, Any]) -> Attestation:
    return Attestation(
        attestation_id=data["attestation_id"],
        policy_evaluation_id=data["policy_evaluation_id"],
        signed_by=data["signed_by"],
        signed_at=data["signed_at"],
        signature_hash=data["signature_hash"],
        acknowledged_gates=data.get("acknowledged_gates", []),
        acknowledged_checks=data.get("acknowledged_checks", []),
        content_light=data.get("content_light", True),
    )


def write_attestation(attestation: Attestation, path: Path) -> dict[str, Any]:
    data = attestation_to_json(attestation)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return data


def read_attestation(path: Path) -> Attestation | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return attestation_from_json(data)
    except (json.JSONDecodeError, OSError, KeyError):
        return None

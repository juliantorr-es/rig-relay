"""GitHub Provider operation receipts — content-light, schema-validated."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from rig_relay.integrations.github_provider._models import (
    GitHubProviderCapabilityDecision,
    GitHubProviderOperationReceipt,
    GitHubProviderOperationRequest,
)
from rig_relay.integrations.github_provider._redaction import (
    assert_content_light_mapping,
    assert_no_raw_github_token,
    hash_identifier,
)

_SCHEMAS_DIR = Path(__file__).resolve().parents[3] / "docs" / "schemas"


def _load_schema(schema_id: str) -> dict[str, Any]:
    path = _SCHEMAS_DIR / f"{schema_id}.schema.json"
    return json.loads(path.read_text(encoding="utf-8"))


def validate_github_operation_receipt(receipt: dict[str, Any]) -> list[str]:
    import jsonschema

    schema = _load_schema("rig.github_provider.operation_receipt.v1")
    validator = jsonschema.Draft7Validator(schema)
    return [e.message for e in validator.iter_errors(receipt)]


def _compute_receipt_id(data: dict[str, Any]) -> str:
    canonical = json.dumps(data, sort_keys=True, ensure_ascii=False)
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def build_github_operation_receipt(
    request: GitHubProviderOperationRequest,
    decision: GitHubProviderCapabilityDecision,
    response_metadata: dict[str, Any] | None = None,
    *,
    trace_id: str = "",
    parent_trace_id: str = "",
) -> GitHubProviderOperationReceipt:
    response_metadata = response_metadata or {}

    auth_mode = request.auth_state.auth_mode.value
    auth_state_hash = hash_identifier(
        json.dumps(request.auth_state.to_dict(), sort_keys=True)
    )
    request_hash = hash_identifier(
        json.dumps(
            {
                "operation_id": request.operation_id,
                "capability_id": request.capability_id,
            },
            sort_keys=True,
        )
    )
    response_hash = hash_identifier(json.dumps(response_metadata, sort_keys=True))

    receipt = GitHubProviderOperationReceipt(
        operation_id=request.operation_id,
        capability_id=request.capability_id,
        operation_kind=request.operation_kind,
        operation_class=str(request.operation_class),
        auth_mode=auth_mode,
        auth_state_hash=auth_state_hash,
        request_hash=request_hash,
        response_hash=response_hash,
        repository_hash=request.repository_hash,
        actor_hash=request.actor_hash,
        verdict=decision.verdict.value,
        refusal_code=decision.refusal_code,
        content_light=True,
        redaction_status="clean",
        trace_id=trace_id,
        parent_trace_id=parent_trace_id,
    )

    receipt_dict = receipt.to_dict()

    receipt.receipt_id = _compute_receipt_id(receipt_dict)
    receipt_dict["receipt_id"] = receipt.receipt_id

    assert_content_light_mapping(receipt_dict)

    for value in receipt_dict.values():
        if isinstance(value, str):
            assert_no_raw_github_token(value)

    return receipt

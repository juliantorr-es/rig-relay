"""Google Workspace operation receipts — content-light, schema-validated."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from rig_relay.integrations.google_workspace._models import (
    GoogleWorkspaceDecision,
    GoogleWorkspaceOperationReceipt,
    GoogleWorkspaceOperationRequest,
)
from rig_relay.integrations.google_workspace._redaction import (
    assert_no_raw_secret_patterns,
    assert_no_workspace_content_fields,
)

_SCHEMAS_DIR = Path(__file__).resolve().parents[3] / "docs" / "schemas"


def _hash_identifier(value: str) -> str:
    import hashlib

    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def validate_receipt(receipt: dict[str, Any]) -> list[str]:
    import jsonschema

    path = _SCHEMAS_DIR / "rig.google_workspace.operation_receipt.v1.schema.json"
    schema = json.loads(path.read_text(encoding="utf-8"))
    v = jsonschema.Draft7Validator(schema)
    return [e.message for e in v.iter_errors(receipt)]


def build_workspace_receipt(
    request: GoogleWorkspaceOperationRequest,
    decision: GoogleWorkspaceDecision,
    response_metadata: dict[str, Any] | None = None,
) -> GoogleWorkspaceOperationReceipt:
    response_metadata = response_metadata or {}
    receipt = GoogleWorkspaceOperationReceipt(
        operation_id=request.operation_id,
        capability_id=request.capability_id,
        operation_kind=request.operation_kind,
        operation_class=request.operation_class,
        auth_mode=str(request.auth_state.auth_mode),
        auth_state_hash=_hash_identifier(
            json.dumps(request.auth_state.to_dict(), sort_keys=True)
        ),
        request_hash=_hash_identifier(
            json.dumps(
                {
                    "operation_id": request.operation_id,
                    "capability_id": request.capability_id,
                },
                sort_keys=True,
            )
        ),
        response_hash=_hash_identifier(json.dumps(response_metadata, sort_keys=True)),
        subject_hash=request.subject_hash,
        customer_hash=request.customer_hash,
        resource_hash=request.resource_hash,
        verdict=str(decision.verdict),
        refusal_code=decision.refusal_code,
        content_light=True,
        redaction_status="clean",
    )
    data = receipt.to_dict()
    assert_no_workspace_content_fields(data)
    assert_no_raw_secret_patterns(json.dumps(data))
    errors = validate_receipt(data)
    if errors:
        raise ValueError(f"Receipt schema validation failed: {'; '.join(errors)}")
    return receipt

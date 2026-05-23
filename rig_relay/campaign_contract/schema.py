from __future__ import annotations

import hashlib
import json

import jsonschema

from rig_relay.campaign_contract.models import CAMPAIGN_RECORD_ADAPTER


def generate_campaign_contract_schema() -> dict:
    """Generate and self-validate the Draft 2020-12 JSON Schema."""
    schema = CAMPAIGN_RECORD_ADAPTER.json_schema()
    jsonschema.Draft202012Validator.check_schema(schema)
    return schema


def get_deterministic_schema_json() -> str:
    """Return the schema as a deterministically sorted JSON string."""
    schema = generate_campaign_contract_schema()
    return json.dumps(schema, sort_keys=True, indent=2)


def compute_schema_identity() -> str:
    """Return the SHA-256 hex digest of the deterministic schema JSON."""
    return hashlib.sha256(get_deterministic_schema_json().encode("utf-8")).hexdigest()

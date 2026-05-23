from __future__ import annotations

import hashlib
import json
from typing import Literal

import jsonschema
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from rig_relay.campaign_contract._provider_models import (
    ProviderContextAdmissionDecision,
    ProviderContextItemClassification,
    ProviderContextItemDescriptor,
)

# ---- Enumerations ----------------------------------------------------

SensitivityLabel = Literal[
    "none_declared",
    "credential_or_secret",
    "private_authentication_material",
    "patent_or_counsel_material",
    "legal_strategy_material",
    "confidential_audit_artifact",
    "local_crosswalk",
    "provider_policy_evidence_body",
    "encrypted_snapshot",
    "unrelated_repository_content",
    "unclassified",
]

ClassifierOutcome = Literal[
    "eligible_for_fixture_content_scan",
    "descriptor_ready_for_provider_admission",
    "refused_mission_scope_expansion",
    "halt_security_or_confidentiality_boundary",
]

ClassificationBasis = Literal[
    "pre_read_mission_authority_refusal",
    "pre_read_root_digest_mismatch",
    "pre_read_path_integrity_refusal",
    "pre_read_sensitivity_label_refusal",
    "pre_read_confidential_sink_descendant",
    "pre_read_scope_expansion",
    "pre_read_path_and_scope_approved_no_label",
    "post_read_content_signal_refusal",
    "post_read_no_refusal_signals",
    "unclassified_fail_closed",
]

# ---- Classification request ------------------------------------------


class ContextClassificationRequest(BaseModel):
    """Fixture-only classification request.  No raw source, prompts,
    credentials, crosswalks, or evidence bodies permitted.
    """

    model_config = ConfigDict(extra="forbid")

    classification_request_identity: str = Field(min_length=1)
    campaign_identity: str = Field(min_length=1)
    mission_identity: str = Field(min_length=1)
    candidate_relative_path: str = Field(min_length=1)
    approved_fixture_root_digest: str = Field(min_length=1)
    approved_lane_root_digest: str | None = None
    explicit_sensitivity_labels: list[SensitivityLabel] = Field(default_factory=list)
    minimum_necessary_purpose_label: str = Field(min_length=1)
    fixture_only_marker: Literal[True]
    real_confidential_source_processing_performed: Literal[False]
    provider_request_performed: Literal[False]
    external_transmission_performed: Literal[False]

    @property
    def has_security_label(self) -> bool:
        """True if any explicit label triggers security/confidentiality halt."""
        refused_labels = {
            "credential_or_secret",
            "private_authentication_material",
            "patent_or_counsel_material",
            "legal_strategy_material",
            "confidential_audit_artifact",
            "local_crosswalk",
            "provider_policy_evidence_body",
            "encrypted_snapshot",
            "unrelated_repository_content",
            "unclassified",
        }
        return any(lbl in refused_labels for lbl in self.explicit_sensitivity_labels)


# ---- Classification decision -----------------------------------------


class ContextClassificationDecision(BaseModel):
    """Content-light classification decision.  Contains only classifications,
    identities, digests, reason codes, and boolean markers.
    """

    model_config = ConfigDict(extra="forbid")

    classification_decision_identity: str = Field(min_length=1)
    campaign_identity: str = Field(min_length=1)
    mission_identity: str = Field(min_length=1)
    normalized_identity: str = Field(min_length=1)
    identity_digest: str = Field(min_length=1)
    classifier_outcome: ClassifierOutcome
    provider_context_item_classification: ProviderContextItemClassification | None = (
        None
    )
    classification_basis: ClassificationBasis
    pre_read_refusal_marker: bool
    content_read_performed: bool
    content_signal_scan_performed: bool
    source_body_in_decision: Literal[False] = False
    secret_body_in_decision: Literal[False] = False
    provider_request_performed: Literal[False] = False
    external_transmission_performed: Literal[False] = False
    human_transport_activation_still_required: Literal[True] = True
    campaign_halt_required: bool
    residual_risk_markers: list[str] = Field(default_factory=list)
    refusal_reason: str | None = None
    signal_family: str | None = None


# ---- Combined orchestration result -----------------------------------


class ProviderAdmissionRequestTemplate(BaseModel):
    """Metadata template for constructing a provider admission request."""

    model_config = ConfigDict(extra="forbid")
    campaign_identity: str = Field(min_length=1)
    requested_provider_context_mode: str = Field(min_length=1)
    requested_capabilities: list[str]
    requested_endpoint_family: str = Field(min_length=1)
    minimum_necessary_purpose_label: str = Field(min_length=1)
    human_approved_campaign_identity_reference: str = Field(min_length=1)


class ClassifiedProviderAdmissionResult(BaseModel):
    """Content-light combined result from classifier + provider admission."""

    model_config = ConfigDict(extra="forbid")

    classification_decision: ContextClassificationDecision
    admission_decision: ProviderContextAdmissionDecision | None = None
    provider_admission_performed: bool
    classification_only_refusal: bool


# ---- Descriptor conversion -------------------------------------------


def to_provider_context_item_descriptor(
    decision: ContextClassificationDecision,
) -> ProviderContextItemDescriptor | None:
    """Convert a classification decision to an accepted provider descriptor.

    Returns None for non-security refusals (scope expansion, etc.) that
    should not flow through provider admission halt mapping.
    """
    classification = decision.provider_context_item_classification
    if classification is None:
        return None
    return ProviderContextItemDescriptor(
        normalized_identity=decision.normalized_identity,
        context_classification=classification,
        identity_digest=decision.identity_digest,
    )


# ---- Schema surface --------------------------------------------------


class _ClassifierSchemaRoot(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request: ContextClassificationRequest
    decision: ContextClassificationDecision
    result: ClassifiedProviderAdmissionResult


_CLASSIFIER_ADAPTER: TypeAdapter[_ClassifierSchemaRoot] = TypeAdapter(
    _ClassifierSchemaRoot
)


def generate_context_classifier_schema() -> dict:
    schema = _CLASSIFIER_ADAPTER.json_schema()
    jsonschema.Draft202012Validator.check_schema(schema)
    return schema


def compute_context_classifier_schema_identity() -> str:
    schema = generate_context_classifier_schema()
    return hashlib.sha256(
        json.dumps(schema, sort_keys=True, indent=2).encode("utf-8")
    ).hexdigest()

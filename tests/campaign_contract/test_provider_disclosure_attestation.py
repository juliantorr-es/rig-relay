from __future__ import annotations

from pydantic import TypeAdapter, ValidationError
import pytest

from rig_relay.campaign_contract.models import ProviderDisclosureAttestation

_adapter = TypeAdapter(ProviderDisclosureAttestation)


def _valid_approved_attestation(zdr: bool = False) -> dict:
    d: dict = {
        "mode": "hosted_confidential_full_source_user_approved",
        "provider_family_identity": "fam",
        "provider_model_identity": "model1",
        "actual_retention_control_mode_classification": "standard_retention",
        "campaign_scope_digest": "dig",
        "campaign_scope_approval_marker": True,
        "mission_level_provider_scope_enforcement_marker": True,
    }
    if zdr:
        d["actual_retention_control_mode_classification"] = "zero_data_retention"
        d["verified_zdr_marker"] = True
    return d


# ---- ZDR enforcement tests -------------------------------------------


def test_contract_sabotage_zdr_classification_without_verified_marker_fails():
    """Classification: contract/sabotage
    ZDR classification without verified marker true fails through both
    Pydantic and JSON Schema.
    """
    d = _valid_approved_attestation(zdr=False)
    d["actual_retention_control_mode_classification"] = "zero_data_retention"
    # verified_zdr_marker is absent; must fail
    with pytest.raises(ValidationError):
        _adapter.validate_python(d)


def test_contract_sabotage_zdr_asserted_without_verified_marker_fails():
    """Classification: contract/sabotage
    Asserted ZDR without verified marker true fails through both Pydantic
    and JSON Schema.
    """
    d = _valid_approved_attestation()
    d["asserted_zdr_status"] = True
    # verified_zdr_marker absent; must fail
    with pytest.raises(ValidationError):
        _adapter.validate_python(d)


# ---- Provider-refused mode test --------------------------------------


def test_contract_integration_provider_refused_validates_no_identity_transmission_prohibited():
    """Classification: contract/integration
    Provider-refused mode validates without outbound provider identity and
    requires transmission prohibition.
    """
    # Valid
    _adapter.validate_python({
        "mode": "provider_context_refused",
        "transmission_prohibited": True,
    })

    # Refused mode with provider identity must fail
    with pytest.raises(ValidationError):
        _adapter.validate_python({
            "mode": "provider_context_refused",
            "transmission_prohibited": True,
            "provider_family_identity": "fam",
        })

    # Refused mode without transmission_prohibited must fail
    with pytest.raises(ValidationError):
        _adapter.validate_python({
            "mode": "provider_context_refused",
            "transmission_prohibited": False,
        })


# ---- Invalid provider mode test --------------------------------------


def test_contract_adversarial_invalid_provider_mode_or_unapproved_config_fails():
    """Classification: contract/adversarial
    Invalid provider mode or unapproved full-source configuration fails.
    """
    # Unknown mode
    with pytest.raises(ValidationError):
        _adapter.validate_python({
            "mode": "bogus_mode",
            "provider_family_identity": "fam",
        })

    # Approved mode missing required fields
    with pytest.raises(ValidationError):
        _adapter.validate_python({
            "mode": "hosted_confidential_full_source_user_approved",
            "provider_family_identity": "fam",
        })

    # Approved mode with missing campaign_scope_approval_marker
    d = _valid_approved_attestation()
    del d["campaign_scope_approval_marker"]
    with pytest.raises(ValidationError):
        _adapter.validate_python(d)

    # Approved mode with extra forbidden field
    d = _valid_approved_attestation()
    d["extra_secret"] = "leaked"
    with pytest.raises(ValidationError):
        _adapter.validate_python(d)

"""Campaign manifest loader and validator.

Loads and validates a standalone JSON campaign manifest against the
accepted campaign-contract substrate plus runtime extensions.
"""

from __future__ import annotations

import json
from pathlib import Path

from rig_relay.campaign_contract.models import CAMPAIGN_RECORD_ADAPTER
from rig_relay.cli._steward._campaign_models import (
    CampaignManifestExtension,
    compute_manifest_digest,
)


class CampaignManifestLoadError(Exception):
    """Raised when a campaign manifest cannot be loaded or validated."""


def load_campaign_manifest(
    manifest_path: Path,
) -> tuple[CampaignManifestExtension, str]:
    """Load and validate a campaign manifest JSON file.

    Returns (extension, manifest_digest).

    The manifest dict contains two top-level sections:
    - 'contract': the ApprovedCampaignDefinition fields
    - 'runtime': the CampaignManifestExtension fields

    Raises CampaignManifestLoadError on any validation failure.
    """
    try:
        manifest_data = json.loads(manifest_path.read_text())
    except json.JSONDecodeError as e:
        raise CampaignManifestLoadError(
            f"invalid JSON in campaign manifest: {e}"
        ) from e

    # Validate the base campaign contract (only contract fields)
    contract_data = manifest_data.get("contract", manifest_data)
    try:
        CAMPAIGN_RECORD_ADAPTER.validate_python(contract_data)
    except Exception as e:
        raise CampaignManifestLoadError(
            f"campaign contract validation failed: {e}"
        ) from e

    # Validate runtime extensions
    runtime_data = manifest_data.get("runtime", manifest_data)
    try:
        extension = CampaignManifestExtension.model_validate(runtime_data)
    except Exception as e:
        raise CampaignManifestLoadError(
            f"runtime extension validation failed: {e}"
        ) from e

    # Validate operating mode
    if extension.operating_mode != (
        "confidential_autonomous_campaign_with_private_checkpoint_push"
    ):
        raise CampaignManifestLoadError(
            f"unsupported operating mode: {extension.operating_mode}"
        )

    # Validate assigned branch is not a protected branch
    protected_branches = {
        "main",
        "master",
        "preproduction",
        "release",
        "gh-pages",
        "production",
    }
    branch_lower = extension.assigned_local_branch.lower()
    for protected in protected_branches:
        if branch_lower == protected:
            raise CampaignManifestLoadError(
                f"assigned_local_branch '{extension.assigned_local_branch}' "
                f"is a protected branch"
            )

    # Validate human promotion is required
    if extension.human_promotion_required is not True:
        raise CampaignManifestLoadError("human_promotion_required must be True")

    digest = compute_manifest_digest(manifest_data)
    return extension, digest

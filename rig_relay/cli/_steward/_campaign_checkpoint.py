"""Campaign checkpoint authority.

Issues campaign-scoped authorization receipts that feed the existing
canonical Checkpoint tool. Does NOT implement independent git add/commit.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import hashlib
import json
from pathlib import Path
import time

from rig_relay.cli._steward._campaign_models import (
    CampaignManifestExtension,
    CampaignState,
)


def issue_campaign_checkpoint_receipt(
    extension: CampaignManifestExtension,
    state: CampaignState,
    mission_identity: str,
    include_paths: list[str],
    manifest_digest: str,
    validation_status: str = "work_in_progress_checkpoint",
) -> dict:
    """Issue a campaign-scoped checkpoint authorization receipt.

    This receipt is accepted by the canonical Checkpoint tool when the
    campaign branch matches, manifest digest matches, and paths are
    within approved scope.
    """
    receipt = {
        "schema_version": "rig.relay.step_up_authorization_receipt.v1",
        "action": "checkpoint.commit",
        "action_scope": {
            "campaign_id": extension.campaign_id,
            "manifest_digest": manifest_digest,
            "branch": extension.assigned_local_branch,
            "mission_identity": mission_identity,
            "include_paths": sorted(include_paths),
            "checkpoint_sequence": state.checkpoint_count + 1,
        },
        "user_verified": True,
        "method": "campaign_manifest_authorized",
        "issued_at": int(time.time()),
        "expires_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
        "receipt_id": hashlib.sha256(
            json.dumps(
                {
                    "campaign_id": extension.campaign_id,
                    "sequence": state.checkpoint_count + 1,
                    "branch": extension.assigned_local_branch,
                    "paths": sorted(include_paths),
                    "timestamp": int(time.time()),
                },
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest(),
    }
    return receipt


def validate_campaign_checkpoint_request(
    extension: CampaignManifestExtension,
    state: CampaignState,
    include_paths: list[str],
    repo_root: Path,
) -> str | None:
    """Validate a campaign checkpoint request before issuing a receipt.

    Returns None if valid, or a refusal reason string.
    """
    if state.phase not in {"running", "resolver_active", "repair_active"}:
        return f"campaign not in active phase (current: {state.phase})"

    if not include_paths:
        return "no paths specified for checkpoint"

    prohibited_prefixes = [
        ".build/rig-relay/confidential/",
        ".rig/relay/campaigns/",
        ".opencode/",
    ]
    for path in include_paths:
        for prefix in prohibited_prefixes:
            if path.startswith(prefix):
                return (
                    f"path '{path}' is in prohibited checkpoint scope "
                    f"(prefix: {prefix})"
                )

    resolved_root = repo_root.resolve()
    for path in include_paths:
        resolved = (repo_root / path).resolve()
        try:
            resolved.relative_to(resolved_root)
        except ValueError:
            return f"path '{path}' is outside repository root"

    # Check branch is not main
    # This is validated at the Checkpoint tool level when the receipt
    # is consumed; we also validate here for early refusal.
    branch = extension.assigned_local_branch.lower()
    if branch in {"main", "master"}:
        return "checkpoint on main/master is prohibited"

    return None


def persist_checkpoint_authorization_receipt(
    auth_receipt: dict, campaign_id: str, root: Path
) -> Path:
    """Persist a checkpoint authorization receipt BEFORE commit.

    Writes to ``checkpoint_authorization_receipts.v1.jsonl``, a
    dedicated pre-commit ledger distinct from the terminal
    ``checkpoint_receipts.v1.jsonl``.  Recovery uses this ledger to
    reload the exact authorization receipt whose digest is embedded
    in the checkpoint commit trailer.
    """
    ledger_dir = root / ".rig" / "relay" / "campaigns" / campaign_id
    ledger_dir.mkdir(parents=True, exist_ok=True)
    ledger_path = ledger_dir / "checkpoint_authorization_receipts.v1.jsonl"
    record = {**auth_receipt, "outcome": "authorized", "commit_sha": ""}
    with open(ledger_path, "a") as f:
        f.write(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n")
    return ledger_path


def load_latest_checkpoint_authorization_receipt(
    campaign_id: str, root: Path
) -> dict | None:
    """Reload the most recent checkpoint authorization receipt.

    Returns ``None`` if no authorization receipt has been persisted.
    """
    ledger_path = (
        root
        / ".rig"
        / "relay"
        / "campaigns"
        / campaign_id
        / "checkpoint_authorization_receipts.v1.jsonl"
    )
    if not ledger_path.exists():
        return None
    latest: dict | None = None
    for line in ledger_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                latest = json.loads(line)
            except json.JSONDecodeError:
                pass
    return latest

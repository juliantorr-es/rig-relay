"""Campaign private-branch push authority.

Governed push capability that only pushes fast-forward to the assigned
confidential campaign branch on the approved remote repository.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import time

from rig_relay.cli._steward._campaign_models import (
    CampaignManifestExtension,
    CampaignState,
)


def validate_campaign_push_request(
    extension: CampaignManifestExtension,
    state: CampaignState,
    current_branch: str,
    remote_url: str,
    repo_root: Path,
) -> str | None:
    """Validate a campaign push request before execution.

    Returns None if valid, or a refusal reason string.
    """
    if not extension.private_checkpoint_push_authorized:
        return "private checkpoint push not authorized in manifest"

    if current_branch != extension.assigned_local_branch:
        return (
            f"current branch '{current_branch}' does not match "
            f"assigned branch '{extension.assigned_local_branch}'"
        )

    target = extension.assigned_remote_branch.lower()
    protected = {"main", "master", "preproduction", "release", "gh-pages", "production"}
    if target in protected:
        return f"cannot push to protected branch '{target}'"

    if extension.assigned_remote_repository not in remote_url:
        return (
            f"remote '{remote_url}' does not match assigned repository "
            f"'{extension.assigned_remote_repository}'"
        )

    if state.latest_checkpoint_sha is None:
        return "no checkpoint to push"

    return None


def execute_campaign_push(
    extension: CampaignManifestExtension,
    state: CampaignState,
    current_branch: str,
    remote_url: str,
    repo_root: Path,
) -> dict:
    """Execute a private-branch push for the campaign.

    Uses plain fast-forward push only. Returns a content-light receipt.
    """
    push_sequence = state.push_count + 1
    receipt_id = hashlib.sha256(
        json.dumps(
            {
                "campaign_id": extension.campaign_id,
                "sequence": push_sequence,
                "branch": extension.assigned_remote_branch,
                "head": state.latest_checkpoint_sha,
                "timestamp": int(time.time()),
            },
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()

    base_receipt = {
        "receipt_id": receipt_id,
        "campaign_id": extension.campaign_id,
        "push_sequence": push_sequence,
        "remote_repository": extension.assigned_remote_repository,
        "destination_branch": extension.assigned_remote_branch,
        "pushed_head_sha": (state.latest_checkpoint_sha or ""),
        "pushed_to_sha": "",
        "succeeded": False,
        "refusal_reason": None,
        "fast_forward": True,
        "force_pushed": False,
        "tags_pushed": False,
        "manifest_digest": state.manifest_digest,
    }

    push_ref = f"{extension.assigned_remote_branch}:{extension.assigned_remote_branch}"

    try:
        result = subprocess.run(
            ["git", "-C", str(repo_root), "push", "origin", push_ref],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except subprocess.TimeoutExpired:
        base_receipt["refusal_reason"] = "push timed out"
        return base_receipt
    except Exception as e:
        base_receipt["refusal_reason"] = f"push failed: {e}"
        return base_receipt

    if result.returncode != 0:
        base_receipt["refusal_reason"] = (
            f"push failed (exit {result.returncode}): {result.stderr.strip()[:200]}"
        )
        return base_receipt

    base_receipt["succeeded"] = True
    base_receipt["pushed_to_sha"] = get_remote_head_sha(
        extension.assigned_remote_branch, repo_root
    )
    return base_receipt


def get_remote_head_sha(branch: str, repo_root: Path) -> str:
    """Get the SHA of the remote branch head after push."""
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_root), "rev-parse", f"refs/remotes/origin/{branch}"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return ""


def persist_pre_push_intent(intent: dict, campaign_id: str, root: Path) -> Path:
    """Persist a pre-push intent record BEFORE remote mutation.

    Writes to ``pre_push_intents.v1.jsonl`` — a dedicated pre-effect
    ledger distinct from the terminal ``private_push_receipts.v1.jsonl``.
    Recovery uses this ledger to reload the expected predecessor state
    and verify that the remote action was authorized.
    """
    ledger_dir = root / ".rig" / "relay" / "campaigns" / campaign_id
    ledger_dir.mkdir(parents=True, exist_ok=True)
    ledger_path = ledger_dir / "pre_push_intents.v1.jsonl"
    with open(ledger_path, "a") as f:
        f.write(json.dumps(intent, sort_keys=True, separators=(",", ":")) + "\n")
    return ledger_path


def load_latest_pre_push_intent(campaign_id: str, root: Path) -> dict | None:
    """Reload the most recent pre-push intent record.

    Returns ``None`` if no intent has been persisted.
    """
    ledger_path = (
        root
        / ".rig"
        / "relay"
        / "campaigns"
        / campaign_id
        / "pre_push_intents.v1.jsonl"
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


def inspect_remote_branch(remote_url: str, branch: str) -> str | None:
    """Inspect the remote destination branch HEAD via ``git ls-remote``.

    Returns the SHA of the remote branch or ``None`` if the branch
    does not exist or the command fails.
    """
    try:
        result = subprocess.run(
            ["git", "ls-remote", remote_url, f"refs/heads/{branch}"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if result.returncode != 0:
            return None
        output = result.stdout.strip()
        if not output:
            return None
        # Output format: <sha>\trefs/heads/<branch>
        return output.split()[0] if output else None
    except Exception:
        return None


def classify_push_recovery_state(
    remote_sha: str | None, expected_predecessor: str | None, checkpoint_sha: str
) -> str:
    """Classify the remote state for push recovery.

    Returns one of: ``"absent"``, ``"at_predecessor"``,
    ``"at_checkpoint"``, or ``"divergent"``.
    """
    if remote_sha is None:
        return "absent"
    if expected_predecessor is not None and remote_sha == expected_predecessor:
        return "at_predecessor"
    if remote_sha == checkpoint_sha:
        return "at_checkpoint"
    return "divergent"

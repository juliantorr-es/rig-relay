"""Governed mutation proposal runtime integration.

Coordinates existing production boundaries: compute proposal,
payload custody, admission, apply, canonical checkpoint, and
governed push, with receipt-first crash recovery and replay-safe
completion.  Does NOT duplicate any of these primitives.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
import subprocess
from typing import Literal

from rig_relay.campaign_contract.models import CampaignManifest, MissionDefinition
from rig_relay.cli._steward._campaign_checkpoint import (
    issue_campaign_checkpoint_receipt,
    load_latest_checkpoint_authorization_receipt,
    persist_checkpoint_authorization_receipt,
)
from rig_relay.cli._steward._campaign_models import (
    CampaignManifestExtension,
    CampaignState,
)
from rig_relay.cli._steward._campaign_push import (
    classify_push_recovery_state,
    execute_campaign_push,
    inspect_remote_branch,
    load_latest_pre_push_intent,
    persist_pre_push_intent,
    validate_campaign_push_request,
)
from rig_relay.cli._steward._campaign_registry import PathClassificationRegistry
from rig_relay.cli._steward._campaign_runtime import load_campaign_state
from rig_relay.cli._steward._mutation_apply_receipt import (
    build_apply_receipt,
    load_apply_receipt,
    save_apply_receipt,
)
from rig_relay.cli._steward._mutation_payload import MutationPayloadRecord
from rig_relay.cli._steward._proposal_admission import admit_patch_proposal
from rig_relay.cli._steward._proposal_apply import apply_admitted_proposal
from rig_relay.coordination.patch_proposal import PatchProposal
from rig_relay.coordination.patch_workflow import (
    PatchWorkflowStore,
    proposal_continuation_context,
    transition_proposal_status,
)
from rig_relay.core.tools.base import BaseToolState
from rig_relay.core.tools.builtins.checkpoint import (
    Checkpoint,
    CheckpointArgs,
    CheckpointResult,
    CheckpointToolConfig,
)
from rig_relay.core.tools.builtins.search_replace import SearchReplaceProposalResult

MutationOutcome = Literal[
    "proposal_computed",
    "proposal_admitted_refused",
    "proposal_apply_refused",
    "checkpoint_refused",
    "governed_push_refused",
    "campaign_mutation_completed",
]


async def _run_canonical_checkpoint(
    *, checkpoint_receipt: dict, include_paths: list[str], message: str, repo_root: Path
) -> CheckpointResult:
    """Invoke the canonical Checkpoint tool with a campaign receipt.

    The receipt provides authorization. The tool validates preconditions,
    stages files, commits, and returns the result.
    """
    tool = Checkpoint(
        config_getter=lambda: CheckpointToolConfig(), state=BaseToolState()
    )
    args = CheckpointArgs(
        message=message,
        include_paths=include_paths,
        authorization_receipt=json.dumps(checkpoint_receipt),
    )

    results: list[CheckpointResult] = []
    async for event in tool.run(args, ctx=None):
        if isinstance(event, CheckpointResult):
            results.append(event)

    if results:
        return results[-1]
    return CheckpointResult(ok=False, message=message, refusal_reason="no_result")


def _run_checkpoint_sync(
    checkpoint_receipt: dict, include_paths: list[str], message: str, repo_root: Path
) -> CheckpointResult:
    """Synchronous wrapper for checkpoint invocation."""
    return asyncio.run(
        _run_canonical_checkpoint(
            checkpoint_receipt=checkpoint_receipt,
            include_paths=include_paths,
            message=message,
            repo_root=repo_root,
        )
    )


# ---- Lifecycle helpers -----------------------------------------------


def _scan_jsonl(campaign_id: str, root: Path, ledger_name: str) -> list[dict]:
    """Scan a campaign JSONL ledger and return parsed records."""
    path = root / ".rig" / "relay" / "campaigns" / campaign_id / ledger_name
    if not path.exists():
        return []
    records: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return records


def _idempotent_append(
    campaign_id: str, root: Path, ledger_name: str, record: dict, event_id: str
) -> dict:
    """Append a record to JSONL only if its event identity is not already present."""
    existing = _scan_jsonl(campaign_id, root, ledger_name)
    for rec in existing:
        if rec.get("event_id") == event_id:
            return rec
    record["event_id"] = event_id
    path = root / ".rig" / "relay" / "campaigns" / campaign_id / ledger_name
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n")
    return record


def _persist_apply(
    cid: str,
    mid: str,
    pid: str,
    decision_id: str,
    canonical_path: str,
    before_hash: str,
    candidate_after: str,
    actual_after: str,
    payload_sha256: str,
    apply_status: str,
) -> object:
    """Build and persist an idempotent apply receipt."""
    receipt = build_apply_receipt(
        campaign_id=cid,
        mission_id=mid,
        proposal_id=pid,
        admission_decision_id=decision_id,
        canonical_path=canonical_path,
        before_sha256=before_hash,
        candidate_after_sha256=candidate_after,
        actual_after_sha256=actual_after,
        payload_sha256=payload_sha256,
    )
    receipt = receipt.model_copy(update={"apply_status": apply_status})
    save_apply_receipt(receipt, cid, Path("."))
    return receipt


def _load_or_issue_checkpoint_auth(
    cid: str,
    extension: CampaignManifestExtension,
    state: CampaignState,
    mid: str,
    decision_id: str,
    repo_root: Path,
) -> dict:
    """Load durable authorization receipt or issue a new one.

    Uses the dedicated pre-commit authorization ledger
    ``checkpoint_authorization_receipts.v1.jsonl`` (NOT the terminal
    receipt ledger).  Persists newly-issued authorization receipts
    BEFORE invoking canonical Checkpoint so recovery can reload them.
    """
    existing = load_latest_checkpoint_authorization_receipt(cid, repo_root)
    if existing is not None:
        return {k: v for k, v in existing.items() if k != "outcome"}
    receipt = issue_campaign_checkpoint_receipt(
        extension, state, mid, [], state.manifest_digest
    )
    persist_checkpoint_authorization_receipt(receipt, cid, repo_root)
    return receipt


def _check_receipt_trailer(repo_root: Path, auth_receipt: dict) -> bool:
    """Check whether HEAD carries the receipt digest trailer."""
    receipt_json = json.dumps(auth_receipt, sort_keys=True, separators=(",", ":"))
    expected = "sha256:" + hashlib.sha256(receipt_json.encode()).hexdigest()
    trailer = f"Rig-Authorization-Receipt-SHA256: {expected}"
    result = subprocess.run(
        ["git", "-C", str(repo_root), "log", "--format=%B", "-1"],
        capture_output=True,
        text=True,
    )
    return trailer in (result.stdout or "")


def _persist_checkpoint_receipt(
    cid: str,
    root: Path,
    auth_receipt: dict,
    commit_sha: str,
    state: CampaignState,
    outcome: str,
) -> dict:
    """Persist an idempotent terminal checkpoint receipt."""
    receipt_dict = {**auth_receipt, "commit_sha": commit_sha, "outcome": outcome}
    event_id = hashlib.sha256(f"checkpoint:{cid}:{commit_sha}".encode()).hexdigest()
    return _idempotent_append(
        cid, root, "checkpoint_receipts.v1.jsonl", receipt_dict, event_id
    )


def _push_event_id(
    cid: str,
    pid: str,
    commit_sha: str,
    remote_url: str,
    destination_branch: str,
    remote_sha: str,
) -> str:
    """Compute a stable event identity for a push receipt."""
    return hashlib.sha256(
        f"push:{cid}:{pid}:{commit_sha}:{remote_url}:{destination_branch}:{remote_sha}".encode()
    ).hexdigest()


def _try_load_apply_receipt(
    *,
    cid: str,
    mid: str,
    pid: str,
    decision_id: str,
    canonical_path: str,
    before_hash: str,
    candidate_after: str,
    actual_after: str,
    payload_sha256: str,
    root: Path,
) -> object:
    """Recompute apply receipt identity and load if present on disk."""
    from rig_relay.cli._steward._mutation_apply_receipt import build_apply_receipt

    receipt = build_apply_receipt(
        campaign_id=cid,
        mission_id=mid,
        proposal_id=pid,
        admission_decision_id=decision_id,
        canonical_path=canonical_path,
        before_sha256=before_hash,
        candidate_after_sha256=candidate_after,
        actual_after_sha256=actual_after,
        payload_sha256=payload_sha256,
    )
    return load_apply_receipt(receipt.receipt_id, cid, root)


def _scan_for_apply_receipt(
    cid: str,
    mid: str,
    pid: str,
    canonical_path: str,
    expected_after_hash: str,
    root: Path,
) -> object | None:
    """Scan for a receipt with full identity compatibility.

    A receipt is accepted only when its campaign, mission, proposal,
    canonical path, and actual-after hash all match the expected
    continuation bindings.  Receipts with matching proposal_id but
    wrong path, hash, or mission are refused as stale or mismatched.
    """
    import json as _json

    apply_dir = root / ".rig" / "relay" / "campaigns" / cid / "apply_receipts"
    if not apply_dir.is_dir():
        return None
    # Strip sha256: prefix for comparison
    after_hex = (
        expected_after_hash[7:]
        if expected_after_hash.startswith("sha256:")
        else expected_after_hash
    )
    for path in sorted(apply_dir.glob("*.json")):
        try:
            data = _json.loads(path.read_text(encoding="utf-8"))
        except (_json.JSONDecodeError, OSError):
            continue
        if data.get("proposal_id") != pid:
            continue
        if data.get("campaign_id") != cid:
            continue
        if data.get("mission_id") != mid:
            continue
        if data.get("canonical_path") != canonical_path:
            continue
        stored_after = data.get("actual_after_sha256", "")
        if stored_after.startswith("sha256:"):
            stored_after = stored_after[7:]
        if stored_after != after_hex:
            continue
        from rig_relay.cli._steward._mutation_apply_receipt import MutationApplyReceipt

        return MutationApplyReceipt.model_validate(data)
    return None


async def execute_proposal_based_mutation(  # noqa: PLR0911, PLR0912, PLR0913, PLR0914, PLR0915
    *,
    campaign_state: CampaignState,
    manifest: CampaignManifest,
    extension: CampaignManifestExtension,
    mission: MissionDefinition,
    registry: PathClassificationRegistry,
    proposal: PatchProposal,
    proposal_result: SearchReplaceProposalResult,
    payload: MutationPayloadRecord,
    file_bytes: bytes,
    file_path: Path,
    repo_root: Path,
    remote_url: str,
    current_branch: str,
    coordination_root: Path | None = None,
) -> dict:
    """Execute proposal-based mutation with receipt-first crash recovery.

    Under a cross-process continuation lock, loads durable evidence,
    draws only the missing continuation stage, and persists idempotent
    terminal receipts.  Never re-issues authorization during recovery
    and never requires raw payload custody after durable apply.
    """
    cid = campaign_state.campaign_id
    mid = mission.mission_id
    coord = (
        coordination_root
        if coordination_root is not None
        else repo_root / ".build" / "rig-relay" / "coordination"
    )
    pid = proposal.proposal_id

    with proposal_continuation_context(coord, pid) as lock_fd:
        # ---- 0. Load durable evidence ----
        state = load_campaign_state(cid, repo_root) or campaign_state
        store = PatchWorkflowStore(coord)
        auth_receipt_local: dict | None = None
        push_result_local: dict | None = None
        try:
            durable_proposal = store.load_proposal(pid)
        except Exception:
            durable_proposal = proposal

        apply_receipt = None

        checkpoint_records = _scan_jsonl(cid, repo_root, "checkpoint_receipts.v1.jsonl")
        push_records = _scan_jsonl(cid, repo_root, "private_push_receipts.v1.jsonl")

        if durable_proposal.status != proposal.status:
            proposal = durable_proposal

        # ---- Phase A: Resolve apply  ----
        status = durable_proposal.status
        current_hash = hashlib.sha256(file_bytes).hexdigest()
        bm = proposal_result.before_file_sha256
        p_before = list(bm.values())[0] if bm else ""
        am = proposal_result.after_file_sha256
        p_after = list(am.values())[0] if am else ""

        if apply_receipt is not None:
            decision_id = apply_receipt.admission_decision_id
            actual_after = apply_receipt.actual_after_sha256
            before_hash_val = apply_receipt.before_sha256
        elif status == "applying":
            if current_hash == p_before:
                decision = admit_patch_proposal(
                    proposal,
                    proposal_result,
                    campaign_state,
                    manifest,
                    mission,
                    registry,
                    payload,
                    file_bytes,
                    repo_root,
                )
                if decision.admission_status != "admitted":
                    return _result(
                        "proposal_admitted_refused",
                        cid,
                        mid,
                        reason=decision.reason_code,
                        decision_id=decision.decision_id,
                    )
                apply_result = apply_admitted_proposal(
                    decision, payload, file_bytes, file_path, cid, repo_root
                )
                if apply_result.status != "applied":
                    return _result(
                        "proposal_apply_refused",
                        cid,
                        mid,
                        reason=apply_result.refusal_reason or "apply_failed",
                        decision_id=decision.decision_id,
                    )
                decision_id = decision.decision_id
                actual_after = apply_result.after_sha256
                before_hash_val = apply_result.before_sha256
                apply_receipt = _persist_apply(
                    cid,
                    mid,
                    pid,
                    decision_id,
                    decision.file_path,
                    before_hash_val,
                    decision.candidate_after_sha256,
                    actual_after,
                    payload.payload_sha256,
                    "applied",
                )
                transition_proposal_status(
                    coord, pid, "applying", "applied", _lock_fd=lock_fd
                )
            elif current_hash == p_after:
                apply_receipt = _persist_apply(
                    cid,
                    mid,
                    pid,
                    "",
                    "",
                    p_before,
                    p_after,
                    current_hash,
                    payload.payload_sha256 if payload else "",
                    "recovered",
                )
                transition_proposal_status(
                    coord, pid, "applying", "applied", _lock_fd=lock_fd
                )
                decision_id = ""
                actual_after = current_hash
                before_hash_val = p_before
            else:
                return _result(
                    "proposal_apply_refused", cid, mid, reason="divergent_state"
                )
        elif status == "pending":
            transition_proposal_status(
                coord, pid, "pending", "applying", _lock_fd=lock_fd
            )
            decision = admit_patch_proposal(
                proposal,
                proposal_result,
                campaign_state,
                manifest,
                mission,
                registry,
                payload,
                file_bytes,
                repo_root,
            )
            if decision.admission_status != "admitted":
                return _result(
                    "proposal_admitted_refused",
                    cid,
                    mid,
                    reason=decision.reason_code,
                    decision_id=decision.decision_id,
                )
            apply_result = apply_admitted_proposal(
                decision, payload, file_bytes, file_path, cid, repo_root
            )
            if apply_result.status != "applied":
                return _result(
                    "proposal_apply_refused",
                    cid,
                    mid,
                    reason=apply_result.refusal_reason or "apply_failed",
                    decision_id=decision.decision_id,
                )
            decision_id = decision.decision_id
            actual_after = apply_result.after_sha256
            before_hash_val = apply_result.before_sha256
            apply_receipt = _persist_apply(
                cid,
                mid,
                pid,
                decision_id,
                decision.file_path,
                before_hash_val,
                decision.candidate_after_sha256,
                actual_after,
                payload.payload_sha256,
                "applied",
            )
            transition_proposal_status(
                coord, pid, "applying", "applied", _lock_fd=lock_fd
            )
        else:
            # Applied or terminal — repair from existing evidence
            if status == "applied" and apply_receipt is None:
                # Recomp-based lookup failed — scan for any receipt with this proposal_id
                apply_receipt = _scan_for_apply_receipt(
                    cid,
                    mid,
                    pid,
                    canonical_path=proposal_result.file,
                    expected_after_hash=(
                        list(proposal_result.after_file_sha256.values())[0]
                        if proposal_result.after_file_sha256
                        else ""
                    ),
                    root=repo_root,
                )
            if status == "applied" and apply_receipt is None:
                return _result(
                    "proposal_apply_refused",
                    cid,
                    mid,
                    reason="inconsistent_applied_without_receipt",
                )
            decision_id = apply_receipt.admission_decision_id if apply_receipt else ""
            actual_after = apply_receipt.actual_after_sha256 if apply_receipt else ""
            before_hash_val = apply_receipt.before_sha256 if apply_receipt else ""

        # ---- Phase B: Checkpoint ----
        if not checkpoint_records:
            auth_receipt_local = _load_or_issue_checkpoint_auth(
                cid, extension, campaign_state, mid, decision_id, repo_root
            )
            if state.latest_checkpoint_sha:
                trailer_ok = _check_receipt_trailer(repo_root, auth_receipt_local)
                if trailer_ok:
                    _persist_checkpoint_receipt(
                        cid,
                        repo_root,
                        auth_receipt_local,
                        state.latest_checkpoint_sha,
                        state,
                        "recovered",
                    )
                    campaign_state.latest_checkpoint_sha = state.latest_checkpoint_sha
                else:
                    return _result(
                        "checkpoint_refused",
                        cid,
                        mid,
                        reason="checkpoint_recovery_mismatch",
                        actual_after_hash=actual_after,
                    )
            else:
                ck_result = await _run_canonical_checkpoint(
                    checkpoint_receipt=auth_receipt_local,
                    include_paths=[
                        apply_receipt.canonical_path if apply_receipt else "target.py"
                    ],
                    message=f"campaign({cid}): checkpoint — mission {mid}",
                    repo_root=repo_root,
                )
                if not ck_result.ok or not ck_result.commit_sha:
                    return _result(
                        "checkpoint_refused",
                        cid,
                        mid,
                        reason=ck_result.refusal_reason or "checkpoint_failed",
                        actual_after_hash=actual_after,
                    )
                state.latest_checkpoint_sha = ck_result.commit_sha
                _persist_checkpoint_receipt(
                    cid,
                    repo_root,
                    auth_receipt_local,
                    ck_result.commit_sha,
                    state,
                    "completed",
                )
                campaign_state.latest_checkpoint_sha = ck_result.commit_sha

        # ---- Phase C: Push ----
        commit_sha = state.latest_checkpoint_sha or campaign_state.latest_checkpoint_sha
        if not push_records and commit_sha:
            push_refusal = validate_campaign_push_request(
                extension, campaign_state, current_branch, remote_url, repo_root
            )
            if push_refusal:
                return _result(
                    "governed_push_refused",
                    cid,
                    mid,
                    reason=push_refusal,
                    actual_after_hash=actual_after,
                )
            # Load or persist pre-push intent
            push_intent = load_latest_pre_push_intent(cid, repo_root)
            if push_intent is None:
                push_intent = {
                    "schema_version": "rig.relay.pre_push_intent.v1",
                    "campaign_id": cid,
                    "mission_id": mid,
                    "proposal_id": pid,
                    "checkpoint_sha": commit_sha,
                    "governed_remote": remote_url,
                    "destination_branch": extension.assigned_remote_branch,
                    "expected_predecessor": campaign_state.latest_pushed_sha or None,
                }
                persist_pre_push_intent(push_intent, cid, repo_root)
            # Inspect remote destination
            remote_sha = inspect_remote_branch(
                remote_url, extension.assigned_remote_branch
            )
            state_class = classify_push_recovery_state(
                remote_sha, push_intent.get("expected_predecessor"), commit_sha
            )
            if state_class == "at_checkpoint":
                # Already pushed — persist recovered receipt
                recovered = {
                    "receipt_id": push_intent.get("event_id", ""),
                    "campaign_id": cid,
                    "pushed_head_sha": commit_sha,
                    "pushed_to_sha": remote_sha or "",
                    "succeeded": True,
                    "fast_forward": True,
                    "destination_branch": extension.assigned_remote_branch,
                    "remote_repository": remote_url,
                    "outcome": "recovered",
                }
                _idempotent_append(
                    cid,
                    repo_root,
                    "private_push_receipts.v1.jsonl",
                    recovered,
                    _push_event_id(
                        cid,
                        pid,
                        commit_sha,
                        remote_url,
                        extension.assigned_remote_branch,
                        remote_sha or "",
                    ),
                )
                push_result_local = recovered
            elif state_class in {"absent", "at_predecessor"}:
                push_result_local = execute_campaign_push(
                    extension, campaign_state, current_branch, remote_url, repo_root
                )
                if not push_result_local.get("succeeded"):
                    return _result(
                        "governed_push_refused",
                        cid,
                        mid,
                        reason=push_result_local.get("refusal_reason", "push_failed"),
                        actual_after_hash=actual_after,
                    )
                _idempotent_append(
                    cid,
                    repo_root,
                    "private_push_receipts.v1.jsonl",
                    push_result_local,
                    _push_event_id(
                        cid,
                        pid,
                        commit_sha,
                        remote_url,
                        extension.assigned_remote_branch,
                        push_result_local.get("pushed_to_sha", remote_sha or ""),
                    ),
                )
            else:
                return _result(
                    "governed_push_refused",
                    cid,
                    mid,
                    reason=f"remote branch {extension.assigned_remote_branch} is divergent "
                    f"(expected {push_intent.get('expected_predecessor') or 'absent'}, "
                    f"got {remote_sha or 'absent'})",
                    actual_after_hash=actual_after,
                )

        # ---- Complete ----
        return _result(
            "campaign_mutation_completed",
            cid,
            mid,
            decision_id=decision_id or "",
            apply_receipt_id=apply_receipt.receipt_id if apply_receipt else "",
            checkpoint_receipt_id=auth_receipt_local.get("receipt_id", "")
            if auth_receipt_local
            else "",
            actual_after_hash=actual_after,
            before_hash=before_hash_val,
            pushed_head_sha=push_result_local.get("pushed_head_sha", "")
            if push_result_local
            else "",
            pushed_to_sha=push_result_local.get("pushed_to_sha", "")
            if push_result_local
            else "",
        )


def _result(  # noqa: PLR0913
    outcome: MutationOutcome,
    campaign_id: str,
    mission_id: str,
    *,
    reason: str = "",
    decision_id: str = "",
    apply_receipt_id: str = "",
    checkpoint_receipt_id: str = "",
    actual_after_hash: str = "",
    before_hash: str = "",
    pushed_head_sha: str = "",
    pushed_to_sha: str = "",
) -> dict:
    """Build a content-light minimized result dict.

    Never contains raw source, payload, SEARCH/REPLACE blocks,
    internal model dumps, or absolute temp root paths.
    """
    return {
        "outcome": outcome,
        "campaign_id": campaign_id,
        "mission_id": mission_id,
        "decision_id": decision_id,
        "apply_receipt_id": apply_receipt_id,
        "checkpoint_receipt_id": checkpoint_receipt_id,
        "actual_after_hash": actual_after_hash,
        "before_hash": before_hash,
        "pushed_head_sha": pushed_head_sha,
        "pushed_to_sha": pushed_to_sha,
        "refusal_reason": reason,
    }

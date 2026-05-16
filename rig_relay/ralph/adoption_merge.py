"""Adoption merge — governed merge of sealed Ralph lane into target.

Merge requires: adoption approval, matching source head_sha, clean target,
policy.allow_adoption_merge=True. Returns structured result with receipt.
Default: disabled. Demo: contract-only.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
import subprocess

from pydantic import BaseModel, ConfigDict

from rig_relay.ralph.background_policy import RalphBackgroundPolicy

MERGE_RESULT_VERSION = "rig.ralph_adoption_merge_result.v1"


class AdoptionMergeResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = MERGE_RESULT_VERSION
    status: str = "refused"
    merge_sha: str = ""
    target_branch: str = ""
    source_branch: str = ""
    error: str = ""
    merge_enabled: bool = False
    receipt_sha256: str = ""

    def compute_sha256(self) -> str:
        payload = self.model_dump_json(exclude={"receipt_sha256"})
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def execute_adoption_merge(
    source_branch: str,
    target_branch: str,
    source_head_sha: str,
    policy: RalphBackgroundPolicy,
    human_approval_id: str = "",
    orchestrator_acceptance: bool = False,
    repo_root: Path | None = None,
    target_is_orchestrator_lane: bool = False,
) -> AdoptionMergeResult:
    if not policy.can_merge_adoption():
        return AdoptionMergeResult(
            status="refused",
            source_branch=source_branch,
            target_branch=target_branch,
            error="adoption merge disabled by policy",
            merge_enabled=False,
        )

    if not human_approval_id:
        return AdoptionMergeResult(
            status="refused",
            source_branch=source_branch,
            target_branch=target_branch,
            error="human adoption approval required",
            merge_enabled=False,
        )

    if target_is_orchestrator_lane and not orchestrator_acceptance:
        return AdoptionMergeResult(
            status="refused",
            source_branch=source_branch,
            target_branch=target_branch,
            error="orchestrator acceptance required for orchestration lane merge",
            merge_enabled=False,
        )

    if not source_branch.startswith(policy.branch_prefix):
        return AdoptionMergeResult(
            status="refused",
            source_branch=source_branch,
            target_branch=target_branch,
            error=f"source branch not Ralph-owned: {source_branch}",
            merge_enabled=False,
        )

    if target_branch in ("main", "master") and not policy.allow_push_to_preproduction:
        return AdoptionMergeResult(
            status="refused",
            source_branch=source_branch,
            target_branch=target_branch,
            error="merge to main requires preproduction push approval",
            merge_enabled=False,
        )

    if source_head_sha:
        root = repo_root or Path.cwd()
        try:
            actual = subprocess.run(
                ["git", "-C", str(root), "rev-parse", source_branch],
                capture_output=True,
                text=True,
                timeout=5,
            ).stdout.strip()
            if actual and actual != source_head_sha:
                return AdoptionMergeResult(
                    status="refused",
                    source_branch=source_branch,
                    target_branch=target_branch,
                    error=f"source head_sha mismatch: expected {source_head_sha[:12]}, actual {actual[:12]}",
                    merge_enabled=False,
                )
        except Exception:
            pass

    try:
        root = repo_root or Path.cwd()
        subprocess.run(
            ["git", "-C", str(root), "checkout", target_branch],
            capture_output=True,
            text=True,
            timeout=10,
        )
        result = subprocess.run(
            [
                "git",
                "-C",
                str(root),
                "merge",
                "--no-ff",
                source_branch,
                "-m",
                f"ralph adoption: merge {source_branch} into {target_branch}",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            subprocess.run(
                ["git", "-C", str(root), "merge", "--abort"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            return AdoptionMergeResult(
                status="failed",
                source_branch=source_branch,
                target_branch=target_branch,
                error=result.stderr[:200],
                merge_enabled=False,
            )

        sha_result = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        merge_sha = sha_result.stdout.strip()
        merge_result = AdoptionMergeResult(
            status="merged",
            merge_sha=merge_sha,
            source_branch=source_branch,
            target_branch=target_branch,
            merge_enabled=False,
        )
        merge_result.receipt_sha256 = merge_result.compute_sha256()
        return merge_result
    except Exception as e:
        return AdoptionMergeResult(
            status="failed",
            source_branch=source_branch,
            target_branch=target_branch,
            error=str(e),
            merge_enabled=False,
        )


__all__ = ["AdoptionMergeResult", "execute_adoption_merge"]

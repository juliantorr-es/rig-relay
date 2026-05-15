"""Preproduction push — governed push of merged lane to preproduction branch.

Requires: adoption merge completed, validation passed, human approval,
policy.allow_push_to_preproduction=True. Default: disabled.
"""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from rig_relay.ralph.background_policy import RalphBackgroundPolicy

PUSH_RESULT_VERSION = "rig.ralph_preproduction_push_result.v1"


class PreproductionPushResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = PUSH_RESULT_VERSION
    status: str = "refused"
    source_branch: str = ""
    target_branch: str = ""
    merge_sha: str = ""
    error: str = ""
    push_enabled: bool = False
    receipt_sha256: str = ""

    def compute_sha256(self) -> str:
        payload = self.model_dump_json(exclude={"receipt_sha256"})
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def execute_preproduction_push(
    source_branch: str,
    target_branch: str,
    merge_sha: str,
    policy: RalphBackgroundPolicy,
    human_approval_id: str = "",
    validation_passed: bool = False,
    repo_root: Path | None = None,
) -> PreproductionPushResult:
    if not policy.can_push_preproduction():
        return PreproductionPushResult(
            status="refused",
            source_branch=source_branch,
            target_branch=target_branch,
            error="push to preproduction disabled by policy",
            push_enabled=False,
        )

    if not human_approval_id:
        return PreproductionPushResult(
            status="refused",
            source_branch=source_branch,
            target_branch=target_branch,
            error="human preproduction approval required",
            push_enabled=False,
        )

    if not validation_passed:
        return PreproductionPushResult(
            status="refused",
            source_branch=source_branch,
            target_branch=target_branch,
            error="required validations not passed",
            push_enabled=False,
        )

    if not source_branch.startswith(policy.branch_prefix):
        return PreproductionPushResult(
            status="refused",
            source_branch=source_branch,
            target_branch=target_branch,
            error=f"source branch not Ralph-owned: {source_branch}",
            push_enabled=False,
        )

    if merge_sha:
        root = repo_root or Path.cwd()
        try:
            actual = subprocess.run(
                ["git", "-C", str(root), "rev-parse", source_branch],
                capture_output=True, text=True, timeout=5,
            ).stdout.strip()
            if actual and actual != merge_sha:
                return PreproductionPushResult(
                    status="refused",
                    source_branch=source_branch,
                    target_branch=target_branch,
                    merge_sha=merge_sha,
                    error=f"merge_sha mismatch: expected {merge_sha[:12]}, actual {actual[:12]}",
                    push_enabled=False,
                )
        except Exception:
            pass

    try:
        root = repo_root or Path.cwd()
        result = subprocess.run(
            ["git", "-C", str(root), "push", "origin", f"{source_branch}:{target_branch}"],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0:
            return PreproductionPushResult(
                status="failed",
                source_branch=source_branch,
                target_branch=target_branch,
                merge_sha=merge_sha,
                error=result.stderr[:200],
                push_enabled=False,
            )
        push_result = PreproductionPushResult(
            status="pushed",
            source_branch=source_branch,
            target_branch=target_branch,
            merge_sha=merge_sha,
            push_enabled=False,
        )
        push_result.receipt_sha256 = push_result.compute_sha256()
        return push_result
    except Exception as e:
        return PreproductionPushResult(
            status="failed",
            source_branch=source_branch,
            target_branch=target_branch,
            error=str(e),
            push_enabled=False,
        )


__all__ = [
    "PreproductionPushResult",
    "execute_preproduction_push",
]

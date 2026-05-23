"""Context capsule assembly for the OpenCode steward.

Owns: assembly pipeline that reads raw evidence through the canonical
context assembler boundary and produces a validated capsule.
Does not own: classification logic, execution, tracing.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from rig_relay.cli._steward._constants import CAPSULE_PATH
from rig_relay.governance.steward_context_assembler import (
    RawEvidenceBundle,
    digest_to_capsule,
    validate_capsule,
)

_MAX_CAPSULE_AGE_SECONDS = 3600


def read_capsule(root: Path) -> tuple[dict[str, Any] | None, str]:
    capsule_path = root / CAPSULE_PATH
    if not capsule_path.exists():
        return None, "missing"
    try:
        capsule = json.loads(capsule_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None, "invalid"
    valid, fail_reason = validate_capsule(capsule)
    if not valid:
        return None, f"invalid:{fail_reason}"
    generated_at_str = capsule.get("generated_at")
    if generated_at_str:
        try:
            from datetime import UTC, datetime

            dt = datetime.fromisoformat(generated_at_str)
            age = (datetime.now(UTC) - dt).total_seconds()
            if age > _MAX_CAPSULE_AGE_SECONDS:
                return capsule, "stale"
        except (ValueError, TypeError):
            return None, "invalid:timestamp_parse_failed"
    return capsule, "present"


def compile_capsule(
    root: Path,
    evidence: RawEvidenceBundle,
    item: dict[str, Any] | None,
    blockers: list[str],
    comp: dict[str, Any] | None,
    state: str,
    compiler_fallback_status: str,
) -> dict[str, Any]:
    result = digest_to_capsule(
        evidence,
        selected_item=item,
        blockers=blockers,
        completion=comp,
        state=state,
        project_root=root,
    )
    capsule = result.capsule
    capsule["compiler_fallback_status"] = compiler_fallback_status
    return capsule


def append_observation_event(
    root: Path, session_id: str, event_type: str, payload: dict[str, Any]
) -> None:
    if not session_id:
        raise ValueError("Session identifier is required")

    from rig_relay.cli._steward._constants import now_iso

    session_dir = (
        root / ".build/rig-relay/derived/opencode-steward/sessions" / session_id
    )
    session_dir.mkdir(parents=True, exist_ok=True)
    obs_path = session_dir / "observations.v1.jsonl"

    event = {
        "schema_version": "rig.relay.opencode_steward_observation.v1",
        "session_id": session_id,
        "event_type": event_type,
        "generated_at": now_iso(),
        "payload": payload,
    }
    with obs_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")


def _parse_observations(
    obs_path: Path,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    tool_calls = []
    validations = []
    warnings = []
    if obs_path.exists():
        try:
            with obs_path.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    evt = json.loads(line)
                    etype = evt.get("event_type")
                    epayload = evt.get("payload") or {}
                    if etype == "tool_call":
                        tool_calls.append(epayload)
                    elif etype == "validation_run":
                        validations.append(epayload)
                    elif etype == "warning_raised":
                        warnings.append(epayload)
        except Exception:
            pass
    return tool_calls, validations, warnings


def compile_handoff_packet(root: Path, session_id: str) -> dict[str, Any]:
    if not session_id:
        raise ValueError("Session identifier is required")

    from rig_relay.cli._steward._constants import now_iso
    from rig_relay.cli.steward import dirty_files_set, git_branch, git_dirty, git_head

    session_dir = (
        root / ".build/rig-relay/derived/opencode-steward/sessions" / session_id
    )
    dirty = git_dirty(root)
    tool_calls, validations, warnings = _parse_observations(
        session_dir / "observations.v1.jsonl"
    )

    handoff = {
        "schema_version": "rig.relay.opencode_steward_handoff.v1",
        "session_id": session_id,
        "generated_at": now_iso(),
        "non_authoritative_steward_observation_packet": True,
        "evidence_incomplete": (session_dir / "evidence_incomplete.flag").exists(),
        "disclaimer": "This is a non-authoritative OpenCode observation packet. It serves as a coordination handoff and is not canonical Rig release evidence until compared with Rig-owned receipts.",
        "project_identity": {"project_root": str(root), "worktree": "default"},
        "git_snapshot": {
            "branch": git_branch(root),
            "head": git_head(root),
            "dirty_state": {
                "modified_count": dirty.get("modified_count", 0),
                "staged_count": dirty.get("staged_count", 0),
                "untracked_count": dirty.get("untracked_count", 0),
            },
        },
        "files_touched": sorted(list(dirty_files_set(dirty))),
        "tool_calls_observed": tool_calls,
        "validations_observed": validations,
        "warnings_raised_and_ignored": warnings,
        "suggested_next_action": "Run final validation suite and verify changes converge.",
    }

    session_dir.mkdir(parents=True, exist_ok=True)
    (session_dir / "handoff.v1.json").write_text(
        json.dumps(handoff, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return handoff


__all__ = [
    "append_observation_event",
    "compile_capsule",
    "compile_handoff_packet",
    "read_capsule",
]

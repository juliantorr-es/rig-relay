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
    assemble_raw_evidence,
    digest_to_capsule,
    validate_capsule,
)


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
    return capsule, "present"


def compile_capsule(
    root: Path,
    items: list[dict[str, Any]],
    lanes: list[dict[str, Any]],
    dirty: dict[str, Any],
    dirty_files: set[str],
    item: dict[str, Any] | None,
    blockers: list[str],
    comp: dict[str, Any] | None,
    state: str,
    compiler_fallback_status: str,
) -> dict[str, Any]:
    evidence = assemble_raw_evidence(root, dirty=dirty, dirty_files=dirty_files)
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


__all__ = ["compile_capsule", "read_capsule"]

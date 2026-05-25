"""macOS extended-attribute advisory mirror for fleet claims.

xattrs are advisory projections only — never treated as authority
for claim resolution. All write operations degrade gracefully and
never raise exceptions that would invalidate the canonical claim.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import json
import os
from pathlib import Path
import sys

from rig_relay.core.logger import logger

XATTR_CLAIM = "com.rigrelay.fleet.claim.v1"
XATTR_STATE = "com.rigrelay.fleet.state.v1"
XATTR_LAST_FIX = "com.rigrelay.fleet.last_fix.v1"

_CLAIMS_DIR = Path(".rig/relay/fleet/claims")


# ── Enumerations ──────────────────────────────────────────────────────────────


class XattrStatus(StrEnum):
    applied = "applied"
    degraded_xattr_failure = "degraded_xattr_failure"
    platform_unsupported = "platform_unsupported"
    not_applicable = "not_applicable"
    no_target_paths = "no_target_paths"


# ── Payload and result types ──────────────────────────────────────────────────


@dataclass(frozen=True)
class ClaimXattrPayload:
    """Bundle of claim metadata written as xattr JSON on each target path."""

    mission_id: str
    lane_id: str
    agent_id: str
    mode: str
    acquired_at: str
    expires_at: str
    base_sha256: str
    coordination_event_id: str
    state: str


@dataclass(frozen=True)
class XattrResult:
    status: XattrStatus
    claim_id: str | None = None
    target_count: int = 0
    failed_paths: list[str] | None = None
    error_detail: str | None = None


# ── Internal helpers ──────────────────────────────────────────────────────────


def _xattr_available() -> bool:
    return sys.platform == "darwin" and hasattr(os, "setxattr")


def _set_xattr_safe(path: str, key: str, value: bytes) -> bool:
    try:
        os.setxattr(path, key, value, 0)
        return True
    except (OSError, PermissionError, AttributeError):
        return False


def _get_xattr_safe(path: str, key: str) -> bytes | None:
    try:
        return os.getxattr(path, key)
    except (OSError, AttributeError):
        return None


def _remove_xattr_safe(path: str, key: str) -> bool:
    try:
        os.removexattr(path, key)
        return True
    except (OSError, AttributeError):
        return False


def _list_xattrs_safe(path: str) -> list[str]:
    try:
        return list(os.listxattr(path))
    except (OSError, AttributeError):
        return []


def _is_pointer_artifact(path: Path) -> bool:
    try:
        path.relative_to(_CLAIMS_DIR)
        return path.suffix == ".json"
    except ValueError:
        return False


def _build_claim_xattr_value(payload: ClaimXattrPayload) -> bytes:
    value = {
        "mission_id": payload.mission_id,
        "lane_id": payload.lane_id,
        "agent_id": payload.agent_id,
        "mode": payload.mode,
        "acquired_at": payload.acquired_at,
        "expires_at": payload.expires_at,
        "base_sha256": payload.base_sha256,
        "coordination_event_id": payload.coordination_event_id,
    }
    return json.dumps(value, separators=(",", ":")).encode("utf-8")


# ── Public API ────────────────────────────────────────────────────────────────


def project_claim_xattrs(
    claim_id: str, payload: ClaimXattrPayload, target_paths: list[str] | None = None
) -> XattrResult:
    if not _xattr_available():
        return XattrResult(
            status=XattrStatus.platform_unsupported, claim_id=claim_id, target_count=0
        )

    if target_paths is None:
        target_paths = []
    if not target_paths:
        pointer_path = _CLAIMS_DIR / f"{claim_id}.json"
        pointer_path.parent.mkdir(parents=True, exist_ok=True)
        pointer_payload = {
            "claim_id": claim_id,
            "mission_id": payload.mission_id,
            "lane_id": payload.lane_id,
            "agent_id": payload.agent_id,
            "mode": payload.mode,
            "state": payload.state,
            "acquired_at": payload.acquired_at,
            "expires_at": payload.expires_at,
            "coordination_event_id": payload.coordination_event_id,
            "claimed_paths_count": 0,
        }
        pointer_path.write_text(
            json.dumps(pointer_payload, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        target_paths = [str(pointer_path)]

    xattr_value = _build_claim_xattr_value(payload)
    state_bytes = payload.state.encode("utf-8")

    failed_paths: list[str] = []
    for path_str in target_paths:
        claim_ok = _set_xattr_safe(path_str, XATTR_CLAIM, xattr_value)
        state_ok = _set_xattr_safe(path_str, XATTR_STATE, state_bytes)
        if not claim_ok or not state_ok:
            failed_paths.append(path_str)
            logger.warning(
                "xattr write degraded: path=%s claim_ok=%s state_ok=%s",
                path_str,
                claim_ok,
                state_ok,
            )

    if not failed_paths and len(target_paths) > 0:
        return XattrResult(
            status=XattrStatus.applied,
            claim_id=claim_id,
            target_count=len(target_paths),
        )

    return XattrResult(
        status=XattrStatus.degraded_xattr_failure,
        claim_id=claim_id,
        target_count=len(target_paths),
        failed_paths=failed_paths,
    )


def remove_claim_xattrs(target_paths: list[str]) -> XattrResult:
    if not _xattr_available():
        return XattrResult(status=XattrStatus.platform_unsupported)

    if not target_paths:
        return XattrResult(status=XattrStatus.no_target_paths)

    claim_ids_from_pointers: set[str] = set()
    failed_paths: list[str] = []

    for path_str in target_paths:
        claim_ok = _remove_xattr_safe(path_str, XATTR_CLAIM)
        state_ok = _remove_xattr_safe(path_str, XATTR_STATE)

        path_obj = Path(path_str)
        if _is_pointer_artifact(path_obj):
            claim_ids_from_pointers.add(path_obj.stem)

        if not claim_ok or not state_ok:
            failed_paths.append(path_str)

    for cid in claim_ids_from_pointers:
        pointer_path = _CLAIMS_DIR / f"{cid}.json"
        try:
            pointer_path.unlink(missing_ok=True)
        except OSError:
            logger.debug("could not remove pointer artifact: %s", pointer_path)

    if failed_paths:
        return XattrResult(
            status=XattrStatus.degraded_xattr_failure,
            target_count=len(target_paths),
            failed_paths=failed_paths,
        )

    return XattrResult(status=XattrStatus.applied, target_count=len(target_paths))


def read_claim_xattrs(path: str) -> dict[str, str] | None:
    claim_raw = _get_xattr_safe(path, XATTR_CLAIM)
    state_raw = _get_xattr_safe(path, XATTR_STATE)

    if claim_raw is None and state_raw is None:
        return None

    result: dict[str, str] = {}
    if claim_raw is not None:
        try:
            claim_data = json.loads(claim_raw.decode("utf-8"))
            if isinstance(claim_data, dict):
                for k, v in claim_data.items():
                    if isinstance(v, str):
                        result[k] = v
        except (json.JSONDecodeError, UnicodeDecodeError, TypeError):
            result["_claim_parse_error"] = "true"

    if state_raw is not None:
        try:
            result["state"] = state_raw.decode("utf-8")
        except UnicodeDecodeError:
            result["_state_parse_error"] = "true"

    return result if result else None


def find_claimed_files(search_dir: str, workspace_authority_id: str) -> list[str]:
    if not _xattr_available():
        return []

    claimed: list[str] = []
    try:
        for root, _dirs, files in os.walk(search_dir):
            for fname in files:
                fpath = os.path.join(root, fname)
                attrs = _list_xattrs_safe(fpath)
                if XATTR_CLAIM in attrs:
                    claimed.append(fpath)
    except OSError:
        return []

    return claimed


# ── Exports ───────────────────────────────────────────────────────────────────

__all__ = [
    "XATTR_CLAIM",
    "XATTR_LAST_FIX",
    "XATTR_STATE",
    "ClaimXattrPayload",
    "XattrResult",
    "XattrStatus",
    "find_claimed_files",
    "project_claim_xattrs",
    "read_claim_xattrs",
    "remove_claim_xattrs",
]

from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
from typing import Any

from rig_relay.governance.auth_receipts import generate_dev_receipt, validate_receipt

SUPPORTED_DEV_ACTIONS = frozenset({"checkpoint.commit", "lease_cleanup.archive"})
SUPPORTED_LOCAL_AUTH_ACTIONS = SUPPORTED_DEV_ACTIONS
DEFAULT_RECEIPTS_DIR = (
    Path(__file__).resolve().parent.parent.parent
    / ".build"
    / "rig-relay"
    / "desktop"
    / "authorization-receipts"
)


def _sha256_json(data: dict[str, Any]) -> str:
    return (
        "sha256:"
        + hashlib.sha256(
            json.dumps(data, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
    )


def mint_dev_receipt(
    action: str,
    *,
    ttl_seconds: int = 300,
    reason: str | None = None,
    receipts_dir: Path | None = None,
) -> dict[str, Any]:
    if action not in SUPPORTED_DEV_ACTIONS:
        return {
            "valid": False,
            "action": action,
            "status": "refused",
            "expires_at": None,
            "receipt_sha256": "",
            "warnings": [f"Action '{action}' is not enabled for dev receipt minting."],
        }

    bounded_ttl = max(30, min(int(ttl_seconds), 3600))
    receipt = generate_dev_receipt(action, ttl_seconds=bounded_ttl)
    receipt_dir = receipts_dir or DEFAULT_RECEIPTS_DIR
    receipt_dir.mkdir(parents=True, exist_ok=True)
    receipt_path = receipt_dir / f"{receipt['receipt_sha256']}.json"
    receipt_path.write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    warnings = list(receipt.get("warnings", []))
    if reason:
        warnings.append(f"Reason: {reason[:160]}")
    return {
        "valid": True,
        "action": action,
        "status": "minted",
        "created_at": receipt["created_at"],
        "expires_at": receipt["expires_at"],
        "receipt_sha256": receipt["receipt_sha256"],
        "receipt_ref": str(receipt_path),
        "authorization_receipt": receipt,
        "warnings": warnings,
    }


def mint_local_auth_receipt(
    action: str,
    *,
    ttl_seconds: int = 300,
    reason: str | None = None,
    receipts_dir: Path | None = None,
) -> dict[str, Any]:
    if action not in SUPPORTED_LOCAL_AUTH_ACTIONS:
        return {
            "valid": False,
            "action": action,
            "status": "refused",
            "expires_at": None,
            "receipt_sha256": "",
            "warnings": [
                f"Action '{action}' is not enabled for local system auth receipt minting."
            ],
        }

    from rig_relay.desktop.local_system_auth import authenticate_local_user

    auth = authenticate_local_user(reason or f"Authorize {action}", ttl_seconds)
    if auth.status != "authorized":
        return {
            "valid": False,
            "action": action,
            "status": auth.status,
            "expires_at": None,
            "receipt_sha256": "",
            "warnings": auth.warnings + [auth.reason],
        }

    bounded_ttl = max(30, min(int(ttl_seconds), 3600))
    receipt = generate_dev_receipt(action, ttl_seconds=bounded_ttl)
    receipt["method"] = "local_system_auth"
    receipt["warnings"] = list(receipt.get("warnings", [])) + list(auth.warnings)
    receipt["receipt_sha256"] = _sha256_json(receipt)

    receipt_dir = receipts_dir or DEFAULT_RECEIPTS_DIR
    receipt_dir.mkdir(parents=True, exist_ok=True)
    receipt_path = receipt_dir / f"{receipt['receipt_sha256']}.json"
    receipt_path.write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    warnings = list(receipt.get("warnings", []))
    if reason:
        warnings.append(f"Reason: {reason[:160]}")
    return {
        "valid": True,
        "action": action,
        "status": "minted",
        "created_at": receipt["created_at"],
        "expires_at": receipt["expires_at"],
        "receipt_sha256": receipt["receipt_sha256"],
        "receipt_ref": str(receipt_path),
        "authorization_receipt": receipt,
        "warnings": warnings,
    }


def inspect_receipt(receipt: dict[str, Any]) -> dict[str, Any]:
    action = str(receipt.get("action", ""))
    valid, reason = validate_receipt(receipt, action)
    expires_at = receipt.get("expires_at")
    status = "valid" if valid else "invalid"
    if expires_at and isinstance(expires_at, str):
        try:
            if datetime.fromisoformat(expires_at.replace("Z", "+00:00")) < datetime.now(
                UTC
            ):
                status = "expired"
                valid = False
        except ValueError:
            status = "invalid"
            valid = False
    return {
        "valid": valid,
        "action": action,
        "status": status,
        "method": receipt.get("method", ""),
        "expires_at": expires_at,
        "receipt_sha256": receipt.get("receipt_sha256", ""),
        "warnings": [] if valid else [reason],
    }

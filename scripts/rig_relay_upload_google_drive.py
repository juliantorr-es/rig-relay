#!/usr/bin/env python3
# ruff: noqa: PLR0911, PLR0914
"""Rig Relay Google Drive Upload Client.

Dry-run and real upload client for telemetry bundles. Real upload uses Google
Drive API with resumable upload for reliability. Credentials are never stored
in the repo.

In this foundation slice, only dry-run behavior is implemented. Real upload
requires google-api-python-client and google-auth-oauthlib dependencies.

Usage:
    uv run python scripts/rig_relay_upload_google_drive.py \
        --bundle .build/rig-relay/telemetry-bundles/bundle_20260513_test.zip \
        --folder-id 1abc123 \
        --participant-id anon_test_001 \
        --dry-run

    uv run python scripts/rig_relay_upload_google_drive.py \
        --bundle <path> \
        --folder-id <drive-folder-id> \
        --participant-id anon_test_001 \
        --confirm

Content-light: never includes raw prompts, model outputs, file contents,
stdout/stderr bodies, diffs, or secrets. Receipts use content-light metadata only.
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import sys
from typing import Any

from google.auth.transport.requests import Request as GoogleAuthRequest
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

from rig_relay.governance.auth_receipts import validate_receipt

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_RECEIPT_DIR = REPO_ROOT / ".build" / "rig-relay" / "drive-uploads"


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _upload_dry_run(
    bundle_path: Path, folder_id: str | None, participant_id: str, share_level: str
) -> dict[str, Any]:
    """Create a dry-run upload receipt without network access.

    Args:
        bundle_path: Path to the bundle zip.
        folder_id: Target Google Drive folder ID (or None).
        participant_id: Anonymous participant identifier.
        share_level: Share level for this upload.

    Returns:
        Upload receipt dict with status='dry_run'.
    """
    now = datetime.now(UTC)
    bundle_sha256 = _sha256_file(bundle_path)

    receipt: dict[str, Any] = {
        "schema_version": "rig.relay.google_drive_upload_receipt.v1",
        "bundle_id": bundle_path.stem,
        "participant_id": participant_id,
        "share_level": share_level,
        "destination": "google_drive",
        "drive_file_id": None,
        "drive_folder_id": folder_id,
        "uploaded_at": now.isoformat(),
        "upload_method": "dry_run",
        "bundle_sha256": f"sha256:{bundle_sha256}",
        "status": "dry_run",
        "warnings": [],
    }

    if not folder_id:
        receipt["warnings"].append(
            "No folder ID provided. Upload would go to default location."
        )

    return receipt


def _upload_real(
    bundle_path: Path,
    folder_id: str | None,
    participant_id: str,
    share_level: str,
    state_root: Path | None = None,
) -> dict[str, Any]:
    """Real Google Drive upload with resumable upload.

    Requires google-api-python-client and google-auth-oauthlib.

    Args:
        bundle_path: Path to the bundle zip.
        folder_id: Target Google Drive folder ID (or None).
        participant_id: Anonymous participant identifier.
        share_level: Share level for this upload.
        state_root: Explicit state root. If None, uses ~/.rig/relay/.

    Returns:
        Upload receipt dict.

    Raises:
        RuntimeError: If upload fails.
    """
    from typing import cast

    from rig_relay.identity.state_paths import default_relay_state_root

    SCOPES = ["https://www.googleapis.com/auth/drive.file"]

    now = datetime.now(UTC)
    bundle_sha256 = _sha256_file(bundle_path)
    bundle_name = bundle_path.name

    relay_root = state_root or default_relay_state_root()

    # Authenticate (OAuth 2.0 local server flow)
    creds: Credentials | None = None
    token_path = relay_root / "drive_token.json"

    if token_path.is_file():
        creds = cast(
            Credentials, Credentials.from_authorized_user_file(str(token_path), SCOPES)
        )

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(GoogleAuthRequest())
        else:
            creds_path = relay_root / "drive_credentials.json"
            if not creds_path.is_file():
                raise RuntimeError(
                    f"OAuth credentials not found at {creds_path}. "
                    "Download from Google Cloud Console and save to that path."
                )
            flow = InstalledAppFlow.from_client_secrets_file(str(creds_path), SCOPES)
            creds = cast(Credentials, flow.run_local_server(port=0))

        # Save token
        token_path.parent.mkdir(parents=True, exist_ok=True)
        assert creds is not None
        with token_path.open("w") as f:
            f.write(creds.to_json())

    # Build Drive service
    service = build("drive", "v3", credentials=creds)

    # Prepare file metadata
    file_metadata: dict[str, Any] = {"name": bundle_name}
    if folder_id:
        file_metadata["parents"] = [folder_id]

    # Resumable upload
    media = MediaFileUpload(
        str(bundle_path),
        mimetype="application/zip",
        resumable=True,
        chunksize=256 * 1024,  # 256KB chunks
    )

    request = service.files().create(
        body=file_metadata, media_body=media, fields="id, name, size, createdTime"
    )

    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            print(f"  Upload progress: {int(status.progress() * 100)}%")

    file_id = response.get("id")
    file_size = response.get("size", 0)
    print(f"  Uploaded: {response.get('name')} (id={file_id}, size={file_size})")

    receipt: dict[str, Any] = {
        "schema_version": "rig.relay.google_drive_upload_receipt.v1",
        "bundle_id": bundle_path.stem,
        "participant_id": participant_id,
        "share_level": share_level,
        "destination": "google_drive",
        "drive_file_id": file_id,
        "drive_folder_id": folder_id,
        "uploaded_at": now.isoformat(),
        "upload_method": "resumable",
        "bundle_sha256": f"sha256:{bundle_sha256}",
        "status": "uploaded",
        "warnings": [],
    }

    return receipt


def upload_bundle(
    bundle_path: Path,
    *,
    folder_id: str | None = None,
    participant_id: str = "anon_unknown",
    share_level: str = "derived_only",
    dry_run: bool = True,
    confirm: bool = False,
    state_root: Path | None = None,
) -> dict[str, Any]:
    """Upload a telemetry bundle to Google Drive.

    Args:
        bundle_path: Path to the bundle zip file.
        folder_id: Google Drive folder ID to upload to.
        participant_id: Anonymous participant identifier.
        share_level: Share level for this upload.
        dry_run: If True, create a local receipt without network access.
        confirm: If True, proceed with real upload (requires dry_run=False).
        state_root: Explicit state root. If None, uses ~/.rig/relay/.

    Returns:
        Upload receipt dict.
    """
    if dry_run or not confirm:
        return _upload_dry_run(
            bundle_path=bundle_path,
            folder_id=folder_id,
            participant_id=participant_id,
            share_level=share_level,
        )

    return _upload_real(
        bundle_path=bundle_path,
        folder_id=folder_id,
        participant_id=participant_id,
        share_level=share_level,
        state_root=state_root,
    )


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Upload a Rig Relay telemetry bundle to Google Drive."
    )
    parser.add_argument(
        "--bundle",
        type=Path,
        required=True,
        help="Path to the telemetry bundle zip file.",
    )
    parser.add_argument(
        "--folder-id",
        type=str,
        default=None,
        help="Google Drive folder ID for upload destination.",
    )
    parser.add_argument(
        "--participant-id",
        type=str,
        default="anon_unknown",
        help="Anonymous participant identifier.",
    )
    parser.add_argument(
        "--share-level",
        type=str,
        default="derived_only",
        choices=[
            "off",
            "derived_only",
            "evidence_hashes",
            "debug_local_only",
            "debug_opt_in",
        ],
        help="Share level for this upload.",
    )
    parser.add_argument(
        "--dry-run",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Dry-run mode: create local receipt without network (default).",
    )
    parser.add_argument(
        "--confirm",
        action="store_true",
        default=False,
        help="Confirm and proceed with real upload (requires --no-dry-run).",
    )
    parser.add_argument(
        "--authorization-receipt",
        type=Path,
        default=None,
        help="Path to a signed authorization receipt for real uploads.",
    )
    parser.add_argument(
        "--dev-bypass",
        action="store_true",
        default=False,
        help="Skip authorization check (dev mode only).",
    )
    parser.add_argument(
        "--state-root",
        type=Path,
        default=None,
        help="Explicit state root path (default: ~/.rig/relay).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    if not args.bundle.is_file():
        print(f"Error: Bundle not found: {args.bundle}", file=sys.stderr)
        return 1

    if not args.dry_run and not args.confirm:
        print(
            "Error: Real upload requires --confirm. Use --dry-run for safe preview.",
            file=sys.stderr,
        )
        return 1

    # Authorization gate for real uploads
    if not args.dry_run and args.confirm:
        if args.authorization_receipt:
            try:
                receipt_data = json.loads(
                    args.authorization_receipt.read_text(encoding="utf-8")
                )
            except (json.JSONDecodeError, OSError) as e:
                print(
                    f"Error: Failed to read authorization receipt: {e}", file=sys.stderr
                )
                return 1
            scope = {"target_sha256": _sha256_file(args.bundle)}
            valid, reason = validate_receipt(
                receipt_data, "remote_upload.confirm", action_scope=scope
            )
            if not valid:
                print(f"Error: Authorization refused — {reason}", file=sys.stderr)
                return 1
        elif args.dev_bypass:
            print("Warning: Dev bypass enabled — no real authorization performed.")
        else:
            print(
                "Error: Real upload requires --authorization-receipt or --dev-bypass. "
                "Use --dry-run for safe preview.",
                file=sys.stderr,
            )
            return 1

    try:
        state_root = args.state_root
        receipt = upload_bundle(
            bundle_path=args.bundle,
            folder_id=args.folder_id,
            participant_id=args.participant_id,
            share_level=args.share_level,
            dry_run=args.dry_run,
            confirm=args.confirm,
            state_root=state_root,
        )
    except RuntimeError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    # Write receipt
    receipt_dir = DEFAULT_RECEIPT_DIR
    receipt_dir.mkdir(parents=True, exist_ok=True)
    receipt_path = receipt_dir / f"receipt_{args.bundle.stem}.json"
    with receipt_path.open("w", encoding="utf-8") as f:
        json.dump(receipt, f, indent=2)
        f.write("\n")

    status = receipt["status"]
    print(f"\nUpload receipt written to {receipt_path}")
    print(f"  Status: {status}")
    print(f"  Bundle: {args.bundle.name}")
    print(f"  Method: {receipt['upload_method']}")
    print(f"  SHA256: {receipt['bundle_sha256']}")
    if receipt.get("warnings"):
        for w in receipt["warnings"]:
            print(f"  Warning: {w}")

    if status == "dry_run":
        print("\n[Dry-run mode — no network upload performed]")
    elif status == "uploaded":
        print(f"\nUploaded to Drive file ID: {receipt.get('drive_file_id')}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

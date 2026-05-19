"""Google Drive uploader for telemetry bundles.

Uploads telemetry bundle zips to a user-configured Google Drive folder.
Uses OAuth token from DevFileTokenStore for Drive API authentication.

Requires the `drive.file` OAuth scope for minimal permission.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx

DRIVE_UPLOAD_URL = (
    "https://www.googleapis.com/upload/drive/v3/files?uploadType=multipart"
)
DRIVE_FOLDER_URL = "https://www.googleapis.com/drive/v3/files"
GOOGLE_DRIVE_SCOPE = "https://www.googleapis.com/auth/drive.file"
GOOGLE_USERINFO_SCOPE = "https://www.googleapis.com/auth/userinfo.email"

# The predefined folder ID for telemetry bundle uploads.
# Set by the Rig Relay team — users get a copy here automatically.
# Users can also configure their own folder via intent.
DEFAULT_TELEMETRY_FOLDER_ID_ENV = "RIG_RELAY_DRIVE_FOLDER_ID"

_UPLOAD_TIMEOUT = 120.0


class GoogleDriveUploadError(Exception):
    """Error during Google Drive upload."""


def _get_access_token() -> str:
    """Read the Google OAuth access token from the local token store.

    Returns:
        The access token string.

    Raises:
        GoogleDriveUploadError: If no token is available.
    """
    from rig_relay.identity.models import IdentityProviderKind
    from rig_relay.identity.token_store import (
        DevFileTokenStore,
        enable_dev_file_token_store,
    )

    # explicitly opt in to dev-only plaintext token storage
    enable_dev_file_token_store()
    store = DevFileTokenStore()
    metadata = store.get(IdentityProviderKind.GOOGLE)
    if metadata is None:
        raise GoogleDriveUploadError(
            "Not signed in to Google. Run sign_in_google_start + sign_in_google_exchange first."
        )
    if metadata.status.value != "signed_in":
        raise GoogleDriveUploadError(
            f"Google sign-in status is '{metadata.status.value}', expected 'signed_in'."
        )

    # Read the raw token from the dev store file
    import json

    token_path = store._path(IdentityProviderKind.GOOGLE)
    if not token_path.is_file():
        raise GoogleDriveUploadError("Token file not found.")

    data = json.loads(token_path.read_text(encoding="utf-8"))
    raw_token_placeholder = data.get("_raw_token_placeholder", "")
    if not raw_token_placeholder or not raw_token_placeholder.endswith("..."):
        raise GoogleDriveUploadError("No access token available.")

    # For dev store, full token is stored in the metadata field
    # (we store the raw token for development convenience)
    token_bundle = data.get("token_bundle", {})
    access_token = token_bundle.get("access_token", "")
    if not access_token:
        raise GoogleDriveUploadError("Access token not found in store.")

    return access_token


def _get_drive_folder_id() -> str:
    """Get the Drive folder ID for telemetry uploads.

    Prefers the custom folder ID from environment, falls back to
    a default Rig Relay folder.
    """
    import os

    folder_id = os.environ.get(DEFAULT_TELEMETRY_FOLDER_ID_ENV, "")
    if folder_id:
        return folder_id
    # Default fallback: upload to root ("root" tells Drive to use the user's root)
    return "root"


def _make_upload_metadata(bundle_path: Path, parent_folder_id: str) -> dict[str, Any]:
    """Build Drive API metadata for the upload."""
    return {
        "name": bundle_path.name,
        "parents": [parent_folder_id] if parent_folder_id != "root" else [],
        "description": (
            f"Rig Relay telemetry bundle — "
            f"content-light derived datasets only. "
            f"Generated at {bundle_path.stat().st_mtime_ns}."
        ),
        "mimeType": "application/zip",
    }


async def upload_bundle(
    bundle_path: Path,
    target_folder_id: str | None = None,
    access_token: str | None = None,
) -> dict[str, Any]:
    """Upload a telemetry bundle zip to Google Drive.

    Args:
        bundle_path: Path to the bundle zip file.
        target_folder_id: Optional target Drive folder ID. Uses default if None.
        access_token: Optional Google OAuth access token. Reads from store if None.

    Returns:
        Dict with upload result (file_id, name, size_bytes, web_view_link).

    Raises:
        GoogleDriveUploadError: If upload fails.
        FileNotFoundError: If bundle_path doesn't exist.
    """
    if not bundle_path.is_file():
        raise FileNotFoundError(f"Bundle not found: {bundle_path}")

    if access_token is None:
        access_token = _get_access_token()

    folder_id = target_folder_id or _get_drive_folder_id()

    metadata = _make_upload_metadata(bundle_path, folder_id)
    bundle_bytes = bundle_path.read_bytes()

    # Build multipart upload body
    import json as json_mod

    boundary = "-------rig_relay_drive_upload_boundary"
    body_parts: list[bytes] = []

    # Metadata part
    body_parts.append(f"--{boundary}\r\n".encode())
    body_parts.append(b"Content-Type: application/json; charset=UTF-8\r\n\r\n")
    body_parts.append(json_mod.dumps(metadata).encode())
    body_parts.append(b"\r\n")

    # File content part
    body_parts.append(f"--{boundary}\r\n".encode())
    body_parts.append(b"Content-Type: application/zip\r\n\r\n")
    body_parts.append(bundle_bytes)
    body_parts.append(b"\r\n")

    # End boundary
    body_parts.append(f"--{boundary}--\r\n".encode())

    body = b"".join(body_parts)

    async with httpx.AsyncClient(timeout=_UPLOAD_TIMEOUT) as client:
        resp = await client.post(
            DRIVE_UPLOAD_URL,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": f"multipart/related; boundary={boundary}",
            },
            content=body,
        )

        if resp.status_code == 401:
            raise GoogleDriveUploadError(
                "Google Drive access denied. Token may be expired. "
                "Run sign_in_google_start again."
            )
        if resp.status_code == 403:
            raise GoogleDriveUploadError(
                "Google Drive permission denied. "
                "Ensure the account has write access to the target folder."
            )

        resp.raise_for_status()
        result: dict[str, Any] = resp.json()

    file_id = result.get("id", "")

    # Fetch the web view link for the uploaded file
    web_link = ""
    if file_id:
        try:
            meta_resp = await client.get(
                f"{DRIVE_FOLDER_URL}/{file_id}",
                params={"fields": "id,name,size,webViewLink,mimeType"},
                headers={"Authorization": f"Bearer {access_token}"},
            )
            if meta_resp.status_code == 200:
                meta = meta_resp.json()
                web_link = meta.get("webViewLink", "")
        except Exception:
            pass

    return {
        "file_id": file_id,
        "name": result.get("name", bundle_path.name),
        "size_bytes": len(bundle_bytes),
        "mime_type": result.get("mimeType", "application/zip"),
        "web_view_link": web_link,
        "uploaded_at": __import__("datetime")
        .datetime.now(__import__("datetime").timezone.utc)
        .isoformat(),
    }


async def create_telemetry_folder(
    folder_name: str = "Rig Relay Telemetry", access_token: str | None = None
) -> dict[str, Any]:
    """Create a Google Drive folder for telemetry bundles.

    Args:
        folder_name: Name for the Drive folder.
        access_token: Optional Google OAuth access token.

    Returns:
        Dict with folder_id, name, web_view_link.
    """
    if access_token is None:
        access_token = _get_access_token()

    async with httpx.AsyncClient(timeout=_UPLOAD_TIMEOUT) as client:
        resp = await client.post(
            DRIVE_FOLDER_URL,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            },
            json={
                "name": folder_name,
                "mimeType": "application/vnd.google-apps.folder",
            },
        )
        resp.raise_for_status()
        result: dict[str, Any] = resp.json()

    return {
        "folder_id": result.get("id", ""),
        "name": result.get("name", folder_name),
        "web_view_link": (
            f"https://drive.google.com/drive/folders/{result.get('id', '')}"
        ),
    }


__all__ = ["GoogleDriveUploadError", "create_telemetry_folder", "upload_bundle"]

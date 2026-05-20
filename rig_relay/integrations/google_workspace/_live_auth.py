"""Live Google OAuth flow — real HTTP calls, content-light outputs.

No raw tokens, client secrets, or private keys are ever logged,
printed, or returned in any output.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import importlib
import os
from typing import Any

_OAUTH_TOKEN_URL = "https://oauth2.googleapis.com/token"
_OAUTH_TOKENINFO_URL = "https://www.googleapis.com/oauth2/v1/tokeninfo"
_OAUTH_USERINFO_URL = "https://www.googleapis.com/oauth2/v1/userinfo"
_GMAIL_PROFILE_URL = "https://gmail.googleapis.com/gmail/v1/users/me/profile"
_CALENDAR_LIST_URL = "https://www.googleapis.com/calendar/v3/users/me/calendarList"
_DRIVE_FILES_URL = "https://www.googleapis.com/drive/v3/files"


def _sha256_hex(data: str) -> str:
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def _content_light_token_response(raw: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    access_token = raw.get("access_token", "")
    if access_token:
        result["token_hash"] = _sha256_hex(access_token)
    result["expires_in"] = raw.get("expires_in", 0)
    result["scope"] = raw.get("scope", "")
    result["token_type"] = raw.get("token_type", "")
    if "refresh_token" in raw:
        result["refresh_token_hash"] = _sha256_hex(raw["refresh_token"])
    return result


def _get_httpx() -> type | None:
    try:
        importlib.import_module("httpx")
    except ImportError:
        return None
    import httpx

    return httpx


@dataclass
class GoogleLiveAuthConfig:
    client_id: str = field(
        default_factory=lambda: os.environ.get("RIG_GOOGLE_CLIENT_ID", "")
    )
    client_secret: str = field(
        default_factory=lambda: os.environ.get("RIG_GOOGLE_CLIENT_SECRET", "")
    )
    redirect_uri: str = field(
        default_factory=lambda: os.environ.get("RIG_GOOGLE_REDIRECT_URI", "")
    )
    service_account_key_path: str = field(
        default_factory=lambda: os.environ.get(
            "RIG_GOOGLE_SERVICE_ACCOUNT_KEY_PATH", ""
        )
    )
    service_account_email: str = field(
        default_factory=lambda: os.environ.get("RIG_GOOGLE_SERVICE_ACCOUNT_EMAIL", "")
    )
    domain_wide_delegation_subject: str = field(
        default_factory=lambda: os.environ.get(
            "RIG_GOOGLE_DOMAIN_WIDE_DELEGATION_SUBJECT", ""
        )
    )
    admin_email: str = field(
        default_factory=lambda: os.environ.get("RIG_GOOGLE_ADMIN_EMAIL", "")
    )

    def is_configured(self) -> bool:
        has_oauth = bool(self.client_id and self.client_secret)
        has_service_account = bool(
            self.service_account_email
            and self.service_account_key_path
            and os.path.isfile(self.service_account_key_path)
        )
        return has_oauth or has_service_account

    def config_summary(self) -> dict[str, Any]:
        return {
            "oauth_configured": bool(self.client_id and self.client_secret),
            "redirect_uri_configured": bool(self.redirect_uri),
            "service_account_configured": bool(
                self.service_account_email
                and self.service_account_key_path
                and os.path.isfile(self.service_account_key_path)
            ),
            "domain_wide_delegation_configured": bool(
                self.domain_wide_delegation_subject and self.admin_email
            ),
            "client_id_hash": _sha256_hex(self.client_id) if self.client_id else "",
            "service_account_email_hash": _sha256_hex(self.service_account_email)
            if self.service_account_email
            else "",
            "admin_email_hash": _sha256_hex(self.admin_email)
            if self.admin_email
            else "",
        }


class GoogleLiveTokenExchanger:
    @staticmethod
    def exchange_oauth_code(
        code: str,
        code_verifier: str,
        client_id: str,
        client_secret: str,
        redirect_uri: str,
    ) -> dict[str, Any]:
        httpx_mod = _get_httpx()
        if httpx_mod is None:
            return {
                "schema_version": "rig.google_workspace.live_auth_refusal.v1",
                "error": "httpx_not_available",
                "error_description": "httpx library is required for live OAuth",
            }

        response = httpx_mod.post(
            _OAUTH_TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "code_verifier": code_verifier,
                "client_id": client_id,
                "client_secret": client_secret,
                "redirect_uri": redirect_uri,
            },
            headers={"Accept": "application/json"},
        )
        response.raise_for_status()
        raw: dict[str, Any] = response.json()
        return _content_light_token_response(raw)

    @staticmethod
    def exchange_refresh_token(
        refresh_token: str, client_id: str, client_secret: str
    ) -> dict[str, Any]:
        httpx_mod = _get_httpx()
        if httpx_mod is None:
            return {
                "schema_version": "rig.google_workspace.live_auth_refusal.v1",
                "error": "httpx_not_available",
                "error_description": "httpx library is required for live OAuth",
            }

        response = httpx_mod.post(
            _OAUTH_TOKEN_URL,
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": client_id,
                "client_secret": client_secret,
            },
            headers={"Accept": "application/json"},
        )
        response.raise_for_status()
        raw: dict[str, Any] = response.json()
        return _content_light_token_response(raw)

    @staticmethod
    def validate_token(token: str) -> dict[str, Any]:
        httpx_mod = _get_httpx()
        if httpx_mod is None:
            return {
                "schema_version": "rig.google_workspace.live_auth_refusal.v1",
                "error": "httpx_not_available",
                "error_description": "httpx library is required for live token validation",
            }

        response = httpx_mod.get(
            f"{_OAUTH_TOKENINFO_URL}?access_token={token}",
            headers={"Accept": "application/json"},
        )
        response.raise_for_status()
        raw: dict[str, Any] = response.json()
        result: dict[str, Any] = {
            "scope": raw.get("scope", ""),
            "expires_in": raw.get("expires_in", 0),
            "verified_email": raw.get("verified_email", False),
        }
        email = raw.get("email", "")
        if email:
            result["email_hash"] = _sha256_hex(email)
        return result


class GoogleLiveReadOnlySmoke:
    _GMAIL_SCOPES = frozenset({
        "https://www.googleapis.com/auth/gmail.readonly",
        "https://mail.google.com/",
        "https://www.googleapis.com/auth/gmail.metadata",
    })
    _CALENDAR_SCOPES = frozenset({
        "https://www.googleapis.com/auth/calendar.readonly",
        "https://www.googleapis.com/auth/calendar.events.readonly",
        "https://www.googleapis.com/auth/calendar",
    })
    _DRIVE_SCOPES = frozenset({
        "https://www.googleapis.com/auth/drive.metadata.readonly",
        "https://www.googleapis.com/auth/drive.readonly",
        "https://www.googleapis.com/auth/drive",
    })

    @staticmethod
    def _requires_scope(token_scope: str, required: frozenset[str]) -> bool:
        token_scopes = {s.strip() for s in token_scope.split()}
        return bool(token_scopes & required)

    @staticmethod
    def _httpx_refusal(call_name: str) -> dict[str, Any]:
        return {
            "schema_version": "rig.google_workspace.live_auth_refusal.v1",
            "error": "httpx_not_available",
            "error_description": f"httpx library is required for {call_name}",
        }

    @staticmethod
    def _scope_refusal(call_name: str, required_scopes: str) -> dict[str, Any]:
        return {
            "schema_version": "rig.google_workspace.live_auth_refusal.v1",
            "error": "missing_scope",
            "error_description": f"{call_name} requires one of: {required_scopes}",
        }

    @staticmethod
    def inspect_identity(token: str) -> dict[str, Any]:
        httpx_mod = _get_httpx()
        if httpx_mod is None:
            return GoogleLiveReadOnlySmoke._httpx_refusal("inspect_identity")

        try:
            response = httpx_mod.get(
                _OAUTH_USERINFO_URL, headers={"Authorization": f"Bearer {token}"}
            )
            response.raise_for_status()
            raw: dict[str, Any] = response.json()
            return {
                "id_hash": _sha256_hex(raw.get("id", "")),
                "email_hash": _sha256_hex(raw.get("email", ""))
                if raw.get("email")
                else "",
                "verified_email": bool(raw.get("verified_email")),
                "has_name": bool(raw.get("name")),
                "has_picture": bool(raw.get("picture")),
            }
        except Exception as e:
            return {
                "schema_version": "rig.google_workspace.live_auth_refusal.v1",
                "error": "inspect_identity_failed",
                "error_description": str(e)[:256],
            }

    @staticmethod
    def list_gmail_profile(token: str, token_scope: str = "") -> dict[str, Any]:
        httpx_mod = _get_httpx()
        if httpx_mod is None:
            return GoogleLiveReadOnlySmoke._httpx_refusal("list_gmail_profile")

        if token_scope and not GoogleLiveReadOnlySmoke._requires_scope(
            token_scope, GoogleLiveReadOnlySmoke._GMAIL_SCOPES
        ):
            return GoogleLiveReadOnlySmoke._scope_refusal(
                "list_gmail_profile", "gmail.readonly or gmail.metadata"
            )

        try:
            response = httpx_mod.get(
                _GMAIL_PROFILE_URL, headers={"Authorization": f"Bearer {token}"}
            )
            response.raise_for_status()
            raw: dict[str, Any] = response.json()
            return {
                "email_hash": _sha256_hex(raw.get("emailAddress", "")),
                "messages_total": raw.get("messagesTotal", 0),
                "threads_total": raw.get("threadsTotal", 0),
                "history_id_hash": _sha256_hex(str(raw.get("historyId", ""))),
            }
        except Exception as e:
            return {
                "schema_version": "rig.google_workspace.live_auth_refusal.v1",
                "error": "list_gmail_profile_failed",
                "error_description": str(e)[:256],
            }

    @staticmethod
    def list_calendar_list(token: str, token_scope: str = "") -> dict[str, Any]:
        httpx_mod = _get_httpx()
        if httpx_mod is None:
            return GoogleLiveReadOnlySmoke._httpx_refusal("list_calendar_list")

        if token_scope and not GoogleLiveReadOnlySmoke._requires_scope(
            token_scope, GoogleLiveReadOnlySmoke._CALENDAR_SCOPES
        ):
            return GoogleLiveReadOnlySmoke._scope_refusal(
                "list_calendar_list", "calendar.readonly or calendar.events.readonly"
            )

        try:
            response = httpx_mod.get(
                _CALENDAR_LIST_URL, headers={"Authorization": f"Bearer {token}"}
            )
            response.raise_for_status()
            raw: dict[str, Any] = response.json()
            items = raw.get("items", [])
            calendars = []
            for cal in items:
                calendars.append({
                    "id_hash": _sha256_hex(cal.get("id", "")),
                    "summary_hash": _sha256_hex(cal.get("summary", ""))
                    if cal.get("summary")
                    else "",
                    "has_primary": cal.get("primary", False),
                })
            return {"calendar_count": len(calendars), "calendars": calendars[:10]}
        except Exception as e:
            return {
                "schema_version": "rig.google_workspace.live_auth_refusal.v1",
                "error": "list_calendar_list_failed",
                "error_description": str(e)[:256],
            }

    @staticmethod
    def list_drive_metadata(token: str, token_scope: str = "") -> dict[str, Any]:
        httpx_mod = _get_httpx()
        if httpx_mod is None:
            return GoogleLiveReadOnlySmoke._httpx_refusal("list_drive_metadata")

        if token_scope and not GoogleLiveReadOnlySmoke._requires_scope(
            token_scope, GoogleLiveReadOnlySmoke._DRIVE_SCOPES
        ):
            return GoogleLiveReadOnlySmoke._scope_refusal(
                "list_drive_metadata", "drive.metadata.readonly or drive.readonly"
            )

        try:
            response = httpx_mod.get(
                f"{_DRIVE_FILES_URL}?pageSize=5",
                headers={"Authorization": f"Bearer {token}"},
            )
            response.raise_for_status()
            raw: dict[str, Any] = response.json()
            files = []
            for f in raw.get("files", []):
                files.append({
                    "id_hash": _sha256_hex(f.get("id", "")),
                    "name_hash": _sha256_hex(f.get("name", ""))
                    if f.get("name")
                    else "",
                    "mime_type": f.get("mimeType", ""),
                    "is_folder": f.get("mimeType", "")
                    == "application/vnd.google-apps.folder",
                })
            return {
                "file_count": len(files),
                "next_page_token_hash": _sha256_hex(raw.get("nextPageToken", ""))
                if raw.get("nextPageToken")
                else "",
                "files": files,
            }
        except Exception as e:
            return {
                "schema_version": "rig.google_workspace.live_auth_refusal.v1",
                "error": "list_drive_metadata_failed",
                "error_description": str(e)[:256],
            }


__all__ = [
    "GoogleLiveAuthConfig",
    "GoogleLiveReadOnlySmoke",
    "GoogleLiveTokenExchanger",
]

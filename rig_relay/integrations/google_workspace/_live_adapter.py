"""Google Workspace live read-only HTTP adapter.

Makes authenticated httpx GET calls to Google APIs using OAuth2 access tokens.
Content-light: hashes only in receipts, never raw workspace content.
"""

from __future__ import annotations

import hashlib
import json
import os
from typing import Any, cast

import httpx

from rig_relay.integrations.google_workspace._capabilities import (
    evaluate_workspace_capability,
    load_capability_manifest,
)
from rig_relay.integrations.google_workspace._models import (
    GoogleWorkspaceAuthState,
    GoogleWorkspaceCapabilityManifest,
    GoogleWorkspaceOperationReceipt,
    GoogleWorkspaceOperationRequest,
    GoogleWorkspaceVerdict,
)
from rig_relay.integrations.google_workspace._receipts import (
    _hash_identifier,
    build_workspace_receipt,
)
from rig_relay.integrations.google_workspace._redaction import (
    assert_no_raw_secret_patterns,
    assert_no_workspace_content_fields,
)

_REQUIRED_API_SCOPES: dict[str, list[str]] = {
    "google_workspace.gmail.profile.get": [
        "https://www.googleapis.com/auth/gmail.metadata"
    ],
    "google_workspace.gmail.labels.list": [
        "https://www.googleapis.com/auth/gmail.labels"
    ],
    "google_workspace.calendar.calendarList.list": [
        "https://www.googleapis.com/auth/calendar.readonly"
    ],
    "google_workspace.drive.files.list": [
        "https://www.googleapis.com/auth/drive.metadata.readonly"
    ],
    "google_workspace.tasks.tasklists.list": [
        "https://www.googleapis.com/auth/tasks.readonly"
    ],
    "google_workspace.contacts.list": [
        "https://www.googleapis.com/auth/contacts.readonly"
    ],
}

_RESTRICTED_SCOPES: set[str] = {
    "https://www.googleapis.com/auth/drive.readonly",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/drive",
    "https://mail.google.com/",
}

_API_ENDPOINTS: dict[str, dict[str, Any]] = {
    "google_workspace.gmail.profile.get": {
        "url": "https://gmail.googleapis.com/gmail/v1/users/me/profile",
        "params": {"fields": "emailAddress,messagesTotal,threadsTotal"},
    },
    "google_workspace.gmail.labels.list": {
        "url": "https://gmail.googleapis.com/gmail/v1/users/me/labels",
        "params": {"fields": "labels/id,labels/name"},
    },
    "google_workspace.calendar.calendarList.list": {
        "url": "https://www.googleapis.com/calendar/v3/users/me/calendarList",
        "params": {"fields": "items/id,items/summary"},
    },
    "google_workspace.drive.files.list": {
        "url": "https://www.googleapis.com/drive/v3/files",
        "params": {"fields": "files(id,name,mimeType,size,modifiedTime)"},
    },
    "google_workspace.tasks.tasklists.list": {
        "url": "https://www.googleapis.com/tasks/v1/users/@me/lists",
        "params": {"fields": "items/id,items/title"},
    },
    "google_workspace.contacts.list": {
        "url": "https://people.googleapis.com/v1/people/me/connections",
        "params": {"personFields": "names,emailAddresses"},
    },
    "google_workspace.admin.directory.users.list": {
        "url": "https://admin.googleapis.com/admin/directory/v1/users",
        "params": {"fields": "users/primaryEmail"},
    },
}

_LIVE_PROVIDER_TESTS_ENV = "RIG_LIVE_PROVIDER_TESTS"

_MIN_HTTP_ERROR_STATUS = 400


def _sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _redact_contacts(contacts_raw: list[dict]) -> list[dict]:
    redacted: list[dict] = []
    for conn in contacts_raw:
        entry: dict[str, Any] = {}
        if "resourceName" in conn:
            entry["resourceName_hash"] = _sha256_hex(conn["resourceName"])
        names = conn.get("names", [])
        if names:
            entry["names_count"] = len(names)
        emails = conn.get("emailAddresses", [])
        if emails:
            entry["emailAddresses_hashes"] = [
                _sha256_hex(e.get("value", "")) for e in emails
            ]
        redacted.append(entry)
    return redacted


def _redact_drive_files(files: list[dict]) -> list[dict]:
    redacted: list[dict] = []
    for f in files:
        entry: dict[str, Any] = {"id_hash": _sha256_hex(f.get("id", ""))}
        if "name" in f:
            entry["name_hash"] = _sha256_hex(f["name"])
        if "mimeType" in f:
            entry["mimeType"] = f["mimeType"]
        if "size" in f:
            entry["size"] = f["size"]
        if "modifiedTime" in f:
            entry["modifiedTime"] = f["modifiedTime"]
        redacted.append(entry)
    return redacted


def _redact_calendars(calendars: list[dict]) -> list[dict]:
    return [
        {
            "id_hash": _sha256_hex(c.get("id", "")),
            "summary_hash": _sha256_hex(c.get("summary", "")),
        }
        for c in calendars
    ]


def _redact_gmail_labels(labels: list[dict]) -> list[dict]:
    return [
        {
            "id_hash": _sha256_hex(lb.get("id", "")),
            "name_hash": _sha256_hex(lb.get("name", "")),
        }
        for lb in labels
    ]


def _redact_admin_users(users: list[dict]) -> list[dict]:
    return [
        {
            "id_hash": _sha256_hex(u.get("id", "")),
            "primaryEmail_hash": _sha256_hex(u.get("primaryEmail", "")),
        }
        for u in users
    ]


def _redact_tasks(tasklists: list[dict]) -> list[dict]:
    return [
        {
            "id_hash": _sha256_hex(tl.get("id", "")),
            "title_hash": _sha256_hex(tl.get("title", "")),
        }
        for tl in tasklists
    ]


_REDACTORS: dict[str, Any] = {
    "google_workspace.gmail.labels.list": _redact_gmail_labels,
    "google_workspace.calendar.calendarList.list": _redact_calendars,
    "google_workspace.drive.files.list": _redact_drive_files,
    "google_workspace.contacts.list": _redact_contacts,
    "google_workspace.tasks.tasklists.list": _redact_tasks,
    "google_workspace.admin.directory.users.list": _redact_admin_users,
}


def _response_kind_for(capability_id: str) -> str:
    kinds = {
        "google_workspace.gmail.profile.get": "gmail_profile",
        "google_workspace.gmail.labels.list": "gmail_labels",
        "google_workspace.calendar.calendarList.list": "calendar_list",
        "google_workspace.drive.files.list": "drive_files",
        "google_workspace.tasks.tasklists.list": "tasklists",
        "google_workspace.contacts.list": "contacts",
        "google_workspace.admin.directory.users.list": "admin_directory_users",
    }
    return kinds.get(capability_id, "unknown")


async def run_live_workspace_read(
    operation_id: str,
    capability_id: str,
    auth: GoogleWorkspaceAuthState,
    access_token: str,
    *,
    subject_hash: str = "",
    customer_hash: str = "",
    resource_hash: str = "",
    domain: str = "",
    manifest: GoogleWorkspaceCapabilityManifest | None = None,
    trace_id: str = "",
    parent_trace_id: str = "",
) -> GoogleWorkspaceOperationReceipt:
    if manifest is None:
        manifest = load_capability_manifest()

    cap = manifest.get_capability(capability_id)
    op_kind = cap.operation_kind if cap else capability_id
    op_class = str(cap.operation_class) if cap else "public_read"

    decision = evaluate_workspace_capability(
        auth,
        capability_id,
        subject_hash=subject_hash,
        customer_hash=customer_hash,
        resource_hash=resource_hash,
        manifest=manifest,
    )

    request = GoogleWorkspaceOperationRequest(
        operation_id=operation_id,
        capability_id=capability_id,
        operation_kind=op_kind,
        operation_class=op_class,
        auth_state=auth,
        subject_hash=subject_hash,
        customer_hash=customer_hash,
        resource_hash=resource_hash,
    )

    if not decision.is_allowed:
        return build_workspace_receipt(
            request, decision, trace_id=trace_id, parent_trace_id=parent_trace_id
        )

    endpoint = _API_ENDPOINTS.get(capability_id)
    if endpoint is None:
        from rig_relay.integrations.google_workspace._models import (
            GoogleWorkspaceDecision,
        )

        refused = GoogleWorkspaceDecision(
            capability_id,
            GoogleWorkspaceVerdict.REFUSED,
            "google.endpoint.unknown",
            f"No API endpoint for capability: {capability_id}",
        )
        return build_workspace_receipt(
            request, refused, trace_id=trace_id, parent_trace_id=parent_trace_id
        )

    url: str = endpoint["url"]
    params: dict[str, str] = dict(endpoint["params"])

    if "google_workspace.admin.directory" in capability_id and domain:
        params["domain"] = domain

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            resp = await client.get(
                url,
                params=params,
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Accept": "application/json",
                },
            )
            raw_body = resp.text
            status_code = resp.status_code

            assert_no_raw_secret_patterns(raw_body)
        except httpx.HTTPStatusError as e:
            from rig_relay.integrations.google_workspace._models import (
                GoogleWorkspaceDecision,
            )

            failed = GoogleWorkspaceDecision(
                capability_id,
                GoogleWorkspaceVerdict.FAILED,
                "google.http.error",
                f"HTTP {e.response.status_code}",
            )
            return build_workspace_receipt(
                request, failed, trace_id=trace_id, parent_trace_id=parent_trace_id
            )
        except httpx.RequestError:
            from rig_relay.integrations.google_workspace._models import (
                GoogleWorkspaceDecision,
            )

            failed = GoogleWorkspaceDecision(
                capability_id,
                GoogleWorkspaceVerdict.FAILED,
                "google.network.error",
                "Network request failed",
            )
            return build_workspace_receipt(
                request, failed, trace_id=trace_id, parent_trace_id=parent_trace_id
            )

    if status_code >= _MIN_HTTP_ERROR_STATUS:
        from rig_relay.integrations.google_workspace._models import (
            GoogleWorkspaceDecision,
        )

        failed = GoogleWorkspaceDecision(
            capability_id,
            GoogleWorkspaceVerdict.FAILED,
            "google.http.error",
            f"HTTP {status_code}",
        )
        return build_workspace_receipt(
            request, failed, trace_id=trace_id, parent_trace_id=parent_trace_id
        )

    full_response_hash = _hash_identifier(raw_body)

    try:
        parsed = json.loads(raw_body)
    except json.JSONDecodeError:
        parsed = {"raw": "[non-JSON response]"}

    redactor = _REDACTORS.get(capability_id)
    redacted_content = None
    if redactor is not None and isinstance(parsed, dict):
        kind = _response_kind_for(capability_id)
        raw_list: list[dict] = []
        if kind == "contacts":
            raw_list = cast(list[dict], parsed.get("connections", []))
        elif kind == "tasklists":
            raw_list = cast(list[dict], parsed.get("items", []))
        elif kind == "gmail_labels":
            raw_list = cast(list[dict], parsed.get("labels", []))
        elif kind == "calendar_list":
            raw_list = cast(list[dict], parsed.get("items", []))
        elif kind == "drive_files":
            raw_list = cast(list[dict], parsed.get("files", []))
        elif kind == "admin_directory_users":
            raw_list = cast(list[dict], parsed.get("users", []))
        redacted_content = redactor(raw_list)

    response_meta: dict[str, Any] = {
        "live_call": True,
        "status_code": status_code,
        "full_response_hash": full_response_hash,
        "response_kind": _response_kind_for(capability_id),
    }
    if redacted_content is not None:
        response_meta["redacted_metadata_count"] = len(redacted_content)
        response_meta["redacted_metadata"] = redacted_content

    receipt = build_workspace_receipt(
        request,
        decision,
        response_meta,
        trace_id=trace_id,
        parent_trace_id=parent_trace_id,
    )

    receipt_dict = receipt.to_dict()
    assert_no_workspace_content_fields(receipt_dict)
    assert_no_raw_secret_patterns(json.dumps(receipt_dict))

    return receipt


def should_skip_live_tests() -> bool:
    return os.environ.get(_LIVE_PROVIDER_TESTS_ENV, "0") != "1"

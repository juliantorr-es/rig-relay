"""Google Workspace local fixture-backed read-only adapter.

No live Google API calls. Metadata-only outputs.
"""

from __future__ import annotations

from pathlib import Path

from rig_relay.integrations.google_workspace._capabilities import (
    evaluate_workspace_capability,
    load_capability_manifest,
)
from rig_relay.integrations.google_workspace._models import (
    GoogleWorkspaceAuthState,
    GoogleWorkspaceCapabilityManifest,
    GoogleWorkspaceOperationReceipt,
    GoogleWorkspaceOperationRequest,
)
from rig_relay.integrations.google_workspace._receipts import (
    _hash_identifier,
    build_workspace_receipt,
)

_SCHEMAS_DIR = Path(__file__).resolve().parents[3] / "docs" / "schemas"

_FIXTURES: dict[str, dict] = {
    "google_workspace.gmail.labels.list": {
        "labels": ["INBOX", "SENT", "DRAFTS"],
        "count": 3,
    },
    "google_workspace.gmail.profile.get": {
        "emailAddress": "user@example.com",
        "messagesTotal": 42,
    },
    "google_workspace.drive.files.list": {
        "files": [{"id": "file1", "name": "doc1"}, {"id": "file2", "name": "doc2"}]
    },
    "google_workspace.calendar.calendarList.list": {
        "calendars": [
            {"id": "cal1", "summary": "Primary"},
            {"id": "cal2", "summary": "Work"},
        ]
    },
    "google_workspace.admin.directory.users.list": {
        "users": [
            {"id": "u1", "primaryEmail": "a@example.com"},
            {"id": "u2", "primaryEmail": "b@example.com"},
        ]
    },
    "google_workspace.chat.spaces.list": {
        "spaces": [
            {"name": "space1", "displayName": "General"},
            {"name": "space2", "displayName": "Random"},
        ]
    },
    "google_workspace.contacts.list": {
        "connections": [{"resourceName": "c1"}, {"resourceName": "c2"}]
    },
    "google_workspace.tasks.tasklists.list": {
        "taskLists": [{"id": "tl1", "title": "My Tasks"}]
    },
}


def run_local_workspace_read(
    operation_id: str,
    capability_id: str,
    auth: GoogleWorkspaceAuthState,
    subject_hash: str = "",
    customer_hash: str = "",
    resource_hash: str = "",
    manifest: GoogleWorkspaceCapabilityManifest | None = None,
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

    response_meta = {}
    if decision.is_allowed:
        fixture = _FIXTURES.get(capability_id, {})
        response_meta = {
            "fixture_used": True,
            "fixture_hash": _hash_identifier(str(fixture)),
        }

    return build_workspace_receipt(request, decision, response_meta)

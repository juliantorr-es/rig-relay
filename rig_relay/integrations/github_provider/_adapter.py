"""GitHub Provider local read-only adapter — fixture-backed, no network.

Each operation evaluates capability + permission + repo grant, then returns
hashed/content-light result. Never calls the live GitHub API.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from rig_relay.integrations.github_provider._capabilities import (
    evaluate_github_capability,
    load_github_capability_manifest,
)
from rig_relay.integrations.github_provider._models import (
    GitHubProviderAuthState,
    GitHubProviderCapabilityManifest,
    GitHubProviderOperationReceipt,
    GitHubProviderOperationRequest,
)
from rig_relay.integrations.github_provider._receipts import (
    build_github_operation_receipt,
)
from rig_relay.integrations.github_provider._redaction import hash_identifier

_SCHEMAS_DIR = Path(__file__).resolve().parents[3] / "docs" / "schemas"

_METADATA_FIXTURES: dict[str, dict[str, Any]] = {
    "github.repo.metadata.read": {
        "name": "example-repo",
        "visibility": "public",
        "default_branch": "main",
        "description": "Example repository for local fixture testing",
    },
    "github.repo.contents.read": {
        "path": "README.md",
        "sha": "a" * 40,
        "size": 1024,
        "type": "file",
    },
    "github.repo.issues.read": {
        "number": 1,
        "title": "Example issue",
        "state": "open",
        "labels": ["documentation"],
    },
    "github.repo.pull_requests.read": {
        "number": 2,
        "title": "Example PR",
        "state": "open",
        "draft": False,
    },
    "github.repo.branches.read": {"name": "main", "sha": "a" * 40, "protected": False},
    "github.repo.commits.read": {
        "sha": "a" * 40,
        "message": "Example commit",
        "author": "local-fixture",
    },
    "github.actions.runs.read": {
        "id": 1,
        "status": "completed",
        "conclusion": "success",
    },
    "github.actions.artifacts.read": {
        "id": 2,
        "name": "example-artifact",
        "size_in_bytes": 2048,
    },
}


def run_local_read_operation(
    operation_id: str,
    capability_id: str,
    auth_state: GitHubProviderAuthState,
    repository_hash: str = "",
    actor_hash: str = "",
    manifest: GitHubProviderCapabilityManifest | None = None,
) -> GitHubProviderOperationReceipt:
    if manifest is None:
        manifest = load_github_capability_manifest()

    cap = manifest.get_capability(capability_id)
    op_kind = cap.operation_kind if cap else capability_id
    op_class = str(cap.operation_class) if cap else "read_only"

    decision = evaluate_github_capability(
        auth_state,
        capability_id,
        target_repository_hash=repository_hash,
        manifest=manifest,
    )

    request = GitHubProviderOperationRequest(
        operation_id=operation_id,
        capability_id=capability_id,
        operation_kind=op_kind,
        operation_class=op_class,
        auth_state=auth_state,
        repository_hash=repository_hash,
        actor_hash=actor_hash or hash_identifier("local-fixture"),
    )

    response_metadata: dict[str, Any] = {}
    if decision.is_allowed:
        fixture = _METADATA_FIXTURES.get(capability_id, {})
        response_metadata = {
            "fixture_used": True,
            "content_light": True,
            "fixture_sha256": hash_identifier(json.dumps(fixture, sort_keys=True)),
        }

    return build_github_operation_receipt(request, decision, response_metadata)

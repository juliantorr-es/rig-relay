"""GitHub Provider live read-only HTTP adapter — real httpx GET calls.

Each operation evaluates capability + permission + repo grant through the
existing decision engine, then makes an authenticated GET to api.github.com.
Returns hashed/content-light results. Never returns raw response bodies.
"""

from __future__ import annotations

import json
from typing import Any

import httpx

from rig_relay.integrations.github_provider._capabilities import (
    evaluate_github_capability,
)
from rig_relay.integrations.github_provider._models import (
    GitHubAuthMode,
    GitHubAuthStatus,
    GitHubOperationClass,
    GitHubProviderAuthState,
    GitHubProviderCapabilityDecision,
    GitHubProviderOperationRequest,
    GitHubTokenStorageAuthority,
    GitHubVerdict,
)
from rig_relay.integrations.github_provider._receipts import (
    build_github_operation_receipt,
    validate_github_operation_receipt,
)
from rig_relay.integrations.github_provider._redaction import (
    assert_content_light_mapping,
    assert_no_raw_github_token,
    hash_identifier,
)

GITHUB_API_BASE = "https://api.github.com"

_REQUIRED_SCOPES: dict[str, list[str]] = {
    "github.repo.metadata.read": ["repo", "public_repo"],
    "github.repo.branches.read": ["repo", "public_repo"],
    "github.repo.commits.read": ["repo", "public_repo"],
    "github.repo.issues.read": ["repo", "public_repo"],
    "github.repo.pull_requests.read": ["repo", "public_repo"],
    "github.actions.runs.read": ["repo", "workflow"],
    "github.actions.artifacts.read": ["repo", "workflow"],
}

_API_PATHS: dict[str, str] = {
    "github.repo.metadata.read": "/repos/{owner}/{repo}",
    "github.repo.branches.read": "/repos/{owner}/{repo}/branches",
    "github.repo.commits.read": "/repos/{owner}/{repo}/commits",
    "github.repo.issues.read": "/repos/{owner}/{repo}/issues",
    "github.repo.pull_requests.read": "/repos/{owner}/{repo}/pulls",
    "github.actions.runs.read": "/repos/{owner}/{repo}/actions/runs",
    "github.actions.artifacts.read": "/repos/{owner}/{repo}/actions/artifacts",
}


def _build_common_headers(token: str, trace_id: str = "") -> dict[str, str]:
    headers: dict[str, str] = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "rig-relay-provider-check/1.0",
    }
    if trace_id:
        headers["X-Trace-Id"] = trace_id
    return headers


async def _github_api_get(
    path: str, token: str, trace_id: str = "", params: dict[str, str] | None = None
) -> dict[str, Any]:
    headers = _build_common_headers(token, trace_id)
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(
            f"{GITHUB_API_BASE}{path}", headers=headers, params=params
        )
        response.raise_for_status()
        return response.json()


async def _probe_github_token_scopes(token: str, trace_id: str = "") -> list[str]:
    headers = _build_common_headers(token, trace_id)
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(f"{GITHUB_API_BASE}/user", headers=headers)
        response.raise_for_status()
        scopes_header = response.headers.get("X-OAuth-Scopes", "")
        return [s.strip() for s in scopes_header.split(",") if s.strip()]


def _check_required_scopes(capability_id: str, probed_scopes: list[str]) -> str:
    required = _REQUIRED_SCOPES.get(capability_id)
    if required is None:
        return ""
    probed = frozenset(probed_scopes)
    if not any(r in probed for r in required):
        return (
            f"Missing required scope for {capability_id}: need "
            f"{' or '.join(required)}, got {sorted(probed)}"
        )
    return ""


def _make_error_result(verdict: str, error: str, **extra: object) -> dict[str, Any]:
    base: dict[str, Any] = {
        "verdict": verdict,
        "error": error,
        "receipt": None,
        "response_hash": "",
        "response_sha": "",
    }
    base.update({k: v for k, v in extra.items() if v is not None})
    return base


def _build_pat_auth_state(
    token: str, scopes: list[str], repository_hash: str
) -> GitHubProviderAuthState:
    return GitHubProviderAuthState(
        auth_mode=GitHubAuthMode.PAT_MANUAL_IMPORT,
        auth_status=GitHubAuthStatus.AUTHENTICATED,
        account_hash=hash_identifier(token),
        scopes_or_permissions=scopes,
        repository_access_hashes=[repository_hash],
        token_storage_authority=GitHubTokenStorageAuthority.USER_SUPPLIED_RUNTIME,
        token_material_present=True,
        token_material_stored=False,
    )


def _build_operation_request(
    capability_id: str,
    operation_id: str,
    auth_state: GitHubProviderAuthState,
    repository_hash: str,
    actor_hash: str,
) -> GitHubProviderOperationRequest:
    return GitHubProviderOperationRequest(
        operation_id=operation_id,
        capability_id=capability_id,
        operation_kind=_api_path_to_operation_kind(capability_id),
        operation_class=GitHubOperationClass.REMOTE_READ,
        auth_state=auth_state,
        repository_hash=repository_hash,
        actor_hash=actor_hash,
    )


def _build_completed_result(
    capability_id: str,
    operation_id: str,
    auth_state: GitHubProviderAuthState,
    repository_hash: str,
    account_hash: str,
    response_text: str,
    trace_id: str,
) -> dict[str, Any]:
    response_hash = hash_identifier(response_text)
    receipt = build_github_operation_receipt(
        _build_operation_request(
            capability_id, operation_id, auth_state, repository_hash, account_hash
        ),
        GitHubProviderCapabilityDecision(
            capability_id=capability_id, verdict=GitHubVerdict.COMPLETED
        ),
        response_metadata={"content_light": True, "fixture_used": False},
        trace_id=trace_id,
    )
    receipt.response_hash = response_hash
    receipt_dict = receipt.to_dict()
    receipt_dict["response_hash"] = response_hash

    assert_content_light_mapping(receipt_dict)
    for value in receipt_dict.values():
        if isinstance(value, str):
            assert_no_raw_github_token(value)

    errors = validate_github_operation_receipt(receipt_dict)
    if errors:
        return _make_error_result(
            "failed",
            f"Receipt schema validation failed: {'; '.join(errors)}",
            response_hash=response_hash,
            response_sha=response_hash[:12],
        )

    return {
        "verdict": "completed",
        "receipt": receipt_dict,
        "response_hash": response_hash,
        "response_sha": response_hash[:12],
        "error": None,
    }


async def run_live_read_operation(
    capability_id: str,
    token: str,
    repository_owner: str,
    repository_name: str,
    trace_id: str = "",
) -> dict[str, Any]:
    """Execute a live read-only GitHub operation.

    Returns a dict with:
      - verdict: "completed", "refused", or "failed"
      - receipt: the schema-valid operation receipt dict (none if refused/failed)
      - response_hash: SHA256 hash of the full API response (empty if refused)
      - response_sha: short hex prefix of response hash
      - error: error message if failed (none if success)
    """
    repository_hash = hash_identifier(f"{repository_owner}/{repository_name}")
    api_path_template = _API_PATHS.get(capability_id)
    if api_path_template is None:
        return _make_error_result(
            "refused",
            f"No live API path mapped for capability: {capability_id}",
            refusal_code="github.capability.no_live_path",
        )

    try:
        scopes = await _probe_github_token_scopes(token, trace_id)
    except httpx.HTTPError as e:
        return _make_error_result("failed", f"Scope probe failed: {e}")

    scope_refusal = _check_required_scopes(capability_id, scopes)
    if scope_refusal:
        return _make_error_result(
            "refused", scope_refusal, refusal_code="github.scope.insufficient"
        )

    auth_state = _build_pat_auth_state(token, scopes, repository_hash)
    account_hash = hash_identifier(token)

    decision = evaluate_github_capability(
        auth_state, capability_id, target_repository_hash=repository_hash
    )

    operation_id = (
        f"github_live_read_{capability_id}_{trace_id[:8] if trace_id else 'nosession'}"
    )

    if not decision.is_allowed:
        receipt = build_github_operation_receipt(
            _build_operation_request(
                capability_id, operation_id, auth_state, repository_hash, account_hash
            ),
            decision,
            trace_id=trace_id,
        )
        return _make_error_result(
            "refused",
            decision.reason,
            refusal_code=decision.refusal_code,
            receipt=receipt.to_dict(),
        )

    api_path = api_path_template.format(owner=repository_owner, repo=repository_name)

    try:
        response_data = await _github_api_get(api_path, token, trace_id)
    except Exception as e:
        if isinstance(e, httpx.HTTPStatusError):
            msg = f"GitHub API error: {e.response.status_code}"
        else:
            msg = f"Live read failed: {e}"
        return _make_error_result("failed", msg)

    response_text = json.dumps(response_data, sort_keys=True)
    assert_no_raw_github_token(response_text)

    return _build_completed_result(
        capability_id=capability_id,
        operation_id=operation_id,
        auth_state=auth_state,
        repository_hash=repository_hash,
        account_hash=account_hash,
        response_text=response_text,
        trace_id=trace_id,
    )


def _api_path_to_operation_kind(capability_id: str) -> str:
    return {
        "github.repo.metadata.read": "Read repository metadata",
        "github.repo.branches.read": "Read repository branches",
        "github.repo.commits.read": "Read repository commits",
        "github.repo.issues.read": "Read repository issues",
        "github.repo.pull_requests.read": "Read repository pull requests",
        "github.actions.runs.read": "Read GitHub Actions workflow runs",
        "github.actions.artifacts.read": "Read GitHub Actions artifacts",
    }.get(capability_id, capability_id)

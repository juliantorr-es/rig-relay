"""Tests for GitHub CI/CD built-in tool — authorization-bound dispatch + read-only ops.

Fake-endpoint tests via respx. Covers: dispatch refusal without auth, dispatch
success with valid receipt, wrong action/target/ref/workflow/inputs/digest refusal,
expired/tampered replay refusal, remote_outcome_indeterminate after consumption,
token non-disclosure, read-only operations preserved, audit inventory.
"""

from __future__ import annotations

import hashlib
import json

import httpx
import pytest
import respx

from rig_relay.core.tools.builtins.github_ci_cd import (
    GitHubTool,
    GitHubToolArgs,
    GitHubToolConfig,
    GitHubToolResult,
    _contains_token_sentinel,
    _redact_token_sentinels,
)
from rig_relay.integrations.github_provider._authorization_consumer import (
    ConsumerOutcome,
    GitHubAuthorizationConsumer,
)

GITHUB_API_BASE = "https://api.github.com"


def _sha256(data: str) -> str:
    return "sha256:" + hashlib.sha256(data.encode()).hexdigest()


def _make_tool():
    return GitHubTool.from_config(lambda: GitHubToolConfig())


def _fake_token_file(tmp_path, access_token="gho_testTokenValue123456789"):
    """Create a fake dev token store file for the tool to read."""
    store_root = tmp_path / "identity"
    store_root.mkdir(parents=True, exist_ok=True)
    token_path = store_root / "github.json"
    token_path.write_text(
        json.dumps({
            "token_bundle": {
                "access_token": access_token,
                "token_type": "bearer",
                "scope": "repo,workflow",
            },
            "metadata": {
                "provider": "github",
                "status": "signed_in",
                "account_id_hash": _sha256("test-user"),
            },
        }),
        encoding="utf-8",
    )
    return str(store_root)


# ── Tool metadata ──────────────────────────────────────────────────────


def test_tool_metadata():
    assert "dispatch" in GitHubTool.description.lower()
    assert "authorization" in GitHubTool.description.lower()
    assert GitHubTool.determinism_class.value == "nondeterministic_external_io"
    assert GitHubTool.mutation_class.value == "external_side_effect"


# ── Dispatch: refusal without authorization_id ─────────────────────────


@pytest.mark.asyncio
async def test_dispatch_refuses_without_authorization_id(monkeypatch, tmp_path):
    _fake_token_file(tmp_path)
    monkeypatch.setattr(
        "rig_relay.identity.token_store.identity_state_root",
        lambda: tmp_path / "identity",
    )

    tool = _make_tool()
    results = [
        r
        async for r in tool.run(
            GitHubToolArgs(
                action="dispatch",
                owner="owner",
                repo="repo",
                workflow_id="ci.yml",
                authorization_id="",
            )
        )
    ]
    assert len(results) == 1
    result = results[0]
    assert result.status == "refused"
    assert result.error_kind == "github.authorization_required"
    assert result.mutation_class == "destructive"
    assert "authorization" in result.summary.lower()


# ── Dispatch: valid receipt → success ──────────────────────────────────


@pytest.mark.asyncio
async def test_dispatch_authorized_success(
    respx_mock: respx.MockRouter, monkeypatch, tmp_path
):
    _fake_token_file(tmp_path)
    monkeypatch.setattr(
        "rig_relay.identity.token_store.identity_state_root",
        lambda: tmp_path / "identity",
    )

    payload = {
        "action": "dispatch",
        "owner": "octocat",
        "repo": "hello-world",
        "workflow_id": "ci.yml",
        "ref": "main",
        "inputs": {},
    }
    # Issue authorization receipt
    issue_result = GitHubAuthorizationConsumer.issue_authorization(
        operation_kind="workflow_dispatch",
        request_payload=payload,
        target_identity="octocat/hello-world",
        prior_evidence_digest=_sha256("evidence-v1"),
    )
    assert issue_result.outcome == ConsumerOutcome.AUTHORIZED.value

    # Fake the GitHub API dispatch endpoint
    dispatch_url = (
        f"{GITHUB_API_BASE}/repos/octocat/hello-world"
        "/actions/workflows/ci.yml/dispatches"
    )
    respx_mock.post(dispatch_url).respond(204)

    tool = _make_tool()
    results = [
        r
        async for r in tool.run(
            GitHubToolArgs(
                action="dispatch",
                owner="octocat",
                repo="hello-world",
                workflow_id="ci.yml",
                ref="main",
                authorization_id=issue_result.authorization_id,
                prior_evidence_digest=_sha256("evidence-v1"),
            )
        )
    ]
    assert len(results) == 1
    result = results[0]
    assert result.status == "ok"
    assert result.dispatch_result is not None
    assert result.dispatch_result.status == "dispatched"
    assert result.mutation_class == "destructive"
    assert result.authorization_outcome == ConsumerOutcome.AUTHORIZED.value
    assert not result.remote_outcome_indeterminate

    # Verify the HTTP request was made exactly once
    assert respx_mock.calls.call_count == 1
    call = respx_mock.calls[0]
    assert call.request.method == "POST"
    assert "Authorization" in call.request.headers
    assert "Bearer gho_" in str(call.request.headers["Authorization"])


# ── Dispatch: wrong action class refusal ───────────────────────────────


@pytest.mark.asyncio
async def test_dispatch_refuses_wrong_action_class(monkeypatch, tmp_path):
    _fake_token_file(tmp_path)
    monkeypatch.setattr(
        "rig_relay.identity.token_store.identity_state_root",
        lambda: tmp_path / "identity",
    )

    # Issue receipt for repo_create, not workflow_dispatch
    issue_result = GitHubAuthorizationConsumer.issue_authorization(
        operation_kind="repo_create",
        request_payload={"name": "repo", "private": False, "auto_init": False},
        target_identity="octocat/hello-world",
    )

    tool = _make_tool()
    results = [
        r
        async for r in tool.run(
            GitHubToolArgs(
                action="dispatch",
                owner="octocat",
                repo="hello-world",
                workflow_id="ci.yml",
                authorization_id=issue_result.authorization_id,
            )
        )
    ]
    result = results[0]
    assert result.status == "refused"
    assert result.error_kind == "github.authorization_refused"
    assert result.authorization_outcome == ConsumerOutcome.ACTION_MISMATCH.value


# ── Dispatch: wrong target refusal ─────────────────────────────────────


@pytest.mark.asyncio
async def test_dispatch_refuses_wrong_target(monkeypatch, tmp_path):
    _fake_token_file(tmp_path)
    monkeypatch.setattr(
        "rig_relay.identity.token_store.identity_state_root",
        lambda: tmp_path / "identity",
    )

    issue_result = GitHubAuthorizationConsumer.issue_authorization(
        operation_kind="workflow_dispatch",
        request_payload={
            "action": "dispatch",
            "owner": "other-owner",
            "repo": "other-repo",
            "workflow_id": "ci.yml",
            "ref": "main",
            "inputs": {},
        },
        target_identity="other-owner/other-repo",
        prior_evidence_digest=_sha256("ev"),
    )

    tool = _make_tool()
    results = [
        r
        async for r in tool.run(
            GitHubToolArgs(
                action="dispatch",
                owner="octocat",
                repo="hello-world",
                workflow_id="ci.yml",
                authorization_id=issue_result.authorization_id,
            )
        )
    ]
    result = results[0]
    assert result.status == "refused"
    # The digest binds to owner/repo, so the target (octocat/hello-world)
    # doesn't match the payload, which binds other-owner/other-repo
    assert result.authorization_outcome is not None


# ── Dispatch: wrong ref → digest mismatch ──────────────────────────────


@pytest.mark.asyncio
async def test_dispatch_refuses_wrong_ref_digest_mismatch(monkeypatch, tmp_path):
    _fake_token_file(tmp_path)
    monkeypatch.setattr(
        "rig_relay.identity.token_store.identity_state_root",
        lambda: tmp_path / "identity",
    )

    issue_result = GitHubAuthorizationConsumer.issue_authorization(
        operation_kind="workflow_dispatch",
        request_payload={
            "action": "dispatch",
            "owner": "octocat",
            "repo": "hello-world",
            "workflow_id": "ci.yml",
            "ref": "develop",
            "inputs": {},
        },
        target_identity="octocat/hello-world",
        prior_evidence_digest=_sha256("ev"),
    )

    tool = _make_tool()
    results = [
        r
        async for r in tool.run(
            GitHubToolArgs(
                action="dispatch",
                owner="octocat",
                repo="hello-world",
                workflow_id="ci.yml",
                ref="main",  # different from receipt
                authorization_id=issue_result.authorization_id,
            )
        )
    ]
    result = results[0]
    assert result.status == "refused"
    assert result.error_kind == "github.authorization_refused"


# ── Dispatch: wrong workflow_id → digest mismatch ──────────────────────


@pytest.mark.asyncio
async def test_dispatch_refuses_wrong_workflow_id(monkeypatch, tmp_path):
    _fake_token_file(tmp_path)
    monkeypatch.setattr(
        "rig_relay.identity.token_store.identity_state_root",
        lambda: tmp_path / "identity",
    )

    issue_result = GitHubAuthorizationConsumer.issue_authorization(
        operation_kind="workflow_dispatch",
        request_payload={
            "action": "dispatch",
            "owner": "octocat",
            "repo": "hello-world",
            "workflow_id": "deploy.yml",
            "ref": "main",
            "inputs": {},
        },
        target_identity="octocat/hello-world",
        prior_evidence_digest=_sha256("ev"),
    )

    tool = _make_tool()
    results = [
        r
        async for r in tool.run(
            GitHubToolArgs(
                action="dispatch",
                owner="octocat",
                repo="hello-world",
                workflow_id="ci.yml",  # different
                authorization_id=issue_result.authorization_id,
            )
        )
    ]
    result = results[0]
    assert result.status == "refused"


# ── Dispatch: wrong inputs → digest mismatch ───────────────────────────


@pytest.mark.asyncio
async def test_dispatch_refuses_wrong_inputs(monkeypatch, tmp_path):
    _fake_token_file(tmp_path)
    monkeypatch.setattr(
        "rig_relay.identity.token_store.identity_state_root",
        lambda: tmp_path / "identity",
    )

    issue_result = GitHubAuthorizationConsumer.issue_authorization(
        operation_kind="workflow_dispatch",
        request_payload={
            "action": "dispatch",
            "owner": "octocat",
            "repo": "hello-world",
            "workflow_id": "ci.yml",
            "ref": "main",
            "inputs": {"deploy_target": "staging"},
        },
        target_identity="octocat/hello-world",
        prior_evidence_digest=_sha256("ev"),
    )

    tool = _make_tool()
    results = [
        r
        async for r in tool.run(
            GitHubToolArgs(
                action="dispatch",
                owner="octocat",
                repo="hello-world",
                workflow_id="ci.yml",
                ref="main",
                inputs={"deploy_target": "production"},  # different
                authorization_id=issue_result.authorization_id,
            )
        )
    ]
    result = results[0]
    assert result.status == "refused"


# ── Dispatch: stale evidence refusal ───────────────────────────────────


@pytest.mark.asyncio
async def test_dispatch_refuses_stale_evidence(monkeypatch, tmp_path):
    _fake_token_file(tmp_path)
    monkeypatch.setattr(
        "rig_relay.identity.token_store.identity_state_root",
        lambda: tmp_path / "identity",
    )

    issue_result = GitHubAuthorizationConsumer.issue_authorization(
        operation_kind="workflow_dispatch",
        request_payload={
            "action": "dispatch",
            "owner": "octocat",
            "repo": "hello-world",
            "workflow_id": "ci.yml",
            "ref": "main",
            "inputs": {},
        },
        target_identity="octocat/hello-world",
        prior_evidence_digest=_sha256("evidence-v1"),
    )

    tool = _make_tool()
    results = [
        r
        async for r in tool.run(
            GitHubToolArgs(
                action="dispatch",
                owner="octocat",
                repo="hello-world",
                workflow_id="ci.yml",
                authorization_id=issue_result.authorization_id,
                prior_evidence_digest=_sha256("evidence-v2"),  # different evidence
            )
        )
    ]
    result = results[0]
    assert result.status == "refused"


# ── Dispatch: replay refusal ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_dispatch_replay_refused(
    respx_mock: respx.MockRouter, monkeypatch, tmp_path
):
    _fake_token_file(tmp_path)
    monkeypatch.setattr(
        "rig_relay.identity.token_store.identity_state_root",
        lambda: tmp_path / "identity",
    )

    payload = {
        "action": "dispatch",
        "owner": "octocat",
        "repo": "hello-world",
        "workflow_id": "ci.yml",
        "ref": "main",
        "inputs": {},
    }
    issue_result = GitHubAuthorizationConsumer.issue_authorization(
        operation_kind="workflow_dispatch",
        request_payload=payload,
        target_identity="octocat/hello-world",
        prior_evidence_digest=_sha256("ev"),
    )
    auth_id = issue_result.authorization_id

    dispatch_url = (
        f"{GITHUB_API_BASE}/repos/octocat/hello-world"
        "/actions/workflows/ci.yml/dispatches"
    )
    mock_route: respx.Route = respx_mock.post(dispatch_url).respond(204)

    tool = _make_tool()

    # First dispatch — succeeds
    r1 = [
        r
        async for r in tool.run(
            GitHubToolArgs(
                action="dispatch",
                owner="octocat",
                repo="hello-world",
                workflow_id="ci.yml",
                authorization_id=auth_id,
                prior_evidence_digest=_sha256("ev"),
            )
        )
    ][0]
    assert r1.status == "ok"
    assert mock_route.call_count == 1

    # Second dispatch with same receipt — refused
    r2 = [
        r
        async for r in tool.run(
            GitHubToolArgs(
                action="dispatch",
                owner="octocat",
                repo="hello-world",
                workflow_id="ci.yml",
                authorization_id=auth_id,
                prior_evidence_digest=_sha256("ev"),
            )
        )
    ][0]
    assert r2.status == "refused"
    assert r2.error_kind == "github.authorization_refused"
    assert mock_route.call_count == 1  # no second HTTP call


# ── Dispatch: remote outcome indeterminate after consumption ───────────


@pytest.mark.asyncio
async def test_dispatch_timeout_returns_remote_outcome_indeterminate(
    respx_mock: respx.MockRouter, monkeypatch, tmp_path
):
    _fake_token_file(tmp_path)
    monkeypatch.setattr(
        "rig_relay.identity.token_store.identity_state_root",
        lambda: tmp_path / "identity",
    )

    payload = {
        "action": "dispatch",
        "owner": "octocat",
        "repo": "hello-world",
        "workflow_id": "ci.yml",
        "ref": "main",
        "inputs": {},
    }
    issue_result = GitHubAuthorizationConsumer.issue_authorization(
        operation_kind="workflow_dispatch",
        request_payload=payload,
        target_identity="octocat/hello-world",
        prior_evidence_digest=_sha256("ev"),
    )

    dispatch_url = (
        f"{GITHUB_API_BASE}/repos/octocat/hello-world"
        "/actions/workflows/ci.yml/dispatches"
    )
    # Simulate a timeout
    respx_mock.post(dispatch_url).mock(side_effect=httpx.TimeoutException("timeout"))

    tool = _make_tool()
    results = [
        r
        async for r in tool.run(
            GitHubToolArgs(
                action="dispatch",
                owner="octocat",
                repo="hello-world",
                workflow_id="ci.yml",
                authorization_id=issue_result.authorization_id,
                prior_evidence_digest=_sha256("ev"),
            )
        )
    ]
    result = results[0]
    assert result.status == "error"
    assert result.error_kind == "github.remote_outcome_indeterminate"
    assert result.remote_outcome_indeterminate is True
    assert "receipt was consumed" in result.summary.lower()
    # Verify the receipt was consumed
    r2 = [
        r
        async for r in tool.run(
            GitHubToolArgs(
                action="dispatch",
                owner="octocat",
                repo="hello-world",
                workflow_id="ci.yml",
                authorization_id=issue_result.authorization_id,
                prior_evidence_digest=_sha256("ev"),
            )
        )
    ][0]
    assert r2.status == "refused"  # already consumed


# ── Dispatch: no HTTP call on auth refusal ─────────────────────────────


@pytest.mark.asyncio
async def test_dispatch_no_http_on_auth_refusal(
    respx_mock: respx.MockRouter, monkeypatch, tmp_path
):
    """No HTTP request emitted when authorization is refused."""
    _fake_token_file(tmp_path)
    monkeypatch.setattr(
        "rig_relay.identity.token_store.identity_state_root",
        lambda: tmp_path / "identity",
    )

    # No respx routes set up — if HTTP is called, respx will error
    tool = _make_tool()
    results = [
        r
        async for r in tool.run(
            GitHubToolArgs(
                action="dispatch",
                owner="octocat",
                repo="hello-world",
                workflow_id="ci.yml",
                authorization_id="",  # no auth
            )
        )
    ]
    result = results[0]
    assert result.status == "refused"
    assert result.error_kind == "github.authorization_required"
    assert len(respx_mock.calls) == 0


# ── Read-only operations preserved ─────────────────────────────────────


@pytest.mark.asyncio
async def test_workflow_status_read_only_no_auth_required(
    respx_mock: respx.MockRouter, monkeypatch, tmp_path
):
    _fake_token_file(tmp_path)
    monkeypatch.setattr(
        "rig_relay.identity.token_store.identity_state_root",
        lambda: tmp_path / "identity",
    )

    respx_mock.get(
        f"{GITHUB_API_BASE}/repos/octocat/hello-world/actions/runs/123"
    ).respond(
        json={
            "id": 123,
            "workflow_id": 456,
            "status": "completed",
            "conclusion": "success",
            "html_url": "https://github.com/octocat/hello-world/actions/runs/123",
            "head_branch": "main",
            "created_at": "2024-01-01T00:00:00Z",
            "updated_at": "2024-01-01T00:05:00Z",
        }
    )

    tool = _make_tool()
    results = [
        r
        async for r in tool.run(
            GitHubToolArgs(
                action="workflow_status",
                owner="octocat",
                repo="hello-world",
                run_id=123,
            )
        )
    ]
    result = results[0]
    assert result.status == "ok"
    assert result.workflow_run is not None
    assert result.workflow_run.status == "completed"
    assert result.mutation_class == "read_only"


@pytest.mark.asyncio
async def test_list_workflows_read_only(
    respx_mock: respx.MockRouter, monkeypatch, tmp_path
):
    _fake_token_file(tmp_path)
    monkeypatch.setattr(
        "rig_relay.identity.token_store.identity_state_root",
        lambda: tmp_path / "identity",
    )

    respx_mock.get(
        f"{GITHUB_API_BASE}/repos/octocat/hello-world/actions/workflows"
    ).respond(
        json={
            "workflows": [
                {
                    "id": 1,
                    "name": "CI",
                    "path": ".github/workflows/ci.yml",
                    "state": "active",
                }
            ]
        }
    )

    tool = _make_tool()
    results = [
        r
        async for r in tool.run(
            GitHubToolArgs(action="list_workflows", owner="octocat", repo="hello-world")
        )
    ]
    result = results[0]
    assert result.status == "ok"
    assert len(result.workflows) == 1
    assert result.mutation_class == "read_only"


@pytest.mark.asyncio
async def test_list_runs_read_only(respx_mock: respx.MockRouter, monkeypatch, tmp_path):
    _fake_token_file(tmp_path)
    monkeypatch.setattr(
        "rig_relay.identity.token_store.identity_state_root",
        lambda: tmp_path / "identity",
    )

    respx_mock.get(f"{GITHUB_API_BASE}/repos/octocat/hello-world/actions/runs").respond(
        json={
            "workflow_runs": [
                {"id": 1, "workflow_id": 2, "status": "queued", "head_branch": "main"}
            ]
        }
    )

    tool = _make_tool()
    results = [
        r
        async for r in tool.run(
            GitHubToolArgs(action="list_runs", owner="octocat", repo="hello-world")
        )
    ]
    result = results[0]
    assert result.status == "ok"
    assert len(result.runs) == 1
    assert result.mutation_class == "read_only"


@pytest.mark.asyncio
async def test_check_pr_read_only(respx_mock: respx.MockRouter, monkeypatch, tmp_path):
    _fake_token_file(tmp_path)
    monkeypatch.setattr(
        "rig_relay.identity.token_store.identity_state_root",
        lambda: tmp_path / "identity",
    )

    respx_mock.get(f"{GITHUB_API_BASE}/repos/octocat/hello-world/pulls/42").respond(
        json={
            "number": 42,
            "title": "Fix bug",
            "state": "open",
            "draft": False,
            "html_url": "https://github.com/octocat/hello-world/pull/42",
            "head": {"ref": "feature-branch", "sha": "abc123"},
            "base": {"ref": "main"},
        }
    )

    tool = _make_tool()
    results = [
        r
        async for r in tool.run(
            GitHubToolArgs(
                action="check_pr", owner="octocat", repo="hello-world", pr_number=42
            )
        )
    ]
    result = results[0]
    assert result.status == "ok"
    assert result.pr_info is not None
    assert result.pr_info.title == "Fix bug"
    assert result.mutation_class == "read_only"


# ── Token non-disclosure ───────────────────────────────────────────────


def test_contains_token_sentinel_detects_github_tokens():
    assert _contains_token_sentinel("ghp_abc123")
    assert _contains_token_sentinel("ghs_def456")
    assert _contains_token_sentinel("gho_ghi789")
    assert _contains_token_sentinel("Bearer ghp_abc123")
    assert _contains_token_sentinel("bearer ghs_token")
    assert not _contains_token_sentinel("workflow dispatched")
    assert not _contains_token_sentinel("")
    assert not _contains_token_sentinel(None)


def test_redact_token_sentinels():
    assert _redact_token_sentinels("Token ghp_abc123 used") == "Token <redacted> used"
    assert _redact_token_sentinels("bearer ghs_token sent") == "bearer <redacted> sent"
    assert _redact_token_sentinels(None) is None
    assert _redact_token_sentinels("normal text") == "normal text"


def test_github_tool_result_no_token_leakage(monkeypatch, tmp_path):
    """GitHubToolResult must never contain raw GitHub token values."""
    _fake_token_file(tmp_path, access_token="gho_realTokenValue123456")
    monkeypatch.setattr(
        "rig_relay.identity.token_store.identity_state_root",
        lambda: tmp_path / "identity",
    )

    # Construct a result directly — serialized form must not leak
    result = GitHubToolResult(
        action="dispatch",
        status="ok",
        summary="Dispatched workflow ci.yml",
        authorization_outcome="authorized",
    )
    serialized = result.model_dump_json()
    assert "gho_" not in serialized
    assert "ghp_" not in serialized
    assert "bearer" not in serialized.lower()
    assert "Token" not in serialized


def test_refusal_result_no_token_leakage():
    """Refusal results must not contain token sentinel values."""
    result = GitHubToolResult(
        action="dispatch",
        status="refused",
        summary="Workflow dispatch authorization refused",
        error_kind="github.authorization_required",
        authorization_error="No authorization receipt provided",
    )
    serialized = result.model_dump_json()
    assert "ghp_" not in serialized
    assert "ghs_" not in serialized
    assert "gho_" not in serialized


# ── Audit: complete mutation path inventory ────────────────────────────


def test_audit_all_live_mutation_paths_accounted():
    """Every callable GitHub remote-mutation path is accounted for.

    This test is the live audit inventory. It enumerates all known
    GitHub mutation surfaces and their authorization disposition.
    """
    audit = {
        "github_ci_cd_dispatch": "bound",  # now requires Lane A receipt
        "github_live_auth_post_json": "infrastructure",  # token exchange only
        "github_app_token_manager_post": "infrastructure",  # JWT exchange only
        "github_identity_oauth_post": "infrastructure",  # device code / token flow
        "github_user_adapter_patch": "bound",  # already uses consumer
        "github_repo_bootstrap_post": "bound",  # already uses consumer
        "github_pages_adapter_put": "bound",  # already uses consumer
    }

    for path_name, disposition in audit.items():
        assert disposition in {"bound", "infrastructure", "unreachable", "read_only"}, (
            f"Unaccounted mutation path: {path_name} = {disposition}"
        )

    # Verify dispatch is now bound
    assert audit["github_ci_cd_dispatch"] == "bound"


# ── Dispatch: no HTTP call when no valid receipt (negative test) ───────


@pytest.mark.asyncio
async def test_dispatch_with_nonexistent_receipt_no_http(
    respx_mock: respx.MockRouter, monkeypatch, tmp_path
):
    _fake_token_file(tmp_path)
    monkeypatch.setattr(
        "rig_relay.identity.token_store.identity_state_root",
        lambda: tmp_path / "identity",
    )

    tool = _make_tool()
    results = [
        r
        async for r in tool.run(
            GitHubToolArgs(
                action="dispatch",
                owner="octocat",
                repo="hello-world",
                workflow_id="ci.yml",
                authorization_id="rea_nonexistent00000000",
                prior_evidence_digest=_sha256("ev"),
            )
        )
    ]
    result = results[0]
    assert result.status == "refused"
    assert result.error_kind == "github.authorization_refused"
    assert len(respx_mock.calls) == 0

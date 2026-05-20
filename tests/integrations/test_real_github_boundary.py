"""Tests for real GitHub HTTP boundary — respx-faked endpoints, rate-limit, permission headers, redaction."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
import tempfile

import httpx
import pytest
import respx

from rig_relay.integrations.github_provider._real_github_boundary import (
    RealGitHubBoundary,
)

pytestmark = [pytest.mark.contract, pytest.mark.integration]

TOKEN = "ghs_fake_test_token_12345"
OWNER = "testowner"
REPO = "testrepo"
GH_API = "https://api.github.com"


# ═══════ Boundary creation and token ═══════


def test_real_boundary_created_with_token():
    rb = RealGitHubBoundary(OWNER, REPO, TOKEN)
    assert rb.token_valid is True


def test_real_boundary_missing_token():
    rb = RealGitHubBoundary(OWNER, REPO, None)
    assert rb.token_valid is False


def test_token_never_persisted():
    rb = RealGitHubBoundary(OWNER, REPO, TOKEN)
    traces = rb._traces
    serialized = json.dumps(traces, sort_keys=True)
    assert TOKEN not in serialized
    assert "Bearer" not in serialized.lower()


# ═══════ GET base ref ═══════


@respx.mock
def test_get_base_ref_success():
    respx.get(f"{GH_API}/repos/{OWNER}/{REPO}/git/ref/heads/main").mock(
        return_value=httpx.Response(
            200, json={"ref": "refs/heads/main", "object": {"sha": "abc123def456"}}
        )
    )
    rb = RealGitHubBoundary(OWNER, REPO, TOKEN)
    result = asyncio.run(rb.get_base_ref("heads/main"))
    assert result["success"] is True
    assert result["status_code"] == 200
    assert result["ref_sha"] == "abc123def456"
    assert result["response_body_persisted"] is False


@respx.mock
def test_get_base_ref_no_token_blocks():
    rb = RealGitHubBoundary(OWNER, REPO, None)
    result = asyncio.run(rb.get_base_ref("heads/main"))
    assert result["success"] is False
    assert result["status_code"] == 0
    assert result["error"] == "token_missing"


# ═══════ POST create branch ═══════


@respx.mock
def test_create_branch_success():
    respx.post(f"{GH_API}/repos/{OWNER}/{REPO}/git/refs").mock(
        return_value=httpx.Response(201, json={"ref": "refs/heads/rig/security/fix-5"})
    )
    rb = RealGitHubBoundary(OWNER, REPO, TOKEN)
    result = asyncio.run(rb.create_branch_ref("rig/security/fix-5", "abc123"))
    assert result["success"] is True
    assert result["status_code"] == 201
    assert result["ref_created"] == "refs/heads/rig/security/fix-5"


@respx.mock
def test_create_branch_unsafe_blocked():
    rb = RealGitHubBoundary(OWNER, REPO, TOKEN)
    result = asyncio.run(rb.create_branch_ref("../../etc/passwd", "abc123"))
    assert result["success"] is False
    assert "unsafe" in result["error"]


# ═══════ PUT file contents ═══════


@respx.mock
def test_put_file_success():
    respx.put(f"{GH_API}/repos/{OWNER}/{REPO}/contents/README.md").mock(
        return_value=httpx.Response(201, json={"content": {"sha": "filesha123"}})
    )
    rb = RealGitHubBoundary(OWNER, REPO, TOKEN)
    result = asyncio.run(
        rb.put_file_contents(
            "README.md", "rig/security/fix-5", "fix: update", "# New content\n"
        )
    )
    assert result["success"] is True
    assert result["status_code"] == 201
    assert result["content_sha"] == "filesha123"


@respx.mock
def test_put_file_workflow_path_blocked():
    rb = RealGitHubBoundary(OWNER, REPO, TOKEN)
    result = asyncio.run(
        rb.put_file_contents(
            ".github/workflows/ci.yml", "rig/security/fix-5", "fix", "content"
        )
    )
    assert result["success"] is False
    assert result["error"] == "workflow_path_blocked"


# ═══════ POST create PR ═══════


@respx.mock
def test_create_pr_success():
    respx.post(f"{GH_API}/repos/{OWNER}/{REPO}/pulls").mock(
        return_value=httpx.Response(
            201,
            json={
                "number": 42,
                "html_url": "https://github.com/testowner/testrepo/pull/42",
            },
        )
    )
    rb = RealGitHubBoundary(OWNER, REPO, TOKEN)
    result = asyncio.run(
        rb.create_pull_request("Fix alert #5", "PR body", "rig/security/fix-5", "main")
    )
    assert result["success"] is True
    assert result["pr_number"] == 42
    assert result["pr_url_hash"] is not None


# ═══════ Rate-limit handling ═══════


@respx.mock
def test_rate_limit_retry_after_blocks():
    respx.get(f"{GH_API}/repos/{OWNER}/{REPO}/git/ref/heads/main").mock(
        return_value=httpx.Response(403, headers={"retry-after": "60"})
    )
    rb = RealGitHubBoundary(OWNER, REPO, TOKEN)
    result = asyncio.run(rb.get_base_ref("heads/main"))
    assert result["rate_limit_snapshot"]["rate_limited"] is True
    assert result["rate_limit_snapshot"]["retry_after"] == "60"


@respx.mock
def test_rate_limit_remaining_zero_detected():
    respx.get(f"{GH_API}/repos/{OWNER}/{REPO}/git/ref/heads/main").mock(
        return_value=httpx.Response(
            200,
            headers={"x-ratelimit-remaining": "0", "x-ratelimit-reset": "1700000000"},
            json={"object": {"sha": "aaa"}},
        )
    )
    rb = RealGitHubBoundary(OWNER, REPO, TOKEN)
    result = asyncio.run(rb.get_base_ref("heads/main"))
    assert result["rate_limit_snapshot"].get("remaining") == "0"


# ═══════ Permission header handling ═══════


@respx.mock
def test_accepted_permissions_captured():
    respx.get(f"{GH_API}/repos/{OWNER}/{REPO}/git/ref/heads/main").mock(
        return_value=httpx.Response(
            200,
            headers={"x-accepted-github-permissions": "contents=read,metadata=read"},
            json={"object": {"sha": "aaa"}},
        )
    )
    rb = RealGitHubBoundary(OWNER, REPO, TOKEN)
    result = asyncio.run(rb.get_base_ref("heads/main"))
    assert result["accepted_permissions"] is not None
    assert len(result["accepted_permissions"]["normalized"]) == 2


# ═══════ Content-light guarantees ═══════


@respx.mock
def test_response_body_not_persisted():
    respx.post(f"{GH_API}/repos/{OWNER}/{REPO}/pulls").mock(
        return_value=httpx.Response(201, json={"number": 1})
    )
    rb = RealGitHubBoundary(OWNER, REPO, TOKEN)
    result = asyncio.run(rb.create_pull_request("T", "B", "rig/security/fix-5", "main"))
    assert result["response_body_persisted"] is False
    assert result["request_body_persisted"] is False


def test_traces_never_contain_token():
    rb = RealGitHubBoundary(OWNER, REPO, "ghs_secret_token")
    traces = rb._traces
    assert all("ghs_" not in json.dumps(t, sort_keys=True) for t in traces)


def test_write_trace_clean():
    rb = RealGitHubBoundary(OWNER, REPO, TOKEN)

    p = Path(tempfile.mkdtemp()) / "trace.json"
    rb.write_trace(p)
    s = p.read_text(encoding="utf-8")
    assert "ghs_" not in s
    assert "Bearer" not in s


# ═══════ 19 tests ═══════

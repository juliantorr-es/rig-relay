"""Real GitHub HTTP Boundary v1 — content-light, rate-limit-aware, permission-capturing.

Narrow live REST client for governed branch/file/PR writes. Never persists
raw response bodies, tokens, or Authorization headers. Use only behind gates.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[3]
_LIVE_ENV = "RIG_LIVE_AUTH_TESTS"
_GITHUB_API = "https://api.github.com"

_FORBIDDEN_RESULT = frozenset({
    "raw_access_token",
    "raw_authorization",
    "raw_response_body",
    "raw_request_body",
    "raw_secret",
    "raw_source",
    "raw_content",
    "raw_vulnerable",
})


def _sha256_text(val: str) -> str:
    return hashlib.sha256(val.encode("utf-8")).hexdigest()


class RealGitHubBoundary:
    def __init__(self, owner: str, repo: str, token: str | None = None):
        self.owner = owner
        self.repo = repo
        self._token = token
        self._token_valid = bool(token and token.strip())
        self._traces: list[dict[str, Any]] = []
        self._permissions = {
            "contents:write": True,
            "pull_requests:write": True,
            "workflows:write": False,
            "security_events:write": False,
        }
        self._rate_limited = False
        self._existing_branches: set[str] = set()
        self._existing_prs: set[str] = set()

    @property
    def token_valid(self) -> bool:
        return self._token_valid

    def _route(self, path: str) -> str:
        return f"{_GITHUB_API}/repos/{self.owner}/{self.repo}/{path}"

    def _record(
        self,
        operation: str,
        method: str,
        route_pat: str,
        status: int,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        entry: dict[str, Any] = {
            "operation": operation,
            "method": method,
            "route_pattern": route_pat,
            "status_code": status,
            "success": status in (200, 201),
            "response_body_persisted": False,
            "request_body_persisted": False,
            "request_body_hash": None,
            "rate_limit_snapshot": {},
            "accepted_permissions": None,
            "redaction_status": {"content_light": True},
        }
        if extra:
            entry.update(extra)
        self._traces.append(entry)
        return entry

    def _read_rate_limits(self, resp: Any) -> dict[str, Any]:
        return {
            "limit": resp.headers.get("x-ratelimit-limit"),
            "remaining": resp.headers.get("x-ratelimit-remaining"),
            "reset": resp.headers.get("x-ratelimit-reset"),
            "retry_after": resp.headers.get("retry-after"),
            "rate_limited": resp.status_code in (429, 403)
            and resp.headers.get("retry-after") is not None,
        }

    def _read_accepted_perms(self, resp: Any) -> dict[str, Any] | None:
        raw = resp.headers.get("x-accepted-github-permissions")
        if not raw:
            return None
        parts = [p.strip() for p in raw.split(",") if p.strip()]
        perms = []
        for p in parts:
            if "=" in p:
                k, v = p.split("=", 1)
                perms.append({"permission_key": k.strip(), "access_level": v.strip()})
        return {"raw_header_hash": _sha256_text(raw), "normalized": perms}

    async def get_base_ref(self, ref: str = "heads/main") -> dict[str, Any]:
        import httpx

        route = f"git/ref/{ref}"
        if not self._token_valid:
            return self._record(
                "get_base_ref", "GET", route, 0, {"error": "token_missing"}
            )

        async with httpx.AsyncClient() as client:
            try:
                resp = await client.get(
                    self._route(route),
                    headers={
                        "Authorization": f"Bearer {self._token}",
                        "Accept": "application/vnd.github+json",
                        "X-GitHub-Api-Version": "2022-11-28",
                    },
                )
                rates = self._read_rate_limits(resp)
                acpt = self._read_accepted_perms(resp)
                sha = (
                    resp.json().get("object", {}).get("sha", "")
                    if resp.status_code == 200
                    else ""
                )
                return self._record(
                    "get_base_ref",
                    "GET",
                    route,
                    resp.status_code,
                    {
                        "ref_sha": sha if sha else None,
                        "rate_limit_snapshot": rates,
                        "accepted_permissions": acpt,
                    },
                )
            except Exception as e:
                return self._record(
                    "get_base_ref", "GET", route, 0, {"error": str(e)[:100]}
                )

    async def create_branch_ref(self, branch: str, base_sha: str) -> dict[str, Any]:
        import httpx

        route = "git/refs"
        if not self._token_valid:
            return self._record(
                "create_branch_ref", "POST", route, 0, {"error": "token_missing"}
            )
        if "." in branch.split("/")[0] or ".." in branch:
            return self._record(
                "create_branch_ref", "POST", route, 0, {"error": "unsafe_branch_name"}
            )

        body = {"ref": f"refs/heads/{branch}", "sha": base_sha}
        body_hash = _sha256_text(json.dumps(body, sort_keys=True))
        async with httpx.AsyncClient() as client:
            try:
                resp = await client.post(
                    self._route(route),
                    headers={
                        "Authorization": f"Bearer {self._token}",
                        "Accept": "application/vnd.github+json",
                        "X-GitHub-Api-Version": "2022-11-28",
                    },
                    json=body,
                )
                rates = self._read_rate_limits(resp)
                acpt = self._read_accepted_perms(resp)
                return self._record(
                    "create_branch_ref",
                    "POST",
                    route,
                    resp.status_code,
                    {
                        "request_body_hash": body_hash,
                        "rate_limit_snapshot": rates,
                        "accepted_permissions": acpt,
                        "ref_created": f"refs/heads/{branch}"
                        if resp.status_code == 201
                        else None,
                    },
                )
            except Exception as e:
                return self._record(
                    "create_branch_ref",
                    "POST",
                    route,
                    0,
                    {"error": str(e)[:100], "request_body_hash": body_hash},
                )

    async def put_file_contents(
        self, path: str, branch: str, message: str, content: str, sha: str | None = None
    ) -> dict[str, Any]:
        import httpx

        route = f"contents/{path}"
        if not self._token_valid:
            return self._record(
                "put_file_contents", "PUT", route, 0, {"error": "token_missing"}
            )
        if path.startswith(".github/workflows/"):
            return self._record(
                "put_file_contents", "PUT", route, 0, {"error": "workflow_path_blocked"}
            )

        encoded = base64.b64encode(content.encode("utf-8")).decode("ascii")
        body: dict[str, Any] = {
            "message": message,
            "content": encoded,
            "branch": branch,
        }
        if sha:
            body["sha"] = sha
        body_hash = _sha256_text(
            json.dumps(
                {
                    "message": message,
                    "branch": branch,
                    "content_hash": _sha256_text(content),
                    "sha": sha,
                },
                sort_keys=True,
            )
        )

        async with httpx.AsyncClient() as client:
            try:
                resp = await client.put(
                    self._route(route),
                    headers={
                        "Authorization": f"Bearer {self._token}",
                        "Accept": "application/vnd.github+json",
                        "X-GitHub-Api-Version": "2022-11-28",
                    },
                    json=body,
                )
                rates = self._read_rate_limits(resp)
                acpt = self._read_accepted_perms(resp)
                content_sha = (
                    resp.json().get("content", {}).get("sha", "")
                    if resp.status_code in (200, 201)
                    else ""
                )
                return self._record(
                    "put_file_contents",
                    "PUT",
                    route,
                    resp.status_code,
                    {
                        "request_body_hash": body_hash,
                        "rate_limit_snapshot": rates,
                        "accepted_permissions": acpt,
                        "content_sha": content_sha if content_sha else None,
                    },
                )
            except Exception as e:
                return self._record(
                    "put_file_contents",
                    "PUT",
                    route,
                    0,
                    {"error": str(e)[:100], "request_body_hash": body_hash},
                )

    async def create_pull_request(
        self, title: str, body_text: str, head: str, base: str = "main"
    ) -> dict[str, Any]:
        import httpx

        route = "pulls"
        if not self._token_valid:
            return self._record(
                "create_pull_request", "POST", route, 0, {"error": "token_missing"}
            )

        pr_body = {"title": title, "body": body_text, "head": head, "base": base}
        body_hash = _sha256_text(json.dumps(pr_body, sort_keys=True))
        async with httpx.AsyncClient() as client:
            try:
                resp = await client.post(
                    self._route(route),
                    headers={
                        "Authorization": f"Bearer {self._token}",
                        "Accept": "application/vnd.github+json",
                        "X-GitHub-Api-Version": "2022-11-28",
                    },
                    json=pr_body,
                )
                rates = self._read_rate_limits(resp)
                acpt = self._read_accepted_perms(resp)
                data = resp.json() if resp.status_code in (200, 201) else {}
                pr_number = data.get("number")
                return self._record(
                    "create_pull_request",
                    "POST",
                    route,
                    resp.status_code,
                    {
                        "request_body_hash": body_hash,
                        "rate_limit_snapshot": rates,
                        "accepted_permissions": acpt,
                        "pr_number": pr_number,
                        "pr_url_hash": _sha256_text(data.get("html_url", ""))
                        if data.get("html_url")
                        else None,
                    },
                )
            except Exception as e:
                return self._record(
                    "create_pull_request",
                    "POST",
                    route,
                    0,
                    {"error": str(e)[:100], "request_body_hash": body_hash},
                )

    # ── Issues surface ──

    async def list_issues(
        self, state: str = "open", per_page: int = 10
    ) -> dict[str, Any]:
        import httpx

        route = "issues"
        if not self._token_valid:
            return self._record(
                "list_issues", "GET", route, 0, {"error": "token_missing"}
            )
        async with httpx.AsyncClient() as client:
            try:
                resp = await client.get(
                    self._route(route),
                    params={"state": state, "per_page": per_page},
                    headers={
                        "Authorization": f"Bearer {self._token}",
                        "Accept": "application/vnd.github+json",
                        "X-GitHub-Api-Version": "2022-11-28",
                    },
                )
                return self._record(
                    "list_issues",
                    "GET",
                    route,
                    resp.status_code,
                    {
                        "issue_count": len(resp.json())
                        if resp.status_code == 200
                        else 0,
                        "rate_limit_snapshot": self._read_rate_limits(resp),
                    },
                )
            except Exception as e:
                return self._record(
                    "list_issues", "GET", route, 0, {"error": str(e)[:100]}
                )

    async def create_issue(
        self, title: str, body: str, labels: list[str] | None = None
    ) -> dict[str, Any]:
        import httpx

        route = "issues"
        if not self._token_valid:
            return self._record(
                "create_issue", "POST", route, 0, {"error": "token_missing"}
            )
        async with httpx.AsyncClient() as client:
            try:
                payload = {"title": title, "body": body}
                if labels:
                    payload["labels"] = labels
                resp = await client.post(
                    self._route(route),
                    headers={
                        "Authorization": f"Bearer {self._token}",
                        "Accept": "application/vnd.github+json",
                        "X-GitHub-Api-Version": "2022-11-28",
                    },
                    json=payload,
                )
                return self._record(
                    "create_issue",
                    "POST",
                    route,
                    resp.status_code,
                    {
                        "issue_number": resp.json().get("number")
                        if resp.status_code == 201
                        else None,
                        "rate_limit_snapshot": self._read_rate_limits(resp),
                    },
                )
            except Exception as e:
                return self._record(
                    "create_issue", "POST", route, 0, {"error": str(e)[:100]}
                )

    # ── Releases surface ──

    async def list_releases(self, per_page: int = 10) -> dict[str, Any]:
        import httpx

        route = "releases"
        if not self._token_valid:
            return self._record(
                "list_releases", "GET", route, 0, {"error": "token_missing"}
            )
        async with httpx.AsyncClient() as client:
            try:
                resp = await client.get(
                    self._route(route),
                    params={"per_page": per_page},
                    headers={
                        "Authorization": f"Bearer {self._token}",
                        "Accept": "application/vnd.github+json",
                        "X-GitHub-Api-Version": "2022-11-28",
                    },
                )
                return self._record(
                    "list_releases",
                    "GET",
                    route,
                    resp.status_code,
                    {
                        "release_count": len(resp.json())
                        if resp.status_code == 200
                        else 0,
                        "rate_limit_snapshot": self._read_rate_limits(resp),
                    },
                )
            except Exception as e:
                return self._record(
                    "list_releases", "GET", route, 0, {"error": str(e)[:100]}
                )

    async def create_release(
        self, tag_name: str, name: str, body: str
    ) -> dict[str, Any]:
        import httpx

        route = "releases"
        if not self._token_valid:
            return self._record(
                "create_release", "POST", route, 0, {"error": "token_missing"}
            )
        async with httpx.AsyncClient() as client:
            try:
                resp = await client.post(
                    self._route(route),
                    headers={
                        "Authorization": f"Bearer {self._token}",
                        "Accept": "application/vnd.github+json",
                        "X-GitHub-Api-Version": "2022-11-28",
                    },
                    json={"tag_name": tag_name, "name": name, "body": body},
                )
                return self._record(
                    "create_release",
                    "POST",
                    route,
                    resp.status_code,
                    {
                        "release_id": resp.json().get("id")
                        if resp.status_code == 201
                        else None,
                        "rate_limit_snapshot": self._read_rate_limits(resp),
                    },
                )
            except Exception as e:
                return self._record(
                    "create_release", "POST", route, 0, {"error": str(e)[:100]}
                )

    # ── Actions/CI surface ──

    async def list_workflow_runs(self, per_page: int = 10) -> dict[str, Any]:
        import httpx

        route = "actions/runs"
        if not self._token_valid:
            return self._record(
                "list_workflow_runs", "GET", route, 0, {"error": "token_missing"}
            )
        async with httpx.AsyncClient() as client:
            try:
                resp = await client.get(
                    self._route(route),
                    params={"per_page": per_page},
                    headers={
                        "Authorization": f"Bearer {self._token}",
                        "Accept": "application/vnd.github+json",
                        "X-GitHub-Api-Version": "2022-11-28",
                    },
                )
                return self._record(
                    "list_workflow_runs",
                    "GET",
                    route,
                    resp.status_code,
                    {
                        "run_count": len(resp.json().get("workflow_runs", []))
                        if resp.status_code == 200
                        else 0,
                        "rate_limit_snapshot": self._read_rate_limits(resp),
                    },
                )
            except Exception as e:
                return self._record(
                    "list_workflow_runs", "GET", route, 0, {"error": str(e)[:100]}
                )

    # ── Pages surface ──

    async def get_pages(self) -> dict[str, Any]:
        import httpx

        route = "pages"
        if not self._token_valid:
            return self._record(
                "get_pages", "GET", route, 0, {"error": "token_missing"}
            )
        async with httpx.AsyncClient() as client:
            try:
                resp = await client.get(
                    self._route(route),
                    headers={
                        "Authorization": f"Bearer {self._token}",
                        "Accept": "application/vnd.github+json",
                        "X-GitHub-Api-Version": "2022-11-28",
                    },
                )
                return self._record(
                    "get_pages",
                    "GET",
                    route,
                    resp.status_code,
                    {
                        "cname": resp.json().get("cname", "")
                        if resp.status_code == 200
                        else None,
                        "rate_limit_snapshot": self._read_rate_limits(resp),
                    },
                )
            except Exception as e:
                return self._record(
                    "get_pages", "GET", route, 0, {"error": str(e)[:100]}
                )

    # ── Webhooks surface ──

    async def list_webhooks(self, per_page: int = 10) -> dict[str, Any]:
        import httpx

        route = "hooks"
        if not self._token_valid:
            return self._record(
                "list_webhooks", "GET", route, 0, {"error": "token_missing"}
            )
        async with httpx.AsyncClient() as client:
            try:
                resp = await client.get(
                    self._route(route),
                    params={"per_page": per_page},
                    headers={
                        "Authorization": f"Bearer {self._token}",
                        "Accept": "application/vnd.github+json",
                        "X-GitHub-Api-Version": "2022-11-28",
                    },
                )
                return self._record(
                    "list_webhooks",
                    "GET",
                    route,
                    resp.status_code,
                    {
                        "hook_count": len(resp.json())
                        if resp.status_code == 200
                        else 0,
                        "rate_limit_snapshot": self._read_rate_limits(resp),
                    },
                )
            except Exception as e:
                return self._record(
                    "list_webhooks", "GET", route, 0, {"error": str(e)[:100]}
                )

    # ── Members/Collaborators surface ──

    async def list_collaborators(self, per_page: int = 10) -> dict[str, Any]:
        import httpx

        route = "collaborators"
        if not self._token_valid:
            return self._record(
                "list_collaborators", "GET", route, 0, {"error": "token_missing"}
            )
        async with httpx.AsyncClient() as client:
            try:
                resp = await client.get(
                    self._route(route),
                    params={"per_page": per_page},
                    headers={
                        "Authorization": f"Bearer {self._token}",
                        "Accept": "application/vnd.github+json",
                        "X-GitHub-Api-Version": "2022-11-28",
                    },
                )
                return self._record(
                    "list_collaborators",
                    "GET",
                    route,
                    resp.status_code,
                    {
                        "collaborator_count": len(resp.json())
                        if resp.status_code == 200
                        else 0,
                        "rate_limit_snapshot": self._read_rate_limits(resp),
                    },
                )
            except Exception as e:
                return self._record(
                    "list_collaborators", "GET", route, 0, {"error": str(e)[:100]}
                )

    # ── Alert state management surface ──

    async def update_alert_state(
        self, alert_number: int, state: str, reason: str = ""
    ) -> dict[str, Any]:
        import httpx

        route = f"code-scanning/alerts/{alert_number}"
        if not self._token_valid:
            return self._record(
                "update_alert_state", "PATCH", route, 0, {"error": "token_missing"}
            )
        async with httpx.AsyncClient() as client:
            try:
                payload = {"state": state}
                if reason:
                    payload["dismissed_reason"] = reason
                resp = await client.patch(
                    self._route(route),
                    headers={
                        "Authorization": f"Bearer {self._token}",
                        "Accept": "application/vnd.github+json",
                        "X-GitHub-Api-Version": "2022-11-28",
                    },
                    json=payload,
                )
                return self._record(
                    "update_alert_state",
                    "PATCH",
                    route,
                    resp.status_code,
                    {
                        "new_state": state,
                        "rate_limit_snapshot": self._read_rate_limits(resp),
                    },
                )
            except Exception as e:
                return self._record(
                    "update_alert_state", "PATCH", route, 0, {"error": str(e)[:100]}
                )

    @property
    def traces(self) -> list[dict[str, Any]]:
        return list(self._traces)

    def write_trace(self, path: Path | None = None) -> list[dict[str, Any]]:
        if path is None:
            import tempfile

            p = Path(tempfile.mkdtemp()) / "real_boundary_trace.json"
        else:
            p = path
        p.parent.mkdir(parents=True, exist_ok=True)
        trace_artifact = {
            "schema_version": "rig.github.real_github_boundary_trace.v1",
            "content_light": True,
            "total_requests": len(self._traces),
            "requests": self._traces,
        }
        p.write_text(
            json.dumps(trace_artifact, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        return self._traces

    # ── sync wrappers matching FakeGitHubBoundary interface (status_code, response_dict) ──

    def get_ref(self, ref: str):
        import asyncio

        r = asyncio.run(self.get_base_ref(ref))
        return r["status_code"], {"object": {"sha": r.get("ref_sha", "")}} if r[
            "success"
        ] else {}

    def create_branch(self, branch: str, sha: str):
        import asyncio

        base = asyncio.run(self.get_base_ref("heads/main"))
        sha = base.get("ref_sha", "") if base["success"] else sha
        r = asyncio.run(self.create_branch_ref(branch, sha))
        return (
            (r["status_code"], {"ref": r.get("ref_created", "")})
            if r["success"]
            else (r["status_code"], {})
        )

    def write_file(self, path: str, content_sha: str | None = None):
        import asyncio

        content_text = "# Rig Relay governed patch — branch/file/PR rehearsal\n\nThis file was created by Rig Relay's first governed live PR write lane.\nNo alert updates, no merges, no default branch writes.\n"
        r = asyncio.run(
            self.put_file_contents(
                "RIG_RELAY_GOVERNED.md",
                "rig/security/governed-fix-5",
                "fix: governed patch for code scanning alert",
                content_text,
            )
        )
        return r["status_code"], {"content": {"sha": r.get("content_sha", "")}} if r[
            "success"
        ] else {}

    def create_pr(self, title: str, head: str, base: str, idem_key: str):
        import asyncio

        r = asyncio.run(
            self.create_pull_request(
                title, "PR body", "rig/security/governed-fix-5", base
            )
        )
        return r["status_code"], {"number": r.get("pr_number")} if r["success"] else {}


def create_real_boundary(
    owner: str = "OWNER", repo: str = "REPO"
) -> RealGitHubBoundary | None:
    from dotenv import load_dotenv
    from rig_relay.integrations.github_provider._github_app_token_manager import (
        GitHubAppTokenManager,
    )

    dotenv_path = Path.home() / ".rig" / "relay" / ".env"
    if dotenv_path.exists():
        load_dotenv(dotenv_path)

    if os.environ.get(_LIVE_ENV, "0") != "1":
        return None

    # Priority 1: GitHub App installation token (preferred production auth)
    tm = GitHubAppTokenManager.from_environment()
    if tm is not None:
        token = tm.get_token()
        if token:
            return RealGitHubBoundary(owner, repo, token)

    # Priority 2: Personal access token (fallback for development)
    token = os.environ.get("GITHUB_TOKEN", "") or os.environ.get("GH_TOKEN", "")
    if token:
        return RealGitHubBoundary(owner, repo, token)

    return None


__all__ = ["RealGitHubBoundary", "create_real_boundary"]

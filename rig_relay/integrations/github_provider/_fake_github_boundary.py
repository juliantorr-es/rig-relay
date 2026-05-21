"""Fake GitHub HTTP Boundary — deterministic, content-light, traceable.

Simulates GitHub REST responses for tests/simulation. Records a trace artifact.
No live network. No raw response bodies persisted. No credentials.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_TRACE = (
    _REPO_ROOT
    / ".build"
    / "rig-relay"
    / "evidence"
    / "fake_github_pr_mutation_trace_v1.v1.json"
)

_WORKFLOW_PATH_PREFIX = ".github/workflows/"
_BINARY_EXTENSIONS = {
    ".pyc",
    ".so",
    ".dylib",
    ".dll",
    ".exe",
    ".bin",
    ".zip",
    ".gz",
    ".tar",
}


def _sha256_text(val: str) -> str:
    return hashlib.sha256(val.encode("utf-8")).hexdigest()


class FakeGitHubBoundary:
    def __init__(self) -> None:
        self._traces: list[dict] = []
        self._existing_branches: set[str] = set()
        self._existing_prs: set[str] = set()
        self._pr_states: dict[int, dict] = {}
        self._alert_states: dict[int, str] = {}
        self._permissions: dict[str, bool] = {
            "contents:write": True,
            "pull_requests:write": True,
            "workflows:write": False,
            "security_events:write": False,
        }
        self._rate_limited = False

    def set_permission(self, perm: str, granted: bool) -> None:
        self._permissions[perm] = granted

    def set_rate_limited(self, val: bool) -> None:
        self._rate_limited = val

    def add_existing_branch(self, name: str) -> None:
        self._existing_branches.add(name)

    def add_existing_pr(self, idem_key: str) -> None:
        self._existing_prs.add(idem_key)

    def _record(
        self, method: str, route: str, status: int, extra: dict | None = None
    ) -> int:
        entry: dict[str, object] = {
            "method": method,
            "route": route,
            "status_code": status,
            "request_body_hash": _sha256_text(f"{method}:{route}"),
            "response_body_persisted": False,
            "accepted_permissions_header": None,
        }
        if extra:
            entry.update(extra)
        self._traces.append(entry)
        return status

    # ── Pre-PR mutation operations ──

    def get_ref(self, ref: str) -> tuple[int, dict]:
        if self._rate_limited:
            return self._record(
                "GET",
                f"/repos/OWNER/REPO/git/ref/{ref}",
                429,
                {"error": "rate_limited"},
            ), {}
        if ref == "heads/main":
            return self._record("GET", "/repos/OWNER/REPO/git/ref/heads/main", 200), {
                "object": {"sha": "default_base_sha"}
            }
        return self._record("GET", f"/repos/OWNER/REPO/git/ref/{ref}", 404), {}

    def create_branch(self, branch: str, sha: str) -> tuple[int, dict]:
        route = "/repos/OWNER/REPO/git/refs"
        if self._rate_limited:
            return self._record("POST", route, 429, {"error": "rate_limited"}), {}
        if not self._permissions.get("contents:write"):
            return self._record(
                "POST",
                route,
                403,
                {"error": "permission_denied", "missing": "contents:write"},
            ), {}
        if branch in self._existing_branches:
            return self._record("POST", route, 422, {"error": "ref_already_exists"}), {}
        self._existing_branches.add(branch)
        return self._record("POST", route, 201, {"ref": f"refs/heads/{branch}"}), {
            "ref": f"refs/heads/{branch}",
            "object": {"sha": sha},
        }

    def write_file(self, path: str, content_sha: str | None = None) -> tuple[int, dict]:
        route = f"/repos/OWNER/REPO/contents/{path}"
        if self._rate_limited:
            return self._record("PUT", route, 429, {"error": "rate_limited"}), {}
        if path.startswith(_WORKFLOW_PATH_PREFIX):
            return self._record(
                "PUT",
                route,
                403,
                {"error": "workflow_permission_required", "missing": "workflows:write"},
            ), {}
        if not self._permissions.get("contents:write"):
            return self._record(
                "PUT",
                route,
                403,
                {"error": "permission_denied", "missing": "contents:write"},
            ), {}
        ext = Path(path).suffix.lower()
        if ext in _BINARY_EXTENSIONS:
            return self._record("PUT", route, 415, {"error": "binary_unsupported"}), {}
        new_sha = _sha256_text(f"{path}:write:{content_sha or 'nosha'}")
        return self._record("PUT", route, 201, {"content": {"sha": new_sha}}), {
            "content": {"sha": new_sha}
        }

    def create_pr(
        self, title: str, head: str, base: str, idem_key: str
    ) -> tuple[int, dict]:
        route = "/repos/OWNER/REPO/pulls"
        if self._rate_limited:
            return self._record("POST", route, 429, {"error": "rate_limited"}), {}
        if not self._permissions.get("pull_requests:write"):
            return self._record(
                "POST",
                route,
                403,
                {"error": "permission_denied", "missing": "pull_requests:write"},
            ), {}
        if idem_key in self._existing_prs:
            return self._record(
                "POST", route, 200, {"idempotent": True, "pr_number": 42}
            ), {
                "idempotent": True,
                "html_url": "https://github.com/OWNER/REPO/pull/42",
                "number": 42,
            }
        pr_number = len(self._existing_prs) + 1
        self._existing_prs.add(idem_key)
        self._pr_states[pr_number] = {
            "state": "open",
            "checks": "passing",
            "merged": False,
            "review_required": True,
        }
        return self._record("POST", route, 201, {"pr_number": pr_number}), {
            "html_url": f"https://github.com/OWNER/REPO/pull/{pr_number}",
            "number": pr_number,
        }

    # ── Post-PR lifecycle extensions ──

    def get_pr_status(self, pr_number: int) -> tuple[int, dict]:
        if self._rate_limited:
            return self._record(
                "GET",
                f"/repos/OWNER/REPO/pulls/{pr_number}",
                429,
                {"error": "rate_limited"},
            ), {}
        state = self._pr_states.get(pr_number, {})
        if not state:
            return self._record("GET", f"/repos/OWNER/REPO/pulls/{pr_number}", 404), {}
        return self._record("GET", f"/repos/OWNER/REPO/pulls/{pr_number}", 200), {
            "number": pr_number,
            "state": state.get("state", "unknown"),
            "checks": state.get("checks", "unknown"),
            "merged": state.get("merged", False),
            "review_required": state.get("review_required", True),
        }

    def set_pr_state(
        self,
        pr_number: int,
        state: str,
        checks: str = "passing",
        merged: bool = False,
        review_required: bool = True,
    ) -> None:
        self._pr_states[pr_number] = {
            "state": state,
            "checks": checks,
            "merged": merged,
            "review_required": review_required,
        }

    def get_alert_state(self, alert_number: int) -> tuple[int, dict]:
        if self._rate_limited:
            return self._record(
                "GET", f"/repos/OWNER/REPO/code-scanning/alerts/{alert_number}", 429
            ), {}
        if not self._permissions.get("security_events:read", True):
            return self._record(
                "GET",
                f"/repos/OWNER/REPO/code-scanning/alerts/{alert_number}",
                403,
                {"error": "permission_denied"},
            ), {}
        state = self._alert_states.get(alert_number, "open")
        return self._record(
            "GET", f"/repos/OWNER/REPO/code-scanning/alerts/{alert_number}", 200
        ), {"number": alert_number, "state": state}

    def set_alert_state_initial(self, alert_number: int, state: str) -> None:
        self._alert_states[alert_number] = state

    def update_alert_state(
        self, alert_number: int, new_state: str, dismissal_reason: str = ""
    ) -> tuple[int, dict]:
        route = f"/repos/OWNER/REPO/code-scanning/alerts/{alert_number}"
        if self._rate_limited:
            return self._record("PATCH", route, 429, {"error": "rate_limited"}), {}
        if not self._permissions.get("security_events:write"):
            return self._record(
                "PATCH",
                route,
                403,
                {"error": "permission_denied", "missing": "security_events:write"},
            ), {}
        if alert_number not in self._alert_states:
            return self._record("PATCH", route, 404, {"error": "alert_not_found"}), {}
        current = self._alert_states[alert_number]
        if current in {"fixed", "dismissed"}:
            return self._record(
                "PATCH", route, 400, {"error": "alert_already_resolved"}
            ), {}
        self._alert_states[alert_number] = new_state
        return self._record(
            "PATCH",
            route,
            200,
            {
                "number": alert_number,
                "state": new_state,
                "dismissal_reason_hash": _sha256_text(dismissal_reason),
            },
        ), {"number": alert_number, "state": new_state}

    # ── Trace ──

    def write_trace(self, path: Path = _DEFAULT_TRACE) -> list[dict]:
        path.parent.mkdir(parents=True, exist_ok=True)
        trace_artifact = {
            "schema_version": "rig.github.fake_github_mutation_trace.v1",
            "content_light": True,
            "total_requests": len(self._traces),
            "requests": self._traces,
        }
        path.write_text(
            json.dumps(trace_artifact, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        return self._traces

    @property
    def traces(self) -> list[dict]:
        return list(self._traces)

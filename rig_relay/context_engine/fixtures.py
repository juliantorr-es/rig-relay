"""Integration fixtures for deferred J0 and K0 lane dependencies.

Until J0 releases a repository-intake contract and K0 releases an
AgentLoop investigation/proposal contract, this module provides typed
fixtures that conform to the expected intake and evidence shapes.

These are designed to be replaced by live service calls when the
dependent lanes publish their boundaries.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

# ── J0 Intake Fixture (Repository Intake) ─────────────────────────────


@dataclass(frozen=True)
class IntakeFixture:
    """Typed fixture standing in for J0 RepositoryIntakeService output.

    Provides repository identity and structural signals from a real
    repository, formatted to match the expected J0 intake contract shape.
    The fixture reads from an actual repository root but does not depend
    on a live J0 service call.
    """

    repository_root: Path
    project_name: str = ""
    head_sha: str = ""
    branch: str = ""
    is_github_backed: bool = False
    is_local_only: bool = True
    remotes_count: int = 0
    repository_url_digest: str = ""

    @classmethod
    def from_repository(cls, root: Path, project_name: str = "") -> IntakeFixture:
        """Build an intake fixture from a real repository path.

        Reads git state to populate intake identity fields without
        depending on a live J0 service.
        """
        from hashlib import sha256

        resolved = root.resolve()
        branch = _git("rev-parse", "--abbrev-ref", "HEAD", cwd=resolved) or "unknown"
        head = _git("rev-parse", "HEAD", cwd=resolved) or "unknown"
        remotes = _git_remotes(resolved)
        github_backed = any("github.com" in str(r.get("url", "")) for r in remotes)

        name = project_name or resolved.name
        url_digest = sha256(str(resolved).encode()).hexdigest()

        return cls(
            repository_root=resolved,
            project_name=name,
            head_sha=head[:16],
            branch=branch,
            is_github_backed=github_backed,
            is_local_only=len(remotes) == 0,
            remotes_count=len(remotes),
            repository_url_digest=f"sha256:{url_digest}",
        )


# ── K0 Investigation Evidence Fixture ─────────────────────────────────


class InvestigationFinding(BaseModel):
    """A single finding from K0 investigation evidence."""

    model_config = ConfigDict(extra="forbid")

    finding_id: str
    category: str = Field(
        description="security, architecture, testing, documentation, etc."
    )
    summary: str
    severity: str = "info"
    evidence_paths: list[str] = Field(default_factory=list)


class InvestigationEvidenceFixture(BaseModel):
    """Typed fixture standing in for K0 AgentLoop investigation output.

    Provides structured investigation findings from an AgentLoop analysis
    session. Formatted to match the expected K0 evidence contract shape.
    Uses typed fixtures, not live K0 service calls.
    """

    model_config = ConfigDict(extra="forbid")

    session_id: str = "fixture_investigation_k0"
    investigation_sha: str = ""
    findings: list[InvestigationFinding] = Field(default_factory=list)
    validated_claims: list[str] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @classmethod
    def empty(cls) -> InvestigationEvidenceFixture:
        return cls(investigation_sha="fixture:empty")


def _git(*args: str, cwd: Path) -> str:
    import subprocess

    try:
        return subprocess.check_output(
            ["git", *args], text=True, stderr=subprocess.DEVNULL, cwd=cwd
        ).strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return ""


_MIN_REMOTE_LINE_PARTS = 2


def _git_remotes(root: Path) -> list[dict[str, str]]:
    output = _git("remote", "-v", cwd=root)
    if not output:
        return []
    remotes: dict[str, dict[str, str]] = {}
    for line in output.splitlines():
        parts = line.split()
        if len(parts) < _MIN_REMOTE_LINE_PARTS:
            continue
        name = parts[0]
        url = parts[1]
        if name not in remotes:
            remotes[name] = {"name": name, "url": url, "host": _host_from_url(url)}
    return list(remotes.values())


def _host_from_url(url: str) -> str:
    if "github.com" in url:
        return "github.com"
    if "gitlab.com" in url:
        return "gitlab.com"
    if "bitbucket.org" in url:
        return "bitbucket.org"
    return "unknown"


__all__ = ["IntakeFixture", "InvestigationEvidenceFixture", "InvestigationFinding"]

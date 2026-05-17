from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from rig_relay.release_gate._static_artifacts import (
    check_cache_policy,
    check_diagram_safety,
    check_generated_site_present,
    check_schema_coverage,
    check_schema_validation,
    check_secret_leakage,
    run_static_artifact_checks,
)
from rig_relay.release_gate.models import CheckSeverity, CheckStatus


def _write_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


class _FakeGit:
    """Simulate git ls-files output for cache policy check."""

    def __init__(self, committed_pi_lens: list[str] | None = None):
        self._committed = committed_pi_lens or []

    def run(self, args: list[str], **kwargs: object) -> object:
        import subprocess

        result = subprocess.CompletedProcess(args, 0)
        if "--cached" in args:
            result.stdout = "\n".join(self._committed) if self._committed else ""
            result.stderr = ""
            return result
        result.stdout = ""
        result.stderr = ""
        result.returncode = 0
        return result


# ── Schema validation tests ─────────────────────────────────────────────


def test_schema_validation_passes_for_valid_docs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("rig_relay.release_gate._static_artifacts._REPO_ROOT", tmp_path)
    monkeypatch.setattr(
        "rig_relay.release_gate._static_artifacts._DOCS_JSON_DIR",
        tmp_path / "docs" / "json",
    )
    monkeypatch.setattr(
        "rig_relay.release_gate._static_artifacts._DOCS_SCHEMAS_DIR",
        tmp_path / "docs" / "schemas",
    )

    schema = {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "type": "object",
        "required": ["schema_version", "title"],
        "properties": {
            "schema_version": {"const": "rig.test.v1"},
            "title": {"type": "string"},
        },
    }
    _write_json(tmp_path / "docs" / "schemas" / "rig.test.v1.schema.json", schema)
    _write_json(
        tmp_path / "docs" / "json" / "valid.v1.json",
        {"schema_version": "rig.test.v1", "title": "Valid Doc"},
    )

    result = check_schema_validation()
    assert result.status == CheckStatus.PASS


def test_schema_validation_flags_json_parse_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("rig_relay.release_gate._static_artifacts._REPO_ROOT", tmp_path)
    monkeypatch.setattr(
        "rig_relay.release_gate._static_artifacts._DOCS_JSON_DIR",
        tmp_path / "docs" / "json",
    )
    monkeypatch.setattr(
        "rig_relay.release_gate._static_artifacts._DOCS_SCHEMAS_DIR",
        tmp_path / "docs" / "schemas",
    )

    (tmp_path / "docs" / "json").mkdir(parents=True)
    (tmp_path / "docs" / "json" / "bad.v1.json").write_text(
        "{not valid json", encoding="utf-8"
    )

    result = check_schema_validation()
    assert result.status == CheckStatus.FAIL
    assert result.severity == CheckSeverity.BLOCKER
    assert any("json_parse_error" in f.finding_id for f in result.findings)


def test_schema_validation_collects_all_errors_not_just_first(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("rig_relay.release_gate._static_artifacts._REPO_ROOT", tmp_path)
    monkeypatch.setattr(
        "rig_relay.release_gate._static_artifacts._DOCS_JSON_DIR",
        tmp_path / "docs" / "json",
    )
    monkeypatch.setattr(
        "rig_relay.release_gate._static_artifacts._DOCS_SCHEMAS_DIR",
        tmp_path / "docs" / "schemas",
    )

    schema = {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "type": "object",
        "required": ["schema_version", "title", "status"],
        "properties": {
            "schema_version": {"const": "rig.test.v1"},
            "title": {"type": "string"},
            "status": {"type": "string", "minLength": 10},
        },
    }
    _write_json(tmp_path / "docs" / "schemas" / "rig.test.v1.schema.json", schema)
    _write_json(
        tmp_path / "docs" / "json" / "multi_error.v1.json",
        {"schema_version": "rig.test.v1", "status": "short"},
    )

    result = check_schema_validation()
    assert result.status == CheckStatus.FAIL

    findings_for_doc = [f for f in result.findings if "multi_error" in f.source]
    assert len(findings_for_doc) >= 1
    error_desc = findings_for_doc[0].description
    assert "title" in error_desc
    assert "status" in error_desc or "short" in error_desc.lower()


# ── Schema coverage tests ───────────────────────────────────────────────


def test_schema_coverage_flags_orphan_versions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("rig_relay.release_gate._static_artifacts._REPO_ROOT", tmp_path)
    monkeypatch.setattr(
        "rig_relay.release_gate._static_artifacts._DOCS_JSON_DIR",
        tmp_path / "docs" / "json",
    )
    monkeypatch.setattr(
        "rig_relay.release_gate._static_artifacts._DOCS_SCHEMAS_DIR",
        tmp_path / "docs" / "schemas",
    )

    _write_json(
        tmp_path / "docs" / "json" / "orphan.v1.json",
        {"schema_version": "rig.nonexistent.v1", "title": "Orphan"},
    )

    result = check_schema_coverage()
    assert result.status == CheckStatus.FAIL
    assert any("orphan_schema" in f.finding_id for f in result.findings)


# ── Generated site tests ───────────────────────────────────────────────


def test_generated_site_flags_missing_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("rig_relay.release_gate._static_artifacts._REPO_ROOT", tmp_path)
    monkeypatch.setattr(
        "rig_relay.release_gate._static_artifacts._DOCS_DIR", tmp_path / "docs"
    )

    (tmp_path / "docs").mkdir(parents=True)
    # No index.html created

    result = check_generated_site_present()
    assert result.status == CheckStatus.FAIL
    assert any("missing_site_home" in f.finding_id for f in result.findings)


def test_generated_site_passes_when_all_present(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("rig_relay.release_gate._static_artifacts._REPO_ROOT", tmp_path)
    monkeypatch.setattr(
        "rig_relay.release_gate._static_artifacts._DOCS_DIR", tmp_path / "docs"
    )

    docs = tmp_path / "docs"
    (docs / "pages").mkdir(parents=True)
    (docs / "collections").mkdir(parents=True)
    (docs / "assets").mkdir(parents=True)
    (docs / "pages" / "test.html").write_text("<html></html>", encoding="utf-8")
    (docs / "collections" / "test.html").write_text("<html></html>", encoding="utf-8")
    (docs / "assets" / "site.css").write_text("body{}", encoding="utf-8")
    (docs / "assets" / "site.js").write_text("//", encoding="utf-8")
    (docs / "assets" / "favicon.svg").write_text("<svg></svg>", encoding="utf-8")
    (docs / "index.html").write_text("<html></html>", encoding="utf-8")
    (docs / "search-index.json").write_text("[]", encoding="utf-8")
    (docs / "render-manifest.json").write_text("{}", encoding="utf-8")
    (docs / ".nojekyll").write_text("", encoding="utf-8")

    result = check_generated_site_present()
    assert result.status == CheckStatus.PASS


# ── Secret leakage tests ────────────────────────────────────────────────


def test_secret_leakage_detects_github_pat_in_html(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("rig_relay.release_gate._static_artifacts._REPO_ROOT", tmp_path)
    monkeypatch.setattr(
        "rig_relay.release_gate._static_artifacts._DOCS_DIR", tmp_path / "docs"
    )

    (tmp_path / "docs" / "pages").mkdir(parents=True)
    (tmp_path / "docs" / "pages" / "leaky.html").write_text(
        "<html><body><p>Token: github_pat_11ABCDEFGHIJKLMNOPQRSTUVWXYZ</p></body></html>",
        encoding="utf-8",
    )

    result = check_secret_leakage()
    assert result.status == CheckStatus.FAIL
    assert result.severity == CheckSeverity.BLOCKER
    assert any("secret.github_pat" in f.finding_id for f in result.findings)
    # Secret values must NOT appear in finding descriptions
    for f in result.findings:
        assert "github_pat_11" not in f.description


def test_secret_leakage_detects_pem_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("rig_relay.release_gate._static_artifacts._REPO_ROOT", tmp_path)
    monkeypatch.setattr(
        "rig_relay.release_gate._static_artifacts._DOCS_DIR", tmp_path / "docs"
    )

    (tmp_path / "docs" / "pages").mkdir(parents=True)
    (tmp_path / "docs" / "pages" / "leaky.html").write_text(
        "-----BEGIN PRIVATE KEY-----\nMIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQ==\n-----END PRIVATE KEY-----",
        encoding="utf-8",
    )

    result = check_secret_leakage()
    assert result.status == CheckStatus.FAIL
    assert any("secret.pem_private_key" in f.finding_id for f in result.findings)
    for f in result.findings:
        assert "MIIEvQ" not in f.description


def test_secret_leakage_passes_on_clean_site(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("rig_relay.release_gate._static_artifacts._REPO_ROOT", tmp_path)
    monkeypatch.setattr(
        "rig_relay.release_gate._static_artifacts._DOCS_DIR", tmp_path / "docs"
    )

    (tmp_path / "docs" / "pages").mkdir(parents=True)
    (tmp_path / "docs" / "pages" / "clean.html").write_text(
        "<html><body><p>Hello, world!</p></body></html>", encoding="utf-8"
    )

    result = check_secret_leakage()
    assert result.status == CheckStatus.PASS


# ── Diagram safety tests ────────────────────────────────────────────────


def test_diagram_safety_flags_remote_source_url(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("rig_relay.release_gate._static_artifacts._REPO_ROOT", tmp_path)
    monkeypatch.setattr(
        "rig_relay.release_gate._static_artifacts._DOCS_JSON_DIR",
        tmp_path / "docs" / "json",
    )

    _write_json(
        tmp_path / "docs" / "json" / "diagrams" / "remote.v1.json",
        {
            "schema_version": "rig.diagram.v1",
            "diagram_id": "remote-diagram",
            "title": "Remote",
            "kind": "flow",
            "source_data": {"type": "json", "path": "https://evil.com/data.json"},
        },
    )

    result = check_diagram_safety()
    assert result.status == CheckStatus.FAIL
    assert result.severity == CheckSeverity.BLOCKER
    assert any("remote_source" in f.finding_id for f in result.findings)


def test_diagram_safety_flags_absolute_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("rig_relay.release_gate._static_artifacts._REPO_ROOT", tmp_path)
    monkeypatch.setattr(
        "rig_relay.release_gate._static_artifacts._DOCS_JSON_DIR",
        tmp_path / "docs" / "json",
    )

    _write_json(
        tmp_path / "docs" / "json" / "diagrams" / "absolute.v1.json",
        {
            "schema_version": "rig.diagram.v1",
            "diagram_id": "abs-diagram",
            "title": "Absolute",
            "kind": "flow",
            "source_data": {"type": "json", "path": "/etc/passwd"},
        },
    )

    result = check_diagram_safety()
    assert result.status == CheckStatus.FAIL
    assert any("absolute_path" in f.finding_id for f in result.findings)


def test_diagram_safety_flags_script_injection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("rig_relay.release_gate._static_artifacts._REPO_ROOT", tmp_path)
    monkeypatch.setattr(
        "rig_relay.release_gate._static_artifacts._DOCS_JSON_DIR",
        tmp_path / "docs" / "json",
    )

    _write_json(
        tmp_path / "docs" / "json" / "diagrams" / "inject.v1.json",
        {
            "schema_version": "rig.diagram.v1",
            "diagram_id": "inject-diagram",
            "title": "Injected",
            "kind": "flow",
            "nodes": [
                {
                    "id": "n1",
                    "label": '<script>alert("xss")</script>',
                    "status": "active",
                }
            ],
        },
    )

    result = check_diagram_safety()
    assert result.status == CheckStatus.FAIL
    assert any("injection" in f.finding_id for f in result.findings)


# ── Cache policy tests ──────────────────────────────────────────────────


def test_cache_policy_flags_committed_pi_lens(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("rig_relay.release_gate._static_artifacts._REPO_ROOT", tmp_path)

    (tmp_path / ".gitignore").write_text("__pycache__/\n.build/\n", encoding="utf-8")

    fake_git = _FakeGit(
        committed_pi_lens=[".pi-lens/cache/knip.json", ".pi-lens/turn-state.json"]
    )

    with patch("subprocess.run", side_effect=fake_git.run):
        result = check_cache_policy()

    assert result.status == CheckStatus.WARN
    assert any("pi_lens_committed" in f.finding_id for f in result.findings)


def test_cache_policy_passes_when_clean(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("rig_relay.release_gate._static_artifacts._REPO_ROOT", tmp_path)

    (tmp_path / ".gitignore").write_text(
        "__pycache__/\n.build/\n.pi-lens/\n.DS_Store\n", encoding="utf-8"
    )

    fake_git = _FakeGit(committed_pi_lens=[])

    with patch("subprocess.run", side_effect=fake_git.run):
        result = check_cache_policy()

    assert result.status == CheckStatus.PASS


# ── Repository-level smoke test ─────────────────────────────────────────


def test_static_artifact_checks_run_on_real_repo() -> None:
    results = run_static_artifact_checks()
    assert len(results) == 6

    check_ids = {r.check_id for r in results}
    assert check_ids == {
        "static.schemas.valid_json_documents",
        "static.schemas.schema_registry_coverage",
        "static.renderer.generated_site_present",
        "static.renderer.no_secret_leakage",
        "static.diagrams.safe_sources",
        "static.generated_artifacts.cache_policy",
    }

    for r in results:
        assert isinstance(r.status, CheckStatus)
        assert isinstance(r.check_id, str)
        assert isinstance(r.title, str)
        assert isinstance(r.severity, CheckSeverity)
        assert r.findings is not None
        assert r.evidence is not None


def test_check_ids_are_deterministic_on_real_repo() -> None:
    results1 = run_static_artifact_checks()
    results2 = run_static_artifact_checks()

    for r1, r2 in zip(results1, results2, strict=True):
        assert r1.check_id == r2.check_id
        assert r1.status == r2.status
        assert r1.title == r2.title
        assert [f.finding_id for f in r1.findings] == [
            f.finding_id for f in r2.findings
        ]
        assert r1.severity == r2.severity, (
            f"Severity drift for {r1.check_id}: {r1.severity} vs {r2.severity}"
        )


def test_all_check_results_have_evidence_on_real_repo() -> None:
    results = run_static_artifact_checks()
    for r in results:
        assert r.evidence, f"Check {r.check_id} has no evidence"
        assert isinstance(r.summary, str), f"Check {r.check_id} has no summary"

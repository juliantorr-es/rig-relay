from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
AUDIT_SCRIPT = REPO_ROOT / "scripts" / "rig_relay_test_quality_audit.py"
REPORT_PATH = REPO_ROOT / "docs" / "audits" / "test-suite" / "test_quality_report.json"

pytestmark = pytest.mark.smoke


def test_audit_script_exists() -> None:
    assert AUDIT_SCRIPT.exists(), f"Audit script missing: {AUDIT_SCRIPT}"


def test_audit_script_runs() -> None:
    result = subprocess.run(
        [sys.executable, str(AUDIT_SCRIPT)],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        timeout=30,
    )
    assert result.returncode in (0, 1), (
        f"Audit script crashed (code={result.returncode}):\n"
        f"STDERR:\n{result.stderr[:2000]}"
    )


def test_report_json_has_required_keys() -> None:
    data = json.loads(REPORT_PATH.read_text())
    for key in ["doctrine_version", "generated_at", "stats", "findings"]:
        assert key in data, f"Report missing key: {key}"
    for key in ["total_test_files", "total_findings", "by_severity", "by_rule"]:
        assert key in data["stats"], f"Stats missing key: {key}"


def test_report_jsonl_exists() -> None:
    jsonl_path = REPORT_PATH.with_suffix(".jsonl")
    assert jsonl_path.exists(), f"JSONL report missing: {jsonl_path}"


def test_report_summary_md_exists() -> None:
    md_path = REPO_ROOT / "docs" / "audits" / "test-suite" / "test_quality_summary.md"
    assert md_path.exists(), f"Markdown summary missing: {md_path}"


def test_conftest_not_missing() -> None:
    conftest = REPO_ROOT / "tests" / "conftest.py"
    assert conftest.exists(), (
        "tests/conftest.py is missing. "
        "Tests that import tests.conftest will fail on a clean clone."
    )


def test_no_pycache_conftest_without_source() -> None:
    conftest = REPO_ROOT / "tests" / "conftest.py"
    pycache_files = list((REPO_ROOT / "tests" / "__pycache__").glob("conftest*.pyc"))
    if pycache_files and not conftest.exists():
        pytest.fail(
            f"__pycache__/conftest*.pyc exists ({len(pycache_files)} file(s)) "
            "but tests/conftest.py is missing. Clean-clone collection will fail."
        )


def test_markers_registered() -> None:
    result = subprocess.run(
        ["uv", "run", "pytest", "--markers"],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        timeout=30,
    )
    required = [
        "smoke",
        "contract",
        "integration",
        "e2e",
        "packaging",
        "slow",
        "legacy",
        "flaky",
        "network",
        "provider",
        "destructive",
    ]
    for marker in required:
        assert f"@pytest.mark.{marker}:" in result.stdout, (
            f"Marker '{marker}' not registered in pytest config"
        )


def test_doctrine_doc_exists() -> None:
    doc = REPO_ROOT / "docs" / "governance" / "test-suite-doctrine.md"
    assert doc.exists(), f"Doctrine document missing: {doc}"


def test_doctrine_contains_five_rules() -> None:
    doc = REPO_ROOT / "docs" / "governance" / "test-suite-doctrine.md"
    content = doc.read_text()
    required_phrases = [
        "Fast enough",
        "Scoped",
        "Non-duplicative",
        "Deterministic",
        "Named after the behavior",  # exact text from the five rules
    ]
    # The doctrine uses "**Named** after the behavior" (bold markdown)
    assert (
        "Named after the behavior" in content
        or "**Named** after the behavior" in content
    ), "Doctrine missing the 'Named after the behavior' rule"
    for phrase in required_phrases[:4]:
        assert phrase in content, f"Doctrine missing phrase: '{phrase}'"


# ── Synthetic fixture tests ────────────────────────────────────


@pytest.fixture
def synthetic_tests_dir(tmp_path: Path) -> Path:
    d = tmp_path / "tests"
    d.mkdir()
    (d / "conftest.py").write_text("")
    (d / "__init__.py").write_text("")
    return d


def test_synthetic_root_level_is_flagged(
    synthetic_tests_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (synthetic_tests_dir / "test_root.py").write_text("def test_pass(): pass")
    repo = synthetic_tests_dir.parent
    monkeypatch.setattr("scripts.rig_relay_test_quality_audit.REPO_ROOT", repo)
    monkeypatch.setattr(
        "scripts.rig_relay_test_quality_audit.TESTS_DIR", synthetic_tests_dir
    )
    monkeypatch.setattr(
        "scripts.rig_relay_test_quality_audit.OUTPUT_DIR", synthetic_tests_dir
    )

    import scripts.rig_relay_test_quality_audit as audit_mod

    files = audit_mod.collect_test_files()
    findings = audit_mod.check_root_level_tests(files)
    assert len(findings) == 1, f"Expected 1 root-level finding, got {len(findings)}"
    assert findings[0].rule_id == "LAYOUT_ROOT_LEVEL"


def test_synthetic_bad_name_is_flagged(
    synthetic_tests_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (synthetic_tests_dir / "test_foo.py").write_text("def test_basic(): pass")
    repo = synthetic_tests_dir.parent
    monkeypatch.setattr("scripts.rig_relay_test_quality_audit.REPO_ROOT", repo)
    monkeypatch.setattr(
        "scripts.rig_relay_test_quality_audit.TESTS_DIR", synthetic_tests_dir
    )
    monkeypatch.setattr(
        "scripts.rig_relay_test_quality_audit.OUTPUT_DIR", synthetic_tests_dir
    )
    monkeypatch.chdir(str(repo))

    import scripts.rig_relay_test_quality_audit as audit_mod

    files = audit_mod.collect_test_files()
    findings = audit_mod.check_naming(files)
    assert len(findings) >= 1
    assert any(f.rule_id == "NAMING_VAGUE" for f in findings)


def test_synthetic_conftest_pycache_only_is_critical(
    synthetic_tests_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (synthetic_tests_dir / "conftest.py").unlink()
    pycache = synthetic_tests_dir / "__pycache__"
    pycache.mkdir()
    (pycache / "conftest.cpython-312.pyc").write_text("fake")

    monkeypatch.setattr(
        "scripts.rig_relay_test_quality_audit.REPO_ROOT", synthetic_tests_dir.parent
    )
    monkeypatch.setattr(
        "scripts.rig_relay_test_quality_audit.TESTS_DIR", synthetic_tests_dir
    )
    monkeypatch.setattr(
        "scripts.rig_relay_test_quality_audit.OUTPUT_DIR", synthetic_tests_dir
    )

    import scripts.rig_relay_test_quality_audit as audit_mod

    findings = audit_mod.check_conftest()
    criticals = [f for f in findings if f.severity == "critical"]
    assert len(criticals) >= 1, "Expected critical finding for pycache-only conftest"


def test_synthetic_hardcoded_path_is_flagged(
    synthetic_tests_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (synthetic_tests_dir / "test_path.py").write_text("assert '/Users/bob'")
    repo = synthetic_tests_dir.parent
    monkeypatch.setattr("scripts.rig_relay_test_quality_audit.REPO_ROOT", repo)
    monkeypatch.setattr(
        "scripts.rig_relay_test_quality_audit.TESTS_DIR", synthetic_tests_dir
    )
    monkeypatch.setattr(
        "scripts.rig_relay_test_quality_audit.OUTPUT_DIR", synthetic_tests_dir
    )
    monkeypatch.chdir(str(repo))

    import scripts.rig_relay_test_quality_audit as audit_mod

    files = audit_mod.collect_test_files()
    findings = audit_mod.check_determinism_risks(files)
    assert len(findings) >= 1
    assert any(f.rule_id == "DETERM_HARDCODED_PATH" for f in findings)

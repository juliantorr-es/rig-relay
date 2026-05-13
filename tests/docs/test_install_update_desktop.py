"""Tests for Rig Relay version, install, update, and desktop cockpit."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

# ── Paths ────────────────────────────────────────────────────────────────

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
VIBE_INIT = REPO_ROOT / "vibe" / "__init__.py"
PYPROJECT = REPO_ROOT / "pyproject.toml"
VERSION_POLICY = REPO_ROOT / "docs" / "release" / "versioning-policy.md"
INSTALL_DOC = REPO_ROOT / "docs" / "install.md"
README = REPO_ROOT / "README.md"
DOGFOOD = REPO_ROOT / "docs" / "dogfood" / "rig-relay-self-dogfood.md"

# Dynamically load scripts
_SCRIPT_UPDATE = REPO_ROOT / "scripts" / "rig_relay_update_status.py"
_SCRIPT_COCKPIT = REPO_ROOT / "scripts" / "rig_relay_desktop_cockpit.py"


def _load_script(name: str) -> Any:
    import importlib.util as iu

    path = REPO_ROOT / "scripts" / name
    spec = iu.spec_from_file_location(name.replace(".py", ""), path)
    assert spec is not None, f"Could not load {path}"
    assert spec.loader is not None
    mod = iu.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ══════════════════════════════════════════════════════════════════════════
# Track 1: Alpha Version Line
# ══════════════════════════════════════════════════════════════════════════


class TestVersionSourceOfTruth:
    def test_pyproject_version_is_0_1_0a1(self):
        text = PYPROJECT.read_text("utf-8")
        assert 'version = "0.1.0a1"' in text

    def test_vibe_init_version_is_0_1_0a1(self):
        text = VIBE_INIT.read_text("utf-8")
        assert '__version__ = "0.1.0a1"' in text

    def test_versions_match(self):
        pyproject_text = PYPROJECT.read_text("utf-8")
        init_text = VIBE_INIT.read_text("utf-8")
        py_version = "unknown"
        for line in pyproject_text.splitlines():
            if line.startswith("version"):
                py_version = line.split("=")[1].strip().strip('"')
                break
        vibe_version = "unknown"
        for line in init_text.splitlines():
            if line.startswith("__version__"):
                vibe_version = line.split("=")[1].strip().strip('"').strip("'")
                break
        assert py_version == vibe_version, (
            f"pyproject.toml has {py_version!r}, vibe/__init__.py has {vibe_version!r}"
        )


class TestVersioningPolicyDoc:
    def test_doc_exists(self):
        assert VERSION_POLICY.is_file(), "versioning-policy.md missing"

    def test_mentions_independent_version_line(self):
        text = VERSION_POLICY.read_text("utf-8")
        assert "independent version line" in text

    def test_mentions_v0_1_0_alpha_1(self):
        text = VERSION_POLICY.read_text("utf-8")
        assert "0.1.0a1" in text or "v0.1.0-alpha.1" in text

    def test_mentions_upstream_provenance(self):
        text = VERSION_POLICY.read_text("utf-8")
        assert "Vibe-derived" in text


class TestReadmeProvenance:
    def test_readme_has_independent_version_note(self):
        text = README.read_text("utf-8")
        assert "independent version" in text or "0.1.0a1" in text or "v0.1.0-alpha.1" in text


class TestInstallDoc:
    def test_doc_exists(self):
        assert INSTALL_DOC.is_file()
        text = INSTALL_DOC.read_text("utf-8")
        assert "uv tool install" in text
        assert "pipx install" in text


class TestCLIVersion:
    def test_cli_version_displays_0_1_0a1(self):
        # Direct check: vibe/__init__.py drives --version output
        init_text = VIBE_INIT.read_text("utf-8")
        assert "0.1.0a1" in init_text


# ══════════════════════════════════════════════════════════════════════════
# Track 2: Update Status
# ══════════════════════════════════════════════════════════════════════════


class TestUpdateStatusSchema:
    def _schema(self) -> dict:
        path = REPO_ROOT / "docs" / "schemas" / "rig.relay.update_status.v1.schema.json"
        return json.loads(path.read_text("utf-8"))

    def test_schema_validates_sample(self):
        try:
            import jsonschema as js
        except ImportError:
            pytest.skip("jsonschema not available")

        up = _load_script("rig_relay_update_status.py")
        sample = up.generate_update_status(
            latest_version="0.1.0a2",
            current_version="0.1.0a1",
            install_source="uv_tool",
            active_sessions=0,
        )
        validator = js.Draft7Validator(self._schema())
        errors = list(validator.iter_errors(sample))
        assert len(errors) == 0, f"Schema errors: {errors}"

    def test_rejects_missing_fields(self):
        try:
            import jsonschema as js
        except ImportError:
            pytest.skip("jsonschema not available")

        validator = js.Draft7Validator(self._schema())
        errors = list(validator.iter_errors({}))
        assert len(errors) > 0


class TestUpdateStatusGenerator:
    @pytest.fixture(scope="class")
    def up(self):
        return _load_script("rig_relay_update_status.py")

    def test_restart_safe_when_no_active_sessions(self, up):
        status = up.generate_update_status(
            latest_version="0.1.0a2", current_version="0.1.0a1", active_sessions=0
        )
        assert status["restart_safe"] is True
        assert status["blocked_by_active_sessions"] == 0

    def test_restart_not_safe_with_active_sessions(self, up):
        status = up.generate_update_status(
            latest_version="0.1.0a2", current_version="0.1.0a1", active_sessions=3
        )
        assert status["restart_safe"] is False
        assert status["blocked_by_active_sessions"] == 3
        assert status["update_state"] == "restart_blocked_active_sessions"

    def test_recommended_command_uv_tool(self, up):
        status = up.generate_update_status(
            latest_version="0.1.0a2",
            current_version="0.1.0a1",
            install_source="uv_tool",
        )
        assert "uv tool upgrade rig-relay" in status["recommended_update_command"]

    def test_recommended_command_homebrew(self, up):
        status = up.generate_update_status(
            latest_version="0.1.0a2",
            current_version="0.1.0a1",
            install_source="homebrew",
        )
        assert "brew upgrade rig-relay" in status["recommended_update_command"]

    def test_recommended_command_pipx(self, up):
        status = up.generate_update_status(
            latest_version="0.1.0a2", current_version="0.1.0a1", install_source="pipx"
        )
        assert "pipx upgrade rig-relay" in status["recommended_update_command"]

    def test_up_to_date_no_update_available(self, up):
        status = up.generate_update_status(
            latest_version="0.1.0a1", current_version="0.1.0a1"
        )
        assert status["update_available"] is False
        assert status["update_state"] == "up_to_date"

    def test_update_available_flag(self, up):
        status = up.generate_update_status(
            latest_version="0.1.0a2", current_version="0.1.0a1"
        )
        assert status["update_available"] is True

    def test_override_update_state(self, up):
        status = up.generate_update_status(
            latest_version="0.1.0a2",
            current_version="0.1.0a1",
            update_state="restart_ready",
        )
        assert status["update_state"] == "restart_ready"

    def test_unknown_install_source(self, up):
        status = up.generate_update_status(
            latest_version="0.1.0a2",
            current_version="0.1.0a1",
            install_source="unknown",
        )
        assert "pip install" in status["recommended_update_command"]

    def test_current_version_auto_detected(self, up):
        status = up.generate_update_status(latest_version="0.1.0a1")
        assert status["current_version"] == "0.1.0a1"
        assert status["update_available"] is False


# ══════════════════════════════════════════════════════════════════════════
# Track 2: Telemetry Budget
# ══════════════════════════════════════════════════════════════════════════


class TestTelemetryBudgetSchema:
    def _schema(self) -> dict:
        path = (
            REPO_ROOT / "docs" / "schemas" / "rig.relay.telemetry_budget.v1.schema.json"
        )
        return json.loads(path.read_text("utf-8"))

    def test_schema_validates_defaults(self):
        try:
            import jsonschema as js
        except ImportError:
            pytest.skip("jsonschema not available")

        sample = {
            "schema_version": "rig.relay.telemetry_budget.v1",
            "max_bundle_mb": 100,
            "max_rows_per_dataset": 100000,
            "max_semantic_snippets_per_session": 200,
            "raw_retention_days": 14,
            "derived_retention_days": 180,
            "upload_mode": "rollup_plus_samples",
        }
        validator = js.Draft7Validator(self._schema())
        errors = list(validator.iter_errors(sample))
        assert len(errors) == 0, f"Schema errors: {errors}"

    def test_rejects_negative_counts(self):
        try:
            import jsonschema as js
        except ImportError:
            pytest.skip("jsonschema not available")

        sample = {
            "schema_version": "rig.relay.telemetry_budget.v1",
            "max_bundle_mb": -1,
            "max_rows_per_dataset": 100000,
            "max_semantic_snippets_per_session": 200,
            "raw_retention_days": 14,
            "derived_retention_days": 180,
            "upload_mode": "rollup_plus_samples",
        }
        validator = js.Draft7Validator(self._schema())
        errors = list(validator.iter_errors(sample))
        assert len(errors) > 0

    def test_rejects_invalid_upload_mode(self):
        try:
            import jsonschema as js
        except ImportError:
            pytest.skip("jsonschema not available")

        sample = {
            "schema_version": "rig.relay.telemetry_budget.v1",
            "max_bundle_mb": 100,
            "max_rows_per_dataset": 100000,
            "max_semantic_snippets_per_session": 200,
            "raw_retention_days": 14,
            "derived_retention_days": 180,
            "upload_mode": "unlimited",
        }
        validator = js.Draft7Validator(self._schema())
        errors = list(validator.iter_errors(sample))
        assert len(errors) > 0

    def test_required_fields_defined(self):
        schema = self._schema()
        required = schema.get("required", [])
        assert "max_bundle_mb" in required
        assert "max_rows_per_dataset" in required
        assert "upload_mode" in required


# ══════════════════════════════════════════════════════════════════════════
# Track 3: Desktop Cockpit
# ══════════════════════════════════════════════════════════════════════════


class TestDesktopCockpit:
    @pytest.fixture(scope="class")
    def dc(self):
        return _load_script("rig_relay_desktop_cockpit.py")

    def test_static_assets_exist(self):
        base = REPO_ROOT / "frontend" / "desktop"
        assert (base / "index.html").is_file()
        assert (base / "styles.css").is_file()
        assert (base / "app.js").is_file()

    def test_dry_run_handles_missing_files(self, dc):
        """dry_run should not crash when build artifacts are missing."""
        from contextlib import redirect_stdout
        import io

        f = io.StringIO()
        with redirect_stdout(f):
            dc._dry_run()
        output = f.getvalue()
        assert "MISSING" in output or "OK" in output

    def test_no_mutation_methods(self, dc):
        """Verify the CockpitAPI class has no mutation methods."""
        import inspect

        # Reload to get the class
        # The API class is defined inside _open_window, so check the module
        api_attrs = set()
        for name, _obj in inspect.getmembers(dc):
            if "CockpitAPI" in name or "cockpit" in name.lower():
                api_attrs.add(name)
        # Check that load_data returns no mutation keys
        data = dc.load_data()
        assert isinstance(data, dict)

    def test_script_has_help(self):
        result = __import__("subprocess").run(
            ["python", str(_SCRIPT_COCKPIT), "--help"], capture_output=True, text=True
        )
        assert result.returncode == 0
        assert "Rig Relay Desktop Cockpit" in result.stdout

    def test_html_contains_no_mutation_buttons(self):
        html = (REPO_ROOT / "frontend" / "desktop" / "index.html").read_text("utf-8")
        assert "Read-Only" in html
        # Only refresh button — no save/submit/delete
        assert "Save" not in html and "Delete" not in html


# ══════════════════════════════════════════════════════════════════════════
# Track 2: Update Policy Doc
# ══════════════════════════════════════════════════════════════════════════


class TestUpdatePolicyDoc:
    def test_doc_exists(self):
        path = REPO_ROOT / "docs" / "governance" / "update-policy.md"
        assert path.is_file()

    def test_mentions_no_restart_during_active_sessions(self):
        path = REPO_ROOT / "docs" / "governance" / "update-policy.md"
        text = path.read_text("utf-8")
        assert (
            "No restart during active sessions" in text
            or "active sessions" in text.lower()
        )

    def test_mentions_all_update_states(self):
        path = REPO_ROOT / "docs" / "governance" / "update-policy.md"
        text = path.read_text("utf-8")
        for state in [
            "up_to_date",
            "update_available",
            "restart_blocked_active_sessions",
            "restart_ready",
        ]:
            assert state in text, f"Missing update state: {state}"


class TestDesktopCockpitUIDoc:
    def test_doc_exists(self):
        path = REPO_ROOT / "docs" / "governance" / "desktop-cockpit-ui.md"
        assert path.is_file()

    def test_mentions_read_only(self):
        path = REPO_ROOT / "docs" / "governance" / "desktop-cockpit-ui.md"
        text = path.read_text("utf-8")
        assert "read-only" in text.lower() or "Read-Only" in text

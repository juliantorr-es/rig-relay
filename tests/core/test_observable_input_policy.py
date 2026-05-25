from __future__ import annotations

import subprocess

import pytest

from rig_relay.core.observable_input_policy import classify_ignored_observable_inputs


def test_ignored_env_refuses():
    """Dotfile name like .env has no suffix — matches full filename against observable set."""
    assessment = classify_ignored_observable_inputs(["config/.env"])
    assert assessment.blocked is True
    assert assessment.observable_count == 1
    assert assessment.unknown_count == 0
    assert assessment.disposable_count == 0
    assert "config/.env" in assessment.observable_paths


def test_ignored_py_source_refuses():
    assessment = classify_ignored_observable_inputs(["generated/helpers.py"])
    assert assessment.blocked is True
    assert assessment.observable_count == 1
    assert "generated/helpers.py" in assessment.observable_paths


def test_ignored_json_config_refuses():
    assessment = classify_ignored_observable_inputs(["config/local.json"])
    assert assessment.observable_count == 1
    assert assessment.blocked is True


def test_ignored_toml_refuses():
    assessment = classify_ignored_observable_inputs(["pyproject.local.toml"])
    assert assessment.observable_count == 1


def test_ignored_yaml_refuses():
    assessment = classify_ignored_observable_inputs(["data/config.yml"])
    assert assessment.observable_count == 1


def test_ignored_sql_refuses():
    assessment = classify_ignored_observable_inputs(["migrations/local.sql"])
    assert assessment.observable_count == 1


def test_ignored_unknown_refuses_conservatively():
    assessment = classify_ignored_observable_inputs(["artifacts/mystery.asset"])
    assert assessment.blocked is True
    assert assessment.unknown_count == 1
    assert "artifacts/mystery.asset" in assessment.unknown_paths


def test_only_pytest_cache_proceeds():
    assessment = classify_ignored_observable_inputs([".pytest_cache/v/cache/nodeids"])
    assert assessment.blocked is False
    assert assessment.disposable_count == 1
    assert ".pytest_cache" in assessment.disposable_categories


def test_only_ruff_cache_proceeds():
    assessment = classify_ignored_observable_inputs([".ruff_cache/0.11.0/12345"])
    assert assessment.blocked is False
    assert assessment.disposable_count == 1


def test_only_pycache_proceeds():
    assessment = classify_ignored_observable_inputs([
        "src/__pycache__/module.cpython-312.pyc"
    ])
    assert assessment.blocked is False
    assert assessment.disposable_count == 1


def test_only_node_modules_proceeds():
    assessment = classify_ignored_observable_inputs(["node_modules/pkg/index.js"])
    assert assessment.blocked is False
    assert assessment.disposable_count == 1


def test_only_dot_venv_proceeds():
    assessment = classify_ignored_observable_inputs([
        ".venv/lib/python3.12/site-packages/numpy/__init__.py"
    ])
    assert assessment.blocked is False
    assert assessment.disposable_count == 1
    assert ".venv" in assessment.disposable_categories


def test_build_output_in_build_dir_is_disposable():
    assessment = classify_ignored_observable_inputs(["build/output.js"])
    assert assessment.blocked is False
    assert assessment.disposable_count == 1
    assert "build" in assessment.disposable_categories


def test_build_output_py_at_root_is_not_disposable():
    assessment = classify_ignored_observable_inputs(["build-output.py"])
    assert assessment.disposable_count == 0
    assert assessment.observable_count == 1
    assert assessment.blocked is True
    assert "build-output.py" in assessment.observable_paths


def test_venv_dir_is_disposable():
    assessment = classify_ignored_observable_inputs(["venv/bin/python"])
    assert assessment.blocked is False
    assert assessment.disposable_count == 1


def test_src_build_output_is_disposable():
    """Any directory named 'build' anywhere in the path is disposable."""
    assessment = classify_ignored_observable_inputs(["src/build/output.py"])
    assert assessment.disposable_count == 1
    assert assessment.observable_count == 0
    assert assessment.blocked is False
    assert "build" in assessment.disposable_categories


def test_mixed_disposable_and_observable_blocks():
    assessment = classify_ignored_observable_inputs([
        ".pytest_cache/v/nodeids",
        "local/config.json",
    ])
    assert assessment.blocked is True
    assert assessment.disposable_count == 1
    assert assessment.observable_count == 1
    assert ".pytest_cache" in assessment.disposable_categories


def test_empty_ignored_list_does_not_block():
    assessment = classify_ignored_observable_inputs([])
    assert assessment.blocked is False
    assert assessment.disposable_count == 0
    assert assessment.observable_count == 0
    assert assessment.unknown_count == 0


def test_receipt_fields_content_light():
    assessment = classify_ignored_observable_inputs([
        ".pytest_cache/v/nodeids",
        "config/.env",
        "artifacts/mystery.asset",
    ])
    fields = assessment.to_receipt_fields()
    assert "ignored_disposable_exclusion_categories" in fields
    assert fields["ignored_disposable_count"] == 1
    assert fields["ignored_observable_candidate_count"] == 1
    assert fields["unknown_ignored_count"] == 1
    flat = str(fields)
    assert "mystery.asset" not in flat


@pytest.mark.real_artifact
@pytest.mark.substrate
def test_classifier_integration_with_real_git_repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(
        ["git", "init", "-b", "main"], cwd=repo, check=True, capture_output=True
    )
    subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=repo, check=True)

    (repo / ".gitignore").write_text("*.env\n*.local.json\nbuild/\n")
    (repo / "README.md").write_text("# test")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(
        ["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True
    )

    (repo / ".env").write_text("SECRET=test")
    (repo / "config.local.json").write_text("{}")
    (repo / "build").mkdir()
    (repo / "build" / "output.js").write_text("// generated")

    proc = subprocess.run(
        ["git", "ls-files", "--others", "--ignored", "--exclude-standard"],
        capture_output=True,
        text=True,
        cwd=repo,
    )
    ignored = [p for p in proc.stdout.strip().splitlines() if p]

    assessment = classify_ignored_observable_inputs(ignored)

    assert assessment.observable_count == 2
    assert assessment.unknown_count == 0
    assert assessment.disposable_count == 1
    assert assessment.blocked is True
    assert "build" in assessment.disposable_categories

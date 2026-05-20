from __future__ import annotations

import json
from pathlib import Path

import pytest

from rig_relay.enterprise.secrets_manager import (
    SecretsBackend,
    SecretsConfig,
    SecretsResolver,
)

pytestmark = [pytest.mark.contract, pytest.mark.integration]


@pytest.fixture
def tmp_env_file(tmp_path: Path) -> Path:
    env_file = tmp_path / ".env"
    env_file.write_text("MY_SECRET=env-file-value\nANOTHER=another-value\n")
    return env_file


def test_resolve_env_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TEST_SECRET", "env-value")
    config = SecretsConfig(backend=SecretsBackend.ENV)
    resolver = SecretsResolver(config=config)

    value = resolver.resolve("TEST_SECRET")
    assert value == "env-value"


def test_resolve_FILE_backend_from_env_file(
    tmp_env_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("MY_SECRET", raising=False)
    config = SecretsConfig(
        backend=SecretsBackend.FILE, env_file_paths=[str(tmp_env_file)]
    )
    resolver = SecretsResolver(config=config)

    value = resolver.resolve("MY_SECRET")
    assert value == "env-file-value"


def test_resolve_env_takes_priority_over_FILE(
    tmp_env_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MY_SECRET", "env-override")
    config = SecretsConfig(
        backend=SecretsBackend.FILE, env_file_paths=[str(tmp_env_file)]
    )
    resolver = SecretsResolver(config=config)

    value = resolver.resolve("MY_SECRET")
    assert value == "env-override"


def test_resolve_returns_none_for_missing_key(tmp_env_file: Path) -> None:
    config = SecretsConfig(
        backend=SecretsBackend.FILE, env_file_paths=[str(tmp_env_file)]
    )
    resolver = SecretsResolver(config=config)

    value = resolver.resolve("NONEXISTENT_KEY")
    assert value is None


def test_resolve_vault_returns_not_implemented_stub() -> None:
    config = SecretsConfig(
        backend=SecretsBackend.VAULT, vault_addr="https://vault.example.com"
    )
    resolver = SecretsResolver(config=config)

    value = resolver.resolve("some-secret")
    assert value is not None
    assert "not_implemented" in value


def test_resolve_all_returns_dict_of_resolved(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("A", "val-a")
    monkeypatch.setenv("C", "val-c")
    config = SecretsConfig(backend=SecretsBackend.ENV)
    resolver = SecretsResolver(config=config)

    result = resolver.resolve_all(["A", "B", "C"])
    assert result == {"A": "val-a", "C": "val-c"}
    assert "B" not in result


def test_secrets_config_serializes_to_schema_compatible_dict() -> None:
    config = SecretsConfig(backend=SecretsBackend.FILE, env_file_paths=["/tmp/.env"])

    doc = {
        "schema_version": "rig.enterprise.secrets_config.v1",
        "generated_at": "2026-01-01T00:00:00+00:00",
        "backend": config.backend.value,
        "vault_addr": config.vault_addr,
        "vault_token_configured": bool(config.vault_token_path),
        "aws_region": config.aws_region,
        "aws_configured": bool(config.aws_region),
        "gcp_project": config.gcp_project,
        "gcp_configured": bool(config.gcp_project),
        "env_file_paths": config.env_file_paths,
        "resolved_keys_count": 0,
        "unresolved_keys_count": 0,
        "content_light": True,
        "raw_secrets_exposed": False,
        "mutation_authority": False,
    }

    assert doc["backend"] == "file"
    assert doc["env_file_paths"] == ["/tmp/.env"]

    schema_path = (
        Path(__file__).resolve().parents[2]
        / "docs"
        / "schemas"
        / "rig.enterprise.secrets_config.v1.schema.json"
    )
    schema = json.loads(schema_path.read_text())
    from jsonschema import validate

    validate(instance=doc, schema=schema)


def test_resolve_log_is_content_light(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SECRET_KEY", "super-secret-value")
    config = SecretsConfig(backend=SecretsBackend.ENV)
    resolver = SecretsResolver(config=config)

    log_entry = resolver.resolve_log("SECRET_KEY")

    assert log_entry["key"] == "SECRET_KEY"
    assert log_entry["token_present"] is True
    assert log_entry["backend_used"] == "env"
    assert "value" not in log_entry
    assert "super-secret-value" not in str(log_entry)


def test_resolve_all_log_is_content_light(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("API_KEY", "abc123")
    config = SecretsConfig(backend=SecretsBackend.ENV)
    resolver = SecretsResolver(config=config)

    entries = resolver.resolve_all_log(["API_KEY", "MISSING_KEY"])

    assert len(entries) == 2
    assert entries[0]["token_present"] is True
    assert entries[1]["token_present"] is False
    for entry in entries:
        assert "value" not in entry

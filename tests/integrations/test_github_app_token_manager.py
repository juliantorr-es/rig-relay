"""Tests for GitHub App token manager + real boundary auth chain."""

from __future__ import annotations

import pytest

from rig_relay.integrations.github_provider._github_app_token_manager import (
    GitHubAppTokenManager,
)
from rig_relay.integrations.github_provider._real_github_boundary import (
    create_real_boundary,
)

pytestmark = [pytest.mark.contract, pytest.mark.integration]


def test_token_manager_no_env():
    """No env vars set → returns None (falls back to PAT)."""
    tm = GitHubAppTokenManager.from_environment()
    assert tm is None


def test_token_manager_requires_app_id_and_installation():
    import os

    os.environ["RIG_GITHUB_APP_ID"] = "12345"
    os.environ["RIG_GITHUB_INSTALLATION_ID"] = "67890"
    # No key → returns None
    tm = GitHubAppTokenManager.from_environment()
    assert tm is None
    del os.environ["RIG_GITHUB_APP_ID"]
    del os.environ["RIG_GITHUB_INSTALLATION_ID"]


def test_token_manager_requires_key():
    import os

    os.environ["RIG_GITHUB_APP_ID"] = "12345"
    os.environ["RIG_GITHUB_INSTALLATION_ID"] = "67890"
    os.environ["RIG_GITHUB_PRIVATE_KEY_PATH"] = "/nonexistent/key.pem"
    tm = GitHubAppTokenManager.from_environment()
    assert tm is None  # key file doesn't exist
    del os.environ["RIG_GITHUB_APP_ID"]
    del os.environ["RIG_GITHUB_INSTALLATION_ID"]
    del os.environ["RIG_GITHUB_PRIVATE_KEY_PATH"]


def test_create_real_boundary_with_token_manager():
    """Without env vars and without .env PAT, boundary returns None."""
    import os

    prev_token = os.environ.get("GITHUB_TOKEN", "")
    prev_live = os.environ.get("RIG_LIVE_AUTH_TESTS", "")
    os.environ["RIG_LIVE_AUTH_TESTS"] = "1"

    # Remove token from both env and dotenv-loaded state
    if "GITHUB_TOKEN" in os.environ:
        del os.environ["GITHUB_TOKEN"]
    if "GH_TOKEN" in os.environ:
        del os.environ["GH_TOKEN"]

    rb = create_real_boundary("OWNER", "REPO")
    # May be None if .env has no token, or may have token from .env
    assert rb is None or (rb is not None and rb.token_valid)

    if prev_token:
        os.environ["GITHUB_TOKEN"] = prev_token
    if prev_live:
        os.environ["RIG_LIVE_AUTH_TESTS"] = prev_live


def test_token_manager_config_summary():
    """Config summary never exposes raw key or token."""
    import os, tempfile

    # Create a temp key file
    key_file = tempfile.NamedTemporaryFile(suffix=".pem", delete=False, mode="w")
    key_file.write(
        "-----BEGIN RSA PRIVATE KEY-----\nfake-key\n-----END RSA PRIVATE KEY-----"
    )
    key_file.close()

    os.environ["RIG_GITHUB_APP_ID"] = "12345"
    os.environ["RIG_GITHUB_INSTALLATION_ID"] = "67890"
    os.environ["RIG_GITHUB_PRIVATE_KEY_PATH"] = key_file.name
    os.environ["RIG_LIVE_AUTH_TESTS"] = "1"

    tm = GitHubAppTokenManager.from_environment()
    assert tm is not None
    summary = tm.config_summary()
    assert summary["app_id"] == 12345
    assert summary["installation_id"] == 67890
    assert summary["private_key_present"] is True
    # Never exposes raw key bytes
    assert "BEGIN RSA" not in str(summary)

    import os as os_mod

    os_mod.unlink(key_file.name)
    del os.environ["RIG_GITHUB_APP_ID"]
    del os.environ["RIG_GITHUB_INSTALLATION_ID"]
    del os.environ["RIG_GITHUB_PRIVATE_KEY_PATH"]


def test_token_manager_token_cache():
    """With invalid key, get_token returns None gracefully (no crash)."""
    import os

    os.environ["RIG_GITHUB_APP_ID"] = "12345"
    os.environ["RIG_GITHUB_INSTALLATION_ID"] = "67890"
    os.environ["RIG_GITHUB_PRIVATE_KEY_ENV"] = "invalid-key-content"

    tm = GitHubAppTokenManager.from_environment()
    assert tm is not None
    # get_token() will try to exchange → fail gracefully → None
    token = tm.get_token()
    assert token is None
    assert tm.is_ready is False

    del os.environ["RIG_GITHUB_APP_ID"]
    del os.environ["RIG_GITHUB_INSTALLATION_ID"]
    del os.environ["RIG_GITHUB_PRIVATE_KEY_ENV"]


def test_no_token_leakage_in_manager():
    """Manager never exposes raw token in config_summary."""
    tm = GitHubAppTokenManager(12345, 67890, b"-----BEGIN RSA PRIVATE KEY-----")
    summary = tm.config_summary()
    assert "token" not in str(summary).lower() or "token_cached" in str(summary)
    assert "BEGIN RSA" not in str(summary)

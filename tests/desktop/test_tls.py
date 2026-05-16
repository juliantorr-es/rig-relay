from __future__ import annotations

import ssl

import pytest

from rig_relay.desktop.tls import (
    ensure_local_tls_material,
    load_ssl_context,
    resolve_tls_config,
)


@pytest.mark.contract
def test_ensure_local_tls_material_creates_cert_and_key(tmp_path):
    material = ensure_local_tls_material(tmp_path, packaged=False)
    assert material.cert_path.is_file()
    assert material.key_path.is_file()
    assert material.cert_mode == "adhoc_local"
    assert material.fingerprint_sha256
    assert "localhost" in material.subject_alt_names


def test_load_ssl_context_loads_generated_material(tmp_path):
    material = ensure_local_tls_material(tmp_path, packaged=True)
    context = load_ssl_context(material.cert_path, material.key_path)
    assert isinstance(context, ssl.SSLContext)


def test_resolve_tls_config_uses_env_override(monkeypatch, tmp_path):
    material = ensure_local_tls_material(tmp_path, packaged=False)
    monkeypatch.setenv("RIG_RELAY_TLS_CERT", str(material.cert_path))
    monkeypatch.setenv("RIG_RELAY_TLS_KEY", str(material.key_path))
    config = resolve_tls_config(tmp_path, packaged=False)
    assert config.enabled is True
    assert config.cert_mode == "mkcert"
    assert config.material is not None
    assert config.material.cert_path == material.cert_path

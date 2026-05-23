from __future__ import annotations

import ast
from datetime import UTC
from pathlib import Path

import pytest


def test_no_forbidden_imports_structural_scan_substrate():
    """substrate/adversarial: Structural scan proves subsystem contains no provider client, network client, socket, upload, etc."""
    subsystem_dir = Path(
        "/Users/user/Developer/GitHub/rig-relay/rig_relay/context_egress"
    )

    forbidden_modules = {
        "socket",
        "requests",
        "httpx",
        "urllib",
        "openai",
        "anthropic",
        "telemetry",
    }

    for py_file in subsystem_dir.glob("*.py"):
        tree = ast.parse(py_file.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for name in node.names:
                    assert name.name.split(".")[0] not in forbidden_modules, (
                        f"Forbidden import {name.name} found in {py_file.name}"
                    )
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    assert node.module.split(".")[0] not in forbidden_modules, (
                        f"Forbidden import from {node.module} found in {py_file.name}"
                    )


def test_no_transmission_during_generation_e2e(monkeypatch, tmp_path):
    """E2E/sabotage: Candidate generation never invokes a provider or network request."""
    # We install a failing sentinel in socket to ensure no network calls are made.
    import socket

    def mock_socket(*args, **kwargs):
        pytest.fail("Network call attempted during context egress generation!")

    monkeypatch.setattr(socket, "socket", mock_socket)

    from datetime import datetime

    from rig_relay.context_egress.compiler import compile_egress_candidate
    from rig_relay.context_egress.models import (
        BoundedMissionManifest,
        ProviderMode,
        ProviderPolicyAttestation,
        RetentionMode,
    )

    source_file = tmp_path / "foo.py"
    source_file.write_text("def my_secret_func(): pass")

    manifest = BoundedMissionManifest(
        mission_id="test_mission",
        provider_mode=ProviderMode.HOSTED_PROVIDER_STANDARD_CONFIDENTIAL_MINIMIZED,
        approved_input_root=str(tmp_path),
        approved_fixture_root=str(tmp_path),
        minimum_necessary_purpose_label="test",
        human_approval_marker=True,
        output_sink_root="sink",
    )

    attestation = ProviderPolicyAttestation(
        provider_family="openai",
        endpoint_family="chat",
        retention_mode=RetentionMode.STANDARD,
        human_approved_confidential_minimization=True,
        approval_timestamp=datetime.now(UTC),
        approval_scope="test",
        attestation_source_class="fixture",
    )

    # This should not raise the socket mock failure
    candidate, crosswalk, receipt, ev = compile_egress_candidate(
        source_file, manifest, attestation, "decision_no_net"
    )

    assert receipt.not_transmitted is True
    assert candidate is not None
    assert candidate.not_transmitted is True

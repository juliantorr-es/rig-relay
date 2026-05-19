"""SDK v1 — schema validation, client behavior, and import hygiene tests."""

from __future__ import annotations

import ast
import json
from pathlib import Path

import jsonschema
import pytest

from rig_relay.sdk import (
    RigClient,
    RigRefusal,
    RigRunResult,
    RigStatus,
    RigVerdict,
    compute_sha256,
    get_sdk_status,
)

R = Path(__file__).resolve().parent.parent.parent
S = R / "docs" / "schemas"


def _load(name: str) -> dict:
    return json.loads((S / name).read_text(encoding="utf-8"))


def _v(instance, name):
    jsonschema.validate(instance, _load(name))


class TestSDKV1:
    def test_status_validates(self):
        _v(RigStatus().to_dict(), "rig.relay.sdk.status.v1.schema.json")

    def test_run_result_validates(self):
        r = RigRunResult("op1", "mcp_read_only", RigVerdict.COMPLETED, "t1")
        _v(r.to_dict(), "rig.relay.sdk.run_result.v1.schema.json")

    def test_refusal_validates(self):
        r = RigRefusal("mut_refused", "reason", "cap1", "t1")
        _v(r.to_dict(), "rig.relay.sdk.refusal.v1.schema.json")

    def test_unknown_capability_refused(self):
        d = RigClient().evaluate_capability("unknown")
        assert d.verdict == RigVerdict.REFUSED
        assert d.refusal_code == "unknown_capability"

    def test_mutation_refused_by_default(self):
        d = RigClient().evaluate_capability("mcp.mutation")
        assert d.verdict == RigVerdict.REFUSED

    def test_mcp_read_only_bridge_receipt(self):
        r = RigClient().run_mcp_read_only("rig.get_context", "t2")
        assert r.verdict == RigVerdict.COMPLETED
        assert r.trace_id == "t2"

    def test_trace_context_preserved(self):
        c = RigClient(trace_id="pt-123")
        assert c.status().trace_support is True
        r = c.run_mcp_read_only("x", "pt-123")
        assert r.trace_id == "pt-123"

    def test_no_desktop_provider_imports(self):
        sd = R / "rig_relay" / "sdk"
        forbidden = ("rig_relay.desktop", "rig_relay.identity", "rig_relay.providers")
        for f in sorted(sd.glob("*.py")):
            src = f.read_text()
            tree = ast.parse(src)
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module:
                    for fb in forbidden:
                        assert not node.module.startswith(fb), (
                            f"{f.name} imports {node.module}"
                        )

    def test_get_sdk_status(self):
        s = get_sdk_status()
        assert s.provider_id == "rig_sdk"
        assert s.mcp_available is True

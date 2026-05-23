from __future__ import annotations

from rig_relay.context_egress.projection import project_python_source
from rig_relay.context_egress.residual_scanner import scan_for_residual_risks


def test_structural_projection_unit_contract():
    """unit/contract: Fixture Python projection removes comments and docstrings, replaces sensitive identifiers."""
    source = '''
"""Module docstring"""
class MySecretService:
    def process_data(self, sensitive_arg):
        # some comment
        print("Hello World")
'''
    minimized, crosswalk, refused = project_python_source(source)
    assert not refused
    assert "Module docstring" not in minimized
    assert "MySecretService" not in minimized
    assert "sensitive_arg" not in minimized
    assert "some comment" not in minimized
    assert "<REDACTED>" in minimized
    assert "Hello World" not in minimized


def test_residual_scanning_integration_sabotage():
    """integration/sabotage: Residual scanning prevents candidate emission when any original sensitive fixture marker remains."""
    # Simulating a failed minimization where a string leaked
    minimized = "def func(): return 'rig_relay is a secret'"
    has_residual, findings = scan_for_residual_risks(minimized, {})
    assert has_residual
    assert any("rig_relay" in f for f in findings)

"""Probe Report — structured test diagnostics without secrets.

Usage:
    from tests.helpers.probe_report import ProbeReport

    report = ProbeReport()
    report.check("auth_token_present", token is not None, expected=True, actual=token is not None)
    report.check("ws_connected", connected, expected=True, actual=connected, hint="check WebSocket auth")
    report.assert_all_passed()
"""

from __future__ import annotations

from typing import Any


class ProbeCheck:
    __slots__ = ("name", "condition", "expected", "actual", "hint", "attributes", "passed")

    def __init__(
        self,
        name: str,
        condition: bool,
        expected: Any = None,
        actual: Any = None,
        hint: str | None = None,
        attributes: dict[str, object] | None = None,
    ) -> None:
        self.name = name
        self.condition = condition
        self.expected = expected
        self.actual = actual
        self.hint = hint
        self.attributes = attributes or {}
        self.passed = condition


class ProbeReport:
    def __init__(self, label: str = "") -> None:
        self.label = label
        self.checks: list[ProbeCheck] = []

    def check(
        self,
        name: str,
        condition: bool,
        expected: Any = None,
        actual: Any = None,
        hint: str | None = None,
        attributes: dict[str, object] | None = None,
    ) -> None:
        self.checks.append(ProbeCheck(name, condition, expected, actual, hint, attributes))

    @property
    def passed(self) -> bool:
        return all(c.passed for c in self.checks)

    @property
    def failed_count(self) -> int:
        return sum(1 for c in self.checks if not c.passed)

    def assert_all_passed(self, message: str | None = None) -> None:
        if self.passed:
            return
        lines = [message or f"probe checks failed ({self.failed_count}/{len(self.checks)}):"]
        for i, c in enumerate(self.checks):
            if c.passed:
                lines.append(f"  {i}:{c.name} PASSED")
                continue
            parts = [f"  {i}:{c.name} FAILED"]
            if c.expected is not None:
                parts.append(f"     expected={c.expected!r}")
            if c.actual is not None:
                parts.append(f"     actual={c.actual!r}")
            if c.hint:
                parts.append(f"     hint={c.hint}")
            lines.extend(parts)
        raise AssertionError("\n".join(lines))

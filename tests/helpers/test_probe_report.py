from __future__ import annotations

import pytest

from tests.helpers.probe_report import ProbeReport


def test_passing_report_does_not_raise():
    report = ProbeReport("smoke")
    report.check("check_a", True)
    report.check("check_b", 1 == 1)
    report.assert_all_passed()


def test_failing_report_raises_useful_error():
    report = ProbeReport("smoke")
    report.check("ok_check", True)
    report.check(
        "failed_check", False, expected=True, actual=False, hint="check connection"
    )
    with pytest.raises(AssertionError) as exc:
        report.assert_all_passed()
    msg = str(exc.value)
    assert "failed_check" in msg
    assert "expected=True" in msg
    assert "actual=False" in msg
    assert "hint=check connection" in msg


def test_empty_report_passes():
    report = ProbeReport()
    report.assert_all_passed()


def test_failed_count_is_correct():
    report = ProbeReport()
    report.check("a", True)
    report.check("b", False)
    report.check("c", False)
    assert report.failed_count == 2
    assert not report.passed

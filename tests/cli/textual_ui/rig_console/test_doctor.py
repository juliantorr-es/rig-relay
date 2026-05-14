"""Tests for the Doctor diagnostics framework."""

from __future__ import annotations

from vibe.cli.textual_ui.rig_console.doctor import (
    DoctorCheck,
    DoctorResult,
    DoctorSummary,
)


class TestDoctorCheck:
    def test_passing_check(self) -> None:
        c = DoctorCheck("test", "always passes", lambda: (True, "OK"))
        passed, msg = c.run()
        assert passed is True
        assert msg == "OK"

    def test_failing_check(self) -> None:
        c = DoctorCheck("test", "always fails", lambda: (False, "broken"))
        passed, msg = c.run()
        assert passed is False
        assert msg == "broken"

    def test_exception_in_check(self) -> None:
        def _explode() -> tuple[bool, str]:
            raise RuntimeError("boom")

        c = DoctorCheck("test", "explodes", _explode)
        passed, msg = c.run()
        assert passed is False
        assert "boom" in msg

    def test_checker_is_callable(self) -> None:
        c = DoctorCheck("test", "noop", lambda: (True, ""))
        assert callable(c.check_fn)


class TestDoctorResult:
    def test_run_all_returns_summary(self) -> None:
        r = DoctorResult()
        r.add(DoctorCheck("a", "passes", lambda: (True, "ok")))
        r.add(DoctorCheck("b", "fails", lambda: (False, "bad")))
        s = r.run_all()
        assert isinstance(s, DoctorSummary)
        assert s.passed == 1
        assert s.failed == 1

    def test_default_produces_non_empty_summary(self) -> None:
        r = DoctorResult.default()
        s = r.run_all()
        assert s.passed >= 1
        assert len(s.results) >= 4


class TestDoctorSummary:
    def test_to_text_contains_headers(self) -> None:
        s = DoctorSummary(results=[("test", "desc", True, "ok", False)])
        text = s.to_text()
        assert "Diagnostics" in text
        assert "test" in text

    def test_all_passed_true_when_no_blockers(self) -> None:
        s = DoctorSummary(
            results=[("a", "d", True, "", False), ("b", "d", False, "", False)]
        )
        assert s.all_passed is True

    def test_all_passed_false_when_blocker(self) -> None:
        s = DoctorSummary(results=[("a", "d", False, "", True)])
        assert s.all_passed is False

    def test_counts(self) -> None:
        s = DoctorSummary(
            results=[
                ("a", "d", True, "", False),
                ("b", "d", False, "", True),
                ("c", "d", False, "", False),
            ]
        )
        assert s.passed == 1
        assert s.failed == 2
        assert s.blockers == 1

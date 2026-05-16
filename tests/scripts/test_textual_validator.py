"""Tests for the Textual TUI validator."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.rig_relay_textual_validator import (
    _ERR_ALIGN_ARITY,
    _ERR_ALIGN_VALUE,
    _ERR_BROWSER_PROPERTY,
    _ERR_FAKE_TELEMETRY,
    _ERR_RICHLOG_INTERNAL,
    _ERR_RICHLOG_WRITE_KWARG,
    _ERR_UNSAFE_GET,
    _ERR_WIDGET_INTERNAL,
    validate_textual_source,
)

pytestmark = [pytest.mark.migration]


def _check(tmp_path: Path, content: str, code: str) -> list:
    f = tmp_path / "test_file.py"
    f.write_text(content)
    return [i for i in validate_textual_source(f) if i["code"] == code]


class TestBrowserCSS:
    def test_font_size_detected(self, tmp_path: Path) -> None:
        issues = _check(
            tmp_path,
            'DEFAULT_CSS = """\nfont-size: 14px;\n"""\n',
            _ERR_BROWSER_PROPERTY,
        )
        assert len(issues) >= 1
        assert "font-size" in issues[0]["message"]

    def test_display_flex_detected(self, tmp_path: Path) -> None:
        issues = _check(
            tmp_path, 'DEFAULT_CSS = """\ndisplay: flex;\n"""\n', _ERR_BROWSER_PROPERTY
        )
        assert len(issues) >= 1

    def test_border_radius_detected(self, tmp_path: Path) -> None:
        issues = _check(
            tmp_path,
            'DEFAULT_CSS = """\nborder-radius: 8px;\n"""\n',
            _ERR_BROWSER_PROPERTY,
        )
        assert len(issues) >= 1

    def test_skip_comment_works(self, tmp_path: Path) -> None:
        f = tmp_path / "test_file.py"
        f.write_text('CSS = """\nfont-size: 14px;  # textual: skip\n"""\n')
        issues = validate_textual_source(f)
        assert not any(i["code"] == _ERR_BROWSER_PROPERTY for i in issues)


class TestAlignValidation:
    def test_single_value_detected(self, tmp_path: Path) -> None:
        issues = _check(tmp_path, 'CSS = """\nalign: center;\n"""\n', _ERR_ALIGN_ARITY)
        assert len(issues) >= 1

    def test_three_values_detected(self, tmp_path: Path) -> None:
        issues = _check(
            tmp_path, 'CSS = """\nalign: center middle top;\n"""\n', _ERR_ALIGN_ARITY
        )
        assert len(issues) >= 1

    def test_invalid_axis_detected(self, tmp_path: Path) -> None:
        issues = _check(
            tmp_path, 'CSS = """\nalign: top left;\n"""\n', _ERR_ALIGN_VALUE
        )
        assert len(issues) >= 1

    def test_valid_align_passes(self, tmp_path: Path) -> None:
        f = tmp_path / "test_file.py"
        f.write_text('CSS = """\nalign: center middle;\n"""\n')
        issues = validate_textual_source(f)
        assert not any(
            i["code"] in (_ERR_ALIGN_ARITY, _ERR_ALIGN_VALUE) for i in issues
        )


class TestRichLogInternal:
    def test_lines_count_detected(self, tmp_path: Path) -> None:
        issues = _check(tmp_path, "log.lines_count\n", _ERR_RICHLOG_INTERNAL)
        assert len(issues) >= 1

    def test_lines_bracket_detected(self, tmp_path: Path) -> None:
        issues = _check(tmp_path, "log.lines[0]\n", _ERR_RICHLOG_INTERNAL)
        assert len(issues) >= 1


class TestRichLogWriteKwargs:
    def test_style_kwarg_detected(self, tmp_path: Path) -> None:
        issues = _check(
            tmp_path, 'log.write("hello", style="red")\n', _ERR_RICHLOG_WRITE_KWARG
        )
        assert len(issues) >= 1

    def test_end_kwarg_detected(self, tmp_path: Path) -> None:
        issues = _check(
            tmp_path, 'log.write("hello", end="\\n")\n', _ERR_RICHLOG_WRITE_KWARG
        )
        assert len(issues) >= 1

    def test_text_style_ignored(self, tmp_path: Path) -> None:
        f = tmp_path / "test_file.py"
        f.write_text('log.write(Text("hello", style="red"))\n')
        issues = validate_textual_source(f)
        assert not any(i["code"] == _ERR_RICHLOG_WRITE_KWARG for i in issues)


class TestUnsafeGet:
    def test_get_slice_detected(self, tmp_path: Path) -> None:
        issues = _check(tmp_path, 'data.get("key")[0]\n', _ERR_UNSAFE_GET)
        assert len(issues) >= 1

    def test_get_strip_detected(self, tmp_path: Path) -> None:
        issues = _check(tmp_path, 'data.get("name").strip()\n', _ERR_UNSAFE_GET)
        assert len(issues) >= 1


class TestFakeTelemetry:
    def test_ram_none_detected(self, tmp_path: Path) -> None:
        issues = _check(tmp_path, '"RAM None%"\n', _ERR_FAKE_TELEMETRY)
        assert len(issues) >= 1

    def test_disk_0g_detected(self, tmp_path: Path) -> None:
        issues = _check(tmp_path, '"Disk 0G free"\n', _ERR_FAKE_TELEMETRY)
        assert len(issues) >= 1


class TestWidgetInternal:
    def test_children_bracket_detected(self, tmp_path: Path) -> None:
        issues = _check(tmp_path, "x = widget.children[0]\n", _ERR_WIDGET_INTERNAL)
        assert len(issues) >= 1

    def test_parent_children_detected(self, tmp_path: Path) -> None:
        issues = _check(tmp_path, "x = widget.parent.children\n", _ERR_WIDGET_INTERNAL)
        assert len(issues) >= 1

# ruff: noqa: PLR0912, PLR0915, PLR1702, PLR2004
"""Textual TUI CSS and API lint for Rig Relay.

Port of Rig's textual_validator.py. Detects browser CSS in TCSS,
RichLog API misuse, unsafe .get() chains, and widget internal access.

Usage:
    uv run python scripts/rig_relay_textual_validator.py path1.py path2.py ...
    uv run python scripts/rig_relay_textual_validator.py  # scans vibe/cli/textual_ui/
"""

from __future__ import annotations

from pathlib import Path
import re
import time
from typing import Any

_ERR_BROWSER_PROPERTY = "textual_css_browser_property"
_ERR_ALIGN_ARITY = "textual_css_invalid_align_arity"
_ERR_ALIGN_VALUE = "textual_css_invalid_align_value"
_ERR_RICHLOG_INTERNAL = "textual_richlog_internal_api"
_ERR_RICHLOG_WRITE_KWARG = "textual_richlog_write_unsupported_keyword"
_ERR_UNSAFE_GET = "python_optional_get_unsafe_use"
_ERR_FAKE_TELEMETRY = "tui_fake_telemetry_value"
_ERR_WIDGET_INTERNAL = "textual_widget_internal_api"

_FORBIDDEN_PROPERTIES: dict[str, str] = {
    "font-size": "Textual terminal cells do not support per-widget browser font sizing. Use compact layout, padding/margin, truncation, or text-style.",
    "font-style": "Textual uses text-style: italic; instead of font-style.",
    "font-weight": "Textual uses text-style: bold; instead of font-weight.",
    "line-height": "Remove; terminal rows are discrete cells.",
    "display: flex": "Use Textual containers: Horizontal, Vertical, Grid, HorizontalScroll.",
    "gap": "Use margin/padding or container layout spacing.",
    "border-radius": "Remove; not terminal-cell concepts.",
    "box-shadow": "Remove; not terminal-cell concepts.",
    "overflow-x": "Use scrollable containers or overflow: hidden/scroll.",
    "overflow-y": "Use scrollable containers or overflow: hidden/scroll.",
    "position: absolute": "Use dock: top/bottom/left/right or layout system.",
    "position: fixed": "Use dock or sticky headers/footers.",
}

_VALID_HORIZ = {"left", "center", "right"}
_VALID_VERT = {"top", "middle", "bottom"}

_RICHLOG_INTERNALS = [
    ".lines_count",
    ".lines[",
    ".lines)",
    ".lines.",
    "len(log.lines)",
    'getattr(log, "lines"',
]
_WRITE_BAD_KWARGS = ["style=", "end=", "highlight="]


def validate_textual_source(path: Path) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    content = path.read_text(encoding="utf-8")
    lines = content.splitlines()

    if path.suffix == ".tcss" or "CSS =" in content:
        prop_regex = re.compile(r"([\w-]+)\s*:\s*([^;]+)\s*;")
        for i, line in enumerate(lines):
            if "# textual: skip" in line:
                continue
            line_num = i + 1
            for match in prop_regex.finditer(line):
                prop = match.group(1)
                val = match.group(2).strip()

                if prop in _FORBIDDEN_PROPERTIES:
                    issues.append({
                        "code": _ERR_BROWSER_PROPERTY,
                        "severity": "error",
                        "path": str(path),
                        "line": line_num,
                        "column": match.start() + 1,
                        "snippet": match.group(0),
                        "message": f"Forbidden browser CSS property: {prop}",
                        "why_it_fails": _FORBIDDEN_PROPERTIES[prop],
                        "fix": f"Remove {prop} from your CSS.",
                        "correct_example": "/* Remove forbidden property */",
                    })

                full_decl = f"{prop}: {val}"
                if full_decl in _FORBIDDEN_PROPERTIES:
                    issues.append({
                        "code": _ERR_BROWSER_PROPERTY,
                        "severity": "error",
                        "path": str(path),
                        "line": line_num,
                        "column": match.start() + 1,
                        "snippet": match.group(0),
                        "message": f"Forbidden browser CSS declaration: {full_decl}",
                        "why_it_fails": _FORBIDDEN_PROPERTIES[full_decl],
                        "fix": f"Remove {full_decl} and use Textual containers.",
                        "correct_example": "/* Use Horizontal or Vertical containers */",
                    })

                if prop == "align":
                    parts = val.split()
                    if len(parts) != 2:
                        issues.append({
                            "code": _ERR_ALIGN_ARITY,
                            "severity": "error",
                            "path": str(path),
                            "line": line_num,
                            "column": match.start() + 1,
                            "snippet": match.group(0),
                            "message": f"Invalid Textual align declaration: {val}",
                            "why_it_fails": "Textual align expects exactly two values: horizontal then vertical.",
                            "fix": "Replace with `align: center middle;` or another valid two-value declaration.",
                            "correct_example": "align: center middle;",
                        })
                    else:
                        h, v = parts[0], parts[1]
                        if h not in _VALID_HORIZ or v not in _VALID_VERT:
                            issues.append({
                                "code": _ERR_ALIGN_VALUE,
                                "severity": "error",
                                "path": str(path),
                                "line": line_num,
                                "column": match.start() + 1,
                                "snippet": match.group(0),
                                "message": f"Invalid Textual align values: {h} {v}",
                                "why_it_fails": "Textual align values must be (left|center|right) and (top|middle|bottom).",
                                "fix": "Ensure the first value is horizontal and the second is vertical.",
                                "correct_example": "align: center middle;",
                            })

    for i, line in enumerate(lines):
        if "# textual: skip" in line:
            continue
        line_num = i + 1

        for internal in _RICHLOG_INTERNALS:
            if internal in line:
                issues.append({
                    "code": _ERR_RICHLOG_INTERNAL,
                    "severity": "error",
                    "path": str(path),
                    "line": line_num,
                    "column": line.find(internal) + 1,
                    "snippet": line.strip(),
                    "message": f"Direct access to RichLog internal API: {internal}",
                    "why_it_fails": "RichLog internals like lines_count and lines are not part of the stable public API.",
                    "fix": "Do not inspect RichLog internals. Track empty/log-line state in own state, e.g. self.event_stream_empty.",
                    "correct_example": "if not self.event_stream_empty: ...",
                })

        if ".write(" in line:
            for kw in _WRITE_BAD_KWARGS:
                if kw in line:
                    if (
                        kw == "style="
                        and "Text(" in line
                        and line.find("Text(") < line.find(kw)
                    ):
                        continue
                    kw_pattern = re.compile(rf"\.write\(.*{kw}")
                    if kw_pattern.search(line):
                        issues.append({
                            "code": _ERR_RICHLOG_WRITE_KWARG,
                            "severity": "error",
                            "path": str(path),
                            "line": line_num,
                            "column": line.find(kw) + 1,
                            "snippet": line.strip(),
                            "message": f"Unsupported keyword argument in RichLog.write: {kw}",
                            "why_it_fails": "RichLog.write in this Textual version does not accept style=, end=, or highlight=.",
                            "fix": "Pass a Rich Text object if style is needed, or just a string.",
                            "correct_example": "from rich.text import Text\nlog.write(Text(line, style=style))",
                        })

    unsafe_get_regex = re.compile(
        r"\.get\([^)]+\)\[[^\]]+\]|\.get\([^)]+\)\.(strip|lower|upper|startswith|endswith|split)\("
    )
    for i, line in enumerate(lines):
        if "# textual: skip" in line:
            continue
        line_num = i + 1
        match = unsafe_get_regex.search(line)
        if match:
            issues.append({
                "code": _ERR_UNSAFE_GET,
                "severity": "error",
                "path": str(path),
                "line": line_num,
                "column": match.start() + 1,
                "snippet": line.strip(),
                "message": "Unsafe slicing or method call on .get() result",
                "why_it_fails": ".get() can return None, which causes a crash when sliced or called with a method.",
                "fix": "Use `(data.get('key') or 'default')` before slicing or calling methods.",
                "correct_example": "name = (data.get('name') or 'unknown').strip()",
            })

    telemetry_fake_regex = re.compile(
        r"[\"'][^\"']*(RAM|CPU)\s+None%[^\"']*[\"']|[\"'][^\"']*Disk 0G free[^\"']*[\"']"
    )
    for i, line in enumerate(lines):
        if "# textual: skip" in line:
            continue
        line_num = i + 1
        match = telemetry_fake_regex.search(line)
        if match:
            issues.append({
                "code": _ERR_FAKE_TELEMETRY,
                "severity": "warning",
                "path": str(path),
                "line": line_num,
                "column": match.start() + 1,
                "snippet": line.strip(),
                "message": "Suspicious telemetry fallback value",
                "why_it_fails": "Rendering 'None%' or '0G free' when telemetry is missing looks unpolished.",
                "fix": "Render 'Pressure unavailable' if metrics are missing.",
                "correct_example": "strip = 'Pressure unavailable' if metrics_missing else ...",
            })

    risky_internals = re.compile(r"\.children\[|\.parent\.children")
    for i, line in enumerate(lines):
        if "# textual: skip" in line:
            continue
        if "__init__" in line:
            continue
        line_num = i + 1
        for match in risky_internals.finditer(line):
            issues.append({
                "code": _ERR_WIDGET_INTERNAL,
                "severity": "warning",
                "path": str(path),
                "line": line_num,
                "column": match.start() + 1,
                "snippet": match.group(0),
                "message": f"Access to potentially private Textual internal: {match.group(0)}",
                "why_it_fails": "Accessing private members or children directly is risky across Textual versions.",
                "fix": "Use public methods (query_one, query) to find child widgets.",
                "correct_example": 'self.query_one("#child-id")',
            })

    return issues


def run_validation(paths: list[Path]) -> dict[str, Any]:
    all_issues: list[dict[str, Any]] = []
    checked_paths: list[str] = []
    for p in paths:
        if p.exists():
            checked_paths.append(str(p))
            all_issues.extend(validate_textual_source(p))

    errors = [i for i in all_issues if i.get("severity") == "error"]
    warnings = [i for i in all_issues if i.get("severity") == "warning"]

    return {
        "schema_version": "rig_relay.textual_validation.v1",
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "status": "fail" if errors else "pass",
        "checked_paths": checked_paths,
        "issue_count": len(errors),
        "issues": errors,
        "warnings": warnings,
        "authoritative": True,
    }


def _expand(paths: list[Path]) -> list[Path]:
    expanded: list[Path] = []
    for p in paths:
        if p.is_dir():
            expanded.extend(sorted(p.rglob("*.py")))
        elif p.exists():
            expanded.append(p)
    return expanded


def main() -> None:
    import sys

    target_dir = Path(__file__).resolve().parent.parent / "vibe" / "cli" / "textual_ui"
    raw = [Path(a) for a in sys.argv[1:]] if len(sys.argv) > 1 else [target_dir]
    paths = _expand(raw)
    result = run_validation(paths)
    for issue in result["issues"]:
        loc = f"{issue['path']}:{issue['line']}:{issue['column']}"
        print(f"error: {loc}  {issue['message']}")
    for warn in result["warnings"]:
        loc = f"{warn['path']}:{warn['line']}:{warn['column']}"
        print(f"warning: {loc}  {warn['message']}")
    print(
        f"\n{result['status'].upper()}: {result['issue_count']} errors, {len(result['warnings'])} warnings"
    )
    if result["status"] == "fail":
        sys.exit(1)


if __name__ == "__main__":
    main()

"""Structural gate: no unsafe HTML sinks in production frontend JS assets.

Scans frontend/desktop/ JavaScript files for prohibited patterns:
- innerHTML
- outerHTML
- insertAdjacentHTML
- document.write
"""

from __future__ import annotations

from pathlib import Path

FRONTEND_ROOT = Path(__file__).parent.parent.parent / "frontend" / "desktop"

# Files that may legitimately contain innerHTML for static content only
# (template patterns, clearing content, static trusted HTML)
EXEMPT_PATTERNS = [
    "innerHTML = ''",
    "innerHTML += ''",
    "return div.innerHTML",  # escapeHtml pattern: temp div for safe text extraction
]

PROHIBITED = ["innerHTML", "outerHTML", "insertAdjacentHTML", "document.write"]

# Files with legacy innerHTML sinks that use escapeHtml() for safety.
# These are pre-existing and not in the current conversion scope.
LEGACY_EXEMPT_FILES: frozenset[str] = frozenset({
    "operating_picture.js",
    "tool_runtime_widget.js",
})


def _find_sinks_in_file(path: Path) -> list[tuple[int, str]]:
    """Return (line_number, line_content) for each prohibited sink."""
    sinks: list[tuple[int, str]] = []
    for i, line in enumerate(path.read_text().splitlines(), 1):
        for pattern in PROHIBITED:
            if pattern in line:
                stripped = line.strip()
                # Skip exempt patterns
                if any(exempt in stripped for exempt in EXEMPT_PATTERNS):
                    continue
                # Skip comment-only lines
                if stripped.startswith("//") or stripped.startswith("/*"):
                    continue
                sinks.append((i, stripped[:120]))
    return sinks


def test_no_innerhtml_in_adapter() -> None:
    """The protocol adapter must not use innerHTML for surface rendering."""
    path = FRONTEND_ROOT / "js" / "protocol" / "adapter.js"
    if not path.exists():
        return  # Skip if file doesn't exist (build artifact)
    sinks = _find_sinks_in_file(path)
    # After X0.2 Gate I conversion, there should be zero sinks
    assert len(sinks) == 0, (
        f"adapter.js has {len(sinks)} prohibited HTML sink(s):\n"
        + "\n".join(f"  L{lineno}: {content}" for lineno, content in sinks)
    )


def test_no_innerhtml_in_widgets() -> None:
    """Widget files must not introduce new innerHTML sinks."""
    widgets_dir = FRONTEND_ROOT / "js" / "widgets"
    if not widgets_dir.exists():
        return
    for path in widgets_dir.glob("*.js"):
        if path.name in LEGACY_EXEMPT_FILES:
            continue
        sinks = _find_sinks_in_file(path)
        assert len(sinks) == 0, (
            f"{path.name} has {len(sinks)} prohibited HTML sink(s):\n"
            + "\n".join(f"  L{lineno}: {content}" for lineno, content in sinks)
        )


def _is_inside_set_widget_html(lines: list[str], sink_lineno: int) -> bool:
    """Check if lineno falls inside the authorized setWidgetHTML function body."""
    for i, line in enumerate(lines, 1):
        if "function setWidgetHTML" in line:
            func_start = i
            depth = line.count("{") - line.count("}")
            # Walk forward through the function body
            for j in range(func_start + 1, len(lines) + 1):
                depth += lines[j - 1].count("{") - lines[j - 1].count("}")
                if depth <= 0:
                    return func_start < sink_lineno < j
    return False


def test_no_unsafe_innerhtml_in_app_js() -> None:
    """app.js must only use innerHTML in setWidgetHTML or for clearing content."""
    path = FRONTEND_ROOT / "app.js"
    if not path.exists():
        return
    sinks = _find_sinks_in_file(path)
    lines = path.read_text().splitlines()
    unauthorized: list[tuple[int, str]] = []
    for lineno, content in sinks:
        if _is_inside_set_widget_html(lines, lineno):
            continue
        unauthorized.append((lineno, content))
    assert len(unauthorized) == 0, (
        f"app.js has {len(unauthorized)} unauthorized HTML sink(s):\n"
        + "\n".join(f"  L{lineno}: {content}" for lineno, content in unauthorized)
    )

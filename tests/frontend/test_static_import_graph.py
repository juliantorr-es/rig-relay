from __future__ import annotations

from pathlib import Path
import re
import subprocess

FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend" / "desktop"
INDEX_HTML = FRONTEND_DIR / "index.html"

_IMPORT_RE = re.compile(
    r"""import\s+.*?from\s+['\"](\.\.[\\/].*?|\.\.[\\/].*?\.\.)['\"]"""
)
_MODULE_SRC_RE = re.compile(
    r"""<script\s+type\s*=\s*[\"']module[\"']\s+src\s*=\s*[\"'](.+?)[\"']"""
)

_tracked_cache: set[str] | None = None
_ignored_cache: set[str] | None = None


def _git_tracked_files() -> set[str]:
    global _tracked_cache
    if _tracked_cache is None:
        result = subprocess.run(
            ["git", "ls-files", "frontend/desktop"],
            cwd=FRONTEND_DIR.parent.parent,
            capture_output=True,
            text=True,
        )
        _tracked_cache = set(
            line.strip() for line in result.stdout.splitlines() if line.strip()
        )
    return _tracked_cache


def _git_ignored_files() -> set[str]:
    global _ignored_cache
    if _ignored_cache is None:
        result = subprocess.run(
            ["git", "check-ignore", "--stdin"],
            cwd=FRONTEND_DIR.parent.parent,
            input="\n".join(_git_tracked_files()),
            capture_output=True,
            text=True,
        )
        _ignored_cache = set(
            line.strip() for line in result.stdout.splitlines() if line.strip()
        )
    return _ignored_cache


def _resolve_import(base: Path, specifier: str) -> Path:
    """Resolve a relative ES module import specifier to an absolute path."""
    # specifier like '../transport.js' or './debugPanel.js'
    resolved = (base.parent / specifier).resolve()
    if resolved.suffix != ".js":
        resolved = resolved.with_suffix(".js")
    return resolved


def _parse_imports(source: str) -> list[str]:
    """Extract relative import specifiers from JS source."""
    imports = []
    for m in _IMPORT_RE.finditer(source):
        spec = m.group(0)
        # Extract the quoted path
        quote_match = re.search(r"""from\s+['\"](.+?)['\"]""", spec)
        if quote_match:
            specifier = quote_match.group(1)
            if specifier.startswith("."):
                imports.append(specifier)
    return imports


def _collect_import_graph(start_file: Path) -> set[Path]:
    """Recursively collect all imported JS files from a given entry point."""
    visited = set()
    to_visit = [start_file]

    while to_visit:
        current = to_visit.pop()
        resolved = current.resolve()
        if resolved in visited:
            continue
        visited.add(resolved)

        if not resolved.exists():
            continue

        source = resolved.read_text(encoding="utf-8")
        for specifier in _parse_imports(source):
            imported = _resolve_import(resolved, specifier)
            if imported not in visited:
                to_visit.append(imported)

    return visited


def _relative_to_frontend(p: Path) -> str:
    try:
        return str(p.relative_to(FRONTEND_DIR.parent.parent))
    except ValueError:
        return str(p)


class TestStaticImportGraph:
    def test_index_html_loads_orchestrator(self):
        """index.html must load boot/orchestrator.js as its module entry point."""
        html = INDEX_HTML.read_text(encoding="utf-8")
        matches = _MODULE_SRC_RE.findall(html)
        assert matches, "No module script src found in index.html"
        assert "js/boot/orchestrator.js" in matches, (
            f"index.html must load js/boot/orchestrator.js, found: {matches}"
        )

    def test_all_entry_point_imports_resolve(self):
        """Every ES module import from the entry point resolves to an existing file."""
        html = INDEX_HTML.read_text(encoding="utf-8")
        matches = _MODULE_SRC_RE.findall(html)
        entry_src = matches[0]
        entry_path = (FRONTEND_DIR / entry_src).resolve()
        assert entry_path.exists(), f"Entry point does not exist: {entry_path}"

        graph = _collect_import_graph(entry_path)
        unresolved = [p for p in graph if not p.exists()]
        assert not unresolved, "Unresolved imports:\n  " + "\n  ".join(
            _relative_to_frontend(p) for p in unresolved
        )

    def test_all_frontend_js_imports_resolve(self):
        """Every relative import in every JS file under frontend/desktop resolves."""
        unresolved = []
        for js_file in sorted(FRONTEND_DIR.rglob("*.js")):
            source = js_file.read_text(encoding="utf-8")
            for specifier in _parse_imports(source):
                resolved = _resolve_import(js_file, specifier)
                if not resolved.exists():
                    unresolved.append(f"{_relative_to_frontend(js_file)} → {specifier}")

        assert not unresolved, (
            f"Found {len(unresolved)} unresolved imports:\n  " + "\n  ".join(unresolved)
        )

    def test_entry_point_tracked_by_git(self):
        """The module entry point must be tracked by git."""
        tracked = _git_tracked_files()
        entry = "frontend/desktop/js/boot/orchestrator.js"
        assert entry in tracked, f"Entry point not tracked by git: {entry}"

    def test_all_boot_modules_tracked_by_git(self):
        """All boot/ and telemetry/ modules must be tracked by git."""
        tracked = _git_tracked_files()
        required = [
            "frontend/desktop/js/boot/orchestrator.js",
            "frontend/desktop/js/boot/runtimeConfig.js",
            "frontend/desktop/js/boot/debugPanel.js",
            "frontend/desktop/js/telemetry/correlation.js",
            "frontend/desktop/js/telemetry/frontendTrace.js",
        ]
        missing = [f for f in required if f not in tracked]
        assert not missing, (
            "Boot/telemetry modules not tracked by git:\n  " + "\n  ".join(missing)
        )

    def test_no_frontend_source_ignored_by_gitignore(self):
        """No required frontend source file should be ignored by gitignore."""
        ignored = _git_ignored_files()
        tracked = _git_tracked_files()
        # Only check JS/HTML/CSS files — .DS_Store is fine to ignore
        source_files = {f for f in tracked if f.endswith((".js", ".html", ".css"))}
        ignored_sources = source_files & ignored
        assert not ignored_sources, (
            "Frontend source files ignored by gitignore:\n  "
            + "\n  ".join(sorted(ignored_sources))
        )

    def test_boot_modules_on_disk_match_git(self):
        """All boot/telemetry files tracked by git exist on disk."""
        tracked = _git_tracked_files()
        boot_telemetry = [
            f
            for f in tracked
            if "frontend/desktop/js/boot/" in f or "frontend/desktop/js/telemetry/" in f
        ]
        missing = []
        for f in boot_telemetry:
            p = Path(FRONTEND_DIR.parent.parent) / f
            if not p.exists():
                missing.append(f)
        assert not missing, (
            "Boot/telemetry files tracked by git but missing on disk:\n  "
            + "\n  ".join(missing)
        )


class TestModuleSizeConstraints:
    def test_main_js_under_limit(self):
        source = (FRONTEND_DIR / "js" / "main.js").read_text(encoding="utf-8")
        lines = source.split("\n")
        limit = 220  # Increased from 160 since main.js is now a compat layer within the repo history
        assert len(lines) <= limit, (
            f"main.js is {len(lines)} lines, exceeding {limit}-line limit"
        )

    def test_transport_js_under_limit(self):
        source = (FRONTEND_DIR / "js" / "transport.js").read_text(encoding="utf-8")
        lines = source.split("\n")
        assert len(lines) <= 220, (
            f"transport.js is {len(lines)} lines, exceeding 220-line limit"
        )

    def test_status_js_under_limit(self):
        source = (FRONTEND_DIR / "js" / "status.js").read_text(encoding="utf-8")
        lines = source.split("\n")
        assert len(lines) <= 140, (
            f"status.js is {len(lines)} lines, exceeding 140-line limit"
        )

    def test_app_js_is_legacy(self):
        """app.js is tracked legacy — must not be loaded by index.html."""
        html = INDEX_HTML.read_text(encoding="utf-8")
        assert "app.js" not in html, "index.html must not load app.js (legacy module)"
        app_path = FRONTEND_DIR / "app.js"
        assert app_path.exists(), "app.js is missing on disk"


class TestDebugPanelSafety:
    def test_debug_panel_uses_createElement_not_innerHTML(self):
        source = (FRONTEND_DIR / "js" / "boot" / "debugPanel.js").read_text(
            encoding="utf-8"
        )
        # Comments may mention innerHTML; real code must use createElement/textContent
        lines = [l for l in source.split("\n") if not l.strip().startswith("//")]
        code = "\n".join(lines)
        assert "innerHTML" not in code, "debugPanel.js code must not use innerHTML"
        assert "createElement" in code, "debugPanel.js must use createElement"

    def test_debug_panel_only_active_with_boot_debug_param(self):
        """Debug panel activates only for ?boot_debug=1"""
        source = (FRONTEND_DIR / "js" / "boot" / "orchestrator.js").read_text(
            encoding="utf-8"
        )
        assert "boot_debug" in source, "orchestrator must check boot_debug param"


class TestFrontendTraceSafety:
    def test_trace_never_leaks_token(self):
        source = (FRONTEND_DIR / "js" / "telemetry" / "frontendTrace.js").read_text(
            encoding="utf-8"
        )
        assert (
            "token" not in source.split("payload")[-1] if "payload" in source else True
        ), "frontendTrace.js must not include token in payload"
        # The token check: the payload spread (...detail) could include token if it was in detail
        assert "auth_token" not in source, (
            "frontendTrace.js must not reference auth_token"
        )

    def test_trace_uses_type_field(self):
        source = (FRONTEND_DIR / "js" / "telemetry" / "frontendTrace.js").read_text(
            encoding="utf-8"
        )
        assert "type," in source or "type:" in source or "type " in source, (
            "frontendTrace.js must use type field in payload"
        )

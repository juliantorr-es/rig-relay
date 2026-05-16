"""Packaged app entrypoint — no-terminal double-click launch.

This is the main entrypoint for the self-contained Rig Relay.app.
It handles first-run setup, demo seeding, and pywebview launch
without requiring CLI args, uv, or a repo checkout.

Usage (inside frozen bundle):
    python rig_relay/packaged_app.py

Usage (source dev mode):
    uv run python rig_relay/packaged_app.py
"""

from __future__ import annotations

import json
import os
import sys
import time
import traceback

from rig_relay import resources


def main() -> int:
    """Entrypoint for the packaged app. Supports CLI flags for SwiftUI shell."""
    args = sys.argv[1:] if len(sys.argv) > 1 else []

    if "--demo-seed" in args:
        return _cmd_seed()
    if "--demo-doctor" in args:
        return _cmd_doctor()
    if "--demo-render-docs" in args:
        return _cmd_render_docs()
    if "--launch-cockpit" in args:
        return _cmd_launch_cockpit()

    # Default: first-run setup + launch cockpit
    try:
        _setup_environment()
        _ensure_first_run()
        _launch_cockpit()
        return 0
    except Exception:
        _show_error(traceback.format_exc())
        return 1


def _cmd_seed() -> int:
    _setup_environment()
    try:
        import rig_relay.cli.demo_commands as dc

        dc.BUILD_ROOT = resources.runtime_dir()
        dc.DEMO_DIR = resources.demo_artifacts_dir()
        dc.demo_seed()
        print("ok=seed")
        _write_startup_log("demo_seed", "ok")
        return 0
    except Exception as e:
        print(f"error=seed:{e}")
        _write_startup_log("demo_seed", str(e))
        return 1


def _cmd_doctor() -> int:
    _setup_environment()
    try:
        import rig_relay.cli.demo_commands as dc

        dc.BUILD_ROOT = resources.runtime_dir()
        dc.DEMO_DIR = resources.demo_artifacts_dir()
        from rig_relay.cli.demo_commands import demo_doctor

        return demo_doctor()
    except Exception as e:
        print(f"error=doctor:{e}")
        return 1


def _cmd_render_docs() -> int:
    _setup_environment()
    try:
        _build_docs_site()
        print("ok=docs")
        _write_startup_log("docs_site", "ok")
        return 0
    except Exception as e:
        print(f"error=docs:{e}")
        _write_startup_log("docs_site", str(e))
        return 1


def _cmd_launch_cockpit() -> int:
    _setup_environment()
    _ensure_first_run()
    try:
        _launch_cockpit()
        return 0
    except Exception:
        _show_error(traceback.format_exc())
        return 1


def _setup_environment() -> None:
    """Set environment for local demo mode."""
    # Disable network-required features
    os.environ.setdefault("RIG_RELAY_LOCAL_MODE", "1")
    os.environ.setdefault("RIG_RELAY_ENABLE_MERGE", "0")
    os.environ.setdefault("RIG_RELAY_ENABLE_PUSH", "0")
    # Ensure log level is reasonable
    os.environ.setdefault("LOG_LEVEL", "WARNING")
    # Create app directories
    resources.ensure_app_dirs()


def _ensure_first_run() -> None:
    """Seed demo data and build docs site on first launch."""
    marker = resources.app_support_dir() / ".first_run_complete"
    if marker.is_file():
        return

    try:
        _seed_demo_data()
        _build_docs_site()
        marker.write_text(time.strftime("%Y-%m-%dT%H:%M:%SZ"))
    except Exception:
        # Write error log but don't block launch
        _write_startup_log("first_run_failed", traceback.format_exc())


def _seed_demo_data() -> None:
    """Seed demo data using the same code as the CLI demo-seed command."""
    try:
        # Override BUILD_ROOT and DEMO_DIR to use app support paths
        import rig_relay.cli.demo_commands as dc
        from rig_relay.cli.demo_commands import demo_seed

        dc.BUILD_ROOT = resources.runtime_dir()
        dc.DEMO_DIR = resources.demo_artifacts_dir()

        demo_seed()
        _write_startup_log("demo_seed", "ok")
    except Exception as e:
        _write_startup_log("demo_seed", str(e))


def _build_docs_site() -> None:
    """Build a minimal local docs site."""
    try:
        docs_dir = resources.docs_site_dir()
        docs_dir.mkdir(parents=True, exist_ok=True)

        # Copy demo/doc markdown as simple HTML

        repo = resources.repo_root() if not resources.is_bundled() else None
        if repo:
            doc_src = repo / "docs" / "demo" / "mcp-night-demo.md"
        else:
            doc_src = (
                resources._bundle_resource_root()
                / "docs"
                / "demo"
                / "mcp-night-demo.md"
            )

        if doc_src.is_file():
            text = doc_src.read_text()
            html = _markdown_to_html(text)
            (docs_dir / "index.html").write_text(html)

        _write_startup_log("docs_site", "ok")
    except Exception as e:
        _write_startup_log("docs_site", str(e))


def _launch_cockpit() -> None:
    """Launch the pywebview cockpit."""
    import rig_relay.cli.desktop_cockpit as cockpit

    # Override paths for packaged mode
    cockpit.FRONTEND_DIR = resources.frontend_dir()
    cockpit.BUILD_ROOT = resources.runtime_dir()

    try:
        cockpit._open_window(ws_port=9876, mode="fixture", server_only=False)
    except Exception as e:
        _write_startup_log("cockpit_launch", str(e))
        raise


def _show_error(tb: str) -> None:
    """Show an error window or write to log."""
    _write_startup_log("fatal_error", tb)
    try:
        import webview

        error_html = f"""<html><body style="font-family: -apple-system; padding: 40px;">
        <h1>Rig Relay — Startup Error</h1>
        <p>Something went wrong during startup.</p>
        <p>Check the log file at:</p>
        <p><code>{resources.logs_dir() / "startup.log"}</code></p>
        <pre style="background:#f5f5f5;padding:10px;font-size:12px;max-height:400px;overflow:auto">{tb[:2000]}</pre>
        </body></html>"""
        webview.create_window(
            title="Rig Relay — Error", html=error_html, width=600, height=400
        )
    except Exception:
        print(tb, file=sys.stderr)


def _write_startup_log(stage: str, message: str) -> None:
    """Append a line to the startup log."""
    log_path = resources.logs_dir() / "startup.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ")
    with log_path.open("a") as f:
        f.write(json.dumps({"ts": timestamp, "stage": stage, "msg": message}) + "\n")


def _markdown_to_html(text: str) -> str:
    """Minimal markdown-to-HTML converter for docs rendering."""
    html = text
    html = html.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    lines = html.split("\n")
    result = [
        "<!DOCTYPE html>",
        '<html><head><meta charset="utf-8"><title>Rig Relay Docs</title>',
        "<style>body{font-family:-apple-system;max-width:800px;margin:40px auto;padding:0 20px;line-height:1.6}",
        "pre{background:#f5f5f5;padding:10px;border-radius:4px;overflow-x:auto}",
        "code{font-size:13px}",
        "h1,h2{border-bottom:1px solid #eee;padding-bottom:8px}</style>",
        "</head><body>",
    ]

    in_code = False
    for line in lines:
        s = line.strip()
        if s.startswith("```"):
            if in_code:
                result.append("</pre>")
                in_code = False
            else:
                result.append("<pre>")
                in_code = True
            continue
        if in_code:
            result.append(line)
            continue
        if s.startswith("# "):
            result.append(f"<h1>{s[2:]}</h1>")
        elif s.startswith("## "):
            result.append(f"<h2>{s[3:]}</h2>")
        elif s.startswith("### "):
            result.append(f"<h3>{s[4:]}</h3>")
        elif s.startswith("- "):
            result.append(f"<li>{s[2:]}</li>")
        elif s.startswith("|"):
            result.append(f"<p><code>{s}</code></p>")
        elif s:
            result.append(f"<p>{s}</p>")
        else:
            result.append("<br>")

    result.append("</body></html>")
    return "\n".join(result)


if __name__ == "__main__":
    sys.exit(main())

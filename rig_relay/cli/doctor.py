from __future__ import annotations

import argparse
from collections.abc import Sequence
import json
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SCHEMA_DIR = REPO_ROOT / "docs" / "schemas"

PUBLIC_DOCS = ["README.md", "LICENSE", "CHANGELOG.md", "AGENTS.md"]

RELEASE_GATE_SCRIPTS = [
    "scripts/rig_relay_validate_schemas.py",
    "scripts/rig_relay_validate_ide_manifest.py",
    "scripts/rig_relay_validate_tool_receipts.py",
    "scripts/rig_relay_validate_telemetry_bundle.py",
]

FORBIDDEN_PYTHON_TOKENS: list[str] = [
    "from __future__ import",
    "import ",
    "def ",
    "class ",
    "# ruff:",
    "__annotations__",
]


def _check_package_version() -> tuple[bool, str, str]:
    from rig_relay import __version__

    return True, __version__, ""


def _check_python_version() -> tuple[bool, str, str]:
    v = sys.version
    return True, v.split()[0], ""


def _check_config_path() -> tuple[bool, str, str]:
    try:
        from rig_relay.core.paths import get_vibe_home_diagnostics

        diag = get_vibe_home_diagnostics()
        active_home = Path(str(diag["active_home"]))
        config_path = active_home / "config.toml"
        if config_path.is_file():
            return True, str(config_path), ""
        return False, str(config_path), "config.toml not found"
    except Exception as e:
        return False, "", str(e)


def _check_schemas() -> tuple[bool, str, str]:
    if not SCHEMA_DIR.is_dir():
        return False, str(SCHEMA_DIR), "schema directory not found"

    errors: list[str] = []
    total = 0
    for path in sorted(SCHEMA_DIR.glob("*.json")):
        total += 1
        try:
            raw = path.read_text(encoding="utf-8")
        except OSError as e:
            errors.append(f"{path.name}: {e}")
            continue

        preamble = raw
        first_brace = raw.find("{")
        if first_brace >= 0:
            preamble = raw[:first_brace]

        for token in FORBIDDEN_PYTHON_TOKENS:
            if token in preamble:
                errors.append(f"{path.name}: Python token {token!r}")
                break

        try:
            json.loads(raw)
        except json.JSONDecodeError as e:
            errors.append(f"{path.name}: Invalid JSON: {e}")

    if errors:
        return (False, f"{total} schemas, {len(errors)} errors", "; ".join(errors[:3]))
    return True, f"{total} schemas valid", ""


def _check_public_docs() -> tuple[bool, str, str]:
    missing: list[str] = []
    present: list[str] = []
    for doc in PUBLIC_DOCS:
        if (REPO_ROOT / doc).is_file():
            present.append(doc)
        else:
            missing.append(doc)
    if missing:
        return (
            False,
            f"{len(present)}/{len(PUBLIC_DOCS)} present",
            f"missing: {', '.join(missing)}",
        )
    return True, f"{len(present)}/{len(PUBLIC_DOCS)} present", ""


def _check_release_gate_validator() -> tuple[bool, str, str]:
    present: list[str] = []
    missing: list[str] = []
    for script in RELEASE_GATE_SCRIPTS:
        if (REPO_ROOT / script).is_file():
            present.append(script)
        else:
            missing.append(script)
    if missing:
        return (
            False,
            f"{len(present)}/{len(RELEASE_GATE_SCRIPTS)} scripts",
            f"missing: {', '.join(missing)}",
        )
    return True, f"{len(present)}/{len(RELEASE_GATE_SCRIPTS)} scripts", ""


def _check_license_match() -> tuple[bool, str, str]:
    license_path = REPO_ROOT / "LICENSE"
    if not license_path.is_file():
        return False, "LICENSE not found", ""

    try:
        license_text = license_path.read_text(encoding="utf-8")
    except OSError as e:
        return False, "", str(e)

    is_agpl = "GNU AFFERO" in license_text or "AGPL" in license_text
    if is_agpl:
        return True, "AGPL-3.0-or-later", ""
    return False, "License mismatch", "LICENSE does not contain AGPL reference"


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Rig Relay installation health check")
    parser.add_argument(
        "--json", action="store_true", help="Emit structured JSON to stdout"
    )
    args = parser.parse_args(argv)

    checks = [
        ("Package version", _check_package_version),
        ("Python version", _check_python_version),
        ("Config path", _check_config_path),
        ("Schema validation", _check_schemas),
        ("Public docs", _check_public_docs),
        ("Release-gate validators", _check_release_gate_validator),
        ("License match", _check_license_match),
    ]

    results: list[dict] = []
    for name, fn in checks:
        ok, detail, error = fn()
        results.append({
            "check": name,
            "status": "pass" if ok else "fail",
            "detail": detail,
            "error": error,
        })

    if args.json:
        print(json.dumps(results, indent=2, ensure_ascii=False))
    else:
        print("Rig Relay Doctor")
        print("=" * 40)
        for r in results:
            icon = "\u2705" if r["status"] == "pass" else "\u274c"
            line = f"  {icon} {r['check']}: {r['detail']}"
            if r["error"]:
                line += f" ({r['error']})"
            print(line)

    has_issues = any(r["status"] != "pass" for r in results)
    if has_issues:
        raise SystemExit(1)


__all__ = ["main"]

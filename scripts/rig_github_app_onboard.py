#!/usr/bin/env python3
"""GitHub App onboarding CLI — guide users through installation and configuration."""

from __future__ import annotations

import argparse

from rig_relay.integrations.github_provider._github_app_onboarding import (
    complete_onboarding,
    generate_permission_manifest,
    get_app_install_url,
    get_installation_status,
    open_install_page,
)


def _print_summary(status: dict[str, str | None]) -> None:
    print("\nGitHub App Onboarding Status")
    print("-" * 30)
    for k in [
        "app_id",
        "installation_id",
        "client_id_present",
        "private_key_configured",
        "github_app_ready",
    ]:
        print(f"  {k:<24} {status.get(k, 'N/A')}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="rig-github-app-onboard", description="GitHub App onboarding wizard."
    )
    sub = parser.add_subparsers(dest="cmd")

    sub.add_parser("status", help="Show current installation status.")
    sub.add_parser("open", help="Open GitHub App installation page in browser.")
    sub.add_parser("permissions", help="Show required permission manifest.")
    save_p = sub.add_parser(
        "save", help="Save installation config after installing the App."
    )
    save_p.add_argument("--app-id", type=int, required=True, help="GitHub App ID.")
    save_p.add_argument(
        "--installation-id",
        type=int,
        required=True,
        help="Installation ID from GitHub.",
    )
    args = parser.parse_args(argv)

    if args.cmd == "status":
        _print_summary(get_installation_status())
    elif args.cmd == "open":
        url = open_install_page()
        print(f"Opened: {url}")
        print(
            "After installing, run: rig-github-app-onboard save --app-id <ID> --installation-id <ID>"
        )
    elif args.cmd == "permissions":
        manifest = generate_permission_manifest()
        for k, v in manifest.items():
            print(f"{k}: {', '.join(v)}")
    elif args.cmd == "save":
        result = complete_onboarding(args.app_id, args.installation_id)
        for k, v in result.items():
            print(f"  {k}: {v}")
        print(
            "\nOnboarding complete. Set RIG_GITHUB_PRIVATE_KEY_PATH if not already in ~/.rig/relay/.env"
        )
    else:
        _print_summary(get_installation_status())
        print(f"\nInstall URL: {get_app_install_url()}")
        print("\nCommands: status | open | permissions | save")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

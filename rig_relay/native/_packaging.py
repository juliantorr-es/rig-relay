"""App packaging service — build, bundle, and package validation (X4)."""

from __future__ import annotations

from datetime import UTC, datetime
import hashlib
from pathlib import Path
import subprocess

from rig_relay.native._evidence_hash import hash_artifact
from rig_relay.native.models import AppPackageEvidence, AppPackageIdentity


class PackagingService:
    """Service boundary for macOS .app bundle creation and validation.

    Provides typed evidence of packaging operations. Does not execute
    privileged signing or notarization — those are owned by
    ReleaseOperationsService.
    """

    def __init__(self, project_root: Path | None = None) -> None:
        self._repo_root = (
            project_root or Path(__file__).resolve().parent.parent.parent.parent
        )
        self._macos_dir = self._repo_root / "macos"
        self._build_script = self._macos_dir / "scripts" / "build-app.sh"
        self._info_plist = self._macos_dir / "Resources" / "Info.plist"
        self._entitlements = (
            self._macos_dir / "Resources" / "RigRelayShell.entitlements"
        )

    def package_identity(self) -> AppPackageIdentity:
        """Read the app identity from Info.plist."""
        bundle_id = "com.rigrelay.RigRelayShell"
        bundle_name = "Rig Relay"
        short_version = "0.1.0"
        build_version = "1"
        min_os = "14.0"

        if self._info_plist.exists():
            try:
                result = subprocess.run(
                    ["/usr/libexec/PlistBuddy", "-c", "Print", str(self._info_plist)],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                output = result.stdout
                for line in output.splitlines():
                    line = line.strip()
                    if "CFBundleIdentifier" in line and "=" in line:
                        bundle_id = line.split("=")[-1].strip()
                    if "CFBundleShortVersionString" in line and "=" in line:
                        short_version = line.split("=")[-1].strip()
                    if "CFBundleVersion" in line and "=" in line:
                        build_version = line.split("=")[-1].strip()
            except (subprocess.TimeoutExpired, FileNotFoundError):
                pass

        return AppPackageIdentity(
            bundle_identifier=bundle_id,
            bundle_name=bundle_name,
            short_version=short_version,
            build_version=build_version,
            minimum_system_version=min_os,
            executable_path=f"{bundle_id}.app/Contents/MacOS/RigRelayShell",
            bundle_path=f"{bundle_id}.app",
        )

    def build_bundle(
        self, config: str = "debug", signing_identity: str | None = None
    ) -> AppPackageEvidence:
        """Build the .app bundle and return evidence.

        Args:
            config: Build configuration ("debug" or "release").
            signing_identity: Optional signing identity to pass to build script.

        Returns:
            AppPackageEvidence with build metadata and hash.
        """
        identity = self.package_identity()
        timestamp = datetime.now(UTC).isoformat()
        evidence = AppPackageEvidence(
            identity=identity,
            build_config=config,
            build_sha256="sha256:unbuilt",
            timestamp=timestamp,
        )

        if not self._build_script.exists():
            evidence.blocking_issues.append(
                f"Build script not found: {self._build_script}"
            )
            return evidence

        args = [str(self._build_script), f"--{config}"]
        if signing_identity:
            args.extend(["--sign", signing_identity])

        try:
            result = subprocess.run(
                ["bash"] + args,
                capture_output=True,
                text=True,
                timeout=300,
                cwd=str(self._macos_dir),
            )

            app_dir = (
                self._macos_dir
                / "RigRelayShell"
                / ".build"
                / "bundle"
                / "RigRelayShell.app"
            )
            if app_dir.exists() and app_dir.is_dir():
                evidence.build_sha256 = hash_artifact(app_dir)
            elif result.returncode != 0:
                evidence.blocking_issues.append(f"Build failed: {result.stderr[:500]}")
            else:
                evidence.build_sha256 = "sha256:built_no_bundle_found"
                evidence.warnings.append(
                    "Build completed but .app bundle not found at expected path"
                )
                if self._entitlements.exists():
                    evidence.entitlements_path = str(self._entitlements)
                    evidence.entitlements_sha256 = hashlib.sha256(
                        self._entitlements.read_bytes()
                    ).hexdigest()

                evidence.signed = signing_identity is not None
                if signing_identity:
                    evidence.signing_identity = signing_identity

        except subprocess.TimeoutExpired:
            evidence.blocking_issues.append("Build timed out (300s)")
        except FileNotFoundError:
            evidence.blocking_issues.append("bash not found in PATH")

        return evidence

    def validate_bundle_structure(self, app_path: Path) -> list[str]:
        """Check that a .app bundle has the expected structure.

        Returns list of missing/invalid items (empty = valid).
        """
        issues: list[str] = []
        required = [
            "Contents/Info.plist",
            "Contents/MacOS/RigRelayShell",
            "Contents/Resources/GridlineFrontend/index.html",
        ]
        for path in required:
            if not (app_path / path).exists():
                issues.append(f"Missing: {path}")
        return issues

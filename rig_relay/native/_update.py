"""Update delivery service — Sparkle integration and update evidence (X4)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from rig_relay.native.models import UpdateEvidenceStatus, UpdateStatus


class UpdateDeliveryService:
    """Service boundary for macOS update delivery via Sparkle 2.

    Provides typed update evidence without raw binaries or keys.
    Actual Sparkle integration requires:
      - SUFeedURL in Info.plist (appcast URL)
      - SUPublicEDKey in Info.plist (Ed25519 public key)
      - SPUStandardUpdaterController in SwiftUI app entry point
      - Manual codesign of Sparkle.framework internals for non-Xcode builds
    """

    def __init__(self, project_root: Path | None = None) -> None:
        self._repo_root = (
            project_root or Path(__file__).resolve().parent.parent.parent.parent
        )
        self._info_plist = self._repo_root / "macos" / "Resources" / "Info.plist"

    def update_status(
        self,
        current_version: str = "0.1.0",
        latest_version: str | None = None,
        feed_url: str | None = None,
    ) -> UpdateEvidenceStatus:
        """Generate content-light update status evidence.

        Does not make network calls. Callers must provide latest_version if
        available from an appcast fetch.
        """
        timestamp = datetime.now(UTC).isoformat()
        evidence = UpdateEvidenceStatus(
            current_version=current_version,
            latest_version=latest_version,
            last_check_at=timestamp,
            feed_url=feed_url,
        )

        if not latest_version:
            evidence.status = UpdateStatus.UP_TO_DATE
            return evidence

        # Simple version comparison for evidence
        try:
            current_parts = [
                int(p)
                for p in current_version.replace("a", ".").replace("b", ".").split(".")
                if p.isdigit()
            ]
            latest_parts = [
                int(p)
                for p in latest_version.replace("a", ".").replace("b", ".").split(".")
                if p.isdigit()
            ]
        except ValueError:
            evidence.warnings.append("Version comparison failed — non-numeric versions")
            return evidence

        evidence.update_available = latest_parts > current_parts
        if evidence.update_available:
            evidence.status = UpdateStatus.UPDATE_AVAILABLE

        return evidence

    def record_update_event(
        self,
        status: UpdateStatus,
        version: str,
        download_sha256: str | None = None,
        ed_signature_verified: bool = False,
    ) -> UpdateEvidenceStatus:
        """Record an update lifecycle event."""
        timestamp = datetime.now(UTC).isoformat()
        return UpdateEvidenceStatus(
            current_version="0.1.0",
            latest_version=version,
            update_available=status != UpdateStatus.UP_TO_DATE,
            status=status,
            download_sha256=download_sha256,
            ed_signature_verified=ed_signature_verified,
            installed_at=timestamp if status == UpdateStatus.INSTALLED else None,
            rolled_back_at=timestamp if status == UpdateStatus.ROLLED_BACK else None,
        )

    def sparkle_required_keys(self) -> dict[str, str]:
        """Return the minimum Sparkle Info.plist key documentation."""
        return {
            "SUFeedURL": "HTTPS URL to the appcast XML feed (e.g., https://rigrelay.dev/appcast.xml)",
            "SUPublicEDKey": "Base64-encoded Ed25519 public key from generate_keys",
            "CFBundleVersion": "Incrementing integer build number in Info.plist",
            "CFBundleShortVersionString": "Human-readable version string (e.g., 0.1.0)",
            "SUEnableInstallerLauncherService": "YES for sandboxed apps",
            "SUVerifyUpdateBeforeExtraction": "YES for security — verify signature before extraction",
            "SUEnableAutomaticChecks": "YES for background update checking",
        }

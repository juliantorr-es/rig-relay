"""Release operations service — signing, notarization, staple (X4)."""

from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import subprocess

from rig_relay.native._evidence_hash import hash_artifact
from rig_relay.native.models import (
    NotarizationEvidence,
    NotarizationStatus,
    SigningEvidence,
    SigningIdentityStatus,
)

_IDENTITY_PARTS_MIN = 2


class ReleaseOperationsService:
    """Service boundary for macOS code signing and notarization.

    All operations are content-light — evidence contains hashes, not raw
    certificates, keys, or binaries. Requires Apple Developer Program
    membership and Developer ID Application certificate for real signing.
    """

    def __init__(self, project_root: Path | None = None) -> None:
        self._repo_root = (
            project_root or Path(__file__).resolve().parent.parent.parent.parent
        )
        self._macos_dir = self._repo_root / "macos"
        self._signing_script = self._macos_dir / "scripts" / "prepare-signing.sh"
        self._entitlements = (
            self._macos_dir / "Resources" / "RigRelayShell.entitlements"
        )

    def signing_identity_status(self) -> SigningIdentityStatus:
        """Check for available signing identities (content-light)."""
        status = SigningIdentityStatus()

        try:
            result = subprocess.run(
                ["security", "find-identity", "-v", "-p", "codesigning"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            identities = result.stdout
            for line in identities.splitlines():
                if "Developer ID Application" in line:
                    status.developer_id_count += 1
                    status.developer_id_available = True
                    parts = line.strip().split()
                    if len(parts) >= _IDENTITY_PARTS_MIN:
                        status.identities.append(f"Developer ID: {parts[1]}")
                elif "Apple Development" in line:
                    status.apple_development_available = True
                    parts = line.strip().split()
                    if len(parts) >= _IDENTITY_PARTS_MIN:
                        status.identities.append(f"Apple Development: {parts[1]}")
                elif "Mac Distribution" in line:
                    status.mac_distribution_available = True
                    parts = line.strip().split()
                    if len(parts) >= _IDENTITY_PARTS_MIN:
                        status.identities.append(f"Mac Distribution: {parts[1]}")

        except (subprocess.TimeoutExpired, FileNotFoundError):
            status.has_keychain_access = False
            status.warnings.append(
                "security CLI not available — cannot check identities"
            )

        try:
            result = subprocess.run(
                [
                    "xcrun",
                    "notarytool",
                    "history",
                    "--keychain-profile",
                    "rig-relay-notary",
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )
            status.has_notary_profile = result.returncode == 0
        except (subprocess.TimeoutExpired, FileNotFoundError):
            status.warnings.append("xcrun notarytool not available")

        if not status.developer_id_available:
            status.blocking_issues.append(
                "No Developer ID Application certificate found — required for notarized distribution"
            )
        if not status.has_notary_profile:
            status.warnings.append(
                "Notary profile not configured — run: xcrun notarytool store-credentials"
            )

        return status

    def sign_bundle(self, app_path: Path, signing_identity: str) -> SigningEvidence:
        """Code sign the .app bundle and return content-light evidence."""
        timestamp = datetime.now(UTC).isoformat()
        identity_hash = hashlib.sha256(signing_identity.encode()).hexdigest()[:16]

        entitlements_sha256 = "sha256:unavailable"
        if self._entitlements.exists():
            entitlements_sha256 = hashlib.sha256(
                self._entitlements.read_bytes()
            ).hexdigest()

        evidence = SigningEvidence(
            identity_used=f"sha256:{identity_hash}",
            identity_type="Developer ID Application",
            entitlements_sha256=entitlements_sha256,
            bundle_sha256_after="sha256:unsigned",
            signed_at=timestamp,
        )

        if not self._signing_script.exists():
            evidence.status = "failed"
            evidence.warnings.append(
                f"Signing script not found: {self._signing_script}"
            )
            return evidence

        if not app_path.exists():
            evidence.status = "failed"
            evidence.warnings.append(f"App bundle not found: {app_path}")
            return evidence

        try:
            result = subprocess.run(
                [
                    "bash",
                    str(self._signing_script),
                    "sign",
                    signing_identity,
                    str(app_path),
                ],
                capture_output=True,
                text=True,
                timeout=120,
                cwd=str(self._macos_dir),
            )
            if result.returncode != 0:
                evidence.status = "failed"
                evidence.warnings.append(f"Signing failed: {result.stderr[:200]}")
            else:
                evidence.status = "signed"
                evidence.bundle_sha256_after = hash_artifact(app_path)

        except subprocess.TimeoutExpired:
            evidence.status = "failed"
            evidence.warnings.append("Signing timed out")
        except FileNotFoundError:
            evidence.status = "failed"
            evidence.warnings.append("bash not found")

        return evidence

    def notarize_bundle(
        self, app_path: Path, signing_identity: str
    ) -> NotarizationEvidence:
        """Submit .app for notarization and return content-light evidence."""
        timestamp = datetime.now(UTC).isoformat()

        evidence = NotarizationEvidence(bundle_sha256="sha256:unsubmitted")

        if not app_path.exists():
            evidence.status = NotarizationStatus.FAILED
            evidence.warnings.append(f"App bundle not found: {app_path}")
            return evidence

        if not self._signing_script.exists():
            evidence.status = NotarizationStatus.FAILED
            evidence.warnings.append(
                f"Signing script not found: {self._signing_script}"
            )
            return evidence

        try:
            result = subprocess.run(
                ["bash", str(self._signing_script), "notarize", signing_identity],
                capture_output=True,
                text=True,
                timeout=600,
                cwd=str(self._macos_dir),
            )
            evidence.bundle_sha256 = hash_artifact(app_path)
            evidence.submitted_at = timestamp

            if result.returncode != 0:
                output = result.stdout + result.stderr
                if "accepted" in output.lower():
                    evidence.status = NotarizationStatus.ACCEPTED
                else:
                    evidence.status = NotarizationStatus.FAILED
                    evidence.issues.append(result.stderr[:500])
            else:
                evidence.status = NotarizationStatus.IN_PROGRESS

            if "status" in result.stdout:
                try:
                    notary_result = json.loads(result.stdout)
                    if isinstance(notary_result, dict):
                        status_str = notary_result.get("status", "in_progress")
                        evidence.status = NotarizationStatus(status_str)
                        evidence.submission_id = notary_result.get("id")
                except (json.JSONDecodeError, ValueError):
                    pass

        except subprocess.TimeoutExpired:
            evidence.status = NotarizationStatus.FAILED
            evidence.warnings.append("Notarization timed out (10 min)")
        except FileNotFoundError:
            evidence.status = NotarizationStatus.FAILED
            evidence.warnings.append("bash or notarytool not found")

        if evidence.status == NotarizationStatus.ACCEPTED:
            evidence.completed_at = datetime.now(UTC).isoformat()

        return evidence

    def staple_ticket(self, app_path: Path) -> NotarizationEvidence:
        """Staple the notarization ticket to the app bundle."""
        bundle_hash = hash_artifact(app_path)

        evidence = NotarizationEvidence(
            bundle_sha256=bundle_hash, status=NotarizationStatus.ACCEPTED
        )

        try:
            result = subprocess.run(
                ["xcrun", "stapler", "staple", str(app_path)],
                capture_output=True,
                text=True,
                timeout=30,
            )
            evidence.ticket_stapled = result.returncode == 0
            if evidence.ticket_stapled:
                evidence.status = NotarizationStatus.STAPLED
                evidence.bundle_sha256 = hash_artifact(app_path)
            else:
                evidence.warnings.append(f"Staple failed: {result.stderr[:200]}")
        except (subprocess.TimeoutExpired, FileNotFoundError):
            evidence.warnings.append("xcrun stapler not available")

        return evidence

"""Local control-plane service state, profile, and capability gating.

One authority path for cockpit, browser, IDE extension, MCP, ACP,
and CLI admin shims. No per-surface auth duplication.

Service lifecycle:
    starting → setup_required (no profile) → ready
    starting → locked (profile exists, not unlocked) → unlocking → ready
    ready → degraded (telemetry disabled, etc.)
    ready/locked/degraded → stopping → stopped
    any → failed

Profile:
    LocalProfile stored at ~/.rig/relay/profile/profile.json
    Content-light — no raw secrets, passkeys, or biometric data.
    First-launch detection: missing profile → setup_required.

Capability gating:
    Read-only/demo always available.
    Provider auth/token, telemetry export, debug packets, mutation
    tools, merge/push approval gated on profile_state in {unlocked, ready}.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum, auto
import json
from pathlib import Path
import secrets
import threading
from typing import Any

from pydantic import BaseModel, ConfigDict

from rig_relay.core.logger import logger
from rig_relay.identity.state_paths import default_relay_state_root

PROFILE_STATE_ROOT_NAME = "profile"
PROFILE_FILENAME = "profile.json"
PROFILE_SCHEMA_VERSION = "rig.relay.profile.v1"


class ServiceState(StrEnum):
    STARTING = auto()
    SETUP_REQUIRED = auto()
    LOCKED = auto()
    UNLOCKING = auto()
    READY = auto()
    DEGRADED = auto()
    STOPPING = auto()
    STOPPED = auto()
    FAILED = auto()


class ProfileState(StrEnum):
    SETUP_REQUIRED = auto()
    LOCKED = auto()
    UNLOCKED = auto()
    DEGRADED = auto()


class LocalProfile(BaseModel):
    """Content-light local profile. No raw secrets, passkeys, or biometric data."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = PROFILE_SCHEMA_VERSION
    profile_id: str
    created_at: str
    local_auth_enabled: bool = False
    passkey_registered: bool = False
    platform_credential_registered: bool = False
    telemetry_mode: str = "disabled"
    profile_state: ProfileState = ProfileState.SETUP_REQUIRED
    updated_at: str = ""

    def is_unlocked(self) -> bool:
        return self.profile_state in {ProfileState.UNLOCKED, ProfileState.DEGRADED}


class ProfileStore:
    """Read/write local profile to ~/.rig/relay/profile/profile.json.

    Content-light — never stores raw secrets, tokens, passkeys, or
    biometric material. Passkey registration is tracked as a boolean
    with credential_id_hash only.
    """

    def __init__(self, root: Path | None = None) -> None:
        if root is None:
            root = default_relay_state_root() / PROFILE_STATE_ROOT_NAME
        self._root = root
        self._lock = threading.RLock()

    @property
    def profile_path(self) -> Path:
        return self._root / PROFILE_FILENAME

    def exists(self) -> bool:
        return self.profile_path.is_file()

    def load(self) -> LocalProfile | None:
        if not self.exists():
            return None
        try:
            data = json.loads(self.profile_path.read_text(encoding="utf-8"))
            return LocalProfile(**data)
        except (json.JSONDecodeError, TypeError, ValueError) as e:
            logger.warning("failed to load profile: %s", e)
            return None

    def save(self, profile: LocalProfile) -> None:
        with self._lock:
            self._root.mkdir(parents=True, exist_ok=True)
            profile.updated_at = datetime.now(UTC).isoformat()
            self.profile_path.write_text(
                json.dumps(profile.model_dump(mode="json"), indent=2) + "\n",
                encoding="utf-8",
            )

    def create_first_launch_profile(self) -> LocalProfile:
        """Create a first-launch profile in setup_required state."""
        if self.exists():
            existing = self.load()
            if existing is not None:
                return existing

        profile = LocalProfile(
            profile_id=secrets.token_hex(16),
            created_at=datetime.now(UTC).isoformat(),
            local_auth_enabled=False,
            passkey_registered=False,
            platform_credential_registered=False,
            telemetry_mode="disabled",
            profile_state=ProfileState.SETUP_REQUIRED,
        )
        self.save(profile)
        return profile

    def unlock(self, passkey_ok: bool = False) -> LocalProfile | None:  # noqa: PLR0911
        """Transition profile from locked to unlocked.

        If passkey_ok is False and local_auth_enabled is True, stays locked.
        Returns updated profile or None if unlock not allowed.
        """
        profile = self.load()
        if profile is None:
            return None

        if profile.profile_state == ProfileState.UNLOCKED:
            return profile

        if profile.profile_state == ProfileState.SETUP_REQUIRED:
            profile.local_auth_enabled = True
            profile.profile_state = ProfileState.UNLOCKED
            self.save(profile)
            return profile

        if profile.profile_state == ProfileState.LOCKED:
            if profile.local_auth_enabled and not passkey_ok:
                return profile
            if profile.local_auth_enabled and passkey_ok:
                profile.profile_state = ProfileState.UNLOCKED
                self.save(profile)
                return profile
            profile.profile_state = ProfileState.UNLOCKED
            self.save(profile)
            return profile

        return profile

    def lock(self) -> LocalProfile | None:
        profile = self.load()
        if profile is None:
            return None
        profile.profile_state = ProfileState.LOCKED
        self.save(profile)
        return profile

    def mark_degraded(self, reason: str = "") -> LocalProfile | None:
        profile = self.load()
        if profile is None:
            return None
        if profile.profile_state in {ProfileState.UNLOCKED, ProfileState.DEGRADED}:
            profile.profile_state = ProfileState.DEGRADED
            self.save(profile)
        return profile

    def profile_summary(self) -> dict[str, Any]:
        profile = self.load()
        if profile is None:
            return {"exists": False, "profile_state": "setup_required"}
        return {
            "exists": True,
            "profile_id": profile.profile_id,
            "schema_version": profile.schema_version,
            "created_at": profile.created_at,
            "local_auth_enabled": profile.local_auth_enabled,
            "passkey_registered": profile.passkey_registered,
            "platform_credential_registered": profile.platform_credential_registered,
            "telemetry_mode": profile.telemetry_mode,
            "profile_state": profile.profile_state.value,
            "updated_at": profile.updated_at,
        }


class CapabilityGate:
    """Gate sensitive operations on profile state.

    Read-only/demo operations are always allowed.
    Sensitive operations require profile in unlocked or ready state.
    """

    # Capabilities that require unlocked profile
    SENSITIVE_CAPABILITIES: frozenset[str] = frozenset({
        "provider_onboarding_save_key",
        "provider_onboarding_remove_key",
        "telemetry_upload_google",
        "telemetry_consent_grant",
        "telemetry_consent_revoke",
        "sign_in_github_start",
        "sign_in_google_start",
        "create_telemetry_bundle_dry_run",
        "create_chatgpt_dev_bundle_dry_run",
        "checkpoint.commit",
        "lease_cleanup.archive",
        "worktree_create",
        "worktree_remove",
        "fleet_orchestrate",
    })

    # ACP commands that require unlocked profile
    ACP_COMMAND_CAPABILITIES: frozenset[str] = frozenset({
        "acp_command:leanstall",
        "acp_command:unleanstall",
        "acp_command:proxy-setup",
    })

    # Mutation tools gated on profile state — prepended with "tool:" prefix
    MUTATION_TOOL_CAPABILITIES: frozenset[str] = frozenset({
        "tool:BashTool",
        "tool:WriteFileTool",
        "tool:SearchReplaceTool",
        "tool:CheckpointTool",
        "tool:CoordinationTool",
        "tool:BehaviorPatchTool",
        "tool:TaskTool",
    })

    # Always allowed regardless of profile state
    ALWAYS_ALLOWED: frozenset[str] = frozenset({
        "refresh_projection",
        "identity_status",
        "get_chat_state",
        "run_storage_audit",
        "run_validation_suite",
        "run_queue_plan_dry_run",
        "run_spawn_plan_dry_run",
        "provider_status",
        "provider_health_check",
        "validate_telemetry_bundle",
        "generate_refinement_report",
        "create_refinement_packets",
        "telemetry_consent_status",
        "inspect_authorization_receipt",
        "mint_authorization_receipt_dev",
        "mint_authorization_receipt_local",
        "worktree_list",
        "workspace_init",
        "fleet_queue_snapshot",
        "fleet_run_once",
        "council_consult",
        "sign_in_github_poll",
        "sign_in_google_poll",
        "sign_in_github_cancel",
        "sign_in_google_cancel",
        "sign_in_github_manual_code",
        "sign_in_google_manual_code",
        "sign_out_provider",
    })

    def __init__(self, profile_store: ProfileStore | None = None) -> None:
        self._profile_store = profile_store or ProfileStore()

    def is_allowed(self, intent_name: str) -> tuple[bool, str]:
        """Check if an intent is allowed given current profile state.

        Returns (allowed, reason).
        """
        if intent_name in self.ALWAYS_ALLOWED:
            return True, ""

        sensitive = (
            intent_name in self.SENSITIVE_CAPABILITIES
            or intent_name in self.ACP_COMMAND_CAPABILITIES
            or (
                intent_name.startswith("tool:")
                and intent_name in self.MUTATION_TOOL_CAPABILITIES
            )
        )

        profile = self._profile_store.load()

        if profile is None:
            # No profile — first launch, everything sensitive is gated
            if sensitive:
                return False, "setup_required: no local profile exists"
            return True, ""

        if profile.is_unlocked():
            return True, ""

        if sensitive:
            return False, f"profile is {profile.profile_state.value}"

        return True, ""

    def check_tool_execution(
        self, tool_name: str, execution_mode: str
    ) -> tuple[bool, str]:
        """Check if a tool execution is allowed given execution mode and profile state.

        Read-only tools always pass. Mutation tools are gated on profile state.
        Returns (allowed, reason).
        """
        if execution_mode not in {"mutation_execution", "mutation_proposal"}:
            return True, ""
        return self.is_allowed(f"tool:{tool_name}")

    def state_summary(self) -> dict[str, Any]:
        """Return service state summary for health/projection."""
        profile = self._profile_store.load()

        if profile is None:
            return {
                "service_state": ServiceState.SETUP_REQUIRED.value,
                "profile_exists": False,
                "profile_state": ProfileState.SETUP_REQUIRED.value,
                "local_auth_enabled": False,
                "passkey_registered": False,
                "telemetry_mode": "disabled",
            }

        profile_state = profile.profile_state
        service_state = _profile_to_service_state(profile_state)

        return {
            "service_state": service_state.value,
            "profile_exists": True,
            "profile_id": profile.profile_id,
            "profile_state": profile_state.value,
            "local_auth_enabled": profile.local_auth_enabled,
            "passkey_registered": profile.passkey_registered,
            "platform_credential_registered": profile.platform_credential_registered,
            "telemetry_mode": profile.telemetry_mode,
            "created_at": profile.created_at,
        }


def _profile_to_service_state(profile_state: ProfileState) -> ServiceState:
    match profile_state:
        case ProfileState.SETUP_REQUIRED:
            return ServiceState.SETUP_REQUIRED
        case ProfileState.LOCKED:
            return ServiceState.LOCKED
        case ProfileState.UNLOCKED:
            return ServiceState.READY
        case ProfileState.DEGRADED:
            return ServiceState.DEGRADED


_service_state: CapabilityGate | None = None
_profile_store_override: ProfileStore | None = None


def set_profile_store_override(store: ProfileStore | None) -> None:
    """Set a profile store override for testing. Call with None to clear."""
    global _profile_store_override, _service_state
    _profile_store_override = store
    _service_state = None


def get_capability_gate() -> CapabilityGate:
    global _service_state, _profile_store_override
    if _service_state is None:
        _service_state = CapabilityGate(profile_store=_profile_store_override)
    return _service_state

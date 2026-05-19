"""ACP local auth state manager — content-light, no raw tokens."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
import hashlib


@dataclass
class ACPLocalAuthState:
    auth_status: str  # unauthenticated | authenticated | deferred | refused
    auth_method: str  # terminal_api_key | oauth | env_var | none | unsupported
    credential_store_ref_hash: str
    auth_state_hash: str
    capability_id: str
    trace_id: str
    deferred_reason: str = ""
    schema_version: str = "rig.relay.acp.auth_state.v1"
    provider_id: str = "acp_local"
    resumable: bool | None = None
    content_light: bool = True
    generated_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict[str, object]:
        d: dict[str, object] = {
            "schema_version": self.schema_version,
            "provider_id": self.provider_id,
            "auth_status": self.auth_status,
            "auth_method": self.auth_method,
            "credential_store_ref_hash": self.credential_store_ref_hash,
            "auth_state_hash": self.auth_state_hash,
            "capability_id": self.capability_id,
            "trace_id": self.trace_id,
            "deferred_reason": self.deferred_reason,
            "content_light": self.content_light,
            "generated_at": self.generated_at,
        }
        if self.resumable is not None:
            d["resumable"] = self.resumable
        return d


def compute_credential_store_ref_hash(profile_path: str = "") -> str:
    seed = f"acp_local:{profile_path}:{datetime.now(UTC).isoformat()}"
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()


def build_acp_local_auth_state(
    *,
    auth_status: str,
    auth_method: str = "none",
    credential_store_ref_hash: str = "",
    capability_id: str,
    trace_id: str = "",
    deferred_reason: str = "",
    resumable: bool | None = None,
) -> ACPLocalAuthState:
    if not credential_store_ref_hash:
        credential_store_ref_hash = compute_credential_store_ref_hash()

    auth_state = ACPLocalAuthState(
        auth_status=auth_status,
        auth_method=auth_method,
        credential_store_ref_hash=credential_store_ref_hash,
        auth_state_hash=hashlib.sha256(
            f"{auth_status}:{auth_method}:{trace_id}".encode()
        ).hexdigest(),
        capability_id=capability_id,
        trace_id=trace_id,
        deferred_reason=deferred_reason,
        resumable=resumable,
    )
    return auth_state


__all__ = [
    "ACPLocalAuthState",
    "build_acp_local_auth_state",
    "compute_credential_store_ref_hash",
]

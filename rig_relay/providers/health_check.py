"""Provider health check — safe, content-light status checks.

Default: no network in tests. network_allowed=False returns configured/skipped
status based on key presence and fingerprint only.

If network_allowed=True, provider-specific minimal auth/model-list checks may
be scaffolded but must not run in tests, print raw keys, or return raw
responses.
"""

from __future__ import annotations

from datetime import UTC, datetime

from rig_relay.providers.key_store import ProviderKeyStore
from rig_relay.providers.models import KeySource, Provider, ProviderStatus
from rig_relay.providers.registry import get_provider_info


def check_provider_status(
    provider: Provider, key_store: ProviderKeyStore, network_allowed: bool = False
) -> ProviderStatus:
    """Check provider status safely — content-light, no network by default.

    Args:
        provider: The provider to check.
        key_store: Key store to read credentials from.
        network_allowed: If True, may attempt a lightweight network check.
            Default False — never makes network requests.

    Returns:
        ProviderStatus with content-light fields. Never contains raw API keys.
    """
    info = get_provider_info(provider)
    now = datetime.now(UTC).isoformat()
    has_key = key_store.has_key(provider)
    key_source = key_store.key_source(provider)
    fingerprint = key_store.fingerprint(provider)
    warnings: list[str] = []

    if not has_key:
        return ProviderStatus(
            provider=provider,
            configured=False,
            key_source=KeySource.MISSING,
            status="skipped",
            last_checked_at=now,
            warnings=["No API key found."],
        )

    configured = True
    base_url = info.base_url if info and info.supports_base_url else None
    default_model = info.default_model if info else None

    # Google-specific: check if both GEMINI_API_KEY and GOOGLE_API_KEY are set
    if provider == Provider.GOOGLE and isinstance(key_store, EnvProviderKeyStore):
        google_warnings = key_store.get_google_warnings()
        warnings.extend(google_warnings)

    if not network_allowed:
        # No network check performed — report as skipped, never valid
        warnings.append(
            "No network check performed. Status may not reflect actual validity."
        )
        return ProviderStatus(
            provider=provider,
            configured=configured,
            key_source=key_source,
            key_fingerprint=fingerprint,
            base_url=base_url,
            default_model=default_model,
            status="skipped",
            last_checked_at=now,
            warnings=warnings,
        )

    # Network check — only returns valid for providers with real checks.
    # network_allowed=True with no implementation returns skipped + warning.
    try:
        status = _run_network_check(provider, key_store)
    except NotImplementedError:
        status = "unknown"
        warnings.append("network_check_not_implemented")
    except Exception as e:
        status = "error"
        warnings.append(f"Network check failed: {e}")

    return ProviderStatus(
        provider=provider,
        configured=configured,
        key_source=key_source,
        key_fingerprint=fingerprint,
        base_url=base_url,
        default_model=default_model,
        status=status,
        last_checked_at=now,
        warnings=warnings,
    )


# Registry of implemented network check providers.
# Only providers listed here have real network checks.
_IMPLEMENTED_NETWORK_CHECKS: set[Provider] = set()


def _run_network_check(provider: Provider, key_store: ProviderKeyStore) -> str:
    """Run a lightweight network check for a provider.

    Must not print raw keys or return raw responses.

    Returns:
        "valid" if the check succeeded, "unknown" if not implemented.

    Raises:
        Exception subclass if the check is implemented but fails.
    """
    if provider not in _IMPLEMENTED_NETWORK_CHECKS:
        msg = f"Network check not implemented for {provider.value}"
        raise NotImplementedError(msg)
    # Future: provider-specific HTTP calls go here.
    return "valid"


# Import at module level for the type hint used in check_provider_status
from rig_relay.providers.key_store import EnvProviderKeyStore

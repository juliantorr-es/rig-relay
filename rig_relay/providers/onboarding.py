"""Provider onboarding — safe intents for provider key management.

Content-light: no raw API keys in return values, audit, or result artifacts.
"""

from __future__ import annotations

from rig_relay.providers.health_check import check_provider_status
from rig_relay.providers.key_store import DevFileProviderKeyStore, ProviderKeyStore
from rig_relay.providers.models import (
    KeySource,
    Provider,
    ProviderOnboardingResult,
    ProviderStatusSummary,
)
from rig_relay.providers.registry import PROVIDER_REGISTRY, is_supported_provider

# Default key store for onboarding operations
_DEFAULT_KEY_STORE = DevFileProviderKeyStore()


def provider_status(key_store: ProviderKeyStore | None = None) -> dict:
    """Return content-light provider summaries for all registered providers.

    Args:
        key_store: Optional key store override. Defaults to DevFileProviderKeyStore.

    Returns:
        Content-light provider status summary dict. No raw API keys.
    """
    ks = key_store or _DEFAULT_KEY_STORE
    providers_list = []
    configured_count = 0

    for info in PROVIDER_REGISTRY:
        has_key = ks.has_key(info.provider)
        fingerprint = ks.fingerprint(info.provider)
        key_source = ks.key_source(info.provider)

        provider_dict = {
            "provider": info.provider.value,
            "display_name": info.display_name,
            "configured": has_key,
            "key_source": key_source.value,
            "key_fingerprint": fingerprint,
            "base_url": info.base_url if info.supports_base_url else None,
            "default_model": info.default_model,
            "status": "skipped",
            "warnings": ["No network check performed."] if has_key else [],
        }
        providers_list.append(provider_dict)
        if has_key:
            configured_count += 1

    summary = ProviderStatusSummary(
        total=len(PROVIDER_REGISTRY),
        configured=configured_count,
        providers=providers_list,
    )
    return summary.to_dict()


def provider_onboarding_save_key(
    provider_name: str, api_key: str, key_store: ProviderKeyStore | None = None
) -> dict:
    """Save a provider API key locally.

    Args:
        provider_name: Provider name (case-insensitive).
        api_key: The API key to store.
        key_store: Optional key store override. Defaults to DevFileProviderKeyStore.

    Returns:
        Content-light onboarding result. No raw key in return.
    """
    if not is_supported_provider(provider_name):
        return {
            "provider": provider_name,
            "status": "failed",
            "key_source": "missing",
            "key_fingerprint": "",
            "summary": f"Unsupported provider: {provider_name}",
            "warnings": [f"Provider '{provider_name}' is not in the registry."],
        }

    provider = Provider(provider_name.lower())
    ks = key_store or _DEFAULT_KEY_STORE
    ks.set_key(provider, api_key)

    fingerprint = ks.fingerprint(provider)
    key_source = ks.key_source(provider)

    result = ProviderOnboardingResult(
        provider=provider,
        status="completed",
        key_source=key_source,
        key_fingerprint=fingerprint,
        summary=f"API key saved for {provider.value.title()} (fingerprint: {fingerprint[:20]}...).",
    )
    return result.to_dict()


def provider_onboarding_remove_key(
    provider_name: str, key_store: ProviderKeyStore | None = None
) -> dict:
    """Remove a locally stored provider API key.

    Args:
        provider_name: Provider name (case-insensitive).
        key_store: Optional key store override. Defaults to DevFileProviderKeyStore.

    Returns:
        Content-light onboarding result.
    """
    if not is_supported_provider(provider_name):
        return {
            "provider": provider_name,
            "status": "failed",
            "key_source": "missing",
            "key_fingerprint": "",
            "summary": f"Unsupported provider: {provider_name}",
            "warnings": [f"Provider '{provider_name}' is not in the registry."],
        }

    provider = Provider(provider_name.lower())
    ks = key_store or _DEFAULT_KEY_STORE
    removed = ks.remove_key(provider)

    if removed:
        return ProviderOnboardingResult(
            provider=provider,
            status="completed",
            key_source=KeySource.MISSING,
            summary=f"API key removed for {provider.value.title()}.",
        ).to_dict()

    return ProviderOnboardingResult(
        provider=provider,
        status="completed",
        key_source=KeySource.MISSING,
        summary=f"No stored key found for {provider.value.title()}.",
    ).to_dict()


def provider_health_check(
    provider_name: str | None = None,
    key_store: ProviderKeyStore | None = None,
    network_allowed: bool = False,
) -> dict:
    """Check provider health — content-light status only.

    Args:
        provider_name: Optional provider name to check. If None, checks all.
        key_store: Optional key store override.
        network_allowed: If True, may attempt lightweight network check.

    Returns:
        Content-light provider status dict(s). No raw keys.
    """
    ks = key_store or _DEFAULT_KEY_STORE

    if provider_name:
        if not is_supported_provider(provider_name):
            return {
                "error": f"Unsupported provider: {provider_name}",
                "warnings": [f"Provider '{provider_name}' is not in the registry."],
            }
        provider = Provider(provider_name.lower())
        status = check_provider_status(provider, ks, network_allowed=network_allowed)
        return {"providers": [status.to_dict()]}

    results = []
    for info in PROVIDER_REGISTRY:
        status = check_provider_status(
            info.provider, ks, network_allowed=network_allowed
        )
        results.append(status.to_dict())

    return {"providers": results}

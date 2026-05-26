"""rig_relay.providers — Cloud model provider onboarding, key storage, and health checks.

This package provides a user-friendly provider onboarding path for configuring
DeepSeek, OpenAI, Anthropic, Google Gemini, and OpenRouter API keys during
alpha setup.

Provider onboarding is separate from:
- Identity (GitHub/Google sign-in — who the tester is)
- Telemetry consent (whether usage data is shared)
- Authorization receipts (what protected actions the machine may perform)

No API keys are stored in telemetry, audit events, result artifacts, or
frontend storage.
"""

from __future__ import annotations

from rig_relay.providers.evidence_ledger import (
    VerifiedLedgerResult,
    VerifiedProviderEvent,
    load_verified_provider_events,
)
from rig_relay.providers.health_check import check_provider_status
from rig_relay.providers.invocation import (
    GatewayProvenance,
    GatewayProvenanceSource,
    InvocationEvidenceCapability,
    InvocationOutcomeClass,
    InvocationOutcomeInput,
    InvocationRefusalClass,
    ProviderInvocationOutcome,
    assert_content_light,
    build_invocation_outcome,
    get_invocation_evidence_capability,
    invocation_evidence_capabilities,
)
from rig_relay.providers.key_store import (
    DevFileProviderKeyStore,
    EnvProviderKeyStore,
    MacKeychainProviderKeyStore,
    ProviderKeyStore,
    get_key_store,
)
from rig_relay.providers.models import (
    KeySource,
    Provider,
    ProviderCapability,
    ProviderClass,
    ProviderConfig,
    ProviderOnboardingResult,
    ProviderStatus,
    ProviderStatusSummary,
    provider_class_for,
)
from rig_relay.providers.onboarding import (
    provider_health_check,
    provider_onboarding_remove_key,
    provider_onboarding_save_key,
    provider_status,
)
from rig_relay.providers.operations import (
    ProviderOperationsReport,
    generate_operations_report,
)
from rig_relay.providers.query import (
    ProviderEvidenceQuery,
    ProviderEvidenceQueryResult,
    ProviderEvidenceQueryService,
    ProviderEvidenceSummary,
)
from rig_relay.providers.registry import (
    PROVIDER_REGISTRY,
    ProviderInfo,
    compute_provider_capabilities,
    get_provider_capability,
    get_provider_class,
)

__all__ = [
    "PROVIDER_REGISTRY",
    "DevFileProviderKeyStore",
    "EnvProviderKeyStore",
    "GatewayProvenance",
    "GatewayProvenanceSource",
    "InvocationEvidenceCapability",
    "InvocationOutcomeClass",
    "InvocationOutcomeInput",
    "InvocationRefusalClass",
    "KeySource",
    "MacKeychainProviderKeyStore",
    "Provider",
    "ProviderCapability",
    "ProviderClass",
    "ProviderConfig",
    "ProviderEvidenceQuery",
    "ProviderEvidenceQueryResult",
    "ProviderEvidenceQueryService",
    "ProviderEvidenceSummary",
    "ProviderInfo",
    "ProviderInvocationOutcome",
    "ProviderKeyStore",
    "ProviderOnboardingResult",
    "ProviderOperationsReport",
    "ProviderStatus",
    "ProviderStatusSummary",
    "VerifiedLedgerResult",
    "VerifiedProviderEvent",
    "assert_content_light",
    "build_invocation_outcome",
    "check_provider_status",
    "compute_provider_capabilities",
    "generate_operations_report",
    "get_invocation_evidence_capability",
    "get_key_store",
    "get_provider_capability",
    "get_provider_class",
    "invocation_evidence_capabilities",
    "load_verified_provider_events",
    "provider_class_for",
    "provider_health_check",
    "provider_onboarding_remove_key",
    "provider_onboarding_save_key",
    "provider_status",
]

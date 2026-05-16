"""Model provider bindings — runtime capability configuration for profiles.

Model/provider selection is attached to profiles as capability config,
not as the conceptual identity of the worker. Each profile may have a
default binding; mission assignments may override it.

Local/demo mode uses synthetic/unavailable bindings without API keys.
"""

from __future__ import annotations

from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

BINDING_VERSION = "rig.model_provider_binding.v1"


class ModelProviderBinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = BINDING_VERSION
    binding_id: str = Field(default_factory=lambda: str(uuid4()))
    provider_id: str = ""
    model_id: str = ""
    display_name: str = ""
    context_window_tokens: int | None = None
    supports_tool_calls: bool = False
    supports_streaming: bool = False
    supports_prompt_cache: bool = False
    supports_json_schema: bool = False
    supports_background_work: bool = False
    trust_tier: str = "observe_only"
    cost_tier: str | None = None
    latency_tier: str | None = None
    requires_network: bool = True
    requires_api_key: bool = True
    allowed_profile_ids: list[str] = Field(default_factory=list)
    forbidden_profile_ids: list[str] = Field(default_factory=list)
    status: str = "unknown"


class ProfileBindingLink(BaseModel):
    """Links a profile to its default model binding."""

    profile_id: str = ""
    default_binding_id: str = ""
    allowed_binding_ids: list[str] = Field(default_factory=list)


class AssignmentBindingOverride(BaseModel):
    """Optional per-assignment model binding override."""

    assignment_id: str = ""
    binding_id: str = ""
    reason: str = ""


class BindingRegistry:
    def __init__(self) -> None:
        self._bindings: dict[str, ModelProviderBinding] = {}

    def register(self, binding: ModelProviderBinding) -> None:
        self._bindings[binding.binding_id] = binding

    def get(self, binding_id: str) -> ModelProviderBinding | None:
        return self._bindings.get(binding_id)

    def available(self) -> list[ModelProviderBinding]:
        return [b for b in self._bindings.values() if b.status == "available"]

    def for_profile(self, profile_id: str) -> list[ModelProviderBinding]:
        return [
            b
            for b in self._bindings.values()
            if profile_id not in b.forbidden_profile_ids
            and (not b.allowed_profile_ids or profile_id in b.allowed_profile_ids)
        ]

    def list_all(self) -> list[ModelProviderBinding]:
        return list(self._bindings.values())


def build_demo_bindings() -> BindingRegistry:
    registry = BindingRegistry()

    bindings = [
        ModelProviderBinding(
            binding_id="binding-local-demo",
            provider_id="local",
            model_id="demo",
            display_name="Local Demo (offline)",
            supports_tool_calls=True,
            supports_streaming=False,
            supports_background_work=True,
            trust_tier="safe_local_maintenance",
            requires_network=False,
            requires_api_key=False,
            status="available",
            cost_tier="free",
            latency_tier="fast",
        ),
        ModelProviderBinding(
            binding_id="binding-deepseek-default",
            provider_id="deepseek",
            model_id="deepseek-chat",
            display_name="DeepSeek Chat",
            supports_tool_calls=True,
            supports_streaming=True,
            context_window_tokens=65536,
            trust_tier="patch_proposal",
            requires_network=True,
            requires_api_key=True,
            status="unavailable",
            cost_tier="low",
            latency_tier="medium",
        ),
        ModelProviderBinding(
            binding_id="binding-openai-default",
            provider_id="openai",
            model_id="gpt-4o",
            display_name="GPT-4o",
            supports_tool_calls=True,
            supports_streaming=True,
            supports_prompt_cache=True,
            supports_json_schema=True,
            context_window_tokens=128000,
            trust_tier="patch_proposal",
            requires_network=True,
            requires_api_key=True,
            status="unavailable",
            cost_tier="medium",
            latency_tier="fast",
        ),
    ]

    for b in bindings:
        registry.register(b)

    return registry


def build_demo_profile_bindings() -> list[ProfileBindingLink]:
    return [
        ProfileBindingLink(
            profile_id="profile-runtime-agent",
            default_binding_id="binding-local-demo",
            allowed_binding_ids=["binding-local-demo", "binding-deepseek-default"],
        ),
        ProfileBindingLink(
            profile_id="profile-frontend-agent",
            default_binding_id="binding-local-demo",
            allowed_binding_ids=["binding-local-demo"],
        ),
        ProfileBindingLink(
            profile_id="profile-docs-agent",
            default_binding_id="binding-local-demo",
            allowed_binding_ids=["binding-local-demo"],
        ),
        ProfileBindingLink(
            profile_id="profile-tests-agent",
            default_binding_id="binding-local-demo",
            allowed_binding_ids=["binding-local-demo", "binding-deepseek-default"],
        ),
        ProfileBindingLink(
            profile_id="profile-analytics-agent",
            default_binding_id="binding-local-demo",
            allowed_binding_ids=["binding-local-demo"],
        ),
        ProfileBindingLink(
            profile_id="profile-ralph-background",
            default_binding_id="binding-local-demo",
            allowed_binding_ids=["binding-local-demo", "binding-deepseek-default"],
        ),
    ]


__all__ = [
    "BINDING_VERSION",
    "AssignmentBindingOverride",
    "BindingRegistry",
    "ModelProviderBinding",
    "ProfileBindingLink",
    "build_demo_bindings",
    "build_demo_profile_bindings",
]

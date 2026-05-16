"""Orchestrator — manages configured subagent profiles, model bindings, and Ralph reports.

The orchestrator is the manager/supervisor. It:
- Manages configured subagent profiles
- Registers model/provider bindings as runtime capability config
- Assigns missions to subagent profile lanes
- Monitors lane projections
- Receives autonomous Ralph reports via RalphReport channel
- Coordinates review/adoption decisions

Ralph is not a normal subagent. Ralph is an autonomous background
convergence worker that reports completed work to the orchestrator
through a separate RalphReport channel.
Model/provider selection is runtime capability config, not role identity.
"""

from __future__ import annotations

from rig_relay.orchestrator.subagent_profiles import (
    BINDING_STATUS_DEMO_LOCAL,
    BINDING_STATUSES,
    BINDING_VERSION,
    MISSION_ASSIGNMENT_STATUSES,
    PROFILE_KIND_AUTONOMOUS_BACKGROUND,
    PROFILE_KIND_STANDARD_SUBAGENT,
    PROFILE_KINDS,
    PROFILE_TRUST_TIERS,
    TRUST_TIER_OBSERVE,
    TRUST_TIER_PATCH_PROPOSAL,
    TRUST_TIER_SAFE_LOCAL,
    BindingRegistry,
    BindingStatus,
    MissionAssignment,
    ModelProviderBinding,
    ProfileKind,
    ProfileRegistry,
    SubagentProfile,
    TrustTier,
    build_demo_bindings,
    build_demo_profiles,
    build_empty_assignment,
    get_binding_registry,
    get_profile_registry,
)

__all__ = [
    "BINDING_STATUSES",
    "BINDING_STATUS_DEMO_LOCAL",
    "BINDING_VERSION",
    "MISSION_ASSIGNMENT_STATUSES",
    "PROFILE_KINDS",
    "PROFILE_KIND_AUTONOMOUS_BACKGROUND",
    "PROFILE_KIND_STANDARD_SUBAGENT",
    "PROFILE_TRUST_TIERS",
    "TRUST_TIER_OBSERVE",
    "TRUST_TIER_PATCH_PROPOSAL",
    "TRUST_TIER_SAFE_LOCAL",
    "BindingRegistry",
    "BindingStatus",
    "MissionAssignment",
    "ModelProviderBinding",
    "ProfileKind",
    "ProfileRegistry",
    "SubagentProfile",
    "TrustTier",
    "build_demo_bindings",
    "build_demo_profiles",
    "build_empty_assignment",
    "get_binding_registry",
    "get_profile_registry",
]

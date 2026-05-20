"""rig_relay.providers.local_inference — Local inference runtime evaluation.

Probes, benchmarks, routing, selection policy, manual execution gate, and governed airlock.
Content-light: no raw prompts, completions, or secrets in any artifact.
"""
from __future__ import annotations

from rig_relay.providers.local_inference.airlock import (
    LocalInferenceAirlock,
    LocalInferenceEndpointConfig,
    get_airlock,
    is_local_inference_available,
    is_local_inference_configured,
)
from rig_relay.providers.local_inference.benchmark_summarizer import (
    summarize_benchmark_jsonl,
    validate_benchmark_content_light,
)
from rig_relay.providers.local_inference.benchmark_writer import (
    build_benchmark_sample,
    compute_prompt_sha256,
    write_sample_to_jsonl,
)
from rig_relay.providers.local_inference.capability_matching import (
    CAPABILITY_FIELD_MAP,
    match_capabilities,
)
from rig_relay.providers.local_inference.execution_client import execute_chat_completion
from rig_relay.providers.local_inference.execution_gate import (
    build_approval,
    build_blocked_receipt,
    build_executed_receipt,
    compute_approval_hash,
    evaluate_execution_gate,
)
from rig_relay.providers.local_inference.fallback import decide_fallback
from rig_relay.providers.local_inference.models import (
    APIProtocol,
    ApprovalStatus,
    ApprovedByMode,
    BenchmarkEvidenceSummary,
    BenchmarkRun,
    BenchmarkSample,
    CapabilityMatchResult,
    CapabilityProbeCapabilities,
    CapabilityProbeResult,
    CapabilityStatus,
    ExecutionStatusKind,
    ExplanationCode,
    LocalRuntimeKind,
    ManualExecutionApproval,
    ManualExecutionRequest,
    ManualExecutionResponseReceipt,
    PersistencePolicy,
    PlatformClass,
    PolicyResultKind,
    PrivacyLocality,
    ProbeStatus,
    ProviderFallbackDecision,
    RequestClass,
    RoutingConfidence,
    RoutingDecision,
    RuntimeDescriptor,
    TaskProfile,
    TaskProfileSpec,
    TaskType,
)
from rig_relay.providers.local_inference.probe import probe_local_endpoint
from rig_relay.providers.local_inference.receipts import (
    build_config_receipt,
    build_probe_receipt,
    build_routing_receipt,
)
from rig_relay.providers.local_inference.routing import select_runtime
from rig_relay.providers.local_inference.selection_policy import (
    evaluate_selection_policy,
)
from rig_relay.providers.local_inference.task_profiles import (
    TASK_PROFILES,
    get_task_profile,
    list_task_profiles,
)

__all__ = [
    "CAPABILITY_FIELD_MAP",
    "TASK_PROFILES",
    "APIProtocol",
    "ApprovalStatus",
    "ApprovedByMode",
    "BenchmarkEvidenceSummary",
    "BenchmarkRun",
    "BenchmarkSample",
    "CapabilityMatchResult",
    "CapabilityProbeCapabilities",
    "CapabilityProbeResult",
    "CapabilityStatus",
    "ExecutionStatusKind",
    "ExplanationCode",
    "LocalInferenceAirlock",
    "LocalInferenceEndpointConfig",
    "LocalRuntimeKind",
    "ManualExecutionApproval",
    "ManualExecutionRequest",
    "ManualExecutionResponseReceipt",
    "PersistencePolicy",
    "PlatformClass",
    "PolicyResultKind",
    "PrivacyLocality",
    "ProbeStatus",
    "ProviderFallbackDecision",
    "RequestClass",
    "RoutingConfidence",
    "RoutingDecision",
    "RuntimeDescriptor",
    "TaskProfile",
    "TaskProfileSpec",
    "TaskType",
    "build_approval",
    "build_benchmark_sample",
    "build_blocked_receipt",
    "build_config_receipt",
    "build_executed_receipt",
    "build_probe_receipt",
    "build_routing_receipt",
    "compute_approval_hash",
    "compute_prompt_sha256",
    "decide_fallback",
    "evaluate_execution_gate",
    "evaluate_selection_policy",
    "execute_chat_completion",
    "get_airlock",
    "get_task_profile",
    "is_local_inference_available",
    "is_local_inference_configured",
    "list_task_profiles",
    "match_capabilities",
    "probe_local_endpoint",
    "select_runtime",
    "summarize_benchmark_jsonl",
    "validate_benchmark_content_light",
    "write_sample_to_jsonl",
]

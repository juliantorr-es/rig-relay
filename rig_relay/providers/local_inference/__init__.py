"""rig_relay.providers.local_inference — Local inference runtime stack.

Probes, benchmarks, policies, execution gates, shadow evaluation,
and automatic runtime orchestration. Content-light throughout.
"""

from __future__ import annotations

from rig_relay.providers.local_inference.airlock import (
    LocalInferenceAirlock,
    LocalInferenceEndpointConfig,
    get_airlock,
    is_local_inference_available,
    is_local_inference_configured,
)
from rig_relay.providers.local_inference.auto_routing import evaluate_auto_routing
from rig_relay.providers.local_inference.backend_registry import (
    REGISTRY as BACKEND_REGISTRY,
    get_backend,
    list_backends,
)
from rig_relay.providers.local_inference.benchmark_executor import (
    BENCHMARK_PROMPTS,
    build_prompt_fixtures,
    run_benchmark_concurrent,
    run_benchmark_loop,
    run_benchmark_sync,
)
from rig_relay.providers.local_inference.benchmark_harness import (
    build_capacity_benchmark_sample,
    plan_benchmark,
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
from rig_relay.providers.local_inference.capacity_scanner import scan_capacity
from rig_relay.providers.local_inference.cloud_reference import execute_cloud_reference
from rig_relay.providers.local_inference.contract_evaluator import evaluate_contract
from rig_relay.providers.local_inference.correlated_trace import new_correlated_trace
from rig_relay.providers.local_inference.dataset_export import build_export_policy
from rig_relay.providers.local_inference.duckdb_projection import (
    compute_benchmark_summary_from_jsonl,
    compute_evidence_dataset_summary,
)
from rig_relay.providers.local_inference.energy_measurement import (
    measure_power_estimate,
)
from rig_relay.providers.local_inference.ev_aggregation import aggregate_rows
from rig_relay.providers.local_inference.evidence_builder import build_evidence_row
from rig_relay.providers.local_inference.execution_client import (
    execute_chat_completion,
    execute_chat_completion_streaming,
)
from rig_relay.providers.local_inference.execution_gate import (
    build_approval,
    build_blocked_receipt,
    build_executed_receipt,
    compute_approval_hash,
    evaluate_execution_gate,
)
from rig_relay.providers.local_inference.fallback import decide_fallback
from rig_relay.providers.local_inference.model_acquisition import (
    compute_command_hash,
    plan_model_download,
)
from rig_relay.providers.local_inference.model_download_executor import (
    execute_model_download,
)
from rig_relay.providers.local_inference.model_fit_planner import plan_models
from rig_relay.providers.local_inference.models import (
    APIProtocol,
    ApprovalStatus,
    ApprovedByMode,
    AutoRoutingDecision,
    AutoRoutingStatus,
    BackendLifecycleStatus,
    BenchmarkEvidenceSummary,
    BenchmarkRun,
    BenchmarkSample,
    CapabilityEvidenceReport,
    CapabilityEvidenceRow,
    CapabilityMatchResult,
    CapabilityProbeCapabilities,
    CapabilityProbeResult,
    CapabilityRecommendation,
    CapabilityStatus,
    CapacityBenchmarkPlan,
    CapacityBenchmarkSample,
    CapacityClass,
    CapacityScan,
    ComparisonStatus,
    ContractResultStatus,
    CorrelatedTraceEvent,
    DatasetExportMode,
    DatasetExportPolicy,
    ExecutionStatusKind,
    ExplanationCode,
    LocalOutputProposal,
    LocalRuntimeKind,
    ManualExecutionApproval,
    ManualExecutionRequest,
    ManualExecutionResponseReceipt,
    ModelAcquisitionPlan,
    ModelCandidate,
    ModelFitPlan,
    OutputContractKind,
    OutputContractResult,
    PersistencePolicy,
    PlatformClass,
    PolicyResultKind,
    PrivacyLocality,
    ProbeError,
    ProbeStatus,
    PromptSourceKind,
    ProposalActionType,
    ProviderFallbackDecision,
    RawRetentionPolicy,
    RecommendedRoute,
    ReferenceComparison,
    RequestClass,
    RetentionMode,
    RoutingConfidence,
    RoutingDecision,
    RuntimeBackend,
    RuntimeDescriptor,
    ScientificComparisonReport,
    ServerLifecycleReceipt,
    ShadowRunReceipt,
    ShadowSafetyPolicy,
    ShadowScenario,
    TaskProfile,
    TaskProfileSpec,
    TaskType,
    TelemetrySummary,
)
from rig_relay.providers.local_inference.mutation_safety_bridge import (
    evaluate_proposal_safety,
)
from rig_relay.providers.local_inference.probe import probe_local_endpoint
from rig_relay.providers.local_inference.proposal_adapter import classify_and_propose
from rig_relay.providers.local_inference.receipts import (
    build_config_receipt,
    build_probe_receipt,
    build_routing_receipt,
)
from rig_relay.providers.local_inference.recommendation_policy import recommend
from rig_relay.providers.local_inference.reference_comparison import (
    compare_to_reference,
)
from rig_relay.providers.local_inference.retention_policy import build_retention_policy
from rig_relay.providers.local_inference.routing import select_runtime
from rig_relay.providers.local_inference.scientific_comparison import (
    compare_local_cloud,
)
from rig_relay.providers.local_inference.selection_policy import (
    evaluate_selection_policy,
)
from rig_relay.providers.local_inference.server_lifecycle import (
    build_server_health_result,
    build_stop_receipt,
    plan_server_start,
)
from rig_relay.providers.local_inference.server_lifecycle_executor import (
    probe_server_health,
    start_server,
    stop_server,
)
from rig_relay.providers.local_inference.shadow_evaluation import run_shadow_evaluation
from rig_relay.providers.local_inference.shadow_safety_policy import (
    build_safety_policy,
    validate_shadow_receipt_safety,
)
from rig_relay.providers.local_inference.task_profiles import (
    TASK_PROFILES,
    get_task_profile,
    list_task_profiles,
)
from rig_relay.providers.local_inference.telemetry_summary import (
    build_telemetry_summary,
    validate_telemetry_content_light,
)

__all__ = [
    "BACKEND_REGISTRY",
    "BENCHMARK_PROMPTS",
    "CAPABILITY_FIELD_MAP",
    "TASK_PROFILES",
    "APIProtocol",
    "ApprovalStatus",
    "ApprovedByMode",
    "AutoRoutingDecision",
    "AutoRoutingStatus",
    "BackendLifecycleStatus",
    "BenchmarkEvidenceSummary",
    "BenchmarkRun",
    "BenchmarkSample",
    "CapabilityEvidenceReport",
    "CapabilityEvidenceRow",
    "CapabilityMatchResult",
    "CapabilityProbeCapabilities",
    "CapabilityProbeResult",
    "CapabilityRecommendation",
    "CapabilityStatus",
    "CapacityBenchmarkPlan",
    "CapacityBenchmarkSample",
    "CapacityClass",
    "CapacityScan",
    "ComparisonStatus",
    "ContractResultStatus",
    "CorrelatedTraceEvent",
    "DatasetExportMode",
    "DatasetExportPolicy",
    "ExecutionStatusKind",
    "ExplanationCode",
    "LocalInferenceAirlock",
    "LocalInferenceEndpointConfig",
    "LocalOutputProposal",
    "LocalRuntimeKind",
    "ManualExecutionApproval",
    "ManualExecutionRequest",
    "ManualExecutionResponseReceipt",
    "ModelAcquisitionPlan",
    "ModelCandidate",
    "ModelFitPlan",
    "OutputContractKind",
    "OutputContractResult",
    "PersistencePolicy",
    "PlatformClass",
    "PolicyResultKind",
    "PrivacyLocality",
    "ProbeError",
    "ProbeStatus",
    "PromptSourceKind",
    "ProposalActionType",
    "ProviderFallbackDecision",
    "RawRetentionPolicy",
    "RecommendedRoute",
    "ReferenceComparison",
    "RequestClass",
    "RetentionMode",
    "RoutingConfidence",
    "RoutingDecision",
    "RuntimeBackend",
    "RuntimeDescriptor",
    "ScientificComparisonReport",
    "ServerLifecycleReceipt",
    "ShadowRunReceipt",
    "ShadowSafetyPolicy",
    "ShadowScenario",
    "TaskProfile",
    "TaskProfileSpec",
    "TaskType",
    "TelemetrySummary",
    "aggregate_rows",
    "build_approval",
    "build_benchmark_sample",
    "build_blocked_receipt",
    "build_capacity_benchmark_sample",
    "build_config_receipt",
    "build_evidence_row",
    "build_executed_receipt",
    "build_export_policy",
    "build_probe_receipt",
    "build_prompt_fixtures",
    "build_retention_policy",
    "build_routing_receipt",
    "build_safety_policy",
    "build_server_health_result",
    "build_stop_receipt",
    "build_telemetry_summary",
    "classify_and_propose",
    "compare_local_cloud",
    "compare_to_reference",
    "compute_approval_hash",
    "compute_benchmark_summary_from_jsonl",
    "compute_command_hash",
    "compute_evidence_dataset_summary",
    "compute_prompt_sha256",
    "decide_fallback",
    "evaluate_auto_routing",
    "evaluate_contract",
    "evaluate_execution_gate",
    "evaluate_proposal_safety",
    "evaluate_selection_policy",
    "execute_chat_completion",
    "execute_chat_completion_streaming",
    "execute_cloud_reference",
    "execute_model_download",
    "get_airlock",
    "get_backend",
    "get_task_profile",
    "is_local_inference_available",
    "is_local_inference_configured",
    "list_backends",
    "list_task_profiles",
    "match_capabilities",
    "measure_power_estimate",
    "new_correlated_trace",
    "plan_benchmark",
    "plan_model_download",
    "plan_models",
    "plan_server_start",
    "probe_local_endpoint",
    "probe_server_health",
    "recommend",
    "run_benchmark_concurrent",
    "run_benchmark_loop",
    "run_benchmark_sync",
    "run_shadow_evaluation",
    "scan_capacity",
    "select_runtime",
    "start_server",
    "stop_server",
    "summarize_benchmark_jsonl",
    "validate_benchmark_content_light",
    "validate_shadow_receipt_safety",
    "validate_telemetry_content_light",
    "write_sample_to_jsonl",
]

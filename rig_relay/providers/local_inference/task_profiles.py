"""Task profiles for local inference selection policy.

Each profile defines the capabilities required for a specific agent task type.
Profiles are content-light: no prompts, completions, or private data.
"""

from __future__ import annotations

from rig_relay.providers.local_inference.models import TaskProfileSpec

TASK_PROFILES: dict[str, TaskProfileSpec] = {
    "chat_light": TaskProfileSpec(
        profile_name="chat_light",
        display_name="Chat (Light)",
        required_capabilities=["chat_completions"],
        preferred_capabilities=["streaming"],
        streaming_preferred=True,
        manual_selection_allowed=True,
        policy_selection_allowed=False,
        fallback_behavior="use_remote",
        description="Simple conversational chat with low latency preference.",
    ),
    "code_review_light": TaskProfileSpec(
        profile_name="code_review_light",
        display_name="Code Review (Light)",
        required_capabilities=["chat_completions"],
        preferred_capabilities=["streaming"],
        min_context_window_tokens=8192,
        streaming_preferred=True,
        manual_selection_allowed=True,
        policy_selection_allowed=False,
        fallback_behavior="use_remote",
        description="Lightweight code review with moderate context window.",
    ),
    "structured_json": TaskProfileSpec(
        profile_name="structured_json",
        display_name="Structured JSON Output",
        required_capabilities=["chat_completions", "structured_json_output"],
        preferred_capabilities=["tool_calling"],
        structured_output_required=True,
        manual_selection_allowed=True,
        policy_selection_allowed=False,
        fallback_behavior="use_remote",
        description="Tasks requiring structured JSON output compliance.",
    ),
    "tool_planning": TaskProfileSpec(
        profile_name="tool_planning",
        display_name="Tool Planning",
        required_capabilities=["chat_completions", "tool_calling"],
        preferred_capabilities=["structured_json_output", "streaming"],
        tool_call_required=True,
        streaming_preferred=True,
        manual_selection_allowed=True,
        policy_selection_allowed=False,
        fallback_behavior="use_remote",
        description="Tasks requiring tool/function calling capability.",
    ),
    "long_context_summary": TaskProfileSpec(
        profile_name="long_context_summary",
        display_name="Long Context Summary",
        required_capabilities=["chat_completions"],
        preferred_capabilities=["streaming"],
        min_context_window_tokens=32768,
        manual_selection_allowed=True,
        policy_selection_allowed=False,
        fallback_behavior="use_remote",
        description="Summarization tasks requiring large context windows.",
    ),
    "embedding_or_retrieval": TaskProfileSpec(
        profile_name="embedding_or_retrieval",
        display_name="Embedding / Retrieval",
        required_capabilities=["embeddings"],
        preferred_capabilities=[],
        manual_selection_allowed=True,
        policy_selection_allowed=False,
        fallback_behavior="use_remote",
        description="Embedding generation and vector retrieval tasks.",
    ),
    "vision_or_multimodal": TaskProfileSpec(
        profile_name="vision_or_multimodal",
        display_name="Vision / Multimodal",
        required_capabilities=["chat_completions", "vision"],
        preferred_capabilities=["streaming"],
        manual_selection_allowed=True,
        policy_selection_allowed=False,
        fallback_behavior="use_remote",
        description="Tasks requiring image/vision/multimodal input.",
    ),
    "unknown": TaskProfileSpec(
        profile_name="unknown",
        display_name="Unknown / Conservative",
        required_capabilities=["chat_completions"],
        preferred_capabilities=[],
        manual_selection_allowed=False,
        policy_selection_allowed=False,
        fallback_behavior="use_remote",
        description="Conservative fallback for unknown task types.",
    ),
}


def get_task_profile(name: str) -> TaskProfileSpec:
    return TASK_PROFILES.get(name, TASK_PROFILES["unknown"])


def list_task_profiles() -> list[TaskProfileSpec]:
    return list(TASK_PROFILES.values())


__all__ = ["TASK_PROFILES", "get_task_profile", "list_task_profiles"]

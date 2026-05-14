"""Utilities package. Re-exports all public and test-used symbols from submodules.

Import read_safe / read_safe_async / decode_safe (returns ReadSafeResult) from rig_relay.core.utils.io and create_slug from
vibe.core.utils.slug when needed to avoid circular imports with config.
"""

from __future__ import annotations

from rig_relay.core.utils.async_subprocess import kill_async_subprocess
from rig_relay.core.utils.concurrency import (
    AsyncExecutor,
    ConversationLimitException,
    run_sync,
)
from rig_relay.core.utils.display import compact_reduction_display
from rig_relay.core.utils.http import (
    build_ssl_context,
    get_server_url_from_api_base,
    get_user_agent,
)
from rig_relay.core.utils.matching import name_matches
from rig_relay.core.utils.merge import MergeConflictError, MergeStrategy
from rig_relay.core.utils.paths import is_dangerous_directory
from rig_relay.core.utils.platform import is_windows
from rig_relay.core.utils.retry import async_generator_retry, async_retry
from rig_relay.core.utils.tags import (
    CANCELLATION_TAG,
    KNOWN_TAGS,
    TOOL_ERROR_TAG,
    VIBE_STOP_EVENT_TAG,
    VIBE_WARNING_TAG,
    CancellationReason,
    TaggedText,
    get_user_cancellation_message,
    is_user_cancellation_event,
)
from rig_relay.core.utils.time import utc_now

__all__ = [
    "CANCELLATION_TAG",
    "KNOWN_TAGS",
    "TOOL_ERROR_TAG",
    "VIBE_STOP_EVENT_TAG",
    "VIBE_WARNING_TAG",
    "AsyncExecutor",
    "CancellationReason",
    "ConversationLimitException",
    "MergeConflictError",
    "MergeStrategy",
    "TaggedText",
    "async_generator_retry",
    "async_retry",
    "build_ssl_context",
    "compact_reduction_display",
    "get_server_url_from_api_base",
    "get_user_agent",
    "get_user_cancellation_message",
    "is_dangerous_directory",
    "is_user_cancellation_event",
    "is_windows",
    "kill_async_subprocess",
    "name_matches",
    "run_sync",
    "utc_now",
]

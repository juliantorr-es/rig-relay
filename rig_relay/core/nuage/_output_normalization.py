"""Remote workflow event translator mixin — output normalization."""
from __future__ import annotations

from typing import Any



import logging
from typing import Any

from pydantic import BaseModel, ValidationError

from rig_relay.core.logger import logger
from rig_relay.core.nuage.remote_workflow_event_models import (
    WaitForInputPayload,
    PredefinedAnswersState,
)
from rig_relay.core.types import (
    AssistantEvent,
    BaseEvent,
    LLMMessage,
    Role,
    UserMessageEvent,
    WaitingForInputEvent,
)



class OutputNormalizationMixin:
    """Mixin providing output normalization methods for RemoteWorkflowEventTranslator."""

    def _normalize_mapping(self, value: Any) -> dict[str, Any]:
        if isinstance(value, dict):
            return cast(dict[str, Any], self._json_safe_value(value))
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
            except json.JSONDecodeError:
                return {}
            if isinstance(parsed, dict):
                return cast(dict[str, Any], self._json_safe_value(parsed))
        return {}


    def _normalize_output(self, output: Any) -> dict[str, Any]:
        if isinstance(output, dict):
            return cast(dict[str, Any], self._json_safe_value(output))
        if isinstance(output, str):
            try:
                parsed = json.loads(output)
            except json.JSONDecodeError:
                return {"value": output}
            if isinstance(parsed, dict):
                return cast(dict[str, Any], self._json_safe_value(parsed))
            return {"value": parsed}
        return {"value": self._json_safe_value(output)}


    def _output_preview_text(self, output: Any) -> str | None:
        output_dict = self._normalize_output(output)

        # Priority: known preview keys > raw string > single-value dict > all scalar fields
        for key in ("preview", "message", "status_text", "status", "delta"):
            value = output_dict.get(key)
            if isinstance(value, str) and value:
                return value

        if isinstance(output, str) and output:
            return output

        if len(output_dict) == 1 and "value" in output_dict:
            value = output_dict["value"]
            return value if isinstance(value, str) and value else None

        return (
            "\n".join(
                f"{key}: {value}"
                for key, value in output_dict.items()
                if value is not None and not isinstance(value, (dict, list))
            )
            or None
        )


"""Remote workflow event translator mixin — json helpers."""
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



class JsonHelpersMixin:
    """Mixin providing json helpers methods for RemoteWorkflowEventTranslator."""

    def _json_safe_value(self, value: Any) -> Any:
        if isinstance(value, BaseModel):
            return self._json_safe_value(value.model_dump(mode="json"))
        if isinstance(value, dict):
            return {
                str(key): self._json_safe_value(item) for key, item in value.items()
            }
        if isinstance(value, list | tuple):
            return [self._json_safe_value(item) for item in value]
        if isinstance(value, set):
            return [self._json_safe_value(item) for item in sorted(value, key=repr)]
        return value


    def _json_string(self, value: Any) -> str:
        return json.dumps(self._json_safe_value(value))


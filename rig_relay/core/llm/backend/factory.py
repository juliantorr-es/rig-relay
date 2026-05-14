from __future__ import annotations

from rig_relay.core.llm.backend.generic import GenericBackend
from rig_relay.core.llm.backend.mistral import MistralBackend
from rig_relay.core.types import Backend

BACKEND_FACTORY = {Backend.MISTRAL: MistralBackend, Backend.GENERIC: GenericBackend}

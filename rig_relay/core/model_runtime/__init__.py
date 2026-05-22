"""ModelRuntime — LLM call execution and middleware metadata assembly.

Owns:
  - LLM call preparation (context assembly, telemetry, metadata)
  - Backend invocation (streaming and non-streaming)
  - Provider error translation
  - Stats accounting
  - Middleware setup and result handling
  - Backend request metadata

Public API:
  ModelRuntime — the runtime
"""

from __future__ import annotations

from rig_relay.core.model_runtime.runtime import ModelRuntime

__all__ = ["ModelRuntime"]

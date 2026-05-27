"""Rig-governed MLX-backed inference engine.

Uses mlx-lm Python APIs directly for model loading and text generation,
wrapped in Rig Relay's governance boundary. Returns visible responses
for UI consumption and content-light hashes for evidence.

MLX thread safety: mlx-lm uses a module-level Metal stream. The engine
initializes a thread-local stream on the caller's thread. Future batching
will require a dedicated worker thread with serialized execution.

Tool-call parsing: detects tool-call-formatted output from model-generated
text using family-specific patterns (Llama, Qwen, DeepSeek, GLM, Mistral).
Tool calls are classified as proposals — never executed directly.

OMLX-informed patterns:
  - MLX stream initialization: engine_core.py _init_mlx_thread (Apache 2.0)
  - Tool-call family detection: api/tool_calling.py multi-family parsing (Apache 2.0)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
import hashlib
import json
import re
import secrets
import threading
import time

from rig_relay.core.logger import logger
from rig_relay.local_inference.runtime._models import (
    FinishReason,
    LocalInferenceResponse,
    ToolCallProposal,
)

try:
    import mlx.core as _  # noqa: F401
    import mlx.nn.layers.base as mlx_base
    import mlx_lm.tokenizer_utils

    HAS_MLX = True
except ImportError:
    HAS_MLX = False


class MlxNotAvailableError(Exception):
    """Raised when MLX is not available on this platform."""


class ModelNotLoadedError(Exception):
    """Raised when a model is requested but not loaded."""


@dataclass
class LoadedModel:
    model_id_hash: str
    model_path: str
    loaded_at: str
    mlx_model: mlx_base.Module = field(repr=False)
    tokenizer: mlx_lm.tokenizer_utils.TokenizerWrapper = field(repr=False)


class RiggedMlxEngine:
    """MLX-backed inference engine under Rig Relay governance.

    Loads models via mlx-lm.load(), performs text generation via
    mlx-lm.generate(), and returns visible LocalInferenceResponse
    with parsed tool-call proposals. The response text is transient
    for UI consumption; the evidence system records only SHA256 hashes.

    Thread safety: MLX operations run on the calling thread with
    thread-local stream initialization. For multi-request scenarios,
    the caller must serialize access. A future dedicated worker
    thread will own the execution for scaling to batching.
    """

    def __init__(self) -> None:
        self._loaded_models: dict[str, LoadedModel] = {}
        self._mlx_available: bool | None = None
        self._stream_initialized: bool = False
        self._lock: threading.Lock = threading.Lock()

    @property
    def is_mlx_available(self) -> bool:
        if self._mlx_available is None:
            try:
                import mlx.core as _  # noqa: F401

                self._mlx_available = True
            except ImportError:
                self._mlx_available = False
                logger.debug("MLX not available — local inference disabled")
        return self._mlx_available

    @property
    def loaded_model_count(self) -> int:
        return len(self._loaded_models)

    def list_loaded_models(self) -> list[LoadedModel]:
        return list(self._loaded_models.values())

    def load_model(self, model_path: str, model_id: str = "") -> LoadedModel:
        if not self.is_mlx_available:
            raise MlxNotAvailableError("MLX is not available on this platform")

        model_id_hash = _sha256(model_path)[:16]
        display_id = model_id or model_path

        with self._lock:
            if model_id_hash in self._loaded_models:
                logger.debug("Model already loaded: %s", display_id)
                return self._loaded_models[model_id_hash]

            logger.info("Loading model via mlx-lm: %s", display_id)
            self._ensure_mlx_stream()

            import mlx_lm as _mlx

            result = _mlx.load(model_path)
            mlx_model = result[0]
            tokenizer = result[1]

            loaded = LoadedModel(
                model_id_hash=model_id_hash,
                model_path=model_path,
                loaded_at=_now_iso(),
                mlx_model=mlx_model,
                tokenizer=tokenizer,
            )
            self._loaded_models[model_id_hash] = loaded
            logger.info("Model loaded: %s (hash=%s)", display_id, model_id_hash)
            return loaded

    def unload_model(self, model_id_hash: str) -> bool:
        with self._lock:
            if model_id_hash in self._loaded_models:
                del self._loaded_models[model_id_hash]
                logger.info("Model unloaded: %s", model_id_hash)
                return True
        return False

    def generate(
        self,
        model_id_hash: str,
        messages: list[dict],
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ) -> LocalInferenceResponse:
        """Generate text via mlx-lm and return visible response.

        Uses the loaded model's tokenizer chat template for proper
        prompt formatting (including tool schemas when present).
        Parses tool-call output from model-generated text.
        Returns LocalInferenceResponse with visible content, tool
        proposals, finish reason, and generation metadata.
        """
        with self._lock:
            loaded = self._loaded_models.get(model_id_hash)

        if loaded is None:
            return LocalInferenceResponse(content="", finish_reason=FinishReason.ERROR)

        self._ensure_mlx_stream()
        tokenizer = loaded.tokenizer
        prompt = _build_prompt_using_chat_template(messages, tokenizer)
        start = time.monotonic()

        try:
            import mlx_lm as _mlx

            response = _mlx.generate(
                loaded.mlx_model,
                tokenizer,
                prompt=prompt,
                max_tokens=max_tokens,
                verbose=False,
            )
            elapsed = (time.monotonic() - start) * 1000
            output_text = response if isinstance(response, str) else str(response)

            usage = _estimate_usage(prompt, output_text, tokenizer)
            finish_reason = FinishReason.STOP
            tool_proposals = _parse_tool_calls(output_text)

            if tool_proposals:
                finish_reason = FinishReason.TOOL_CALLS

            return LocalInferenceResponse(
                content=output_text,
                finish_reason=finish_reason,
                tool_call_proposals=tool_proposals,
                prompt_tokens=usage.get("prompt_tokens", 0),
                completion_tokens=usage.get("completion_tokens", 0),
                total_tokens=usage.get("total_tokens", 0),
                latency_ms=int(elapsed),
                model_id_hash=model_id_hash,
            )

        except Exception as e:
            elapsed = (time.monotonic() - start) * 1000
            logger.error("mlx-lm generation error: %s", e)
            return LocalInferenceResponse(
                content="",
                finish_reason=FinishReason.ERROR,
                latency_ms=int(elapsed),
                model_id_hash=model_id_hash,
            )

    def _ensure_mlx_stream(self) -> None:
        if self._stream_initialized:
            return

        self._stream_initialized = True
        if not self.is_mlx_available:
            return

        try:
            import mlx.core as mx
            import mlx_lm.generate as mlx_gen

            if not hasattr(mlx_gen, "generation_stream"):
                mlx_gen.generation_stream = mx.new_stream(mx.default_device())
            logger.debug("MLX generation stream initialized")
        except Exception:
            pass


def _build_prompt_using_chat_template(messages: list[dict], tokenizer: object) -> str:
    """Build prompt using the loaded model's chat template.

    Uses tokenizer.apply_chat_template() when available (most
    HuggingFace tokenizers support this). Falls back to role-prefixed
    plain text for tokenizers without template support.
    """
    if hasattr(tokenizer, "apply_chat_template"):
        try:
            formatted = tokenizer.apply_chat_template(
                messages, tokenize=False, add_generation_prompt=True
            )
            if isinstance(formatted, str) and formatted:
                return formatted
        except Exception as e:
            logger.debug("Chat template failed, falling back: %s", e)

    parts: list[str] = []
    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        parts.append(f"{role}: {content}")
    return "\n".join(parts)


def _parse_tool_calls(text: str) -> list[ToolCallProposal]:
    """Parse tool calls from model-generated text.

    Detects tool-call-formatted output using patterns informed by
    OMLX api/tool_calling.py multi-family parsing (Apache 2.0).
    Supports: JSON tool-call blocks, function-call tags, XML-style
    tool-use blocks common across Llama, Qwen, DeepSeek, GLM models.
    """
    proposals: list[ToolCallProposal] = []

    json_blocks = re.findall(r"```json\s*(.*?)```", text, re.DOTALL)
    for block in json_blocks:
        try:
            data = json.loads(block)
            if isinstance(data, dict) and "name" in data:
                proposals.append(
                    ToolCallProposal(
                        call_id=_make_call_id(),
                        tool_name=str(data.get("name", "")),
                        arguments=json.dumps(
                            data.get("arguments", data.get("parameters", {}))
                        ),
                        rationale=str(data.get("rationale", "")),
                    )
                )
        except (json.JSONDecodeError, TypeError):
            continue

    func_call_pattern = re.findall(
        r"<function_call>\s*(.*?)\s*</function_call>", text, re.DOTALL
    )
    for block in func_call_pattern:
        try:
            data = json.loads(block)
            if isinstance(data, dict):
                proposals.append(
                    ToolCallProposal(
                        call_id=_make_call_id(),
                        tool_name=str(data.get("name", "")),
                        arguments=json.dumps(data.get("arguments", {})),
                    )
                )
        except (json.JSONDecodeError, TypeError):
            continue

    tool_use_pattern = re.findall(
        r"<tool_call>\s*(.*?)\s*</tool_call>", text, re.DOTALL
    )
    for block in tool_use_pattern:
        try:
            data = json.loads(block)
            if isinstance(data, dict):
                proposals.append(
                    ToolCallProposal(
                        call_id=_make_call_id(),
                        tool_name=str(data.get("name", data.get("function", ""))),
                        arguments=json.dumps(
                            data.get("arguments", data.get("parameters", {}))
                        ),
                    )
                )
        except (json.JSONDecodeError, TypeError):
            continue

    return proposals


def _make_call_id() -> str:
    return f"call_{secrets.token_hex(8)}"


def _estimate_usage(
    prompt: str, output: str, tokenizer: object | None
) -> dict[str, int]:
    try:
        if tokenizer is not None and hasattr(tokenizer, "encode"):
            prompt_tokens = len(tokenizer.encode(prompt))
            completion_tokens = len(tokenizer.encode(output))
            return {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": prompt_tokens + completion_tokens,
            }
    except Exception:
        pass
    prompt_tokens = len(prompt) // 4
    completion_tokens = len(output) // 4
    return {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": prompt_tokens + completion_tokens,
    }


def _sha256(content: str) -> str:
    return hashlib.sha256(content.encode()).hexdigest()


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()

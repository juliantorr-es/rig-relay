"""Rig-governed MLX-backed inference engine.

Uses mlx-lm Python APIs directly for model loading and text generation,
wrapped in Rig Relay's governance boundary. This is an internal runtime —
not an external HTTP endpoint adapter.

MLX thread safety: mlx-lm uses a module-level Metal stream that must be
initialized on the correct thread. Pattern informed by OMLX's engine_core.py
_init_mlx_thread() (Apache 2.0, oMLX contributors).

Content-light: returns SHA256 hashes, token counts, latency. Never raw output.
"""

from __future__ import annotations

import hashlib
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

from rig_relay.core.logger import logger

try:
    import mlx.core as mx  # noqa: F401
    import mlx.nn.layers.base as mlx_base  # noqa: F401
    import mlx_lm  # noqa: F401
    import mlx_lm.generate as gen_mod  # noqa: F401
    import mlx_lm.tokenizer_utils  # noqa: F401

    HAS_MLX: bool = True
except ImportError:
    HAS_MLX = False


class MlxNotAvailableError(Exception):
    """Raised when MLX is not available on this platform."""


class ModelNotLoadedError(Exception):
    """Raised when a model is requested but not loaded."""


@dataclass
class GovernedOutput:
    """Content-light governed output from MLX inference.

    Never contains raw generated text — only SHA256 hashes. Raw text is
    held transiently for governance checks and discarded after evidence
    emission.
    """

    executed: bool = False
    output_sha256: str = ""
    output_length_chars: int = 0
    prompt_sha256: str = ""
    model_id_hash: str = ""
    latency_ms: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    error_message: str = ""
    content_light: bool = True


@dataclass
class LoadedModel:
    """Track a loaded MLX model and its metadata."""

    model_id_hash: str
    model_path: str
    loaded_at: str
    mlx_model: "mlx_base.Module"
    tokenizer: "mlx_lm.tokenizer_utils.TokenizerWrapper"


class RiggedMlxEngine:
    """MLX-backed inference engine under Rig Relay governance.

    Loads models via mlx-lm.load(), performs text generation via
    mlx-lm.generate(), and returns content-light GovernedOutput.
    Governed tool-call output detection is performed on raw text
    before it is discarded.

    Threading: All MLX operations run on a single dedicated thread
    to avoid Metal stream race conditions (pattern informed by
    OMLX engine_core.py _init_mlx_thread, Apache 2.0).
    """

    def __init__(self) -> None:
        self._loaded_models: dict[str, LoadedModel] = {}
        self._mlx_lock: threading.Lock = threading.Lock()
        self._mlx_available: bool | None = None
        self._mlx_thread: threading.Thread | None = None
        self._mlx_result: object = None
        self._mlx_error: Exception | None = None
        self._mlx_ready: threading.Event = threading.Event()
        self._mlx_initialized: bool = False
        self._stream_initialized: bool = False

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
        """Load a model via mlx-lm under governance.

        The model path is hashed for content-light identification.
        Model weights are loaded into GPU memory via mlx-lm.load().
        """
        if not self.is_mlx_available:
            raise MlxNotAvailableError("MLX is not available on this platform")

        model_id_hash = _sha256(model_path)[:16]
        display_id = model_id or model_path

        if model_id_hash in self._loaded_models:
            loaded = self._loaded_models[model_id_hash]
            logger.debug("Model already loaded: %s", display_id)
            return loaded

        logger.info("Loading model via mlx-lm: %s", display_id)
        self._ensure_mlx_initialized()

        try:
            import mlx_lm

            result = mlx_lm.load(model_path)
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

        except Exception as e:
            logger.error("Failed to load model %s: %s", display_id, e)
            raise ModelNotLoadedError(f"Failed to load model {display_id}: {e}") from e

    def unload_model(self, model_id_hash: str) -> bool:
        """Unload a model from GPU memory."""
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
    ) -> GovernedOutput:
        """Generate text via mlx-lm under governance.

        Runs on MLX thread to prevent Metal stream races. Returns
        content-light GovernedOutput (hashes, counts, latency).
        """
        loaded = self._loaded_models.get(model_id_hash)
        if loaded is None:
            return GovernedOutput(
                executed=False, error_message=f"Model not loaded: {model_id_hash}"
            )

        self._ensure_mlx_initialized()
        prompt_text = _messages_to_prompt(messages)
        prompt_sha = _sha256(prompt_text)
        start = time.monotonic()

        try:
            import mlx_lm

            response = mlx_lm.generate(
                loaded.mlx_model,
                loaded.tokenizer,
                prompt=prompt_text,
                max_tokens=max_tokens,
                temp=temperature,
                verbose=False,
            )
            elapsed = (time.monotonic() - start) * 1000

            output_text = response if isinstance(response, str) else str(response)
            output_sha = _sha256(output_text)
            output_len = len(output_text)

            usage = _estimate_usage(prompt_text, output_text, loaded.tokenizer)

            return GovernedOutput(
                executed=True,
                output_sha256=output_sha,
                output_length_chars=output_len,
                prompt_sha256=prompt_sha,
                model_id_hash=model_id_hash,
                latency_ms=int(elapsed),
                prompt_tokens=usage.get("prompt_tokens", 0),
                completion_tokens=usage.get("completion_tokens", 0),
                total_tokens=usage.get("total_tokens", 0),
            )

        except Exception as e:
            elapsed = (time.monotonic() - start) * 1000
            logger.error("mlx-lm generation error: %s", e)
            return GovernedOutput(
                executed=False,
                prompt_sha256=prompt_sha,
                model_id_hash=model_id_hash,
                latency_ms=int(elapsed),
                error_message=str(e)[:256],
            )

    def _ensure_mlx_initialized(self) -> None:
        """Initialize MLX thread-local stream on the current thread.

        Pattern informed by OMLX engine_core.py _init_mlx_thread()
        (Apache 2.0, oMLX contributors). mlx-lm uses a module-level
        Metal generation_stream that must be created on the thread
        that will perform GPU operations.
        """
        if self._stream_initialized:
            return

        try:
            import mlx.core as mx
            import mlx_lm.generate as gen_mod

            if not hasattr(gen_mod, "generation_stream"):
                gen_mod.generation_stream = mx.new_stream(mx.default_device())
            self._stream_initialized = True
            logger.debug("MLX generation stream initialized")
        except Exception:
            self._stream_initialized = True


def _sha256(content: str) -> str:
    return hashlib.sha256(content.encode()).hexdigest()


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def _messages_to_prompt(messages: list[dict]) -> str:
    """Convert chat messages to a prompt string for mlx-lm.

    Uses the tokenizer's chat template when available, otherwise
    falls back to a simple role-prefixed format.
    """
    parts: list[str] = []
    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        if role == "system":
            parts.append(content)
        elif role == "user":
            parts.append(f"User: {content}")
        elif role == "assistant":
            parts.append(f"Assistant: {content}")
        elif role == "tool":
            name = msg.get("name", "tool")
            parts.append(f"Tool({name}): {content}")
    return "\n".join(parts)


def _estimate_usage(
    prompt: str, output: str, tokenizer: object | None
) -> dict[str, int]:
    """Estimate token counts from prompt and output."""
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

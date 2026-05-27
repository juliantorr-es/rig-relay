"""Model inventory from local filesystem.

Scans configured model directories for MLX-compatible models. Classifies
models by type (LLM, VLM, embedding, reranker, audio) using patterns
informed by OMLX's model_discovery.py (Apache 2.0, oMLX contributors).

Content-light: returns ModelInventoryEntry with SHA256 hashes and capability
classes only. Never exposes raw model paths, download metadata, or secrets.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import TYPE_CHECKING

from rig_relay.core.logger import logger
from rig_relay.local_inference.runtime._models import (
    ModelInventoryEntry,
    ModelTypeClass,
)

if TYPE_CHECKING:
    pass

_HF_CACHE_DIRS: list[Path] = [
    Path.home() / ".cache" / "huggingface" / "hub",
    Path.home() / ".cache" / "huggingface_hub",
    Path.home() / ".omlx" / "models",
]

_VLM_ARCHITECTURES: set[str] = {
    "qwen2_vl",
    "qwen2_5_vl",
    "qwen3_vl",
    "llava",
    "llava_next",
    "llava_onevision",
    "pixtral",
    "pixtral_vision",
    "gemma3",
    "gemma4",
    "gemma3_text_is_also_vlm",
    "internvl",
    "internvl2",
    "minicpmv",
    "phi3_v",
    "phi4mm",
    "phi4_multimodal",
    "paligemma",
    "idefics3",
    "fuyu",
    "molmo",
    "smolvlm",
    "florence2",
    "deepseek_ocr",
    "dots_ocr",
    "glm_ocr",
}

_EMBEDDING_ARCHITECTURES: set[str] = {
    "bert",
    "roberta",
    "xlm_roberta",
    "modernbert",
    "siglip",
    "colqwen2_5",
    "gemma3_text",
    "gemma4_text",
    "qwen3_for_text_embedding",
}

_RERANKER_ARCHITECTURES: set[str] = {
    "modernbert_for_sequence_classification",
    "xlm_roberta_for_sequence_classification",
    "jina_for_ranking",
}


def scan_model_inventory(
    model_dirs: list[Path] | None = None,
) -> list[ModelInventoryEntry]:
    """Scan local filesystem for MLX-compatible models.

    Searches configured directories for model directories containing
    a config.json. Classifies model type using architecture patterns.
    Returns content-light ModelInventoryEntry list.

    Args:
        model_dirs: Optional override directories. Defaults to
            standard HuggingFace cache and ~/.omlx/models.

    Returns:
        List of ModelInventoryEntry with safe model identifiers.
    """
    dirs = model_dirs or list(_HF_CACHE_DIRS)
    seen: set[str] = set()
    entries: list[ModelInventoryEntry] = []

    for base_dir in dirs:
        if not base_dir.exists():
            continue
        for config_path in base_dir.rglob("**/config.json"):
            model_dir = config_path.parent
            try:
                entry = _scan_single_model(model_dir, config_path)
            except Exception:
                logger.debug("Failed to scan model dir: %s", model_dir, exc_info=True)
                continue

            if entry.model_id_hash and entry.model_id_hash not in seen:
                seen.add(entry.model_id_hash)
                entries.append(entry)

    entries.sort(key=lambda e: e.display_name_safe)
    return entries


def _scan_single_model(model_dir: Path, config_path: Path) -> ModelInventoryEntry:
    """Scan a single model directory and build a ModelInventoryEntry."""
    model_id = str(model_dir.absolute())
    model_id_hash = _sha256(model_id)[:16]
    config = _read_json(config_path)

    model_type = _classify_model_type(config)
    display_name = model_dir.name

    capabilities = _detect_capabilities(config)
    license_family = _safe_license(config.get("license", ""))
    source_safe = _safe_source(model_dir)

    return ModelInventoryEntry(
        model_id_hash=model_id_hash,
        model_type=model_type,
        display_name_safe=display_name,
        capabilities=capabilities,
        license_family_safe=license_family,
        source_safe=source_safe,
    )


def _classify_model_type(config: dict) -> ModelTypeClass:
    """Classify model type from config.json.

    Pattern informed by OMLX model_discovery.py (Apache 2.0, oMLX
    contributors): architecture-based VLM detection, model class-based
    embedding/reranker detection.
    """
    architectures = config.get("architectures", [])
    model_type = str(config.get("model_type", "")).lower()
    arch_lower = " ".join(a.lower() for a in architectures) if architectures else ""

    for arch in _VLM_ARCHITECTURES:
        if arch in arch_lower or arch in model_type:
            return ModelTypeClass.VLM

    for arch in _EMBEDDING_ARCHITECTURES:
        if arch in arch_lower or arch in model_type:
            return ModelTypeClass.EMBEDDING

    for arch in _RERANKER_ARCHITECTURES:
        if arch in arch_lower or arch in model_type:
            return ModelTypeClass.RERANKER

    if "for_sequence_classification" in model_type:
        return ModelTypeClass.RERANKER
    if "for_text_embedding" in model_type:
        return ModelTypeClass.EMBEDDING
    if "for_causal_lm" in model_type or "for_conditional_generation" in model_type:
        return ModelTypeClass.LLM
    if "whisper" in model_type or "asr" in model_type:
        return ModelTypeClass.AUDIO_STT
    if "tts" in model_type:
        return ModelTypeClass.AUDIO_TTS

    return ModelTypeClass.LLM


def _detect_capabilities(config: dict) -> list[str]:
    """Detect model capabilities from config."""
    caps: list[str] = []
    architectures = config.get("architectures", [])
    arch_lower = " ".join(a.lower() for a in architectures) if architectures else ""
    model_type = str(config.get("model_type", "")).lower()

    if any(
        k in arch_lower or k in model_type
        for k in ("vlm", "vision", "llava", "pixtral", "gemma3")
    ):
        caps.append("vision")
    if "tool" in model_type or "tool_use" in arch_lower:
        caps.append("tool_calling")
    return caps


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _safe_license(license_value: str | list | None) -> str:
    if isinstance(license_value, str):
        return license_value
    if isinstance(license_value, list):
        return ", ".join(str(l) for l in license_value)
    return ""


def _safe_source(model_dir: Path) -> str:
    """Return safe source identifier — never raw path."""
    return model_dir.name


def _sha256(content: str) -> str:
    return hashlib.sha256(content.encode()).hexdigest()

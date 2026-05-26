"""Test data for native Gemini adapter tests.

Derived from Gemini generateContent API response shapes
(https://ai.google.dev/api/generate-content).
"""

from __future__ import annotations

import json
from typing import Any

from tests.backend.data import Chunk, JsonResponse, ResultData

GEMINI_TEST_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"


def _sse_chunk(data: dict[str, Any]) -> Chunk:
    return f"data: {json.dumps(data, separators=(',', ':'))}\n\n".encode()


def _usage(prompt_tokens: int = 0, completion_tokens: int = 0) -> dict[str, int]:
    return {"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens}


GEMINI_SIMPLE_TEXT_RESPONSE: JsonResponse = {
    "candidates": [
        {
            "content": {
                "role": "model",
                "parts": [{"text": "Hello! How can I help you today?"}],
            },
            "finishReason": "STOP",
            "safetyRatings": [],
        }
    ],
    "usageMetadata": {
        "promptTokenCount": 10,
        "candidatesTokenCount": 8,
        "totalTokenCount": 18,
    },
}

GEMINI_SIMPLE_TEXT_RESULT: ResultData = {
    "message": "Hello! How can I help you today?",
    "usage": {"prompt_tokens": 10, "completion_tokens": 8},
}

GEMINI_SAFETY_REFUSAL_RESPONSE: JsonResponse = {
    "candidates": [{"finishReason": "SAFETY", "safetyRatings": []}],
    "usageMetadata": {
        "promptTokenCount": 5,
        "candidatesTokenCount": 0,
        "totalTokenCount": 5,
    },
}

GEMINI_SAFETY_BLOCK_RESPONSE: JsonResponse = {
    "promptFeedback": {"blockReason": "OTHER"},
    "usageMetadata": {
        "promptTokenCount": 3,
        "candidatesTokenCount": 0,
        "totalTokenCount": 3,
    },
}

GEMINI_EMPTY_CANDIDATES_RESPONSE: JsonResponse = {
    "candidates": [],
    "usageMetadata": {
        "promptTokenCount": 0,
        "candidatesTokenCount": 0,
        "totalTokenCount": 0,
    },
}

GEMINI_ERROR_RESPONSE: JsonResponse = {
    "error": {
        "code": 400,
        "message": "API key not valid. Please pass a valid API key.",
        "status": "INVALID_ARGUMENT",
    }
}

GEMINI_STREAM_CHUNKS: list[Chunk] = [
    _sse_chunk({
        "candidates": [{"content": {"role": "model", "parts": [{"text": "Hello"}]}}]
    }),
    _sse_chunk({
        "candidates": [{"content": {"role": "model", "parts": [{"text": "!"}]}}]
    }),
    _sse_chunk({
        "candidates": [{"content": {"role": "model", "parts": [{"text": " How"}]}}]
    }),
    _sse_chunk({
        "candidates": [
            {"content": {"role": "model", "parts": [{"text": " can I help?"}]}}
        ]
    }),
    _sse_chunk({
        "usageMetadata": {
            "promptTokenCount": 10,
            "candidatesTokenCount": 5,
            "totalTokenCount": 15,
        }
    }),
]

GEMINI_STREAM_RESULTS: list[ResultData] = [
    {"message": "Hello", "usage": _usage(0, 0)},
    {"message": "!", "usage": _usage(0, 0)},
    {"message": " How", "usage": _usage(0, 0)},
    {"message": " can I help?", "usage": _usage(0, 0)},
    {"message": "", "usage": _usage(10, 5)},
]

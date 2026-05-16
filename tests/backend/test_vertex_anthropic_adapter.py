from __future__ import annotations

import json
from unittest.mock import MagicMock, PropertyMock, patch

import pytest

from rig_relay.core.config import ProviderConfig
from rig_relay.core.llm.backend.vertex import (
    VertexAnthropicAdapter,
    VertexCredentials,
    build_vertex_base_url,
    build_vertex_endpoint,
)
from rig_relay.core.types import AvailableFunction, AvailableTool, LLMMessage, Role


@pytest.fixture
def adapter():
    adapter = VertexAnthropicAdapter()
    with patch.object(
        VertexCredentials,
        "access_token",
        new_callable=PropertyMock,
        return_value="fake-token",
    ):
        yield adapter


@pytest.fixture
def provider():
    return ProviderConfig(
        name="vertex",
        api_base="",
        project_id="test-project",
        region="us-central1",
        api_style="vertex-anthropic",
    )


class TestBuildVertexEndpoint:
    def test_non_streaming(self):
        endpoint = build_vertex_endpoint(
            "us-central1", "my-project", "claude-3-5-sonnet"
        )
        assert endpoint == (
            "/v1/projects/my-project/locations/us-central1/"
            "publishers/anthropic/models/claude-3-5-sonnet:rawPredict"
        )

    def test_streaming(self):
        endpoint = build_vertex_endpoint(
            "us-central1", "my-project", "claude-3-5-sonnet", streaming=True
        )
        assert endpoint == (
            "/v1/projects/my-project/locations/us-central1/"
            "publishers/anthropic/models/claude-3-5-sonnet:streamRawPredict"
        )

    def test_base_url(self):
        base = build_vertex_base_url("us-central1")
        assert base == "https://us-central1-aiplatform.googleapis.com"

    def test_global_endpoint(self):
        endpoint = build_vertex_endpoint("global", "my-project", "claude-3-5-sonnet")
        assert endpoint == (
            "/v1/projects/my-project/locations/global/"
            "publishers/anthropic/models/claude-3-5-sonnet:rawPredict"
        )

    def test_global_base_url(self):
        base = build_vertex_base_url("global")
        assert base == "https://aiplatform.googleapis.com"


class TestPrepareRequest:
    def test_basic_request(self, adapter, provider):
        messages = [LLMMessage(role=Role.user, content="Hello")]
        req = adapter.prepare_request(
            model_name="claude-3-5-sonnet",
            messages=messages,
            temperature=0.5,
            tools=None,
            max_tokens=1024,
            tool_choice=None,
            enable_streaming=False,
            provider=provider,
        )

        payload = json.loads(req.body)
        assert payload["anthropic_version"] == "vertex-2023-10-16"
        assert "model" not in payload
        assert payload["max_tokens"] == 1024
        assert payload["temperature"] == 0.5
        assert req.headers["Authorization"] == "Bearer fake-token"
        assert req.headers["anthropic-beta"] == adapter.BETA_FEATURES
        assert "rawPredict" in req.endpoint
        assert "streamRawPredict" not in req.endpoint
        assert req.base_url == "https://us-central1-aiplatform.googleapis.com"

    def test_streaming_request(self, adapter, provider):
        messages = [LLMMessage(role=Role.user, content="Hello")]
        req = adapter.prepare_request(
            model_name="claude-3-5-sonnet",
            messages=messages,
            temperature=0.5,
            tools=None,
            max_tokens=1024,
            tool_choice=None,
            enable_streaming=True,
            provider=provider,
        )

        payload = json.loads(req.body)
        assert payload.get("stream") is True
        assert "streamRawPredict" in req.endpoint

    def test_no_beta_features_for_vertex(self, adapter, provider):
        """Vertex AI doesn't support the same beta features as direct Anthropic API."""
        messages = [LLMMessage(role=Role.user, content="Hello")]
        req = adapter.prepare_request(
            model_name="claude-3-5-sonnet",
            messages=messages,
            temperature=0.5,
            tools=None,
            max_tokens=1024,
            tool_choice=None,
            enable_streaming=False,
            provider=provider,
        )

        # Vertex AI doesn't support prompt-caching or other beta features
        assert req.headers.get("anthropic-beta", "") == ""

    def test_with_extended_thinking(self, adapter, provider):
        messages = [LLMMessage(role=Role.user, content="Hello")]
        req = adapter.prepare_request(
            model_name="claude-3-5-sonnet",
            messages=messages,
            temperature=0.5,
            tools=None,
            max_tokens=1024,
            tool_choice=None,
            enable_streaming=False,
            provider=provider,
            thinking="medium",
        )

        payload = json.loads(req.body)
        assert payload["thinking"] == {"type": "enabled", "budget_tokens": 10000}
        assert payload["max_tokens"] == 1024
        assert payload["temperature"] == 1

    def test_with_tools(self, adapter, provider):
        messages = [LLMMessage(role=Role.user, content="Hello")]
        tools = [
            AvailableTool(
                function=AvailableFunction(
                    name="test_tool",
                    description="A test tool",
                    parameters={"type": "object", "properties": {}},
                )
            )
        ]
        req = adapter.prepare_request(
            model_name="claude-3-5-sonnet",
            messages=messages,
            temperature=0.5,
            tools=tools,
            max_tokens=1024,
            tool_choice=None,
            enable_streaming=False,
            provider=provider,
        )

        payload = json.loads(req.body)
        assert len(payload["tools"]) == 1
        assert payload["tools"][0]["name"] == "test_tool"

    def test_missing_project_id(self, adapter):
        provider = ProviderConfig(
            name="vertex",
            api_base="",
            region="us-central1",
            api_style="vertex-anthropic",
        )
        with pytest.raises(ValueError, match="project_id"):
            adapter.prepare_request(
                model_name="claude-3-5-sonnet",
                messages=[LLMMessage(role=Role.user, content="Hello")],
                temperature=0.5,
                tools=None,
                max_tokens=1024,
                tool_choice=None,
                enable_streaming=False,
                provider=provider,
            )

    def test_missing_region(self, adapter):
        provider = ProviderConfig(
            name="vertex",
            api_base="",
            project_id="test-project",
            api_style="vertex-anthropic",
        )
        with pytest.raises(ValueError, match="region"):
            adapter.prepare_request(
                model_name="claude-3-5-sonnet",
                messages=[LLMMessage(role=Role.user, content="Hello")],
                temperature=0.5,
                tools=None,
                max_tokens=1024,
                tool_choice=None,
                enable_streaming=False,
                provider=provider,
            )

    def test_default_max_tokens(self, adapter, provider):
        messages = [LLMMessage(role=Role.user, content="Hello")]
        req = adapter.prepare_request(
            model_name="claude-3-5-sonnet",
            messages=messages,
            temperature=0.5,
            tools=None,
            max_tokens=None,
            tool_choice=None,
            enable_streaming=False,
            provider=provider,
        )

        payload = json.loads(req.body)
        assert payload["max_tokens"] == adapter.DEFAULT_MAX_TOKENS


class TestAdapterInheritanceContract:
    """VertexAnthropicAdapter inherits AnthropicAdapter.parse_response
    and streaming event parsing correctly.
    """

    def test_inherits_parse_response(self, adapter, provider):
        """Vertex adapter delegates parse_response to AnthropicAdapter."""
        data = {
            "content": [{"type": "text", "text": "Hello from Vertex"}],
            "usage": {"input_tokens": 10, "output_tokens": 5},
        }
        chunk = adapter.parse_response(data, provider)
        assert chunk.message.content == "Hello from Vertex"
        assert chunk.usage.prompt_tokens == 10

    def test_inherits_streaming_events(self, adapter, provider):
        """Vertex adapter delegates streaming parse to AnthropicAdapter."""
        chunk, _idx = adapter._parse_streaming_event({
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "text_delta", "text": "streamed"},
        })
        assert chunk.message.content == "streamed"

    def test_inherits_cache_control(self, adapter):
        """Vertex adapter inherits cache control helper from AnthropicAdapter."""
        messages: list[dict] = [
            {"role": "user", "content": [{"type": "text", "text": "Hello"}]}
        ]
        adapter._add_cache_control_to_last_user_message(messages)
        assert messages[-1]["content"][-1].get("cache_control") == {"type": "ephemeral"}

    def test_inherits_thinking_detection(self, adapter):
        """Vertex adapter inherits thinking content detection from AnthropicAdapter."""
        messages: list[dict] = [
            {"role": "user", "content": [{"type": "thinking", "thinking": "x"}]}
        ]
        assert adapter._has_thinking_content(messages)


class TestVertexCredentials:
    def _make_creds(
        self, *, valid: bool = True, token: str | None = "tok"
    ) -> MagicMock:
        creds = MagicMock()
        creds.valid = valid
        creds.token = token
        return creds

    @patch("vibe.core.llm.backend.vertex.google.auth.default")
    def test_initializes_credentials_on_first_access(self, mock_default: MagicMock):
        creds = self._make_creds()
        mock_default.return_value = (creds, "project")

        vc = VertexCredentials()
        token = vc.access_token

        assert token == "tok"
        mock_default.assert_called_once()

    @patch("vibe.core.llm.backend.vertex.google.auth.default")
    def test_caches_credentials_across_calls(self, mock_default: MagicMock):
        creds = self._make_creds()
        mock_default.return_value = (creds, "project")

        vc = VertexCredentials()
        _ = vc.access_token
        _ = vc.access_token
        _ = vc.access_token

        mock_default.assert_called_once()

    @patch("vibe.core.llm.backend.vertex.google.auth.default")
    def test_refreshes_when_token_invalid(self, mock_default: MagicMock):
        creds = self._make_creds(valid=False)
        mock_default.return_value = (creds, "project")

        vc = VertexCredentials()
        _ = vc.access_token

        creds.refresh.assert_called_once()

    @patch("vibe.core.llm.backend.vertex.google.auth.default")
    def test_skips_refresh_when_token_valid(self, mock_default: MagicMock):
        creds = self._make_creds(valid=True)
        mock_default.return_value = (creds, "project")

        vc = VertexCredentials()
        _ = vc.access_token

        creds.refresh.assert_not_called()

    @patch("vibe.core.llm.backend.vertex.google.auth.default")
    def test_raises_when_token_is_none(self, mock_default: MagicMock):
        creds = self._make_creds(valid=True, token=None)
        mock_default.return_value = (creds, "project")

        vc = VertexCredentials()
        with pytest.raises(RuntimeError, match="did not produce a token"):
            _ = vc.access_token

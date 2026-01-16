"""Tests for LLM Provider with AISuite MCP - Written FIRST (TDD Red Phase).

These tests define the expected behavior of the new LLM provider
that uses AISuite native MCP support and LiteLLM embeddings.
"""

from unittest.mock import MagicMock, patch

import pytest


class TestAISuiteLLMWrapperContract:
    """Test the AISuite LLM wrapper contract."""

    @pytest.fixture
    def mock_ai_client(self):
        """Create mock AISuite client."""
        client = MagicMock()
        return client

    @pytest.fixture
    def mock_response(self):
        """Create mock chat completion response."""
        response = MagicMock()
        response.choices = [MagicMock()]
        response.choices[0].message.content = "Test response"
        response.usage = MagicMock()
        response.usage.prompt_tokens = 10
        response.usage.completion_tokens = 20
        response.usage.total_tokens = 30
        return response

    def test_invoke_returns_llm_response(self, mock_ai_client, mock_response):
        """invoke must return LLMResponse with content."""
        mock_ai_client.chat.completions.create.return_value = mock_response

        from app.services.rag.llm_provider import AISuiteLLMWrapper, LLMResponse

        wrapper = AISuiteLLMWrapper(
            client=mock_ai_client,
            model="openai:gpt-4o-mini",
            max_tokens=1000,
            temperature=0.1,
        )

        result = wrapper.invoke("Hello")

        assert isinstance(result, LLMResponse)
        assert result.content == "Test response"

    def test_invoke_includes_usage_stats(self, mock_ai_client, mock_response):
        """invoke must include token usage statistics."""
        mock_ai_client.chat.completions.create.return_value = mock_response

        from app.services.rag.llm_provider import AISuiteLLMWrapper

        wrapper = AISuiteLLMWrapper(
            client=mock_ai_client,
            model="openai:gpt-4o-mini",
            max_tokens=1000,
            temperature=0.1,
        )

        result = wrapper.invoke("Hello")

        assert result.usage is not None
        assert result.usage["prompt_tokens"] == 10
        assert result.usage["completion_tokens"] == 20
        assert result.usage["total_tokens"] == 30

    def test_invoke_passes_correct_parameters(self, mock_ai_client, mock_response):
        """invoke must pass model, messages, temperature, max_tokens."""
        mock_ai_client.chat.completions.create.return_value = mock_response

        from app.services.rag.llm_provider import AISuiteLLMWrapper

        wrapper = AISuiteLLMWrapper(
            client=mock_ai_client,
            model="openai:gpt-4o-mini",
            max_tokens=500,
            temperature=0.5,
        )

        wrapper.invoke("Test prompt")

        call_kwargs = mock_ai_client.chat.completions.create.call_args[1]
        assert call_kwargs["model"] == "openai:gpt-4o-mini"
        assert call_kwargs["temperature"] == 0.5
        assert call_kwargs["max_tokens"] == 500
        assert call_kwargs["messages"][0]["role"] == "user"
        assert call_kwargs["messages"][0]["content"] == "Test prompt"

    def test_invoke_with_tools_returns_tool_call_result(
        self, mock_ai_client, mock_response
    ):
        """invoke_with_tools must return ToolCallResult."""
        mock_ai_client.chat.completions.create.return_value = mock_response

        from app.services.rag.llm_provider import AISuiteLLMWrapper, ToolCallResult

        wrapper = AISuiteLLMWrapper(
            client=mock_ai_client,
            model="openai:gpt-4o-mini",
            max_tokens=1000,
            temperature=0.1,
            mcp_url="http://localhost:8000/mcp",
        )

        result = wrapper.invoke_with_tools("What is BTC price?")

        assert isinstance(result, ToolCallResult)
        assert result.content == "Test response"

    def test_invoke_with_tools_passes_mcp_config(self, mock_ai_client, mock_response):
        """invoke_with_tools must pass MCP configuration to AISuite."""
        mock_ai_client.chat.completions.create.return_value = mock_response

        from app.services.rag.llm_provider import AISuiteLLMWrapper

        wrapper = AISuiteLLMWrapper(
            client=mock_ai_client,
            model="openai:gpt-4o-mini",
            max_tokens=1000,
            temperature=0.1,
            mcp_url="http://localhost:8000/mcp",
        )

        wrapper.invoke_with_tools("Test")

        call_kwargs = mock_ai_client.chat.completions.create.call_args[1]
        assert "tools" in call_kwargs
        assert len(call_kwargs["tools"]) == 1
        assert call_kwargs["tools"][0]["type"] == "mcp"
        assert call_kwargs["tools"][0]["name"] == "bisq"
        assert call_kwargs["tools"][0]["server_url"] == "http://localhost:8000/mcp"

    def test_invoke_with_tools_passes_max_turns(self, mock_ai_client, mock_response):
        """invoke_with_tools must pass max_turns for automatic tool loop."""
        mock_ai_client.chat.completions.create.return_value = mock_response

        from app.services.rag.llm_provider import AISuiteLLMWrapper

        wrapper = AISuiteLLMWrapper(
            client=mock_ai_client,
            model="openai:gpt-4o-mini",
            max_tokens=1000,
            temperature=0.1,
            mcp_url="http://localhost:8000/mcp",
        )

        wrapper.invoke_with_tools("Test", max_turns=5)

        call_kwargs = mock_ai_client.chat.completions.create.call_args[1]
        assert call_kwargs["max_turns"] == 5

    def test_invoke_with_tools_handles_error(self, mock_ai_client):
        """invoke_with_tools must handle errors gracefully."""
        mock_ai_client.chat.completions.create.side_effect = Exception("API Error")

        from app.services.rag.llm_provider import AISuiteLLMWrapper

        wrapper = AISuiteLLMWrapper(
            client=mock_ai_client,
            model="openai:gpt-4o-mini",
            max_tokens=1000,
            temperature=0.1,
            mcp_url="http://localhost:8000/mcp",
        )

        result = wrapper.invoke_with_tools("Test")

        assert "Error" in result.content
        assert result.tool_calls_made == []
        assert result.iterations == 0

    def test_mcp_url_stored_in_wrapper(self, mock_ai_client):
        """Wrapper must store mcp_url attribute."""
        from app.services.rag.llm_provider import AISuiteLLMWrapper

        wrapper = AISuiteLLMWrapper(
            client=mock_ai_client,
            model="openai:gpt-4o-mini",
            max_tokens=1000,
            temperature=0.1,
            mcp_url="http://custom:9000/mcp",
        )

        assert wrapper.mcp_url == "http://custom:9000/mcp"

    def test_mcp_url_defaults_to_localhost(self, mock_ai_client):
        """Wrapper must default mcp_url to localhost:8000/mcp."""
        from app.services.rag.llm_provider import AISuiteLLMWrapper

        wrapper = AISuiteLLMWrapper(
            client=mock_ai_client,
            model="openai:gpt-4o-mini",
            max_tokens=1000,
            temperature=0.1,
        )

        assert wrapper.mcp_url == "http://localhost:8000/mcp"


class TestLLMProviderContract:
    """Test the LLMProvider class contract."""

    @pytest.fixture
    def mock_settings(self):
        """Create mock settings."""
        settings = MagicMock()
        settings.OPENAI_API_KEY = "test-key"
        settings.OPENAI_MODEL = "openai:gpt-4o-mini"
        settings.MAX_TOKENS = 1000
        settings.LLM_TEMPERATURE = 0.1
        settings.EMBEDDING_PROVIDER = "openai"
        settings.EMBEDDING_MODEL = "text-embedding-3-small"
        settings.EMBEDDING_DIMENSIONS = None
        return settings

    def test_initialize_embeddings_uses_litellm(self, mock_settings):
        """initialize_embeddings must use LiteLLM provider."""
        with patch("aisuite.Client"):
            with patch(
                "app.services.rag.llm_provider.LiteLLMEmbeddings"
            ) as MockLiteLLM:
                from app.services.rag.llm_provider import LLMProvider

                provider = LLMProvider(mock_settings)
                provider.initialize_embeddings()

                MockLiteLLM.from_settings.assert_called_once_with(mock_settings)

    def test_initialize_llm_returns_wrapper(self, mock_settings):
        """initialize_llm must return AISuiteLLMWrapper."""
        with patch("aisuite.Client"):
            from app.services.rag.llm_provider import AISuiteLLMWrapper, LLMProvider

            provider = LLMProvider(mock_settings)
            llm = provider.initialize_llm(mcp_url="http://test:8000/mcp")

            assert isinstance(llm, AISuiteLLMWrapper)

    def test_initialize_llm_passes_mcp_url(self, mock_settings):
        """initialize_llm must pass MCP URL to wrapper."""
        with patch("aisuite.Client"):
            from app.services.rag.llm_provider import LLMProvider

            provider = LLMProvider(mock_settings)
            llm = provider.initialize_llm(mcp_url="http://custom:9000/mcp")

            assert llm.mcp_url == "http://custom:9000/mcp"

    def test_raises_without_api_key(self):
        """Must raise ValueError if API key missing."""
        settings = MagicMock()
        settings.OPENAI_API_KEY = None

        with patch("aisuite.Client"):
            from app.services.rag.llm_provider import LLMProvider

            provider = LLMProvider(settings)

            with pytest.raises(ValueError):
                provider.initialize_llm()

    def test_initialize_embeddings_returns_litellm_instance(self, mock_settings):
        """initialize_embeddings must return LiteLLMEmbeddings instance."""
        with patch("aisuite.Client"):
            with patch(
                "app.services.rag.llm_provider.LiteLLMEmbeddings"
            ) as MockLiteLLM:
                mock_embeddings = MagicMock()
                MockLiteLLM.from_settings.return_value = mock_embeddings

                from app.services.rag.llm_provider import LLMProvider

                provider = LLMProvider(mock_settings)
                result = provider.initialize_embeddings()

                assert result == mock_embeddings


class TestLLMProviderNoLegacyCode:
    """Verify legacy code patterns are removed."""

    def test_no_convert_mcp_tools_function(self):
        """convert_mcp_tools_to_openai_format should not exist."""
        from app.services.rag import llm_provider

        assert not hasattr(llm_provider, "convert_mcp_tools_to_openai_format")

    def test_no_direct_openai_client(self):
        """AISuiteLLMWrapper should not have openai_client attribute."""
        with patch("aisuite.Client") as MockClient:
            mock_client = MagicMock()
            MockClient.return_value = mock_client

            from app.services.rag.llm_provider import AISuiteLLMWrapper

            wrapper = AISuiteLLMWrapper(
                client=mock_client,
                model="openai:gpt-4o-mini",
                max_tokens=1000,
                temperature=0.1,
            )

            assert not hasattr(wrapper, "openai_client")

    def test_no_openai_model_attribute(self):
        """AISuiteLLMWrapper should not have openai_model attribute."""
        with patch("aisuite.Client") as MockClient:
            mock_client = MagicMock()
            MockClient.return_value = mock_client

            from app.services.rag.llm_provider import AISuiteLLMWrapper

            wrapper = AISuiteLLMWrapper(
                client=mock_client,
                model="openai:gpt-4o-mini",
                max_tokens=1000,
                temperature=0.1,
            )

            assert not hasattr(wrapper, "openai_model")

    def test_invoke_with_tools_no_tools_parameter(self):
        """invoke_with_tools must NOT accept tools parameter."""
        import inspect

        from app.services.rag.llm_provider import AISuiteLLMWrapper

        sig = inspect.signature(AISuiteLLMWrapper.invoke_with_tools)
        param_names = list(sig.parameters.keys())

        assert "tools" not in param_names

"""Tests for LLM provider review fixes (findings A5, A6, A7).

- A5: system-message support in invoke() and invoke_with_tools()
- A6: grounded default temperature
- A7: per-model completion parameter adaptation for reasoning models
"""

from unittest.mock import MagicMock

import pytest
from app.services.rag.llm_provider import AISuiteLLMWrapper, _completion_params


@pytest.fixture
def mock_ai_client():
    return MagicMock()


@pytest.fixture
def mock_response():
    response = MagicMock()
    response.choices = [MagicMock()]
    response.choices[0].message.content = "Test response"
    response.choices[0].intermediate_messages = []
    response.usage = MagicMock()
    response.usage.prompt_tokens = 10
    response.usage.completion_tokens = 20
    response.usage.total_tokens = 30
    return response


def _make_wrapper(client, model="openai:gpt-4.1-nano"):
    return AISuiteLLMWrapper(
        client=client,
        model=model,
        max_tokens=500,
        temperature=0.2,
    )


class TestSystemMessageSupport:
    """A5: persona/guardrails must be sent at system trust level."""

    def test_invoke_with_system_content_sends_system_and_user_roles(
        self, mock_ai_client, mock_response
    ):
        mock_ai_client.chat.completions.create.return_value = mock_response
        wrapper = _make_wrapper(mock_ai_client)

        wrapper.invoke("What is Bisq?", system_content="GUARDRAILS: be safe.")

        messages = mock_ai_client.chat.completions.create.call_args[1]["messages"]
        assert messages == [
            {"role": "system", "content": "GUARDRAILS: be safe."},
            {"role": "user", "content": "What is Bisq?"},
        ]

    def test_invoke_without_system_content_sends_single_user_message(
        self, mock_ai_client, mock_response
    ):
        mock_ai_client.chat.completions.create.return_value = mock_response
        wrapper = _make_wrapper(mock_ai_client)

        wrapper.invoke("What is Bisq?")

        messages = mock_ai_client.chat.completions.create.call_args[1]["messages"]
        assert messages == [{"role": "user", "content": "What is Bisq?"}]

    def test_invoke_with_tools_supports_system_content(
        self, mock_ai_client, mock_response
    ):
        mock_ai_client.chat.completions.create.return_value = mock_response
        wrapper = _make_wrapper(mock_ai_client)

        wrapper.invoke_with_tools(
            "What is Bisq?", system_content="GUARDRAILS: be safe."
        )

        messages = mock_ai_client.chat.completions.create.call_args[1]["messages"]
        assert messages[0] == {"role": "system", "content": "GUARDRAILS: be safe."}
        assert messages[1] == {"role": "user", "content": "What is Bisq?"}


class TestCompletionParams:
    """A7: reasoning-model families need adapted completion parameters."""

    @pytest.mark.parametrize(
        "model_id,expected",
        [
            ("openai:gpt-4.1-nano", {"temperature": 0.2, "max_tokens": 100}),
            ("openai:o4-mini", {"max_completion_tokens": 100}),
            ("openai:o1-preview", {"max_completion_tokens": 100}),
            ("openai:o3", {"max_completion_tokens": 100}),
            ("openai:gpt-5-nano", {"max_completion_tokens": 100}),
            ("xai:grok-3", {"temperature": 0.2, "max_tokens": 100}),
        ],
    )
    def test_completion_params_per_model(self, model_id, expected):
        assert _completion_params(model_id, temperature=0.2, max_tokens=100) == expected

    def test_invoke_uses_max_completion_tokens_for_reasoning_model(
        self, mock_ai_client, mock_response
    ):
        mock_ai_client.chat.completions.create.return_value = mock_response
        wrapper = _make_wrapper(mock_ai_client, model="openai:o4-mini")

        wrapper.invoke("What is Bisq?")

        call_kwargs = mock_ai_client.chat.completions.create.call_args[1]
        assert call_kwargs["max_completion_tokens"] == 500
        assert "max_tokens" not in call_kwargs
        assert "temperature" not in call_kwargs

    def test_invoke_keeps_standard_params_for_standard_model(
        self, mock_ai_client, mock_response
    ):
        mock_ai_client.chat.completions.create.return_value = mock_response
        wrapper = _make_wrapper(mock_ai_client, model="openai:gpt-4.1-nano")

        wrapper.invoke("What is Bisq?")

        call_kwargs = mock_ai_client.chat.completions.create.call_args[1]
        assert call_kwargs["max_tokens"] == 500
        assert call_kwargs["temperature"] == 0.2
        assert "max_completion_tokens" not in call_kwargs

    def test_invoke_with_tools_adapts_params_for_reasoning_model(
        self, mock_ai_client, mock_response
    ):
        mock_ai_client.chat.completions.create.return_value = mock_response
        wrapper = _make_wrapper(mock_ai_client, model="openai:gpt-5-nano")

        wrapper.invoke_with_tools("What is Bisq?")

        call_kwargs = mock_ai_client.chat.completions.create.call_args[1]
        assert call_kwargs["max_completion_tokens"] == 500
        assert "max_tokens" not in call_kwargs
        assert "temperature" not in call_kwargs


class TestDefaultTemperature:
    """A6: grounded answer path must default to a low temperature."""

    def test_default_llm_temperature_is_grounded(self):
        from app.core.config import Settings

        assert Settings.model_fields["LLM_TEMPERATURE"].default == 0.2

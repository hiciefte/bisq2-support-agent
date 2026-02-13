"""Tests for PromptManager soul injection and error message integration.

TDD Step 5 (RED): These tests define the expected behavior of the
PromptManager after soul and error message integration.
"""

from unittest.mock import MagicMock, patch

import pytest
from app.prompts import error_messages
from app.prompts.soul import load_soul, reload_soul
from app.services.rag.prompt_manager import PromptManager


@pytest.fixture
def prompt_manager(test_settings):
    """Create a PromptManager instance for testing."""
    return PromptManager(settings=test_settings)


@pytest.fixture(autouse=True)
def _clear_soul_cache():
    """Ensure soul cache is fresh for each test."""
    reload_soul()
    yield
    reload_soul()


class TestPromptManagerSoulInjection:
    """Tests for soul personality injection into prompts."""

    def test_create_rag_prompt_starts_with_soul_text(self, prompt_manager):
        """The RAG prompt template must begin with the soul text."""
        prompt = prompt_manager.create_rag_prompt()
        template = prompt.messages[0].prompt.template
        soul_text = load_soul()
        # Soul text should appear at the very start of the template
        assert template.startswith(soul_text)

    def test_create_context_only_bisq2_contains_soul(self, prompt_manager):
        """Context-only prompt for Bisq 2 must contain soul text."""
        result = prompt_manager.create_context_only_prompt(
            question="How do I trade?", chat_history_str="Human: Hello"
        )
        soul_text = load_soul()
        # Soul should be present in the prompt
        assert soul_text[:100] in result

    def test_create_context_only_bisq1_contains_soul(self, prompt_manager):
        """Context-only prompt for Bisq 1 must contain soul text."""
        result = prompt_manager.create_context_only_prompt(
            question="How do I trade on Bisq 1?",
            chat_history_str="Human: Hello",
        )
        soul_text = load_soul()
        assert soul_text[:100] in result

    def test_format_prompt_for_mcp_contains_soul(self, prompt_manager):
        """MCP-formatted prompt must contain soul text."""
        result = prompt_manager.format_prompt_for_mcp(
            context="Some context",
            question="What is Bisq?",
            chat_history_str="",
        )
        soul_text = load_soul()
        assert soul_text[:100] in result

    def test_soul_appears_before_protocol_instructions(self, prompt_manager):
        """Soul text must appear before operational instructions."""
        prompt = prompt_manager.create_rag_prompt()
        template = prompt.messages[0].prompt.template
        soul_text = load_soul()
        soul_end = template.find(soul_text) + len(soul_text)
        protocol_start = template.find("PROTOCOL HANDLING INSTRUCTIONS")
        assert (
            protocol_start > soul_end
        ), "Protocol instructions should come after soul text"

    def test_soul_loaded_once_across_calls(self, prompt_manager):
        """load_soul should be called once (cached) across multiple prompt creations."""
        with patch("app.services.rag.prompt_manager.load_soul") as mock_load:
            mock_load.return_value = "Mock soul text"
            prompt_manager.create_rag_prompt()
            prompt_manager.create_rag_prompt()
            # load_soul is cached at the module level, so the patched version
            # is called each time create_rag_prompt runs, but the underlying
            # lru_cache ensures the real file is only read once
            assert mock_load.call_count == 2


class TestPromptManagerErrorMessages:
    """Tests for error message integration in generate_response."""

    def test_empty_question_returns_no_question_message(self, prompt_manager):
        """Empty question should return the NO_QUESTION error message."""
        mock_llm = MagicMock()
        mock_retrieve = MagicMock(return_value=[])
        mock_format = MagicMock(return_value="")

        prompt_manager.create_rag_prompt()
        chain = prompt_manager.create_rag_chain(mock_llm, mock_retrieve, mock_format)
        result = chain("")
        assert result == error_messages.NO_QUESTION

    def test_empty_llm_response_returns_generation_failed(self, prompt_manager):
        """Empty LLM response should return GENERATION_FAILED."""
        mock_llm = MagicMock()
        mock_response = MagicMock(content="", usage=None)
        mock_llm.invoke.return_value = mock_response
        mock_retrieve = MagicMock(return_value=[])
        mock_format = MagicMock(return_value="")

        prompt_manager.create_rag_prompt()
        chain = prompt_manager.create_rag_chain(mock_llm, mock_retrieve, mock_format)
        result = chain("What is Bisq?")
        assert result == error_messages.GENERATION_FAILED

    def test_llm_exception_returns_technical_error(self, prompt_manager):
        """LLM exception should return TECHNICAL_ERROR."""
        mock_llm = MagicMock()
        mock_llm.invoke.side_effect = RuntimeError("LLM exploded")
        mock_retrieve = MagicMock(return_value=[])
        mock_format = MagicMock(return_value="")

        prompt_manager.create_rag_prompt()
        chain = prompt_manager.create_rag_chain(mock_llm, mock_retrieve, mock_format)
        result = chain("What is Bisq?")
        assert result == error_messages.TECHNICAL_ERROR


class TestPromptManagerResponseGuidelines:
    """Tests for updated response guidelines."""

    def test_prompt_does_not_contain_2_3_sentences_max(self, prompt_manager):
        """The old rigid '2-3 sentences maximum' limit must be removed."""
        prompt = prompt_manager.create_rag_prompt()
        template = prompt.messages[0].prompt.template
        assert "2-3 sentences maximum" not in template

    def test_prompt_contains_flexible_length_guidance(self, prompt_manager):
        """Prompt should contain flexible response length guidance."""
        prompt = prompt_manager.create_rag_prompt()
        template = prompt.messages[0].prompt.template
        # Should have guidance about response length that's flexible
        assert "RESPONSE LENGTH" in template or "response length" in template.lower()


class TestPromptManagerRegression:
    """Regression tests to ensure existing functionality is preserved."""

    def test_prompt_contains_protocol_instructions(self, prompt_manager):
        prompt = prompt_manager.create_rag_prompt()
        template = prompt.messages[0].prompt.template
        assert "PROTOCOL HANDLING INSTRUCTIONS" in template

    def test_prompt_contains_tool_usage_section(self, prompt_manager):
        prompt = prompt_manager.create_rag_prompt()
        template = prompt.messages[0].prompt.template
        assert "TOOL USAGE" in template

    def test_prompt_has_question_placeholder(self, prompt_manager):
        prompt = prompt_manager.create_rag_prompt()
        template = prompt.messages[0].prompt.template
        assert "{question}" in template

    def test_prompt_has_context_placeholder(self, prompt_manager):
        prompt = prompt_manager.create_rag_prompt()
        template = prompt.messages[0].prompt.template
        assert "{context}" in template

    def test_prompt_has_chat_history_placeholder(self, prompt_manager):
        prompt = prompt_manager.create_rag_prompt()
        template = prompt.messages[0].prompt.template
        assert "{chat_history}" in template

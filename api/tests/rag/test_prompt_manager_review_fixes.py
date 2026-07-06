"""Tests for PromptManager review fixes (findings A2, A3, A4, A5, A8).

- A4: single-pass placeholder substitution (no injection via user input)
- A3: context-only prompt honors the detected version
- A5: prompt split into system/user message contents
- A2: RAG chain accepts pre-retrieved documents (no second retrieval)
- A8: MCP prompt path truncates oversized context
"""

import re
from unittest.mock import MagicMock

import pytest
from app.services.rag.prompt_manager import PromptManager
from langchain_core.documents import Document


@pytest.fixture
def prompt_manager(test_settings):
    return PromptManager(settings=test_settings)


class TestPlaceholderInjection:
    """A4: substituted values must never be re-scanned for placeholders."""

    def test_question_containing_context_placeholder_is_not_expanded(
        self, prompt_manager
    ):
        prompt = prompt_manager.create_rag_prompt()
        question = "What does {context} mean in templates?"
        formatted = prompt.format(
            question=question,
            chat_history="",
            context="CTX_SENTINEL documentation text",
        )
        assert formatted.count("CTX_SENTINEL documentation text") == 1
        assert question in formatted

    def test_question_containing_chat_history_placeholder_is_not_expanded(
        self, prompt_manager
    ):
        prompt = prompt_manager.create_rag_prompt()
        question = "Why does {chat_history} appear here?"
        formatted = prompt.format(
            question=question,
            chat_history="HIST_SENTINEL previous exchange",
            context="",
        )
        assert formatted.count("HIST_SENTINEL previous exchange") == 1
        assert question in formatted

    def test_mcp_prompt_is_not_vulnerable_to_placeholder_injection(
        self, prompt_manager
    ):
        result = prompt_manager.format_prompt_for_mcp(
            context="CTX_SENTINEL docs",
            question="tell me about {context} please",
            chat_history_str="",
        )
        assert result.count("CTX_SENTINEL docs") == 1
        assert "tell me about {context} please" in result

    def test_unknown_placeholders_are_left_untouched(self, prompt_manager):
        prompt = prompt_manager.create_rag_prompt()
        formatted = prompt.format(question="q", chat_history="", context="c")
        # Template contains no other placeholders, but formatting must not
        # crash or mangle literal braces that are not known keys.
        assert "{question}" not in formatted


class TestContextOnlyDetectedVersion:
    """A3: detected version must drive the context-only policy block."""

    def test_detected_bisq1_forces_multisig_policy(self, prompt_manager):
        result = prompt_manager.create_context_only_prompt(
            question="How do I reopen my dispute?",
            chat_history_str="Human: I'm using Bisq 1",
            detected_version="Bisq 1",
        )
        assert "The user asked about Bisq 1" in result
        assert "The user asked about Bisq 2/Bisq Easy" not in result

    def test_detected_multisig_protocol_forces_multisig_policy(self, prompt_manager):
        result = prompt_manager.create_context_only_prompt(
            question="How do I reopen my dispute?",
            chat_history_str="Human: I'm using Bisq 1",
            detected_version="multisig_v1",
        )
        assert "The user asked about Bisq 1" in result

    def test_detected_bisq2_uses_bisq2_policy(self, prompt_manager):
        result = prompt_manager.create_context_only_prompt(
            question="How do I complete my trade?",
            chat_history_str="Human: hi",
            detected_version="Bisq 2",
        )
        assert "The user asked about Bisq 2/Bisq Easy" in result

    def test_no_detected_version_falls_back_to_question_text(self, prompt_manager):
        result = prompt_manager.create_context_only_prompt(
            question="How does multisig work?",
            chat_history_str="Human: hi",
        )
        assert "The user asked about Bisq 1" in result


class TestPromptMessageSplit:
    """A5: prompts are split into system content and user question."""

    def test_format_prompt_messages_splits_system_and_user(self, prompt_manager):
        system_content, user_content = prompt_manager.format_prompt_messages(
            question="How do I trade?",
            chat_history_str="Human: hi",
            context="Some docs about trading",
        )
        assert "Question: How do I trade?" in user_content
        assert "How do I trade?" not in system_content
        # Guardrails and the untrusted-data boundary live in the system message.
        assert "ANSWER CONTRACT" in system_content
        assert "UNTRUSTED DATA BOUNDARY" in system_content
        # Chat history and retrieved context stay at user trust level.
        assert "Human: hi" in user_content
        assert "Some docs about trading" in user_content
        assert "Human: hi" not in system_content
        assert "Some docs about trading" not in system_content

    def test_format_prompt_messages_truncates_context(
        self, prompt_manager, test_settings
    ):
        oversized = "y" * (test_settings.MAX_CONTEXT_LENGTH + 500)
        _, user_content = prompt_manager.format_prompt_messages(
            question="q?",
            chat_history_str="",
            context=oversized,
        )
        longest_run = max(
            (len(run) for run in re.findall(r"y+", user_content)), default=0
        )
        assert longest_run <= test_settings.MAX_CONTEXT_LENGTH

    def test_context_only_prompt_messages_split(self, prompt_manager):
        system_content, user_content = (
            prompt_manager.create_context_only_prompt_messages(
                question="What did I ask before?",
                chat_history_str="Human: What is Bisq Easy?",
                detected_version="Bisq 2",
            )
        )
        assert "Question: What did I ask before?" in user_content
        assert "What did I ask before?" not in system_content
        assert "CONTEXT-ONLY FALLBACK" in system_content
        assert "UNTRUSTED DATA BOUNDARY" in system_content
        assert "Human: What is Bisq Easy?" in user_content
        assert "Human: What is Bisq Easy?" not in system_content

    def test_chat_history_messages_are_bounded(self, prompt_manager, test_settings):
        test_settings.MAX_CHAT_HISTORY_LENGTH = 2
        test_settings.MAX_CHAT_HISTORY_MESSAGE_LENGTH = 12
        formatted = prompt_manager.format_chat_history(
            [
                {"role": "user", "content": "old message"},
                {"role": "assistant", "content": "older answer"},
                {"role": "user", "content": "x" * 40},
            ]
        )

        assert "old message" not in formatted
        assert "older answer" in formatted
        assert "x" * 40 not in formatted
        assert "[truncated]" in formatted


class TestRagChainPreRetrievedDocs:
    """A2: the chain must use provided docs instead of re-retrieving."""

    def _make_chain(self, prompt_manager, llm=None, retrieve=None, fmt=None):
        llm = llm or MagicMock()
        llm.invoke.return_value = MagicMock(content="chain answer", usage=None)
        retrieve = retrieve if retrieve is not None else MagicMock(return_value=[])
        fmt = fmt if fmt is not None else MagicMock(return_value="ctx")
        prompt_manager.create_rag_prompt()
        chain = prompt_manager.create_rag_chain(llm, retrieve, fmt)
        return chain, llm, retrieve, fmt

    def test_chain_skips_internal_retrieval_when_docs_provided(self, prompt_manager):
        chain, llm, retrieve, fmt = self._make_chain(prompt_manager)
        docs = [Document(page_content="pre-retrieved content", metadata={})]

        result = chain("What is Bisq?", [], docs=docs)

        retrieve.assert_not_called()
        fmt.assert_called_once_with(docs)
        assert result == "chain answer"

    def test_chain_still_retrieves_when_docs_not_provided(self, prompt_manager):
        chain, llm, retrieve, fmt = self._make_chain(prompt_manager)

        result = chain("What is Bisq?", [])

        retrieve.assert_called_once_with("What is Bisq?")
        assert result == "chain answer"

    def test_chain_generation_context_matches_provided_docs(self, prompt_manager):
        llm = MagicMock()
        llm.invoke.return_value = MagicMock(content="chain answer", usage=None)
        docs = [Document(page_content="DOC_SENTINEL body", metadata={})]
        chain, llm, retrieve, fmt = self._make_chain(
            prompt_manager,
            llm=llm,
            fmt=MagicMock(side_effect=lambda d: "\n".join(x.page_content for x in d)),
        )

        chain("What is Bisq?", [], docs=docs)

        invoked_content = " ".join(
            " ".join(str(a) for a in call.args)
            + " ".join(str(v) for v in call.kwargs.values())
            for call in llm.invoke.call_args_list
        )
        assert "DOC_SENTINEL body" in invoked_content


class TestMcpContextTruncation:
    """A8: MCP prompt path must truncate oversized context."""

    def test_format_prompt_for_mcp_truncates_oversized_context(
        self, prompt_manager, test_settings
    ):
        oversized = "z" * (test_settings.MAX_CONTEXT_LENGTH + 500)
        result = prompt_manager.format_prompt_for_mcp(
            context=oversized,
            question="What is Bisq?",
            chat_history_str="",
        )
        longest_run = max((len(run) for run in re.findall(r"z+", result)), default=0)
        assert longest_run <= test_settings.MAX_CONTEXT_LENGTH

    def test_format_prompt_for_mcp_keeps_short_context_intact(
        self, prompt_manager, test_settings
    ):
        context = "short context body"
        result = prompt_manager.format_prompt_for_mcp(
            context=context,
            question="What is Bisq?",
            chat_history_str="",
        )
        assert context in result

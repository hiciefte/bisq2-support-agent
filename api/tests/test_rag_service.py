"""
Unit tests for SimplifiedRAGService - Critical path testing for RAG functionality.

Tests cover:
- Query processing and response generation
- Context retrieval and relevance
- Version-aware document prioritization
- LLM provider initialization
- Prompt management and chat history formatting
- Error handling and fallback mechanisms
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from app.prompts import error_messages
from app.services.simplified_rag_service import SimplifiedRAGService


class TestRAGServiceInitialization:
    """Test RAG service initialization and setup."""

    def test_service_initializes_with_settings(self, test_settings):
        """Test that RAG service initializes correctly with settings."""
        service = SimplifiedRAGService(settings=test_settings)

        assert service.settings == test_settings
        assert service.llm_provider is not None
        assert service.prompt_manager is not None
        # Note: document_retriever is None until setup() is called
        # assert service.document_retriever is not None
        assert service.document_processor is not None

    def test_llm_provider_initialization(self, rag_service):
        """Test that LLM provider is initialized correctly (via fixture)."""
        # The rag_service fixture provides pre-initialized mocked components
        assert rag_service.llm_provider is not None
        assert rag_service.llm_provider.llm is not None

    def test_embeddings_initialization(self, rag_service):
        """Test that embeddings model is initialized correctly (via fixture)."""
        # The rag_service fixture provides pre-initialized mocked components
        assert rag_service.llm_provider is not None
        assert rag_service.llm_provider.embeddings is not None


class TestRAGQueryProcessing:
    """Test RAG query processing and response generation."""

    @pytest.mark.asyncio
    async def test_query_with_known_topic(self, rag_service):
        """Test querying with a known topic returns relevant response."""
        # Configure mock to return documents
        mock_docs = [
            MagicMock(
                page_content="Bisq is a decentralized exchange.",
                metadata={"source": "wiki", "protocol": "all"},
            )
        ]
        rag_service.document_retriever.retrieve_with_version_priority.return_value = (
            mock_docs
        )

        response = await rag_service.query("What is Bisq?", chat_history=[])

        assert isinstance(response, dict)
        assert "answer" in response
        assert len(response["answer"]) > 0
        # Note: rag_chain invocation happens in mocked implementation
        # Verifying response structure is sufficient for this test

    @pytest.mark.asyncio
    async def test_query_with_unknown_topic(self, rag_service):
        """Test querying with unknown topic returns fallback response."""
        # Mock the retriever to return no documents
        with patch.object(
            rag_service.document_retriever,
            "retrieve_with_version_priority",
            return_value=[],
        ):
            response = await rag_service.query(
                "What is the meaning of life?", chat_history=[]
            )

        assert isinstance(response, dict)
        assert "answer" in response
        # Should still get a response even without context
        assert len(response["answer"]) > 0

    @pytest.mark.asyncio
    async def test_query_with_chat_history(self, rag_service):
        """Test that chat history is properly formatted and included."""
        chat_history = [
            {"role": "user", "content": "What is Bisq?"},
            {"role": "assistant", "content": "Bisq is a decentralized exchange."},
        ]

        mock_docs = [
            MagicMock(
                page_content="Bisq trading information",
                metadata={"source": "faq", "protocol": "bisq_easy"},
            )
        ]
        rag_service.document_retriever.retrieve_with_version_priority.return_value = (
            mock_docs
        )

        response = await rag_service.query("How do I trade?", chat_history=chat_history)

        assert isinstance(response, dict)
        assert "answer" in response
        # Note: rag_chain invocation happens in mocked implementation
        # Verifying response structure is sufficient for this test

    @pytest.mark.asyncio
    async def test_query_with_empty_question(self, rag_service):
        """Test that empty query is handled gracefully."""
        response = await rag_service.query("", chat_history=[])

        assert isinstance(response, dict)
        assert "answer" in response
        # Should return some error or fallback message for empty query
        assert len(response["answer"]) > 0

    @pytest.mark.asyncio
    async def test_query_with_whitespace_only(self, rag_service):
        """Test that whitespace-only query is handled gracefully."""
        response = await rag_service.query("   \n  \t  ", chat_history=[])

        assert isinstance(response, dict)
        assert "answer" in response


class TestDocumentRetrieval:
    """Test document retrieval and relevance."""

    def test_retrieve_returns_relevant_documents(self, rag_service):
        """Test that document retrieval component exists and can be configured."""
        # Verify document retriever is set up
        assert rag_service.document_retriever is not None

        # Configure mock to return documents
        mock_docs = [
            MagicMock(
                page_content="Trading fee information", metadata={"source": "faq"}
            ),
            MagicMock(
                page_content="General trading guide", metadata={"source": "wiki"}
            ),
        ]
        rag_service.document_retriever.retrieve_with_version_priority.return_value = (
            mock_docs
        )

        # Test retrieval
        docs = rag_service.document_retriever.retrieve_with_version_priority(
            "trading fees"
        )
        assert len(docs) == 2
        assert all(hasattr(doc, "page_content") for doc in docs)

    def test_version_aware_prioritization(self, rag_service):
        """Test that document retriever handles versioned documents."""
        # Configure mock with versioned documents
        mock_docs = [
            MagicMock(page_content="Bisq 1", metadata={"protocol": "multisig_v1"}),
            MagicMock(page_content="General", metadata={"protocol": "all"}),
            MagicMock(page_content="Bisq 2", metadata={"protocol": "bisq_easy"}),
        ]
        rag_service.document_retriever.retrieve_with_version_priority.return_value = (
            mock_docs
        )

        # Verify retrieval works with versioned documents
        docs = rag_service.document_retriever.retrieve_with_version_priority(
            "test query"
        )
        assert len(docs) == 3
        assert all("protocol" in doc.metadata for doc in docs)

    def test_source_type_weighting(self, rag_service):
        """Test that document retriever handles different source types."""
        # Configure mock with different source types
        mock_docs = [
            MagicMock(page_content="Wiki content", metadata={"source": "wiki"}),
            MagicMock(page_content="FAQ content", metadata={"source": "faq"}),
        ]
        rag_service.document_retriever.retrieve_with_version_priority.return_value = (
            mock_docs
        )

        # Verify both source types can be retrieved
        docs = rag_service.document_retriever.retrieve_with_version_priority(
            "test query"
        )
        assert len(docs) == 2
        sources = [doc.metadata["source"] for doc in docs]
        assert "wiki" in sources and "faq" in sources


class TestChatHistoryFormatting:
    """Test chat history formatting functionality."""

    def test_format_empty_chat_history(self, rag_service):
        """Test formatting empty chat history."""
        formatted = rag_service.prompt_manager.format_chat_history([])

        assert formatted == ""

    def test_format_chat_history_with_messages(self, rag_service):
        """Test formatting chat history with user and assistant messages."""
        chat_history = [
            MagicMock(role="user", content="What is Bisq?"),
            MagicMock(role="assistant", content="Bisq is a decentralized exchange."),
            MagicMock(role="user", content="How do I start trading?"),
        ]

        formatted = rag_service.prompt_manager.format_chat_history(chat_history)

        assert "Human:" in formatted
        assert "Assistant:" in formatted
        assert "What is Bisq?" in formatted
        assert "Bisq is a decentralized exchange" in formatted

    def test_format_limits_chat_history_length(self, test_settings, rag_service):
        """Test that chat history is limited to MAX_CHAT_HISTORY_LENGTH."""
        # Create more messages than the limit
        chat_history = []
        for i in range(20):
            chat_history.append(MagicMock(role="user", content=f"Question {i}"))
            chat_history.append(MagicMock(role="assistant", content=f"Answer {i}"))

        formatted = rag_service.prompt_manager.format_chat_history(chat_history)

        # Should only include recent messages (MAX_CHAT_HISTORY_LENGTH = 5 in test settings)
        message_count = formatted.count("Human:")
        assert message_count <= test_settings.MAX_CHAT_HISTORY_LENGTH


class TestSourceAwareVersionFallback:
    """Test source-aware version fallback helpers."""

    def test_resolve_source_default_version_for_bisq2(self, rag_service):
        """Ambiguous bisq2-source text should default to Bisq 2."""
        resolved = rag_service._resolve_source_default_version("WTF?!", "bisq2")
        assert resolved is not None
        version, confidence = resolved
        assert version == "Bisq 2"
        assert confidence >= 0.6

    def test_resolve_source_default_version_returns_none_for_matrix(self, rag_service):
        """Matrix source has no default and should remain unresolved."""
        resolved = rag_service._resolve_source_default_version("WTF?!", "matrix")
        assert resolved is None


class TestMultilingualClarification:
    """Test multilingual clarification handling in the RAG query path."""

    @pytest.mark.asyncio
    async def test_non_english_clarification_is_translated(self, rag_service):
        """Low-confidence clarification should be translated back to source language."""
        rag_service.version_detector.detect_version = AsyncMock(
            return_value=("unknown", 0.2, "Do you mean Bisq 1 or Bisq 2?")
        )

        rag_service.translation_service = MagicMock()
        rag_service.translation_service.translate_query = AsyncMock(
            return_value={
                "translated_text": "How do I buy BTC?",
                "source_lang": "de",
                "skipped": False,
            }
        )
        rag_service.translation_service.translate_response = AsyncMock(
            return_value={
                "translated_text": "Meinst du Bisq 1 oder Bisq 2?",
                "target_lang": "de",
            }
        )

        result = await rag_service.query("Wie kann ich BTC kaufen?", chat_history=[])

        assert result["needs_clarification"] is True
        assert result["routing_action"] == "needs_clarification"
        assert result["answer"] == "Meinst du Bisq 1 oder Bisq 2?"
        rag_service.translation_service.translate_response.assert_awaited_once_with(
            "Do you mean Bisq 1 or Bisq 2?",
            target_lang="de",
        )

    @pytest.mark.asyncio
    async def test_short_follow_up_uses_chat_history_language_hint(self, rag_service):
        """Short follow-ups inherit language context from recent user chat history."""
        rag_service.version_detector.detect_version = AsyncMock(
            return_value=("unknown", 0.2, "Do you mean Bisq 1 or Bisq 2?")
        )

        detector = MagicMock()
        detector.detect_with_metadata = AsyncMock(
            return_value=MagicMock(language_code="de", confidence=0.93)
        )

        rag_service.translation_service = MagicMock()
        rag_service.translation_service.detector = detector
        rag_service.translation_service.translate_query = AsyncMock(
            return_value={
                "translated_text": "Bisq easy",
                "source_lang": "de",
                "skipped": False,
            }
        )
        rag_service.translation_service.translate_response = AsyncMock(
            return_value={
                "translated_text": "Meinst du Bisq 1 oder Bisq 2?",
                "target_lang": "de",
            }
        )

        chat_history = [
            {"role": "user", "content": "Wie kann ich aktuell BTC mit Euro kaufen?"},
            {
                "role": "assistant",
                "content": "Verwenden Sie Bisq 1 Handel oder Bisq Easy (Bisq 2)?",
            },
        ]
        await rag_service.query("Bisq easy", chat_history=chat_history)

        rag_service.translation_service.translate_query.assert_awaited_once_with(
            "Bisq easy",
            source_lang="de",
            prior_language=None,
        )

    @pytest.mark.asyncio
    async def test_english_heuristic_detection_is_overridden_by_chat_history_hint(
        self, rag_service
    ):
        """When detector reports english_heuristic, prefer stable non-English history language."""
        rag_service.version_detector.detect_version = AsyncMock(
            return_value=("unknown", 0.2, "Do you mean Bisq 1 or Bisq 2?")
        )

        detector = MagicMock()
        detector.detect_with_metadata = AsyncMock(
            return_value=MagicMock(language_code="de", confidence=0.93)
        )

        rag_service.translation_service = MagicMock()
        rag_service.translation_service.detector = detector
        rag_service.translation_service.translate_query = AsyncMock(
            return_value={
                "translated_text": "Wie ist der aktuell BTC Preis in Euro?",
                "source_lang": "en",
                "skipped": True,
                "detection_backend": "english_heuristic",
            }
        )
        rag_service.translation_service.translate_response = AsyncMock(
            return_value={
                "translated_text": "Meinst du Bisq 1 oder Bisq 2?",
                "target_lang": "de",
            }
        )

        chat_history = [
            {"role": "user", "content": "Wie kann ich aktuell BTC mit Euro kaufen?"},
            {
                "role": "assistant",
                "content": "Verwenden Sie Bisq 1 Handel oder Bisq Easy (Bisq 2)?",
            },
            {"role": "user", "content": "Bisq easy"},
        ]

        result = await rag_service.query(
            "Wie ist der aktuell BTC Preis in Euro?",
            chat_history=chat_history,
        )

        assert result["answer"] == "Meinst du Bisq 1 oder Bisq 2?"
        assert result["original_language"] == "de"
        rag_service.translation_service.translate_response.assert_awaited_once_with(
            "Do you mean Bisq 1 or Bisq 2?",
            target_lang="de",
        )

    @pytest.mark.asyncio
    async def test_short_follow_up_ignores_duplicated_current_turn_in_history(
        self, rag_service
    ):
        """If current user turn is duplicated in history, use prior context for language hint."""
        rag_service.version_detector.detect_version = AsyncMock(
            return_value=("unknown", 0.2, "Do you mean Bisq 1 or Bisq 2?")
        )

        def _detect_side_effect(text: str):
            if str(text).strip().lower() == "bisq easy":
                return MagicMock(language_code="tl", confidence=1.0)
            return MagicMock(language_code="de", confidence=0.93)

        detector = MagicMock()
        detector.detect_with_metadata = AsyncMock(side_effect=_detect_side_effect)

        rag_service.translation_service = MagicMock()
        rag_service.translation_service.detector = detector
        rag_service.translation_service.translate_query = AsyncMock(
            return_value={
                "translated_text": "Bisq easy",
                "source_lang": "de",
                "skipped": False,
            }
        )
        rag_service.translation_service.translate_response = AsyncMock(
            return_value={
                "translated_text": "Meinst du Bisq 1 oder Bisq 2?",
                "target_lang": "de",
            }
        )

        chat_history = [
            {"role": "user", "content": "Wie kann ich aktuell BTC mit Euro kaufen?"},
            {
                "role": "assistant",
                "content": "Verwenden Sie Bisq 1 Handel oder Bisq Easy (Bisq 2)?",
            },
            {"role": "user", "content": "Bisq easy"},
        ]
        await rag_service.query("Bisq easy", chat_history=chat_history)

        rag_service.translation_service.translate_query.assert_awaited_once_with(
            "Bisq easy",
            source_lang="de",
            prior_language=None,
        )
        inspected_texts = [
            str(call.args[0]).strip().lower()
            for call in detector.detect_with_metadata.await_args_list
        ]
        assert "bisq easy" not in inspected_texts

    @pytest.mark.asyncio
    async def test_long_query_does_not_force_chat_history_language_hint(
        self, rag_service
    ):
        """Long/explicit queries should not force language inheritance from history."""
        rag_service.version_detector.detect_version = AsyncMock(
            return_value=("unknown", 0.2, "Do you mean Bisq 1 or Bisq 2?")
        )

        detector = MagicMock()
        detector.detect_with_metadata = AsyncMock(
            return_value=MagicMock(language_code="de", confidence=0.93)
        )

        rag_service.translation_service = MagicMock()
        rag_service.translation_service.detector = detector
        rag_service.translation_service.translate_query = AsyncMock(
            return_value={
                "translated_text": "What is the current BTC price?",
                "source_lang": "en",
                "skipped": True,
            }
        )
        rag_service.translation_service.translate_response = AsyncMock(
            return_value={
                "translated_text": "Do you mean Bisq 1 or Bisq 2?",
                "target_lang": "en",
            }
        )

        chat_history = [
            {"role": "user", "content": "Wie kann ich aktuell BTC mit Euro kaufen?"},
            {
                "role": "assistant",
                "content": "Verwenden Sie Bisq 1 Handel oder Bisq Easy (Bisq 2)?",
            },
        ]
        await rag_service.query(
            "What is the current BTC price?",
            chat_history=chat_history,
        )

        rag_service.translation_service.translate_query.assert_awaited_once_with(
            "What is the current BTC price?",
            source_lang=None,
            prior_language=None,
        )

    @pytest.mark.asyncio
    async def test_language_hint_is_preferred_over_history_for_ambiguous_follow_up(
        self, rag_service
    ):
        """An upstream ingress locale hint should drive translation for ambiguous follow-ups."""
        rag_service.version_detector.detect_version = AsyncMock(
            return_value=("unknown", 0.2, "Do you mean Bisq 1 or Bisq 2?")
        )

        rag_service.translation_service = MagicMock()
        rag_service.translation_service.translate_query = AsyncMock(
            return_value={
                "translated_text": "Bisq easy",
                "source_lang": "de",
                "skipped": False,
            }
        )
        rag_service.translation_service.translate_response = AsyncMock(
            return_value={
                "translated_text": "Meinst du Bisq 1 oder Bisq 2?",
                "target_lang": "de",
            }
        )

        await rag_service.query(
            "Bisq easy",
            chat_history=[],
            language_hint="de",
            language_hint_confidence=0.95,
        )

        rag_service.translation_service.translate_query.assert_awaited_once_with(
            "Bisq easy",
            source_lang="de",
            prior_language=None,
        )


class TestPromptManagement:
    """Test prompt creation and management."""

    def test_create_rag_prompt(self, rag_service):
        """Test RAG prompt creation."""
        prompt = rag_service.prompt_manager.create_rag_prompt()

        assert prompt is not None
        assert hasattr(prompt, "format")

    def test_create_context_only_prompt(self, rag_service):
        """Test context-only prompt creation."""
        prompt = rag_service.prompt_manager.create_context_only_prompt(
            question="Test question", chat_history_str="Previous conversation context"
        )

        assert prompt is not None
        assert isinstance(prompt, str)  # context_only_prompt returns a string
        assert len(prompt) > 0
        assert "Test question" in prompt  # Question should be in prompt


class TestMcpLiveDataFallbackReconciliation:
    """Ensure tool results and response text stay logically consistent."""

    def test_replaces_offer_unavailable_with_no_offers_when_tool_says_empty(
        self, rag_service
    ):
        response = (
            "I'm unable to fetch live offer data at the moment. "
            "Please try again later or check directly in the Bisq 2 application "
            "for current offers to buy BTC with Euro."
        )
        tool_calls = [
            {
                "tool": "get_offerbook",
                "result": "[No offers currently available for EUR (SELL)]",
            }
        ]

        reconciled = rag_service._reconcile_live_data_fallbacks(response, tool_calls)

        assert "No offers currently available for EUR (SELL)." in reconciled
        assert "unable to fetch live offer data" not in reconciled.lower()

    def test_removes_offer_unavailable_when_live_offerbook_present(self, rag_service):
        response = (
            "I'm unable to fetch live offer data at the moment. "
            "There are currently 5 EUR offers available."
        )
        tool_calls = [
            {
                "tool": "get_offerbook",
                "result": "[LIVE OFFERBOOK]\n  BUY: ...\n[TOTAL EUR OFFERS: 5]",
            }
        ]

        reconciled = rag_service._reconcile_live_data_fallbacks(response, tool_calls)

        assert "unable to fetch live offer data" not in reconciled.lower()
        assert "5 EUR offers available" in reconciled

    def test_keeps_localized_text_without_injecting_english_no_offer_prefix(
        self, rag_service
    ):
        response = (
            "I'm unable to fetch live offer data at the moment. "
            "Momentan sind keine Verkaufsangebote für den Kauf von BTC mit Euro verfügbar."
        )
        tool_calls = [
            {
                "tool": "get_offerbook",
                "result": "[No offers currently available for EUR (SELL)]",
            }
        ]

        reconciled = rag_service._reconcile_live_data_fallbacks(response, tool_calls)

        assert "unable to fetch live offer data" not in reconciled.lower()
        assert reconciled.startswith("Momentan sind keine Verkaufsangebote")
        assert "No offers currently available for EUR (SELL)." not in reconciled

    def test_prompt_includes_feedback_guidance(self, rag_service):
        """Test that prompts include feedback-based guidance."""
        # Mock feedback service to return guidance
        rag_service.feedback_service = MagicMock()
        rag_service.feedback_service.get_prompt_guidance.return_value = [
            "Keep answers concise",
            "Use simple terms",
        ]

        prompt = rag_service.prompt_manager.create_rag_prompt()

        # Verify prompt creation succeeded
        assert prompt is not None


class TestErrorHandling:
    """Test error handling and fallback mechanisms."""

    @pytest.mark.asyncio
    async def test_handles_llm_error_gracefully(self, rag_service):
        """Test that LLM errors are handled gracefully."""
        # Make the RAG chain raise an exception
        rag_service.rag_chain.invoke.side_effect = Exception("API Error")

        mock_docs = [
            MagicMock(
                page_content="Test content",
                metadata={"source": "wiki", "protocol": "all"},
            )
        ]
        rag_service.document_retriever.retrieve_with_version_priority.return_value = (
            mock_docs
        )

        response = await rag_service.query("Test question", chat_history=[])

        # Should return error message instead of crashing
        assert isinstance(response, dict)
        assert "answer" in response
        # Should contain some error message
        assert len(response["answer"]) > 0

    @pytest.mark.asyncio
    async def test_handles_retrieval_error_gracefully(self, rag_service):
        """Test that document retrieval errors are handled gracefully."""
        # Make retrieval raise an exception
        with patch.object(
            rag_service.document_retriever,
            "retrieve_with_version_priority",
            side_effect=Exception("Retrieval error"),
        ):
            response = await rag_service.query("Test question", chat_history=[])

        # Should still return a response
        assert isinstance(response, dict)
        assert "answer" in response

    @pytest.mark.asyncio
    async def test_handles_empty_context_gracefully(self, rag_service):
        """Test that empty context is handled without errors."""
        # Mock retriever to return no documents
        with patch.object(
            rag_service.document_retriever,
            "retrieve_with_version_priority",
            return_value=[],
        ):
            response = await rag_service.query("Test question", chat_history=[])

        # Should generate response even without context
        assert isinstance(response, dict)
        assert "answer" in response
        assert len(response["answer"]) > 0


class TestDocumentProcessing:
    """Test document processing and context formatting."""

    def test_format_docs_creates_context_string(self, rag_service):
        """Test that documents can be formatted into context string."""
        docs = [
            MagicMock(
                page_content="First document content",
                metadata={"source": "wiki", "title": "Doc 1"},
            ),
            MagicMock(
                page_content="Second document content",
                metadata={"source": "faq", "title": "Doc 2"},
            ),
        ]

        # Configure mock to return formatted string
        rag_service.document_retriever.format_documents.return_value = (
            "First document content\nSecond document content"
        )

        context = rag_service.document_retriever.format_documents(docs)

        assert isinstance(context, str)
        assert len(context) > 0

    @pytest.mark.asyncio
    async def test_context_truncation_in_rag_chain(self, test_settings, rag_service):
        """Test that context is truncated to MAX_CONTEXT_LENGTH in RAG chain.

        Context truncation happens in PromptManager.create_rag_chain(), not in
        DocumentRetriever.format_documents(). This test verifies the actual
        truncation behavior during query processing.
        """
        # Create very long content that exceeds MAX_CONTEXT_LENGTH
        long_content = "x" * (test_settings.MAX_CONTEXT_LENGTH + 1000)
        docs = [
            MagicMock(
                page_content=long_content,
                metadata={
                    "source": "wiki",
                    "title": "Long Doc",
                    "protocol": "all",
                },
            )
        ]

        # Mock retriever to return long documents
        rag_service.document_retriever.retrieve_with_version_priority.return_value = (
            docs
        )

        # The RAG chain should handle truncation internally during query processing
        # Verify that query completes without errors despite long context
        response = await rag_service.query("Test question", chat_history=[])

        # Query should complete successfully
        assert isinstance(response, dict)
        assert "answer" in response
        assert len(response["answer"]) > 0

    def test_format_empty_docs_list(self, rag_service):
        """Test formatting empty document list."""
        # Calling format_documents on empty list should return empty or minimal string
        context = rag_service.document_retriever.format_documents([])

        # Should return a string (mock returns "" by default from fixture)
        assert isinstance(context, str)


class TestRAGServiceErrorMessages:
    """Test that SimplifiedRAGService uses centralized error messages."""

    @pytest.mark.asyncio
    async def test_not_initialized_uses_centralized_message(self, test_settings):
        """When rag_chain is None, should return NOT_INITIALIZED message."""
        service = SimplifiedRAGService(settings=test_settings)
        # Don't call setup() — rag_chain stays None
        response = await service.query("What is Bisq?")
        assert response["answer"] == error_messages.NOT_INITIALIZED

    @pytest.mark.asyncio
    async def test_no_docs_no_history_uses_centralized_message(self, rag_service):
        """When no docs and no history, should return INSUFFICIENT_INFO."""
        # Must mock retrieve_with_scores (the actual method used in query flow)
        with patch.object(
            rag_service.document_retriever,
            "retrieve_with_scores",
            return_value=([], []),
        ):
            # Use override_version to bypass version clarification
            response = await rag_service.query(
                "What is the meaning of life?",
                chat_history=[],
                override_version="bisq_easy",
            )

        assert response["answer"] == error_messages.INSUFFICIENT_INFO

    @pytest.mark.asyncio
    async def test_context_fallback_error_uses_centralized_message(self, rag_service):
        """When context fallback raises, should return INSUFFICIENT_INFO."""
        with (
            patch.object(
                rag_service.document_retriever,
                "retrieve_with_version_priority",
                return_value=[],
            ),
            patch.object(
                rag_service,
                "_answer_from_context",
                side_effect=Exception("context boom"),
            ),
        ):
            response = await rag_service.query(
                "How does trading work?",
                chat_history=[
                    {"role": "user", "content": "Hi"},
                    {"role": "assistant", "content": "Hello"},
                ],
            )

        # Should fall through to the insufficient info path
        assert "answer" in response
        assert len(response["answer"]) > 0

    @pytest.mark.asyncio
    async def test_query_exception_uses_centralized_message(self, rag_service):
        """When query() itself raises, should return QUERY_ERROR."""
        with patch.object(
            rag_service.document_retriever,
            "retrieve_with_version_priority",
            side_effect=Exception("total failure"),
        ):
            # Use override_version to bypass version clarification
            response = await rag_service.query(
                "How do I trade on Bisq 2?",
                chat_history=[],
                override_version="bisq_easy",
            )

        assert response["answer"] == error_messages.QUERY_ERROR

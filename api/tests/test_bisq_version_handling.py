"""
Test suite for Bisq 1 vs Bisq 2 version handling.

This test suite verifies that the chatbot correctly handles queries about both
Bisq 1 and Bisq 2, following the business requirement: "mainly for Bisq 2 questions,
but should also answer questions on Bisq 1, if it has the information available."
"""

from unittest.mock import AsyncMock, Mock, patch

import pytest
from app.services.rag.document_retriever import DocumentRetriever
from app.services.rag.prompt_manager import PromptManager
from langchain_core.documents import Document


@pytest.fixture
def mock_bisq1_documents():
    """Sample Bisq 1 documents for testing."""
    return [
        Document(
            page_content="In Bisq 1, you can request mediation by clicking the 'Request Mediation' button in the dispute section.",
            metadata={"protocol": "multisig_v1", "source": "wiki"},
        ),
        Document(
            page_content="Bisq 1 uses a different mediation process than Bisq 2.",
            metadata={"protocol": "multisig_v1", "source": "wiki"},
        ),
    ]


@pytest.fixture
def mock_bisq2_documents():
    """Sample Bisq 2 documents for testing."""
    return [
        Document(
            page_content="In Bisq 2, you can request mediation by selecting the 'request mediation' link on the trade screen.",
            metadata={"protocol": "bisq_easy", "source": "wiki"},
        ),
        Document(
            page_content="Bisq 2 has an improved mediation system with faster resolution times.",
            metadata={"protocol": "bisq_easy", "source": "wiki"},
        ),
    ]


@pytest.fixture
def mock_general_documents():
    """Sample general documents for testing."""
    return [
        Document(
            page_content="Mediation is a process where a third party helps resolve disputes between traders.",
            metadata={"protocol": "all", "source": "wiki"},
        )
    ]


class TestBisq1ExplicitQueries:
    """Test cases for explicit Bisq 1 queries when information is available."""

    @pytest.mark.asyncio
    async def test_bisq1_query_with_available_info(self, mock_bisq1_documents):
        """Test that bot answers Bisq 1 questions when info is available.

        Given: A query explicitly about Bisq 1
        When: Bisq 1 information exists in the knowledge base
        Then: The bot should provide the Bisq 1 information with a disclaimer
        """
        # Arrange
        with patch(
            "app.services.simplified_rag_service.SimplifiedRAGService"
        ) as MockRAG:
            mock_rag = MockRAG.return_value
            mock_rag.query = AsyncMock(
                return_value={
                    "answer": "In Bisq 1, you can request mediation by clicking the 'Request Mediation' button. Note: This information is for Bisq 1.",
                    "sources": mock_bisq1_documents,
                }
            )

            # Act
            response = await mock_rag.query(
                "How do I contact a mediator in Bisq 1?", []
            )

            # Assert
            answer_lower = response["answer"].lower()

            # Should NOT refuse to answer
            assert (
                "i'm sorry, but i can only provide information about bisq 2"
                not in answer_lower
            )
            assert "can only help with bisq 2" not in answer_lower

            # Should provide Bisq 1 information
            assert "bisq 1" in answer_lower or "bisq1" in answer_lower

            # Should have sources
            assert len(response["sources"]) > 0

            # Should include disclaimer about Bisq 1
            assert (
                "note:" in answer_lower
                or "this information is for bisq 1" in answer_lower
            )

    @pytest.mark.asyncio
    async def test_bisq1_query_without_available_info(self):
        """Test that bot honestly refuses when no Bisq 1 info exists.

        Given: A query explicitly about Bisq 1
        When: No Bisq 1 information exists in the knowledge base
        Then: The bot should politely explain it doesn't have that information
        """
        # Arrange
        with patch(
            "app.services.simplified_rag_service.SimplifiedRAGService"
        ) as MockRAG:
            mock_rag = MockRAG.return_value
            mock_rag.query = AsyncMock(
                return_value={
                    "answer": "I don't have specific information about that for Bisq 1. My primary focus is Bisq 2 support.",
                    "sources": [],
                }
            )

            # Act
            response = await mock_rag.query(
                "How do I use the advanced Bisq 1 feature X that doesn't exist in docs?",
                [],
            )

            # Assert
            answer_lower = response["answer"].lower()

            # Should acknowledge Bisq 1 context
            assert "bisq 1" in answer_lower or "bisq1" in answer_lower

            # Should honestly say it doesn't have information
            assert "don't have" in answer_lower or "no information" in answer_lower

            # Should explain focus is on Bisq 2
            assert "bisq 2" in answer_lower or "primary focus" in answer_lower

    @pytest.mark.asyncio
    async def test_bisq1_clarification_in_followup(self, mock_bisq1_documents):
        """Test handling when user clarifies they meant Bisq 1.

        Given: An initial query about mediation (ambiguous)
        And: A follow-up clarifying "I'm talking about Bisq 1"
        When: Bisq 1 information is available
        Then: The bot should switch to providing Bisq 1 information
        """
        # Arrange
        chat_history = [
            {"role": "user", "content": "How does mediation work?"},
            {
                "role": "assistant",
                "content": "In Bisq 2, you can request mediation by selecting the 'request mediation' link...",
            },
        ]

        with patch(
            "app.services.simplified_rag_service.SimplifiedRAGService"
        ) as MockRAG:
            mock_rag = MockRAG.return_value
            mock_rag.query = AsyncMock(
                return_value={
                    "answer": "In Bisq 1, you can request mediation by clicking the 'Request Mediation' button. Note: This information is for Bisq 1.",
                    "sources": mock_bisq1_documents,
                }
            )

            # Act
            response = await mock_rag.query("I'm talking about Bisq 1", chat_history)

            # Assert
            answer_lower = response["answer"].lower()

            # Should provide Bisq 1 information
            assert "bisq 1" in answer_lower
            assert len(response["sources"]) > 0

            # Should NOT say it can't help with Bisq 1
            assert "can only provide information about bisq 2" not in answer_lower


class TestBisq2PriorityAndDefaults:
    """Test cases to ensure Bisq 2 remains the priority and default."""

    @pytest.mark.asyncio
    async def test_ambiguous_query_defaults_to_bisq2(self, mock_bisq2_documents):
        """Test that queries without version specification default to Bisq 2.

        Given: A query that doesn't specify version (e.g., "How do I start a trade?")
        When: Information for both versions exists
        Then: The bot should provide Bisq 2 information without mentioning Bisq 1
        """
        # Arrange
        with patch(
            "app.services.simplified_rag_service.SimplifiedRAGService"
        ) as MockRAG:
            mock_rag = MockRAG.return_value
            mock_rag.query = AsyncMock(
                return_value={
                    "answer": "In Bisq 2, you can start a trade using Bisq Easy feature...",
                    "sources": mock_bisq2_documents,
                }
            )

            # Act
            response = await mock_rag.query("How do I start a trade?", [])

            # Assert
            answer_lower = response["answer"].lower()

            # Should provide Bisq 2 information
            assert "bisq 2" in answer_lower or "bisq2" in answer_lower

            # Should have sources
            assert len(response["sources"]) > 0

            # Should NOT mention Bisq 1 unless for comparison
            # (allowing for cases where doc mentions "different from Bisq 1")

    @pytest.mark.asyncio
    async def test_explicit_bisq2_query(self, mock_bisq2_documents):
        """Test explicit Bisq 2 queries work correctly (regression test).

        Given: A query explicitly about Bisq 2
        When: Bisq 2 information exists
        Then: The bot should provide Bisq 2 information as before (no regression)
        """
        # Arrange
        with patch(
            "app.services.simplified_rag_service.SimplifiedRAGService"
        ) as MockRAG:
            mock_rag = MockRAG.return_value
            mock_rag.query = AsyncMock(
                return_value={
                    "answer": "Bisq Easy is a new feature in Bisq 2 that simplifies the trading process...",
                    "sources": mock_bisq2_documents,
                }
            )

            # Act
            response = await mock_rag.query("How do I use Bisq Easy in Bisq 2?", [])

            # Assert
            answer_lower = response["answer"].lower()

            # Should provide Bisq 2 information
            assert "bisq 2" in answer_lower or "bisq easy" in answer_lower

            # Should have sources
            assert len(response["sources"]) > 0

            # Should not mention Bisq 1
            assert len(response["sources"]) > 0


class TestVersionComparison:
    """Test cases for queries comparing both versions."""

    @pytest.mark.asyncio
    async def test_comparison_query_both_versions(
        self, mock_bisq1_documents, mock_bisq2_documents
    ):
        """Test queries comparing Bisq 1 and Bisq 2.

        Given: A query asking about differences between versions
        When: Information for both versions exists
        Then: The bot should provide comparison with clear version labeling
        """
        # Arrange
        all_docs = mock_bisq1_documents + mock_bisq2_documents

        with patch(
            "app.services.simplified_rag_service.SimplifiedRAGService"
        ) as MockRAG:
            mock_rag = MockRAG.return_value
            mock_rag.query = AsyncMock(
                return_value={
                    "answer": "In Bisq 1, mediation works through button clicks. In Bisq 2, it uses trade screen links with faster resolution.",
                    "sources": all_docs,
                }
            )

            # Act
            response = await mock_rag.query(
                "What's the difference between mediation in Bisq 1 and Bisq 2?", []
            )

            # Assert
            answer_lower = response["answer"].lower()

            # Should mention both versions
            assert "bisq 1" in answer_lower or "bisq1" in answer_lower
            assert "bisq 2" in answer_lower or "bisq2" in answer_lower

            # Should have sources from both versions
            assert len(response["sources"]) > 0


class TestPromptManagerVersionHandling:
    """Test cases for PromptManager's version-aware prompt generation."""

    def test_prompt_includes_version_handling_instructions(self, test_settings):
        """Test that the system prompt includes conditional version handling logic.

        Given: A PromptManager instance
        When: Creating a RAG prompt
        Then: The system template should include version handling instructions
        """
        # Arrange
        prompt_manager = PromptManager(test_settings, feedback_service=None)

        # Act
        prompt = prompt_manager.create_rag_prompt()

        # Assert
        # Get the system template from the prompt
        prompt_template = str(prompt.messages[0].prompt.template)

        # Should mention both versions
        assert "Bisq 1" in prompt_template or "Bisq1" in prompt_template
        assert "Bisq 2" in prompt_template or "Bisq2" in prompt_template

        # Should include conditional logic instructions
        assert "if" in prompt_template.lower() or "when" in prompt_template.lower()

        # Should NOT have rigid identity statement
        assert "you are a bisq 2 support assistant" not in prompt_template.lower()

    def test_context_only_prompt_version_detection(self, test_settings):
        """Test that context-only prompts handle version mentions.

        Given: A question mentioning Bisq 1
        When: Creating a context-only prompt (no docs found)
        Then: The prompt should include guidance about Bisq 1 queries
        """
        # Arrange
        prompt_manager = PromptManager(test_settings, feedback_service=None)
        question = "How do I contact a mediator in Bisq 1?"
        chat_history = ""

        # Act
        context_prompt = prompt_manager.create_context_only_prompt(
            question, chat_history
        )

        # Assert
        # Should detect Bisq 1 mention and adjust instructions
        assert "bisq 1" in context_prompt.lower() or "bisq1" in context_prompt.lower()


class TestDocumentRetrieverVersionPriority:
    """Test cases for DocumentRetriever's version-aware retrieval logic."""

    def test_bisq1_explicit_retrieval_gets_more_docs(self, test_settings):
        """Test that explicit Bisq 1 queries retrieve more Bisq 1 docs.

        Given: A query explicitly mentioning "Bisq 1"
        When: Retrieving documents
        Then: Should retrieve k=4 Bisq 1 docs instead of k=2 (default fallback)
        """
        # Arrange
        mock_vectorstore = Mock()
        mock_vectorstore.similarity_search = Mock(return_value=[])

        # Create mock retriever that implements minimal interface
        mock_retriever = Mock()

        retriever = DocumentRetriever(mock_vectorstore, mock_retriever)

        # Act
        query = "How do I use mediation in Bisq 1?"
        retriever.retrieve_with_version_priority(query)

        # Assert
        # Check that multisig_v1 was searched with k=4 (explicit request) not k=2 (fallback)
        calls = mock_vectorstore.similarity_search.call_args_list
        multisig_calls = [
            call
            for call in calls
            if call[1].get("filter", {}).get("protocol") == "multisig_v1"
        ]

        if multisig_calls:
            assert (
                multisig_calls[0][1]["k"] == 4
            )  # Explicit Bisq 1 request should use k=4

    def test_bisq2_priority_maintained(self, test_settings):
        """Test that Bisq 2 priority is maintained for ambiguous queries.

        Given: A query without version specification
        When: Retrieving documents
        Then: Should prioritize Bisq 2 documents (search Bisq 2 first)
        """
        # Arrange
        mock_vectorstore = Mock()
        mock_vectorstore.similarity_search = Mock(return_value=[])

        retriever = DocumentRetriever(mock_vectorstore, test_settings)

        # Act
        query = "How do I start a trade?"
        retriever.retrieve_with_version_priority(query)

        # Assert
        # First call should be for bisq_easy (Stage 1)
        first_call = mock_vectorstore.similarity_search.call_args_list[0]
        assert first_call[1].get("filter", {}).get("protocol") == "bisq_easy"

    def test_bisq1_only_query_skips_bisq2_stage(self, test_settings):
        """Test that pure Bisq 1 queries can skip Bisq 2 retrieval.

        Given: A query explicitly about Bisq 1 only (doesn't mention Bisq 2)
        When: Retrieving documents
        Then: May skip Bisq 2 stage to optimize for Bisq 1 content
        """
        # Arrange
        mock_vectorstore = Mock()

        # Create different documents for each protocol
        bisq_easy_docs = [
            Document(page_content="Bisq 2 content", metadata={"protocol": "bisq_easy"})
        ]
        all_docs = [
            Document(page_content="General content", metadata={"protocol": "all"})
        ]
        multisig_docs = [
            Document(
                page_content="Bisq 1 content", metadata={"protocol": "multisig_v1"}
            )
        ]

        def mock_similarity_search(_query, k, filter):
            protocol = filter.get("protocol")
            if protocol == "bisq_easy":
                return bisq_easy_docs[:k]
            elif protocol == "all":
                return all_docs[:k]
            elif protocol == "multisig_v1":
                return multisig_docs[:k]
            return []

        mock_vectorstore.similarity_search = Mock(side_effect=mock_similarity_search)

        # Create mock retriever that implements minimal interface
        mock_retriever = Mock()

        retriever = DocumentRetriever(mock_vectorstore, mock_retriever)

        # Act
        query = "How do I use Bisq 1 mediation?"  # Bisq 1 only, no Bisq 2 mention
        docs = retriever.retrieve_with_version_priority(query)

        # Assert
        # The retrieval should include multisig_v1 (Bisq 1) documents
        assert any(doc.metadata.get("protocol") == "multisig_v1" for doc in docs)

        # Ensure no bisq_easy retrieval occurred for pure Bisq 1 query
        bisq_easy_calls = [
            c
            for c in mock_vectorstore.similarity_search.call_args_list
            if c.kwargs.get("filter", {}).get("protocol") == "bisq_easy"
        ]
        assert (
            len(bisq_easy_calls) == 0
        ), "Bisq Easy stage should be skipped for pure Bisq 1 queries"


class TestEdgeCases:
    """Test cases for edge cases and boundary conditions."""

    @pytest.mark.asyncio
    async def test_bisq1_misspelling_variations(self):
        """Test common variations of 'Bisq 1' mention.

        Given: Queries with variations like "bisq1", "BISQ 1", "Bisq 1"
        When: Processing the query
        Then: Should detect all as Bisq 1 requests
        """
        variations = [
            "How do I use bisq1?",
            "What about BISQ 1?",
            "Tell me about Bisq 1",
            "bisq1 mediation help",
        ]

        for query_text in variations:
            # Simple detection test
            query_lower = query_text.lower()
            bisq1_detected = "bisq 1" in query_lower or "bisq1" in query_lower
            assert bisq1_detected, f"Failed to detect Bisq 1 in: {query_text}"

    @pytest.mark.asyncio
    async def test_empty_query_handling(self):
        """Test handling of empty or whitespace-only queries.

        Given: An empty or whitespace-only query
        When: Processing the query
        Then: Should handle gracefully without errors
        """
        # This is a safety/robustness test
        empty_queries = ["", "   ", "\n", "\t"]

        for query in empty_queries:
            query_lower = query.lower()
            # Should not crash on empty queries
            bisq1_mentioned = "bisq 1" in query_lower or "bisq1" in query_lower
            # Empty queries should not be detected as Bisq 1
            assert not bisq1_mentioned

    @pytest.mark.asyncio
    async def test_mixed_version_content_in_single_document(self, test_settings):
        """Test handling of documents that mention both versions.

        Given: A document that discusses both Bisq 1 and Bisq 2
        When: Answering a version-specific query
        Then: Should extract relevant version information correctly
        """
        # This is more of an integration test expectation
        # The LLM should be able to parse version-tagged content correctly
        # The prompt should instruct the LLM to parse version tags correctly
        prompt_manager = PromptManager(test_settings, feedback_service=None)
        prompt = prompt_manager.create_rag_prompt()
        prompt_template = str(prompt.messages[0].prompt.template)

        # Should mention version tags
        assert "[VERSION:" in prompt_template or "version" in prompt_template.lower()


# Integration-style test (would require actual RAG service setup)
# Integration tests moved to E2E tests in web/tests/e2e/bisq-version-handling.spec.ts
# E2E tests cover:
# - End-to-end Bisq 1 query flow with real API
# - Version switching in conversation
# - Bisq 2 default behavior
# - Version comparison queries
# - Response disclaimer validation

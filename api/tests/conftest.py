"""
Pytest configuration and fixtures for the bisq2-support-agent API.

This module provides:
- Test settings with isolated test environment
- Database fixtures with cleanup
- Service fixtures with mocked dependencies
- Utility fixtures for common test scenarios
"""

import os
import shutil
import tempfile
from pathlib import Path
from typing import Generator
from unittest.mock import MagicMock

import pytest
import pytest_asyncio
from app.core.config import Settings
from app.db.run_migrations import run_migrations
from app.services.faq_service import FAQService
from app.services.feedback_service import FeedbackService
from app.services.simplified_rag_service import SimplifiedRAGService
from fastapi.testclient import TestClient


@pytest.fixture(scope="session")
def test_data_dir() -> Generator[str, None, None]:
    """Create a temporary directory for test data.

    This fixture creates an isolated data directory for tests to prevent
    interference with actual application data. The directory is automatically
    cleaned up after all tests complete.

    Yields:
        str: Path to the temporary test data directory
    """
    temp_dir = tempfile.mkdtemp(prefix="bisq_test_")
    yield temp_dir
    shutil.rmtree(temp_dir, ignore_errors=True)


@pytest.fixture
def test_settings(test_data_dir: str) -> Settings:
    """Create test settings with isolated test environment.

    This fixture provides a Settings instance configured for testing:
    - Uses temporary data directory
    - Sets debug mode
    - Provides test API keys
    - Uses minimal model configuration

    Note: Changed from scope="session" to default (function) scope to ensure
    proper database isolation between test files.

    Args:
        test_data_dir: Temporary directory for test data

    Returns:
        Settings: Configured settings instance for testing
    """
    settings = Settings(
        DEBUG=True,
        DATA_DIR=test_data_dir,
        OPENAI_API_KEY="test-api-key",
        ADMIN_API_KEY="test-admin-key-with-sufficient-length-24chars",
        ENVIRONMENT="testing",
        COOKIE_SECURE=False,
        # Use minimal model configuration for faster tests
        OPENAI_MODEL="openai:gpt-4o-mini",
        MAX_CHAT_HISTORY_LENGTH=5,
        MAX_CONTEXT_LENGTH=1000,
    )

    # Initialize database and run migrations for test environment
    # This ensures all tests have access to migrated schema
    from app.db.database import get_database

    db_path = os.path.join(test_data_dir, "feedback.db")
    db = get_database()

    # Reset database state to handle singleton pattern across tests
    db.reset()
    db.initialize(db_path)

    # Run migrations after initial schema creation
    run_migrations(db_path)

    # Reset and reinitialize to load migrated schema
    db.reset()
    db.initialize(db_path)

    return settings


@pytest.fixture
def test_client(test_settings: Settings) -> TestClient:
    """Create a FastAPI test client.

    This fixture provides a test client for making HTTP requests to the API
    during tests. The client uses the test settings for isolation.

    Args:
        test_settings: Test settings instance

    Returns:
        TestClient: FastAPI test client
    """
    # Import app here to avoid triggering Settings validation at module load time
    from app.core.config import get_settings
    from app.main import app

    # Clear LRU cache to ensure test settings override takes effect
    get_settings.cache_clear()

    app.dependency_overrides[get_settings] = lambda: test_settings
    client = TestClient(app)
    yield client
    app.dependency_overrides.clear()

    # Clear cache after test to prevent state pollution
    get_settings.cache_clear()


@pytest.fixture
def sample_faq_data() -> list[dict]:
    """Provide sample FAQ data for testing.

    Returns:
        list[dict]: List of sample FAQ entries with varied metadata
    """
    return [
        {
            "question": "How do I create a Bisq account?",
            "answer": "Bisq doesn't require account creation. Simply download and install the Bisq application.",
            "category": "account",
            "source": "Manual",
            "protocol": "bisq_easy",
        },
        {
            "question": "What is the trading fee?",
            "answer": "The trading fee is 0.7% of the trade amount.",
            "category": "trading",
            "source": "Manual",
            "protocol": "all",
        },
        {
            "question": "How do I dispute a trade?",
            "answer": "Open the trade details and click the 'Open Dispute' button.",
            "category": "trading",
            "source": "Extracted",
            "protocol": "multisig_v1",
        },
    ]


@pytest.fixture
def sample_feedback_data() -> list[dict]:
    """Provide sample feedback data for testing.

    Returns:
        list[dict]: List of sample feedback entries with varied ratings
    """
    return [
        {
            "question": "How do I backup my wallet?",
            "answer": "Go to Account > Backup and follow the instructions.",
            "helpful": True,
            "explanation": "Very clear and helpful",
            "timestamp": "2025-01-15T10:00:00",
            "sources_used": [{"type": "wiki", "title": "Backup Guide"}],
        },
        {
            "question": "Why is my trade stuck?",
            "answer": "Trades can get stuck due to various reasons...",
            "helpful": False,
            "explanation": "Too vague, not specific enough",
            "timestamp": "2025-01-16T11:00:00",
            "sources_used": [{"type": "faq", "title": "Trading Issues"}],
        },
    ]


@pytest.fixture(autouse=True)
def reset_faq_service_singleton():
    """Reset FAQService singleton before each test to prevent state pollution."""
    import logging

    from app.services.faq_service import FAQService

    # Reset singleton state
    if FAQService._instance is not None:
        if hasattr(FAQService._instance, "initialized"):
            delattr(FAQService._instance, "initialized")
        lock = getattr(FAQService._instance, "_file_lock", None)
        if lock is not None:
            try:
                # Safe to attempt; lock may not be acquired at this moment
                lock.release()
            except Exception as e:
                logging.debug("FAQService lock release (pre-test) ignored: %s", e)
    FAQService._instance = None

    yield

    # Cleanup after test
    if FAQService._instance is not None:
        if hasattr(FAQService._instance, "initialized"):
            delattr(FAQService._instance, "initialized")
        lock = getattr(FAQService._instance, "_file_lock", None)
        if lock is not None:
            try:
                lock.release()
            except Exception as e:
                logging.debug("FAQService lock release (post-test) ignored: %s", e)
    FAQService._instance = None


@pytest.fixture
def faq_service(test_settings: Settings, sample_faq_data: list[dict]) -> FAQService:
    """Create an FAQService instance with sample data.

    This fixture provides a fully initialized FAQService for testing with
    pre-loaded sample FAQ data in an isolated environment.

    Args:
        test_settings: Test settings instance
        sample_faq_data: Sample FAQ entries

    Returns:
        FAQService: Initialized FAQ service with sample data
    """
    from app.models.faq import FAQItem

    # Initialize service (creates SQLite database)
    service = FAQService(settings=test_settings)

    # Add sample FAQs to the database
    for faq_dict in sample_faq_data:
        faq_item = FAQItem(**faq_dict)
        service.add_faq(faq_item)

    return service


@pytest_asyncio.fixture
async def feedback_service(
    test_settings: Settings, sample_feedback_data: list[dict]
) -> FeedbackService:
    """Create a FeedbackService instance with sample data.

    This fixture provides a fully initialized FeedbackService for testing with
    pre-loaded sample feedback data in an isolated environment.

    Note: Database migrations are already applied by the test_settings fixture,
    so we only need to initialize the service and load sample data.

    Args:
        test_settings: Test settings instance
        sample_feedback_data: Sample feedback entries

    Returns:
        FeedbackService: Initialized feedback service with sample data
    """
    # Initialize service (database already migrated by test_settings fixture)
    service = FeedbackService(settings=test_settings)

    # Create feedback directory
    feedback_dir = Path(test_settings.FEEDBACK_DIR_PATH)
    feedback_dir.mkdir(parents=True, exist_ok=True)

    # Store sample feedback
    for feedback in sample_feedback_data:
        payload = {
            "question": feedback["question"],
            "answer": feedback["answer"],
            "rating": 1 if feedback.get("helpful") else 0,
            "explanation": feedback.get("explanation"),
            "sources_used": feedback.get("sources_used", []),
            "timestamp": feedback.get("timestamp"),
        }
        await service.store_feedback(payload)

    return service


@pytest.fixture
def mock_llm():
    """Create a mock LLM for testing without making actual API calls.

    Returns:
        MagicMock: Mock LLM that returns predefined responses
    """
    mock = MagicMock()
    mock.invoke.return_value = "This is a test response from the mock LLM."
    return mock


@pytest.fixture
def mock_embeddings():
    """Create a mock embeddings model for testing.

    Returns:
        MagicMock: Mock embeddings model with minimal embedding dimension
    """
    mock = MagicMock()
    # Return a simple embedding vector
    mock.embed_documents.return_value = [[0.1, 0.2, 0.3]] * 5
    mock.embed_query.return_value = [0.1, 0.2, 0.3]
    return mock


@pytest.fixture
def rag_service(
    test_settings: Settings, mock_llm, mock_embeddings
) -> SimplifiedRAGService:
    """Create a SimplifiedRAGService instance with mocked LLM.

    This fixture provides a RAG service for testing without making actual
    OpenAI API calls. The LLM and embeddings are mocked.

    Args:
        test_settings: Test settings instance
        mock_llm: Mock LLM instance
        mock_embeddings: Mock embeddings instance

    Returns:
        SimplifiedRAGService: RAG service with mocked dependencies
    """
    service = SimplifiedRAGService(settings=test_settings)

    # Replace the real LLM and embeddings with mocks
    service.llm_provider.llm = mock_llm
    service.llm_provider.embeddings = mock_embeddings

    # Mock the vectorstore to avoid requiring actual vector database
    mock_vectorstore = MagicMock()
    mock_vectorstore.similarity_search.return_value = []
    service.vectorstore = mock_vectorstore

    # Mock document_retriever and its methods with sensible defaults
    # Tests can override these with patch.object if needed
    mock_document_retriever = MagicMock()
    mock_document_retriever.retrieve_documents.return_value = []
    mock_document_retriever.format_documents.return_value = ""
    service.document_retriever = mock_document_retriever

    # Mock the RAG chain to avoid initialization requirements
    mock_rag_chain = MagicMock()
    mock_rag_chain.invoke.return_value = {
        "answer": "This is a test response from the mock LLM."
    }
    service.rag_chain = mock_rag_chain

    # Mock the prompt to avoid initialization requirements
    mock_prompt = MagicMock()
    mock_prompt.format.return_value = "Formatted prompt text"
    service.prompt = mock_prompt

    return service


@pytest.fixture
def clean_test_files(test_data_dir: str):
    """Clean up test files after each test.

    This fixture ensures that each test starts with a clean slate by
    removing all files from the test data directory after the test completes.

    Args:
        test_data_dir: Temporary directory for test data
    """
    yield
    # Clean up after test
    for item in Path(test_data_dir).iterdir():
        if item.is_file():
            item.unlink()
        elif item.is_dir():
            shutil.rmtree(item)


# Pytest configuration
def pytest_configure(config):
    """Configure pytest with custom markers.

    Args:
        config: Pytest configuration object
    """
    config.addinivalue_line("markers", "integration: mark test as an integration test")
    config.addinivalue_line("markers", "unit: mark test as a unit test")
    config.addinivalue_line("markers", "slow: mark test as slow running")

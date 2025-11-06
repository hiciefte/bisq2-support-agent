"""
Tests for FAQ RAG Loader verified FAQ filtering functionality.

This module tests the FAQRAGLoader's ability to filter FAQs based on
their verified status, ensuring only verified FAQs are loaded into
the vector store for RAG context.
"""

import json
from pathlib import Path

import pytest
from app.services.faq.faq_rag_loader import FAQRAGLoader


@pytest.fixture
def faq_data_with_verified_status() -> list[dict]:
    """Provide sample FAQ data with verified status for testing.

    Returns:
        list[dict]: List of FAQ entries with mixed verified statuses
    """
    return [
        {
            "question": "What is Bisq?",
            "answer": "Bisq is a decentralized bitcoin exchange.",
            "category": "General",
            "source": "Manual",
            "verified": True,
        },
        {
            "question": "How do I create an account?",
            "answer": "Download and install Bisq application.",
            "category": "Account",
            "source": "Manual",
            "verified": False,
        },
        {
            "question": "What are the trading fees?",
            "answer": "Trading fees are 0.7% of trade amount.",
            "category": "Trading",
            "source": "Extracted",
            "verified": True,
        },
        {
            "question": "How do I backup my wallet?",
            "answer": "Go to Account > Backup and follow instructions.",
            "category": "Security",
            "source": "Extracted",
            "verified": False,
        },
    ]


@pytest.fixture
def temp_faq_file(
    test_data_dir: str, faq_data_with_verified_status: list[dict]
) -> Path:
    """Create a temporary FAQ file with verified status data.

    Args:
        test_data_dir: Temporary directory for test data
        faq_data_with_verified_status: Sample FAQ data

    Returns:
        Path: Path to the temporary FAQ file
    """
    faq_file = Path(test_data_dir) / "test_extracted_faq.jsonl"
    with open(faq_file, "w", encoding="utf-8") as f:
        for faq in faq_data_with_verified_status:
            f.write(json.dumps(faq) + "\n")
    return faq_file


@pytest.mark.unit
def test_load_only_verified_faqs(temp_faq_file: Path):
    """Test that only verified FAQs are loaded into documents.

    Given a FAQ file with mixed verified statuses
    When load_faq_data is called with only_verified=True
    Then only FAQs with verified=True should be loaded
    """
    loader = FAQRAGLoader()
    documents = loader.load_faq_data(temp_faq_file, only_verified=True)

    # Should load exactly 2 verified FAQs
    assert len(documents) == 2

    # Verify the loaded questions are the verified ones
    loaded_questions = [
        doc.metadata.get("title", "").replace("...", "") for doc in documents
    ]
    assert any("What is Bisq" in q for q in loaded_questions)
    assert any("What are the trading fees" in q for q in loaded_questions)

    # Verify unverified FAQs are not loaded
    assert not any("How do I create an account" in q for q in loaded_questions)
    assert not any("How do I backup my wallet" in q for q in loaded_questions)


@pytest.mark.unit
def test_load_all_faqs_when_filtering_disabled(temp_faq_file: Path):
    """Test that all FAQs are loaded when verified filtering is disabled.

    Given a FAQ file with mixed verified statuses
    When load_faq_data is called with only_verified=False
    Then all FAQs should be loaded regardless of verified status
    """
    loader = FAQRAGLoader()
    documents = loader.load_faq_data(temp_faq_file, only_verified=False)

    # Should load all 4 FAQs
    assert len(documents) == 4


@pytest.mark.unit
def test_default_behavior_loads_only_verified(temp_faq_file: Path):
    """Test that default behavior is to load only verified FAQs.

    Given a FAQ file with mixed verified statuses
    When load_faq_data is called without only_verified parameter
    Then only verified FAQs should be loaded by default
    """
    loader = FAQRAGLoader()
    documents = loader.load_faq_data(temp_faq_file)

    # Default should be to load only verified FAQs
    assert len(documents) == 2


@pytest.mark.unit
def test_handles_missing_verified_field_gracefully(test_data_dir: str):
    """Test handling of FAQs without verified field.

    Given a FAQ file with entries missing the verified field
    When load_faq_data is called with only_verified=True
    Then entries without verified field should be treated as unverified
    """
    # Create FAQ file with missing verified fields
    faq_file = Path(test_data_dir) / "test_missing_verified.jsonl"
    faqs = [
        {
            "question": "FAQ with verified true",
            "answer": "Answer",
            "category": "General",
            "verified": True,
        },
        {
            "question": "FAQ without verified field",
            "answer": "Answer",
            "category": "General",
            # No verified field
        },
        {
            "question": "FAQ with verified false",
            "answer": "Answer",
            "category": "General",
            "verified": False,
        },
    ]

    with open(faq_file, "w", encoding="utf-8") as f:
        for faq in faqs:
            f.write(json.dumps(faq) + "\n")

    loader = FAQRAGLoader()
    documents = loader.load_faq_data(faq_file, only_verified=True)

    # Should load only the one with verified=True
    assert len(documents) == 1
    assert "FAQ with verified true" in documents[0].page_content


@pytest.mark.unit
def test_verified_status_in_metadata(temp_faq_file: Path):
    """Test that verified status is included in document metadata.

    Given verified FAQs are loaded
    When documents are created
    Then each document should have verified=True in metadata
    """
    loader = FAQRAGLoader()
    documents = loader.load_faq_data(temp_faq_file, only_verified=True)

    # All loaded documents should have verified=True in metadata
    for doc in documents:
        assert doc.metadata.get("verified") is True


@pytest.mark.unit
def test_empty_file_returns_empty_list(test_data_dir: str):
    """Test that empty FAQ file returns empty document list.

    Given an empty FAQ file
    When load_faq_data is called
    Then an empty list should be returned
    """
    empty_file = Path(test_data_dir) / "empty.jsonl"
    empty_file.touch()

    loader = FAQRAGLoader()
    documents = loader.load_faq_data(empty_file, only_verified=True)

    assert documents == []


@pytest.mark.unit
def test_nonexistent_file_returns_empty_list(test_data_dir: str):
    """Test that nonexistent file returns empty document list.

    Given a nonexistent FAQ file path
    When load_faq_data is called
    Then an empty list should be returned
    """
    nonexistent_file = Path(test_data_dir) / "nonexistent.jsonl"

    loader = FAQRAGLoader()
    documents = loader.load_faq_data(nonexistent_file, only_verified=True)

    assert documents == []

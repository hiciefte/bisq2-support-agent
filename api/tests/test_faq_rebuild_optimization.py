"""
Tests for FAQ rebuild optimization - verifying that vector store rebuilds
are only triggered when verified FAQs are modified or deleted.

This module tests the performance optimization that prevents unnecessary
vector store rebuilds when unverified FAQs (which are not in the vector
store) are updated or deleted.
"""

import json
import uuid
from pathlib import Path
from unittest.mock import Mock

import pytest
from app.core.config import Settings
from app.models.faq import FAQItem
from app.services.faq_service import FAQService


@pytest.fixture(scope="function")
def faq_service_with_mock_callback(test_data_dir):
    """Create FAQ service with isolated test directory and mocked update callback.

    This fixture creates a unique subdirectory for each test instance, ensuring
    perfect test isolation and preventing race conditions. Each test gets its own
    Settings instance pointing to its own directory.

    IMPORTANT: FAQService uses a Singleton pattern, so we must reset it between
    tests to prevent state leakage.

    Args:
        test_data_dir: Session-scoped temporary directory (shared parent)

    Returns:
        tuple: (FAQService instance, Mock callback for tracking rebuilds)
    """
    # Reset the FAQService singleton to ensure test isolation
    # Without this, all tests share the same FAQService instance
    FAQService._instance = None

    # Create unique subdirectory for THIS test instance
    test_dir = Path(test_data_dir) / str(uuid.uuid4())
    test_dir.mkdir(parents=True, exist_ok=True)

    # Create isolated Settings instance for this test
    settings = Settings(
        DEBUG=True,
        DATA_DIR=str(test_dir),
        OPENAI_API_KEY="test-api-key",
        ADMIN_API_KEY="test-admin-key",
        ENVIRONMENT="testing",
        COOKIE_SECURE=False,
        OPENAI_MODEL="openai:gpt-4o-mini",
        MAX_CHAT_HISTORY_LENGTH=5,
        MAX_CONTEXT_LENGTH=1000,
    )

    # Use the FAQ file path from settings to ensure consistency
    faq_file = Path(settings.FAQ_FILE_PATH)

    # Ensure parent directory exists
    faq_file.parent.mkdir(parents=True, exist_ok=True)

    # Write test FAQs to the file BEFORE creating FAQService
    # This ensures the file exists and is populated when FAQRepository initializes
    test_faqs = [
        {
            "question": "Verified FAQ 1",
            "answer": "Answer 1",
            "category": "General",
            "source": "Manual",
            "verified": True,
        },
        {
            "question": "Unverified FAQ 1",
            "answer": "Answer 2",
            "category": "General",
            "source": "Manual",
            "verified": False,
        },
        {
            "question": "Verified FAQ 2",
            "answer": "Answer 3",
            "category": "Trading",
            "source": "Manual",
            "verified": True,
        },
        {
            "question": "Unverified FAQ 2",
            "answer": "Answer 4",
            "category": "Trading",
            "source": "Manual",
            "verified": False,
        },
    ]

    with open(faq_file, "w", encoding="utf-8") as f:
        for faq in test_faqs:
            f.write(json.dumps(faq) + "\n")

    # Now create FAQ service (repository will find the populated file)
    faq_service = FAQService(settings=settings)

    # Create a mock callback to track when rebuilds are triggered
    mock_callback = Mock()
    faq_service.register_update_callback(mock_callback)

    return faq_service, mock_callback


@pytest.mark.unit
def test_delete_verified_faq_triggers_rebuild(faq_service_with_mock_callback):
    """Test that deleting a verified FAQ triggers vector store rebuild."""
    faq_service, mock_callback = faq_service_with_mock_callback

    # Get a verified FAQ
    all_faqs = faq_service.get_all_faqs()
    assert len(all_faqs) > 0, "No FAQs loaded - fixture setup failed"

    verified_faq = next((faq for faq in all_faqs if faq.verified), None)
    assert verified_faq is not None, "No verified FAQ found in test data"

    # Delete it
    result = faq_service.delete_faq(verified_faq.id)

    # Verify deletion succeeded and rebuild was triggered
    assert result is True
    mock_callback.assert_called_once()


@pytest.mark.unit
def test_delete_unverified_faq_skips_rebuild(faq_service_with_mock_callback):
    """Test that deleting an unverified FAQ does NOT trigger vector store rebuild."""
    faq_service, mock_callback = faq_service_with_mock_callback

    # Get an unverified FAQ
    all_faqs = faq_service.get_all_faqs()
    unverified_faq = next((faq for faq in all_faqs if not faq.verified), None)
    assert unverified_faq is not None, "No unverified FAQ found in test data"

    # Delete it
    result = faq_service.delete_faq(unverified_faq.id)

    # Verify deletion succeeded but rebuild was NOT triggered
    assert result is True
    mock_callback.assert_not_called()


@pytest.mark.unit
def test_update_verified_faq_triggers_rebuild(faq_service_with_mock_callback):
    """Test that updating a verified FAQ triggers vector store rebuild."""
    faq_service, mock_callback = faq_service_with_mock_callback

    # Get a verified FAQ
    all_faqs = faq_service.get_all_faqs()
    verified_faq = next((faq for faq in all_faqs if faq.verified), None)
    assert verified_faq is not None, "No verified FAQ found in test data"

    # Update it
    updated_data = FAQItem(
        question=verified_faq.question,
        answer="Updated answer",
        category=verified_faq.category,
        source=verified_faq.source,
        verified=True,
    )
    result = faq_service.update_faq(verified_faq.id, updated_data)

    # Verify update succeeded and rebuild was triggered
    assert result is not None
    mock_callback.assert_called_once()


@pytest.mark.unit
def test_update_unverified_faq_skips_rebuild(faq_service_with_mock_callback):
    """Test that updating an unverified FAQ does NOT trigger vector store rebuild."""
    faq_service, mock_callback = faq_service_with_mock_callback

    # Get an unverified FAQ
    all_faqs = faq_service.get_all_faqs()
    unverified_faq = next((faq for faq in all_faqs if not faq.verified), None)
    assert unverified_faq is not None, "No unverified FAQ found in test data"

    # Update it
    updated_data = FAQItem(
        question=unverified_faq.question,
        answer="Updated answer",
        category=unverified_faq.category,
        source=unverified_faq.source,
        verified=False,
    )
    result = faq_service.update_faq(unverified_faq.id, updated_data)

    # Verify update succeeded but rebuild was NOT triggered
    assert result is not None
    mock_callback.assert_not_called()


@pytest.mark.unit
def test_verify_unverified_faq_triggers_rebuild(faq_service_with_mock_callback):
    """Test that verifying an unverified FAQ triggers vector store rebuild."""
    faq_service, mock_callback = faq_service_with_mock_callback

    # Get an unverified FAQ
    all_faqs = faq_service.get_all_faqs()
    unverified_faq = next((faq for faq in all_faqs if not faq.verified), None)
    assert unverified_faq is not None, "No unverified FAQ found in test data"

    # Verify it (change verified=False to verified=True)
    updated_data = FAQItem(
        question=unverified_faq.question,
        answer=unverified_faq.answer,
        category=unverified_faq.category,
        source=unverified_faq.source,
        verified=True,  # This is the key change
    )
    result = faq_service.update_faq(unverified_faq.id, updated_data)

    # Verify update succeeded and rebuild was triggered
    assert result is not None
    assert result.verified is True
    mock_callback.assert_called_once()


@pytest.mark.unit
def test_bulk_delete_only_verified_triggers_rebuild(faq_service_with_mock_callback):
    """Test that bulk deleting only verified FAQs triggers rebuild."""
    faq_service, mock_callback = faq_service_with_mock_callback

    # Get all verified FAQs
    all_faqs = faq_service.get_all_faqs()
    verified_faq_ids = [faq.id for faq in all_faqs if faq.verified]

    # Delete them all
    success, failed = faq_service.bulk_delete_faqs(verified_faq_ids)[:2]

    # Verify deletions succeeded and rebuild was triggered once
    assert success == len(verified_faq_ids)
    assert failed == 0
    mock_callback.assert_called_once()


@pytest.mark.unit
def test_bulk_delete_only_unverified_skips_rebuild(faq_service_with_mock_callback):
    """Test that bulk deleting only unverified FAQs does NOT trigger rebuild."""
    faq_service, mock_callback = faq_service_with_mock_callback

    # Get all unverified FAQs
    all_faqs = faq_service.get_all_faqs()
    unverified_faq_ids = [faq.id for faq in all_faqs if not faq.verified]

    # Delete them all
    success, failed = faq_service.bulk_delete_faqs(unverified_faq_ids)[:2]

    # Verify deletions succeeded but rebuild was NOT triggered
    assert success == len(unverified_faq_ids)
    assert failed == 0
    mock_callback.assert_not_called()


@pytest.mark.unit
def test_bulk_delete_mixed_triggers_rebuild_once(faq_service_with_mock_callback):
    """Test that bulk deleting mixed FAQs triggers rebuild only once."""
    faq_service, mock_callback = faq_service_with_mock_callback

    # Get all FAQs (both verified and unverified)
    all_faqs = faq_service.get_all_faqs()
    all_faq_ids = [faq.id for faq in all_faqs]

    # Delete them all
    success, failed = faq_service.bulk_delete_faqs(all_faq_ids)[:2]

    # Verify deletions succeeded and rebuild was triggered exactly once
    assert success == len(all_faq_ids)
    assert failed == 0
    mock_callback.assert_called_once()


@pytest.mark.unit
def test_add_faq_always_triggers_rebuild(faq_service_with_mock_callback):
    """Test that adding a new FAQ always triggers rebuild (verified or not)."""
    faq_service, mock_callback = faq_service_with_mock_callback

    # Add a new unverified FAQ
    new_faq = FAQItem(
        question="New FAQ",
        answer="New answer",
        category="General",
        source="Manual",
        verified=False,
    )
    result = faq_service.add_faq(new_faq)

    # Verify addition succeeded and rebuild was triggered
    assert result is not None
    mock_callback.assert_called_once()

    # Reset mock and add a verified FAQ
    mock_callback.reset_mock()
    new_verified_faq = FAQItem(
        question="New Verified FAQ",
        answer="New verified answer",
        category="General",
        source="Manual",
        verified=True,
    )
    result = faq_service.add_faq(new_verified_faq)

    # Verify addition succeeded and rebuild was triggered
    assert result is not None
    mock_callback.assert_called_once()


@pytest.mark.unit
def test_bulk_verify_triggers_rebuild_for_promotions(faq_service_with_mock_callback):
    """Test that bulk verifying unverified FAQs triggers vector store rebuild."""
    faq_service, mock_callback = faq_service_with_mock_callback

    # Get all unverified FAQs
    all_faqs = faq_service.get_all_faqs()
    unverified_faq_ids = [faq.id for faq in all_faqs if not faq.verified]
    assert len(unverified_faq_ids) > 0, "No unverified FAQs found in test data"

    # Verify them all
    success, failed = faq_service.bulk_verify_faqs(unverified_faq_ids)[:2]

    # Verify operation succeeded and rebuild was triggered once
    assert success == len(unverified_faq_ids)
    assert failed == 0
    mock_callback.assert_called_once()


@pytest.mark.unit
def test_bulk_verify_skips_rebuild_when_already_verified(
    faq_service_with_mock_callback,
):
    """Test that bulk verifying already-verified FAQs does NOT trigger rebuild."""
    faq_service, mock_callback = faq_service_with_mock_callback

    # Get all verified FAQs
    all_faqs = faq_service.get_all_faqs()
    verified_faq_ids = [faq.id for faq in all_faqs if faq.verified]
    assert len(verified_faq_ids) > 0, "No verified FAQs found in test data"

    # Try to verify them again (they're already verified)
    success, failed = faq_service.bulk_verify_faqs(verified_faq_ids)[:2]

    # Verify operation succeeded but rebuild was NOT triggered
    # (no promotions occurred since they were already verified)
    assert success == len(verified_faq_ids)
    assert failed == 0
    mock_callback.assert_not_called()

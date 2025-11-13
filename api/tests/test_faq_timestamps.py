"""
Tests for FAQ timestamp functionality - Service layer and migration script.

Tests cover:
- ISO 8601 date string parsing in service layer
- Date range filtering via API endpoints
- FAQ stats endpoint with date filters
- Migration script for backfilling timestamps
"""

import json
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

from app.models.faq import FAQItem
from app.scripts.migrate_faq_timestamps import migrate_faq_timestamps


class TestFAQServiceDateParsing:
    """Test ISO 8601 date string parsing in FAQService."""

    def test_parse_valid_iso_8601_date(self, faq_service):
        """Test parsing valid ISO 8601 date strings."""
        # Valid ISO 8601 with Z suffix
        date_str = "2024-01-15T10:30:00Z"
        result = faq_service.get_faqs_paginated(verified_from=date_str)

        # Should not raise error and return results
        assert result is not None
        assert hasattr(result, "faqs")

    def test_parse_iso_8601_without_z(self, faq_service):
        """Test parsing ISO 8601 without Z suffix."""
        # Valid ISO 8601 with timezone offset
        date_str = "2024-01-15T10:30:00+00:00"
        result = faq_service.get_faqs_paginated(verified_from=date_str)

        # Should not raise error
        assert result is not None
        assert hasattr(result, "faqs")

    def test_parse_invalid_date_format_logs_warning(self, faq_service, caplog):
        """Test that invalid date format logs warning and continues."""
        # Invalid date format
        invalid_date = "not-a-date"

        result = faq_service.get_faqs_paginated(verified_from=invalid_date)

        # Should log warning but not raise error
        assert "Invalid verified_from date format" in caplog.text
        assert result is not None

    def test_parse_date_range_both_dates(self, faq_service):
        """Test parsing both verified_from and verified_to dates."""
        from_date = "2024-01-01T00:00:00Z"
        to_date = "2024-12-31T23:59:59Z"

        result = faq_service.get_faqs_paginated(
            verified_from=from_date, verified_to=to_date
        )

        # Should not raise error
        assert result is not None
        assert hasattr(result, "faqs")

    def test_none_dates_pass_through(self, faq_service):
        """Test that None dates are handled correctly."""
        result = faq_service.get_faqs_paginated(verified_from=None, verified_to=None)

        # Should not raise error
        assert result is not None
        assert hasattr(result, "faqs")


class TestFAQStatsEndpoint:
    """Test FAQ statistics endpoint with date filtering."""

    def test_stats_returns_correct_structure(self, faq_service):
        """Test that stats have the correct structure."""
        # Add some verified FAQs
        for i in range(3):
            faq = FAQItem(
                question=f"Question {i}?",
                answer=f"Answer {i}",
                category="test",
                source="manual",
                verified=True,
            )
            faq_service.add_faq(faq)

        # Get stats
        result = faq_service.get_faqs_paginated(verified=True)

        # Verify structure
        assert result.total_count >= 3
        assert hasattr(result, "faqs")
        assert hasattr(result, "page")
        assert hasattr(result, "page_size")

    def test_stats_with_date_range(self, faq_service):
        """Test stats filtering by date range."""
        now = datetime.now(timezone.utc)
        yesterday = now - timedelta(days=1)

        # Add verified FAQ with specific timestamp
        faq = FAQItem(
            question="Test question?",
            answer="Test answer",
            category="test",
            source="manual",
            verified=True,
            verified_at=yesterday,
        )
        faq_service.add_faq(faq)

        # Get stats for date range
        result = faq_service.get_faqs_paginated(
            verified=True,
            verified_from=yesterday.isoformat(),
            verified_to=now.isoformat(),
        )

        # Should include the FAQ
        assert result.total_count >= 1

    def test_stats_by_category_breakdown(self, faq_service):
        """Test stats with category filtering."""
        # Add FAQs with different categories
        for category in ["backup", "security", "trading"]:
            faq = FAQItem(
                question=f"{category} question?",
                answer=f"{category} answer",
                category=category,
                source="manual",
                verified=True,
            )
            faq_service.add_faq(faq)

        # Get stats for specific category
        result = faq_service.get_faqs_paginated(verified=True, categories=["backup"])

        # Should only include backup FAQs
        assert all(faq.category == "backup" for faq in result.faqs)


class TestFAQTimestampMigration:
    """Test FAQ timestamp migration script."""

    def test_migration_creates_backup(self):
        """Test that migration creates backup file."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Create test FAQ file
            faq_file = Path(temp_dir) / "extracted_faq.jsonl"
            faq_data = {
                "question": "Test?",
                "answer": "Test answer",
                "category": "test",
                "source": "manual",
                "verified": False,
            }
            with open(faq_file, "w") as f:
                f.write(json.dumps(faq_data) + "\n")

            # Run migration
            with patch(
                "app.scripts.migrate_faq_timestamps.get_settings"
            ) as mock_settings:
                mock_settings.return_value = MagicMock(DATA_DIR=Path(temp_dir))
                result = migrate_faq_timestamps(dry_run=False)

            # Check backup was created
            backup_file = Path(temp_dir) / "extracted_faq.jsonl.backup"
            assert backup_file.exists()
            assert result["status"] == "success"

    def test_migration_adds_timestamps(self):
        """Test that migration adds timestamp fields to FAQs."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Create test FAQ without timestamps
            faq_file = Path(temp_dir) / "extracted_faq.jsonl"
            faq_data = {
                "question": "Test?",
                "answer": "Test answer",
                "category": "test",
                "source": "manual",
                "verified": False,
            }
            with open(faq_file, "w") as f:
                f.write(json.dumps(faq_data) + "\n")

            # Run migration
            with patch(
                "app.scripts.migrate_faq_timestamps.get_settings"
            ) as mock_settings:
                mock_settings.return_value = MagicMock(DATA_DIR=Path(temp_dir))
                result = migrate_faq_timestamps(dry_run=False)

            # Read migrated file
            with open(faq_file, "r") as f:
                migrated_faq = json.loads(f.read().strip())

            # Check timestamps were added
            assert "created_at" in migrated_faq
            assert "updated_at" in migrated_faq
            assert "verified_at" in migrated_faq
            assert migrated_faq["verified_at"] is None  # Unverified FAQ
            assert result["migrated"] == 1

    def test_migration_sets_verified_at_for_verified_faqs(self):
        """Test that migration sets verified_at for already verified FAQs."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Create verified FAQ without timestamps
            faq_file = Path(temp_dir) / "extracted_faq.jsonl"
            faq_data = {
                "question": "Verified?",
                "answer": "Verified answer",
                "category": "test",
                "source": "manual",
                "verified": True,
            }
            with open(faq_file, "w") as f:
                f.write(json.dumps(faq_data) + "\n")

            # Run migration
            with patch(
                "app.scripts.migrate_faq_timestamps.get_settings"
            ) as mock_settings:
                mock_settings.return_value = MagicMock(DATA_DIR=Path(temp_dir))
                result = migrate_faq_timestamps(dry_run=False)

            # Read migrated file
            with open(faq_file, "r") as f:
                migrated_faq = json.loads(f.read().strip())

            # Check verified_at was set
            assert migrated_faq["verified_at"] is not None
            assert result["migrated"] == 1

    def test_migration_skips_already_migrated_faqs(self):
        """Test that migration skips FAQs that already have timestamps."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Create FAQ with timestamps
            faq_file = Path(temp_dir) / "extracted_faq.jsonl"
            existing_timestamp = datetime.now(timezone.utc).isoformat()
            faq_data = {
                "question": "Already migrated?",
                "answer": "Yes",
                "category": "test",
                "source": "manual",
                "verified": False,
                "created_at": existing_timestamp,
                "updated_at": existing_timestamp,
                "verified_at": None,
            }
            with open(faq_file, "w") as f:
                f.write(json.dumps(faq_data) + "\n")

            # Run migration
            with patch(
                "app.scripts.migrate_faq_timestamps.get_settings"
            ) as mock_settings:
                mock_settings.return_value = MagicMock(DATA_DIR=Path(temp_dir))
                result = migrate_faq_timestamps(dry_run=False)

            # Check it was skipped
            assert result["skipped"] == 1
            assert result["migrated"] == 0

    def test_migration_dry_run_does_not_modify_files(self):
        """Test that dry run mode does not modify files."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Create test FAQ file
            faq_file = Path(temp_dir) / "extracted_faq.jsonl"
            faq_data = {
                "question": "Test?",
                "answer": "Test answer",
                "category": "test",
                "source": "manual",
                "verified": False,
            }
            with open(faq_file, "w") as f:
                f.write(json.dumps(faq_data) + "\n")

            # Get original content
            with open(faq_file, "r") as f:
                original_content = f.read()

            # Run dry run migration
            with patch(
                "app.scripts.migrate_faq_timestamps.get_settings"
            ) as mock_settings:
                mock_settings.return_value = MagicMock(DATA_DIR=Path(temp_dir))
                result = migrate_faq_timestamps(dry_run=True)

            # Check file was not modified
            with open(faq_file, "r") as f:
                current_content = f.read()

            assert current_content == original_content
            assert result["dry_run"] is True
            assert result["migrated"] == 1  # Would have migrated

    def test_migration_handles_missing_file(self):
        """Test that migration handles missing FAQ file gracefully."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Don't create FAQ file

            # Run migration
            with patch(
                "app.scripts.migrate_faq_timestamps.get_settings"
            ) as mock_settings:
                mock_settings.return_value = MagicMock(DATA_DIR=Path(temp_dir))
                result = migrate_faq_timestamps(dry_run=False)

            # Should return error status
            assert result["status"] == "error"
            assert "not found" in result.get("message", "").lower()

    def test_migration_validates_output(self):
        """Test that migration validates output with Pydantic model."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Create test FAQ file
            faq_file = Path(temp_dir) / "extracted_faq.jsonl"
            faq_data = {
                "question": "Test?",
                "answer": "Test answer",
                "category": "test",
                "source": "manual",
                "verified": False,
            }
            with open(faq_file, "w") as f:
                f.write(json.dumps(faq_data) + "\n")

            # Run migration
            with patch(
                "app.scripts.migrate_faq_timestamps.get_settings"
            ) as mock_settings:
                mock_settings.return_value = MagicMock(DATA_DIR=Path(temp_dir))
                result = migrate_faq_timestamps(dry_run=False)

            # Should succeed validation
            assert result["status"] == "success"
            assert result["migrated"] == 1


class TestFAQTimestampIntegration:
    """Integration tests for FAQ timestamp functionality across layers."""

    def test_end_to_end_timestamp_flow(self, faq_service):
        """Test complete flow from creation to verification with timestamps."""
        # Create unverified FAQ
        faq = FAQItem(
            question="Integration test?",
            answer="Integration answer",
            category="test",
            source="manual",
            verified=False,
        )

        # Add FAQ (should auto-populate created_at, updated_at)
        added_faq = faq_service.add_faq(faq)
        assert added_faq.created_at is not None
        assert added_faq.updated_at is not None
        assert added_faq.verified_at is None

        # Verify FAQ (should set verified_at)
        all_faqs = faq_service.get_all_faqs()
        current_faq = next(faq for faq in all_faqs if faq.id == added_faq.id)

        updated_faq = FAQItem(
            **current_faq.model_dump(exclude={"id"}, exclude_none=False)
        )
        updated_faq.verified = True

        verified_faq = faq_service.update_faq(added_faq.id, updated_faq)
        assert verified_faq.verified_at is not None
        assert verified_faq.created_at == added_faq.created_at  # Preserved
        assert verified_faq.updated_at > added_faq.updated_at  # Updated

    def test_date_range_query_across_layers(self, faq_service):
        """Test date range filtering works from service to repository."""
        now = datetime.now(timezone.utc)
        yesterday = now - timedelta(days=1)

        # Add verified FAQ with yesterday's timestamp
        faq = FAQItem(
            question="Yesterday FAQ?",
            answer="Yesterday answer",
            category="test",
            source="manual",
            verified=True,
            verified_at=yesterday,
        )
        faq_service.add_faq(faq)

        # Query with ISO 8601 date string
        result = faq_service.get_faqs_paginated(
            verified=True,
            verified_from=yesterday.isoformat(),
            verified_to=now.isoformat(),
        )

        # Should include the FAQ
        assert result.total_count >= 1
        assert any("Yesterday" in faq.question for faq in result.faqs)

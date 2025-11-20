"""
Tests for VectorStoreManager SQLite integration.

This test suite validates that VectorStoreManager correctly tracks SQLite database
file changes for vector store rebuild triggers, not JSONL files.
"""

import time

import pytest
from app.services.rag.vectorstore_manager import VectorStoreManager


@pytest.fixture
def vectorstore_manager(tmp_path):
    """Create VectorStoreManager instance with temporary directory."""
    vectorstore_path = tmp_path / "vectorstore"
    vectorstore_path.mkdir()
    manager = VectorStoreManager(vectorstore_path=vectorstore_path, data_dir=tmp_path)
    return manager


@pytest.fixture
def setup_test_files(tmp_path):
    """Create test SQLite database and wiki files."""
    # Create FAQ database file
    faq_db = tmp_path / "faqs.db"
    faq_db.write_text("fake database content")

    # Create wiki directory and file
    wiki_dir = tmp_path / "wiki"
    wiki_dir.mkdir()
    wiki_file = wiki_dir / "processed_wiki.jsonl"
    wiki_file.write_text('{"title": "test", "content": "test content"}')

    return {"faq_db": faq_db, "wiki_file": wiki_file}


class TestVectorStoreManagerSQLite:
    """Test suite for VectorStoreManager SQLite integration."""

    def test_tracks_sqlite_database_not_jsonl(
        self, vectorstore_manager, setup_test_files
    ):
        """Test that VectorStoreManager tracks faqs.db, not extracted_faq.jsonl.

        This is the core test validating the migration to SQLite-based
        change tracking.
        """
        # Action: Collect source metadata
        metadata = vectorstore_manager.collect_source_metadata()

        # Assert: Should track faqs.db
        assert "faq" in metadata["sources"]
        faq_source = metadata["sources"]["faq"]
        assert "faqs.db" in faq_source["path"]
        assert faq_source["mtime"] > 0
        assert faq_source["size"] > 0

    def test_does_not_track_jsonl_file(
        self, vectorstore_manager, setup_test_files, tmp_path
    ):
        """Test that legacy JSONL file is not tracked."""
        # Setup: Create legacy JSONL file
        jsonl_file = tmp_path / "extracted_faq.jsonl"
        jsonl_file.write_text('{"question": "test", "answer": "test"}')

        # Action: Collect source metadata
        metadata = vectorstore_manager.collect_source_metadata()

        # Assert: FAQ source should point to faqs.db, not extracted_faq.jsonl
        assert "faq" in metadata["sources"], "FAQ source must be tracked"
        faq_path = metadata["sources"]["faq"]["path"]
        assert "faqs.db" in faq_path, "FAQ source must point to faqs.db"
        assert "extracted_faq.jsonl" not in faq_path, "FAQ source must not be JSONL"

    def test_detects_database_changes(
        self, vectorstore_manager, setup_test_files, tmp_path
    ):
        """Test that database file changes trigger rebuild detection."""
        # Setup: Get initial metadata
        faq_db = setup_test_files["faq_db"]
        initial_metadata = vectorstore_manager.collect_source_metadata()
        vectorstore_manager.save_metadata(initial_metadata)

        # Wait to ensure mtime difference
        time.sleep(0.1)

        # Action: Modify database file
        faq_db.write_text("modified database content")

        # Collect new metadata
        new_metadata = vectorstore_manager.collect_source_metadata()

        # Assert: Modification time should be different
        assert (
            new_metadata["sources"]["faq"]["mtime"]
            > initial_metadata["sources"]["faq"]["mtime"]
        )

    def test_tracks_wiki_file_unchanged(self, vectorstore_manager, setup_test_files):
        """Test that wiki file tracking remains unchanged."""
        # Action: Collect source metadata
        metadata = vectorstore_manager.collect_source_metadata()

        # Assert: Should still track wiki file
        assert "wiki" in metadata["sources"]
        wiki_source = metadata["sources"]["wiki"]
        assert "processed_wiki.jsonl" in wiki_source["path"]
        assert wiki_source["mtime"] > 0
        assert wiki_source["size"] > 0

    def test_empty_directory_no_faq_source(self, vectorstore_manager):
        """Test that missing database file results in no FAQ source tracking."""
        # Action: Collect metadata from empty directory
        metadata = vectorstore_manager.collect_source_metadata()

        # Assert: No FAQ source should be tracked
        assert "faq" not in metadata["sources"]

    def test_metadata_persistence_with_database_path(
        self, vectorstore_manager, setup_test_files
    ):
        """Test that metadata correctly persists database path."""
        # Setup: Collect and save metadata
        metadata = vectorstore_manager.collect_source_metadata()
        vectorstore_manager.save_metadata(metadata)

        # Action: Load metadata from disk
        metadata_path = vectorstore_manager.get_metadata_path()
        assert metadata_path.exists()

        import json

        with open(metadata_path, "r") as f:
            loaded_metadata = json.load(f)

        # Assert: Loaded metadata should have database path
        assert "faq" in loaded_metadata["sources"]
        assert "faqs.db" in loaded_metadata["sources"]["faq"]["path"]

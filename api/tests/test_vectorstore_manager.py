"""
Tests for VectorStore Manager module.

This test suite covers:
- Metadata tracking and persistence
- Source file change detection
- Vector store rebuild decision logic
- Runtime update triggering
"""

import tempfile
import time
from pathlib import Path
from unittest.mock import Mock

import pytest
from app.services.rag.vectorstore_manager import VectorStoreManager


class TestVectorStoreManager:
    """Test suite for VectorStoreManager."""

    @pytest.fixture
    def temp_dir(self):
        """Create a temporary directory for testing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    @pytest.fixture
    def manager(self, temp_dir):
        """Create a VectorStoreManager instance for testing."""
        return VectorStoreManager(
            vectorstore_path=temp_dir / "vectorstore", data_dir=temp_dir / "data"
        )

    @pytest.fixture
    def sample_source_files(self, temp_dir):
        """Create sample source files."""
        data_dir = temp_dir / "data"
        data_dir.mkdir(parents=True, exist_ok=True)

        # Create wiki file
        wiki_file = data_dir / "wiki" / "processed_wiki.jsonl"
        wiki_file.parent.mkdir(parents=True, exist_ok=True)
        wiki_file.write_text('{"title": "Test Wiki"}\n')

        # Create FAQ database file (SQLite)
        faq_db = data_dir / "faqs.db"
        faq_db.write_text("fake database content")

        return {"wiki": wiki_file, "faq": faq_db}

    def test_manager_initialization(self, manager, temp_dir):
        """Test VectorStoreManager initialization."""
        assert manager.vectorstore_path == temp_dir / "vectorstore"
        assert manager.data_dir == temp_dir / "data"

    def test_get_metadata_path(self, manager, temp_dir):
        """Test metadata path generation."""
        expected_path = temp_dir / "vectorstore" / "build_metadata.json"
        assert manager.get_metadata_path() == expected_path

    def test_collect_source_metadata(self, manager, sample_source_files):
        """Test collection of source file metadata."""
        _ = sample_source_files  # ensure fixture evaluated (ruff: ARG002)
        metadata = manager.collect_source_metadata()

        assert "last_build" in metadata
        assert "sources" in metadata
        assert "wiki" in metadata["sources"]
        assert "faq" in metadata["sources"]

        # Check wiki metadata
        wiki_meta = metadata["sources"]["wiki"]
        assert "path" in wiki_meta
        assert "mtime" in wiki_meta
        assert "size" in wiki_meta
        assert wiki_meta["size"] > 0

        # Check FAQ metadata
        faq_meta = metadata["sources"]["faq"]
        assert "path" in faq_meta
        assert "mtime" in faq_meta
        assert "size" in faq_meta
        assert faq_meta["size"] > 0

    def test_save_and_load_metadata(self, manager, sample_source_files):
        """Test metadata persistence."""
        _ = sample_source_files  # ensure fixture evaluated (ruff: ARG002)
        # Collect and save metadata
        metadata = manager.collect_source_metadata()
        manager.save_metadata(metadata)

        # Load metadata
        loaded_metadata = manager.load_metadata()

        assert loaded_metadata == metadata
        assert loaded_metadata["sources"]["wiki"] == metadata["sources"]["wiki"]
        assert loaded_metadata["sources"]["faq"] == metadata["sources"]["faq"]

    def test_load_metadata_when_missing(self, manager):
        """Test loading metadata when file doesn't exist."""
        metadata = manager.load_metadata()
        assert metadata == {}

    def test_should_rebuild_no_metadata(self, manager, sample_source_files):
        """Test rebuild decision when no metadata exists."""
        _ = sample_source_files  # ensure fixture evaluated (ruff: ARG002)
        assert manager.should_rebuild() is True

    def test_should_rebuild_no_chroma_db(self, manager, sample_source_files):
        """Test rebuild decision when ChromaDB doesn't exist."""
        _ = sample_source_files  # ensure fixture evaluated (ruff: ARG002)
        # Save metadata but don't create chroma.sqlite3
        metadata = manager.collect_source_metadata()
        manager.save_metadata(metadata)

        assert manager.should_rebuild() is True

    def test_should_rebuild_no_changes(self, manager, sample_source_files, temp_dir):
        """Test rebuild decision when no changes detected."""
        _ = sample_source_files  # ensure fixture evaluated (ruff: ARG002)
        # Create chroma.sqlite3
        vectorstore_dir = temp_dir / "vectorstore"
        vectorstore_dir.mkdir(parents=True, exist_ok=True)
        (vectorstore_dir / "chroma.sqlite3").touch()

        # Save metadata
        metadata = manager.collect_source_metadata()
        manager.save_metadata(metadata)

        # Should not rebuild
        assert manager.should_rebuild() is False

    def test_should_rebuild_file_modified(self, manager, sample_source_files, temp_dir):
        """Test rebuild decision when source file is modified."""
        # Create chroma.sqlite3
        vectorstore_dir = temp_dir / "vectorstore"
        vectorstore_dir.mkdir(parents=True, exist_ok=True)
        (vectorstore_dir / "chroma.sqlite3").touch()

        # Save initial metadata
        metadata = manager.collect_source_metadata()
        manager.save_metadata(metadata)

        # Wait to ensure different mtime (1.1s for filesystems with 1s resolution)
        time.sleep(1.1)

        # Modify a source file
        sample_source_files["wiki"].write_text('{"title": "Updated Wiki"}\n')

        # Should rebuild
        assert manager.should_rebuild() is True

    def test_should_rebuild_file_size_changed(
        self, manager, sample_source_files, temp_dir
    ):
        """Test rebuild decision when file size changes."""
        # Create chroma.sqlite3
        vectorstore_dir = temp_dir / "vectorstore"
        vectorstore_dir.mkdir(parents=True, exist_ok=True)
        (vectorstore_dir / "chroma.sqlite3").touch()

        # Save initial metadata
        metadata = manager.collect_source_metadata()
        manager.save_metadata(metadata)

        # Change file size without changing mtime (edge case)
        faq_file = sample_source_files["faq"]
        # Append more content
        faq_file.write_text(
            '{"question": "Test?"}\n{"question": "Another question?"}\n'
        )

        # Should rebuild
        assert manager.should_rebuild() is True

    def test_should_rebuild_new_source_file(
        self, manager, sample_source_files, temp_dir
    ):
        """Test rebuild decision when new source file appears."""
        _ = sample_source_files  # ensure fixture evaluated (ruff: ARG002)
        # Create chroma.sqlite3
        vectorstore_dir = temp_dir / "vectorstore"
        vectorstore_dir.mkdir(parents=True, exist_ok=True)
        (vectorstore_dir / "chroma.sqlite3").touch()

        # Save metadata with only wiki file
        metadata = manager.collect_source_metadata()
        # Remove FAQ from metadata to simulate it being new
        del metadata["sources"]["faq"]
        manager.save_metadata(metadata)

        # Now FAQ file exists but wasn't in metadata
        # Should rebuild
        assert manager.should_rebuild() is True

    def test_get_rebuild_reason(self, manager, sample_source_files, temp_dir):
        """Test getting the reason for rebuild."""
        # No metadata case
        reason = manager.get_rebuild_reason()
        assert "No build metadata found" in reason

        # Create chroma.sqlite3 and save metadata
        vectorstore_dir = temp_dir / "vectorstore"
        vectorstore_dir.mkdir(parents=True, exist_ok=True)
        (vectorstore_dir / "chroma.sqlite3").touch()
        metadata = manager.collect_source_metadata()
        manager.save_metadata(metadata)

        # No changes case
        reason = manager.get_rebuild_reason()
        assert reason is None

        # Modify file case
        time.sleep(1.1)  # Wait for filesystems with 1s mtime resolution
        sample_source_files["wiki"].write_text('{"title": "Modified"}\n')
        reason = manager.get_rebuild_reason()
        assert "wiki" in reason.lower()
        assert "modified" in reason.lower()


class TestRuntimeUpdateTrigger:
    """Test suite for runtime update triggering."""

    @pytest.fixture
    def manager(self, temp_dir):
        """Create a VectorStoreManager instance for testing."""
        return VectorStoreManager(
            vectorstore_path=temp_dir / "vectorstore", data_dir=temp_dir / "data"
        )

    @pytest.fixture
    def temp_dir(self):
        """Create a temporary directory for testing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    def test_register_update_callback(self, manager):
        """Test registering an update callback."""
        callback = Mock()
        manager.register_update_callback(callback)

        assert callback in manager._update_callbacks

    def test_trigger_update_calls_callbacks(self, manager):
        """Test that triggering update calls all registered callbacks."""
        callback1 = Mock()
        callback2 = Mock()

        manager.register_update_callback(callback1)
        manager.register_update_callback(callback2)

        manager.trigger_update("faq")

        callback1.assert_called_once_with("faq")
        callback2.assert_called_once_with("faq")

    def test_trigger_update_with_no_callbacks(self, manager):
        """Test triggering update when no callbacks registered."""
        # Should not raise an exception
        manager.trigger_update("wiki")

    def test_unregister_callback(self, manager):
        """Test unregistering a callback."""
        callback = Mock()
        manager.register_update_callback(callback)
        manager.unregister_update_callback(callback)

        manager.trigger_update("faq")

        # Callback should not be called
        callback.assert_not_called()

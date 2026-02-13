"""Tests for the soul personality loader.

TDD Step 1 (RED): These tests define the expected behavior of the soul loader
before any implementation exists.
"""

import pytest
from app.prompts.soul import load_soul, reload_soul


@pytest.fixture(autouse=True)
def _clear_soul_cache():
    """Isolate each test from the soul cache."""
    reload_soul()
    yield
    reload_soul()


class TestSoulLoader:
    """Tests for load_soul() and reload_soul()."""

    def test_load_soul_returns_nonempty_string(self):
        result = load_soul()
        assert isinstance(result, str)
        assert len(result) > 0

    def test_load_soul_contains_identity_markers(self):
        result = load_soul()
        assert "Bisq" in result
        assert "IDENTITY" in result or "identity" in result.lower()

    def test_load_soul_is_cached(self):
        result1 = load_soul()
        result2 = load_soul()
        # Same object identity means cache is working
        assert result1 is result2

    def test_reload_soul_clears_cache(self):
        first = load_soul()
        reload_soul()
        second = load_soul()
        # Content is the same but it should be a fresh read
        assert first == second
        # After reload, cache_info should show a miss
        info = load_soul.cache_info()
        assert info.misses >= 1

    def test_load_soul_fallback_when_file_missing(self, tmp_path, monkeypatch):
        """When the .md file doesn't exist, load_soul returns the fallback."""
        import app.prompts.soul as soul_module

        monkeypatch.setattr(soul_module, "_SOUL_FILE", tmp_path / "nonexistent.md")
        reload_soul()
        result = load_soul()
        assert isinstance(result, str)
        assert len(result) > 0

    def test_fallback_contains_bisq_identity(self, tmp_path, monkeypatch):
        """The fallback text still mentions Bisq."""
        import app.prompts.soul as soul_module

        monkeypatch.setattr(soul_module, "_SOUL_FILE", tmp_path / "nonexistent.md")
        reload_soul()
        result = load_soul()
        assert "Bisq" in result

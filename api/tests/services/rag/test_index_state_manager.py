"""Tests for index rebuild state management."""

import logging

import pytest
from app.services.rag.index_state_manager import IndexStateManager


@pytest.mark.asyncio
async def test_rebuild_failure_returns_generic_error_and_logs_detail(caplog):
    """Rebuild failures must not expose internal exception details."""
    manager = IndexStateManager()
    manager.mark_change("update", "faq-1")
    internal_detail = "vector backend credential marker"

    async def fail_rebuild():
        raise RuntimeError(internal_detail)

    with caplog.at_level(
        logging.ERROR,
        logger="app.services.rag.index_state_manager",
    ):
        result = await manager.execute_rebuild(fail_rebuild)

    assert result == {
        "success": False,
        "error": "Index rebuild failed",
        "changes_pending": 1,
    }
    assert internal_detail not in str(result)
    assert internal_detail in caplog.text

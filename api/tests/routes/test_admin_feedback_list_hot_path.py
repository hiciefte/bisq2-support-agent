from unittest.mock import MagicMock

import pytest
from app.models.feedback import FeedbackListResponse
from app.routes.admin import feedback as admin_feedback


@pytest.mark.asyncio
async def test_feedback_list_offloads_sync_filter_service(monkeypatch):
    """F15: the async admin route must not run sync SQLite/Pydantic work inline."""
    expected = FeedbackListResponse(
        feedback_items=[],
        total_count=0,
        page=1,
        page_size=50,
        total_pages=0,
        filters_applied={},
    )
    to_thread = MagicMock(return_value=expected)

    async def fake_to_thread(func, /, *args, **kwargs):
        return to_thread(func, *args, **kwargs)

    monkeypatch.setattr(admin_feedback.asyncio, "to_thread", fake_to_thread)

    result = await admin_feedback.get_feedback_list(channel="matrix")

    assert result is expected
    to_thread.assert_called_once()
    called_func = to_thread.call_args.args[0]
    assert getattr(called_func, "__self__", None) is admin_feedback.feedback_service
    assert getattr(called_func, "__name__", "") == "get_feedback_with_filters"
    filters = to_thread.call_args.args[1]
    assert filters.channel == "matrix"

"""Regression tests for error privacy in streamed FAQ exports."""

import logging

import app.main  # noqa: F401 - initialize route dependencies in application order
import pytest
from app.routes.admin import faqs


class BrokenFAQ:
    """FAQ fixture whose formatting failure contains private detail."""

    @property
    def question(self) -> str:
        raise RuntimeError("private-export-storage-detail")


@pytest.mark.asyncio
async def test_csv_row_failure_logs_detail_but_streams_generic_error(
    monkeypatch, caplog
) -> None:
    monkeypatch.setattr(
        faqs.faq_service,
        "get_filtered_faqs",
        lambda **_kwargs: [BrokenFAQ()],
    )

    with caplog.at_level(logging.ERROR):
        response = await faqs.export_faqs_to_csv()
        body = b"".join([chunk async for chunk in response.body_iterator])

    text = body.decode("utf-8")
    assert "ERROR: Failed to export FAQ" in text
    assert "private-export-storage-detail" not in text
    assert "private-export-storage-detail" in caplog.text

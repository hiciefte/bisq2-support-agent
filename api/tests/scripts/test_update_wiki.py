"""Tests for the scheduler-backed wiki update job."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from app.scripts import update_wiki


@pytest.mark.asyncio
async def test_wiki_update_uses_the_configured_persistent_data_directory(
    tmp_path: Path,
    monkeypatch,
) -> None:
    wiki_dir = tmp_path / "persistent-data" / "wiki"
    settings = SimpleNamespace(WIKI_DIR_PATH=str(wiki_dir))

    def download(*, output_dir: str) -> None:
        assert output_dir == str(wiki_dir)
        wiki_dir.mkdir(parents=True, exist_ok=True)
        (wiki_dir / "bisq2_dump.xml").write_text("<mediawiki />", encoding="utf-8")

    processor = MagicMock()
    processor.context = {"article": [{"title": "one"}, {"title": "two"}]}
    processor_class = MagicMock(return_value=processor)

    monkeypatch.setattr(update_wiki, "get_settings", lambda: settings)
    monkeypatch.setattr(update_wiki, "_download_wiki_dump", download)
    monkeypatch.setattr(update_wiki, "_create_wiki_processor", processor_class)

    result = await update_wiki.main()

    assert result == {"pages_processed": 2}
    processor_class.assert_called_once_with(
        str(wiki_dir / "bisq2_dump.xml"),
        str(wiki_dir / "processed_wiki.jsonl"),
    )
    processor.process_dump.assert_called_once_with()

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from app.services.rag.qdrant_index_manager import QdrantIndexManager
from langchain_core.documents import Document


def _settings(tmp_path: Path) -> MagicMock:
    settings = MagicMock()
    settings.DATA_DIR = str(tmp_path)
    settings.QDRANT_COLLECTION = "test_collection"
    settings.QDRANT_HOST = "localhost"
    settings.QDRANT_PORT = 6333
    settings.BM25_VOCABULARY_FILE = "bm25_vocabulary.json"
    settings.EMBEDDING_MODEL = "test-embedding"
    return settings


def _client_without_collection() -> MagicMock:
    client = MagicMock()
    collections = MagicMock()
    collections.collections = []
    client.get_collections.return_value = collections
    return client


def test_rebuild_index_preserves_existing_bm25_vocab_when_embedding_probe_fails(
    tmp_path: Path,
) -> None:
    vocab_path = tmp_path / "bm25_vocabulary.json"
    vocab_path.write_text("existing-vocabulary", encoding="utf-8")

    embeddings = MagicMock()
    embeddings.embed_query.side_effect = RuntimeError("embedding quota exceeded")

    manager = QdrantIndexManager(
        settings=_settings(tmp_path),
        client=_client_without_collection(),
    )

    with pytest.raises(RuntimeError, match="embedding quota exceeded"):
        manager.rebuild_index(
            [Document(page_content="Bisq Easy support content", metadata={})],
            embeddings=embeddings,
            force=True,
        )

    assert vocab_path.read_text(encoding="utf-8") == "existing-vocabulary"

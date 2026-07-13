"""Blue/green Qdrant rebuild regressions."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from app.services.rag.qdrant_index_manager import QdrantIndexManager
from langchain_core.documents import Document


class FakeQdrantClient:
    def __init__(self) -> None:
        self.collections: dict[str, list[object]] = {"test_collection__old": [object()]}
        self.aliases: dict[str, str] = {
            "test_collection__active": "test_collection__old"
        }
        self.deleted: list[str] = []
        self.fail_upsert = False
        self.fail_payload_index = False
        self.raise_after_alias_update = False

    def get_collections(self):
        return SimpleNamespace(
            collections=[SimpleNamespace(name=name) for name in self.collections]
        )

    def get_aliases(self):
        return SimpleNamespace(
            aliases=[
                SimpleNamespace(alias_name=alias, collection_name=collection)
                for alias, collection in self.aliases.items()
            ]
        )

    def get_collection(self, name: str):
        physical = self.aliases.get(name, name)
        if physical not in self.collections:
            raise RuntimeError(f"missing collection: {name}")
        return SimpleNamespace(
            points_count=len(self.collections[physical]),
            indexed_vectors_count=len(self.collections[physical]),
            status="green",
        )

    def create_collection(self, collection_name: str, **kwargs) -> None:
        assert collection_name not in self.collections
        self.collections[collection_name] = []

    def create_payload_index(self, **kwargs) -> None:
        if self.fail_payload_index:
            raise RuntimeError("payload index failed")
        return None

    def upsert(self, collection_name: str, points: list[object], **kwargs) -> None:
        if self.fail_upsert:
            raise RuntimeError("upsert failed")
        existing = {
            getattr(point, "id", index): point
            for index, point in enumerate(self.collections[collection_name])
        }
        for point in points:
            existing[getattr(point, "id")] = point
        self.collections[collection_name] = list(existing.values())

    def update_collection_aliases(self, operations) -> bool:
        for operation in operations:
            if hasattr(operation, "delete_alias"):
                self.aliases.pop(operation.delete_alias.alias_name, None)
            elif hasattr(operation, "create_alias"):
                create = operation.create_alias
                self.aliases[create.alias_name] = create.collection_name
        if self.raise_after_alias_update:
            raise TimeoutError("alias response timed out")
        return True

    def delete_collection(self, collection_name: str) -> None:
        self.deleted.append(collection_name)
        self.collections.pop(collection_name, None)


def _settings(tmp_path: Path) -> MagicMock:
    settings = MagicMock()
    settings.DATA_DIR = str(tmp_path)
    settings.QDRANT_COLLECTION = "test_collection"
    settings.QDRANT_HOST = "localhost"
    settings.QDRANT_PORT = 6333
    settings.BM25_VOCABULARY_FILE = "bm25_vocabulary.json"
    settings.EMBEDDING_MODEL = "test-embedding"
    return settings


def _documents() -> list[Document]:
    return [
        Document(page_content="first support document", metadata={"type": "wiki"}),
        Document(page_content="second support document", metadata={"type": "faq"}),
    ]


def _embeddings() -> MagicMock:
    embeddings = MagicMock()
    embeddings.embed_query.return_value = [0.1, 0.2, 0.3]
    embeddings.embed_documents.side_effect = lambda texts: [
        [0.1, 0.2, 0.3] for _ in texts
    ]
    return embeddings


def test_rebuild_swaps_alias_only_after_verified_build(tmp_path: Path) -> None:
    client = FakeQdrantClient()
    manager = QdrantIndexManager(_settings(tmp_path), client=client)

    result = manager.rebuild_index(_documents(), _embeddings(), force=True)

    active = client.aliases["test_collection__active"]
    assert active != "test_collection__old"
    assert len(client.collections[active]) == 2
    assert "test_collection__old" in client.deleted
    assert result["collection"]["name"] == "test_collection__active"


def test_failed_rebuild_preserves_active_alias_and_old_collection(
    tmp_path: Path,
) -> None:
    client = FakeQdrantClient()
    client.fail_upsert = True
    manager = QdrantIndexManager(_settings(tmp_path), client=client)

    with pytest.raises(RuntimeError, match="upsert failed"):
        manager.rebuild_index(_documents(), _embeddings(), force=True)

    assert client.aliases["test_collection__active"] == "test_collection__old"
    assert "test_collection__old" in client.collections
    assert "test_collection__old" not in client.deleted
    assert all(name == "test_collection__old" for name in client.collections.keys())


def test_applied_alias_swap_timeout_completes_commit_side_state(tmp_path: Path) -> None:
    client = FakeQdrantClient()
    client.raise_after_alias_update = True
    manager = QdrantIndexManager(_settings(tmp_path), client=client)

    result = manager.rebuild_index(_documents(), _embeddings(), force=True)

    active = client.aliases["test_collection__active"]
    assert active != "test_collection__old"
    assert manager.vocab_path.exists()
    assert manager.load_metadata()["qdrant"]["points_upserted"] == 2
    assert "test_collection__old" in client.deleted
    assert result["rebuilt"] is True


def test_partial_collection_creation_is_cleaned_up(tmp_path: Path) -> None:
    client = FakeQdrantClient()
    client.fail_payload_index = True
    manager = QdrantIndexManager(_settings(tmp_path), client=client)

    with pytest.raises(RuntimeError, match="payload index failed"):
        manager.rebuild_index(_documents(), _embeddings(), force=True)

    assert client.aliases["test_collection__active"] == "test_collection__old"
    assert set(client.collections) == {"test_collection__old"}


def test_vocabulary_promotion_failure_restores_old_alias(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = FakeQdrantClient()
    manager = QdrantIndexManager(_settings(tmp_path), client=client)
    manager.vocab_path.write_text("old vocabulary", encoding="utf-8")
    original_replace = Path.replace

    def fail_vocab_promotion(path: Path, target: Path) -> Path:
        if target == manager.vocab_path:
            raise OSError("vocabulary promotion failed")
        return original_replace(path, target)

    monkeypatch.setattr(Path, "replace", fail_vocab_promotion)

    with pytest.raises(OSError, match="vocabulary promotion failed"):
        manager.rebuild_index(_documents(), _embeddings(), force=True)

    assert client.aliases["test_collection__active"] == "test_collection__old"
    assert manager.vocab_path.read_text(encoding="utf-8") == "old vocabulary"
    assert "test_collection__old" not in client.deleted


def test_identical_documents_are_deduplicated_before_verification(
    tmp_path: Path,
) -> None:
    client = FakeQdrantClient()
    manager = QdrantIndexManager(_settings(tmp_path), client=client)
    duplicate = Document(
        page_content="identical support document",
        metadata={"type": "wiki", "title": "Same"},
    )

    result = manager.rebuild_index(
        [duplicate, duplicate.model_copy()], _embeddings(), force=True
    )

    active = client.aliases["test_collection__active"]
    assert len(client.collections[active]) == 1
    assert result["points_upserted"] == 1

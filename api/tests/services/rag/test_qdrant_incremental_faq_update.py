"""Tests for incremental FAQ point-level upsert/delete in QdrantIndexManager.

Review finding F1: approved/added FAQs never reached the Qdrant index until a
manual full rebuild. These tests cover the new incremental path:
- deterministic point IDs derived from the FAQ id (re-upsert overwrites)
- stale points removed on update/delete (including rebuild-era point IDs)
- new FAQ content visible to search without any rebuild
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List
from unittest.mock import MagicMock

import pytest
from app.services.rag.bm25_tokenizer import BM25SparseTokenizer
from app.services.rag.qdrant_index_manager import QdrantIndexManager, _stable_int_id
from langchain_core.documents import Document
from qdrant_client.http import models as rest

COLLECTION = "test_collection"


def _settings(tmp_path: Path) -> MagicMock:
    settings = MagicMock()
    settings.DATA_DIR = str(tmp_path)
    settings.QDRANT_COLLECTION = COLLECTION
    settings.QDRANT_HOST = "localhost"
    settings.QDRANT_PORT = 6333
    settings.BM25_VOCABULARY_FILE = "bm25_vocabulary.json"
    settings.EMBEDDING_MODEL = "test-embedding"
    return settings


class FakeQdrantClient:
    """Minimal in-memory Qdrant stand-in for upsert/delete/search."""

    def __init__(self, collections: tuple[str, ...] = (COLLECTION,)) -> None:
        self.points: Dict[int, Any] = {}
        self._collections = set(collections)
        self.upsert_calls: List[Any] = []
        self.delete_calls: List[Any] = []

    def get_collections(self):
        return SimpleNamespace(
            collections=[SimpleNamespace(name=name) for name in self._collections]
        )

    def upsert(self, collection_name: str, points, **kwargs):
        assert collection_name in self._collections
        self.upsert_calls.append(list(points))
        for point in points:
            self.points[point.id] = point

    def delete(self, collection_name: str, points_selector, **kwargs):
        assert collection_name in self._collections
        self.delete_calls.append(points_selector)
        conditions = {
            cond.key: cond.match.value for cond in points_selector.filter.must
        }
        stale = [
            point_id
            for point_id, point in self.points.items()
            if all(point.payload.get(k) == v for k, v in conditions.items())
        ]
        for point_id in stale:
            del self.points[point_id]

    def search_contents(self, text: str) -> List[Dict[str, Any]]:
        """Naive retrieval helper: payloads whose content contains ``text``."""
        return [
            point.payload
            for point in self.points.values()
            if text.lower() in (point.payload.get("content") or "").lower()
        ]


def _embeddings(dim: int = 3) -> MagicMock:
    embeddings = MagicMock()
    embeddings.embed_documents.side_effect = lambda texts: [[0.1] * dim for _ in texts]
    return embeddings


def _faq_doc(faq_id: str, question: str, answer: str) -> Document:
    return Document(
        page_content=f"Question: {question}\nAnswer: {answer}",
        metadata={
            "type": "faq",
            "id": faq_id,
            "question": question,
            "answer": answer,
            "protocol": "all",
            "verified": True,
        },
    )


@pytest.fixture
def client() -> FakeQdrantClient:
    return FakeQdrantClient()


@pytest.fixture
def manager(tmp_path: Path, client: FakeQdrantClient) -> QdrantIndexManager:
    return QdrantIndexManager(settings=_settings(tmp_path), client=client)


class TestUpsertFAQDocuments:
    def test_upsert_uses_deterministic_ids_and_payload(self, manager, client):
        docs = [
            _faq_doc("faq-1", "How do I trade?", "Use the trade wizard."),
            _faq_doc("faq-1", "How do I trade?", "Second chunk answer."),
        ]

        count = manager.upsert_faq_documents(
            faq_id="faq-1", documents=docs, embeddings=_embeddings()
        )

        assert count == 2
        expected_ids = {
            _stable_int_id("faq:faq-1:chunk:0"),
            _stable_int_id("faq:faq-1:chunk:1"),
        }
        assert set(client.points.keys()) == expected_ids
        payload = client.points[_stable_int_id("faq:faq-1:chunk:0")].payload
        assert payload["type"] == "faq"
        assert payload["id"] == "faq-1"
        assert payload["question"] == "How do I trade?"
        assert "How do I trade?" in payload["content"]

    def test_reupsert_overwrites_same_points(self, manager, client):
        manager.upsert_faq_documents(
            faq_id="faq-1",
            documents=[
                _faq_doc("faq-1", "How do I trade?", "Old answer."),
                _faq_doc("faq-1", "How do I trade?", "Old chunk two."),
            ],
            embeddings=_embeddings(),
        )

        manager.upsert_faq_documents(
            faq_id="faq-1",
            documents=[_faq_doc("faq-1", "How do I trade?", "New answer.")],
            embeddings=_embeddings(),
        )

        # Update collapses to the same deterministic chunk-0 ID and stale
        # chunk-1 is removed.
        assert set(client.points.keys()) == {_stable_int_id("faq:faq-1:chunk:0")}
        payload = client.points[_stable_int_id("faq:faq-1:chunk:0")].payload
        assert "New answer." in payload["content"]
        assert not client.search_contents("Old answer.")

    def test_new_faq_visible_to_search_without_rebuild(self, manager, client):
        manager.upsert_faq_documents(
            faq_id="faq-7",
            documents=[_faq_doc("faq-7", "What is a mediator?", "A dispute helper.")],
            embeddings=_embeddings(),
        )

        hits = client.search_contents("What is a mediator?")
        assert len(hits) == 1
        assert hits[0]["id"] == "faq-7"

    def test_upsert_requires_documents(self, manager):
        with pytest.raises(ValueError):
            manager.upsert_faq_documents(
                faq_id="faq-1", documents=[], embeddings=_embeddings()
            )

    def test_upsert_requires_faq_id(self, manager):
        with pytest.raises(ValueError):
            manager.upsert_faq_documents(
                faq_id="",
                documents=[_faq_doc("faq-1", "Q?", "A.")],
                embeddings=_embeddings(),
            )

    def test_upsert_raises_when_collection_missing(self, tmp_path):
        client = FakeQdrantClient(collections=("other_collection",))
        manager = QdrantIndexManager(settings=_settings(tmp_path), client=client)

        with pytest.raises(RuntimeError):
            manager.upsert_faq_documents(
                faq_id="faq-1",
                documents=[_faq_doc("faq-1", "Q?", "A.")],
                embeddings=_embeddings(),
            )

    def test_upsert_uses_persisted_bm25_vocabulary(self, tmp_path, client):
        vocab_source = BM25SparseTokenizer(
            corpus=["reputation matters when trading", "mediator resolves disputes"]
        )
        vocab_path = tmp_path / "bm25_vocabulary.json"
        vocab_path.write_text(vocab_source.export_vocabulary(), encoding="utf-8")

        manager = QdrantIndexManager(settings=_settings(tmp_path), client=client)
        manager.upsert_faq_documents(
            faq_id="faq-1",
            documents=[_faq_doc("faq-1", "Reputation?", "Reputation matters.")],
            embeddings=_embeddings(),
        )

        point = client.points[_stable_int_id("faq:faq-1:chunk:0")]
        sparse = point.vector["sparse"]
        assert isinstance(sparse, rest.SparseVector)
        assert sparse.indices, "sparse vector should use persisted vocabulary"

    def test_upsert_without_vocabulary_still_succeeds(self, manager, client):
        manager.upsert_faq_documents(
            faq_id="faq-1",
            documents=[_faq_doc("faq-1", "Q?", "A.")],
            embeddings=_embeddings(),
        )

        point = client.points[_stable_int_id("faq:faq-1:chunk:0")]
        assert point.vector["sparse"].indices == []


class TestDeleteFAQPoints:
    def test_delete_removes_all_points_for_faq(self, manager, client):
        # Rebuild-era point: content-hash based ID, but payload identifies FAQ.
        client.points[123456789] = rest.PointStruct(
            id=123456789,
            vector={"dense": [0.1, 0.1, 0.1]},
            payload={"type": "faq", "id": "faq-1", "content": "old rebuild point"},
        )
        manager.upsert_faq_documents(
            faq_id="faq-1",
            documents=[_faq_doc("faq-1", "Q?", "A.")],
            embeddings=_embeddings(),
        )
        # Unrelated wiki point must survive.
        client.points[42] = rest.PointStruct(
            id=42,
            vector={"dense": [0.2, 0.2, 0.2]},
            payload={"type": "wiki", "id": "faq-1", "content": "wiki page"},
        )

        manager.delete_faq_points("faq-1")

        assert set(client.points.keys()) == {42}

    def test_delete_requires_faq_id(self, manager):
        with pytest.raises(ValueError):
            manager.delete_faq_points("")

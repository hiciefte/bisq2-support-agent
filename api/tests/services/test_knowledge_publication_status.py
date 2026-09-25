"""Publication evidence uses actual local Qdrant payloads, never model calls."""

from types import SimpleNamespace

import pytest
from app.services.knowledge_updates.publication_status import check_publication_status
from app.services.rag.document_processor import DocumentProcessor
from app.services.rag.llm_wiki_loader import LLMWikiLoader
from app.services.rag.qdrant_index_manager import QdrantIndexManager
from qdrant_client import QdrantClient
from qdrant_client.http import models


@pytest.fixture
def publication(tmp_path, monkeypatch):
    monkeypatch.setenv("BISQ_DISABLE_TRANSFORMERS", "1")
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    path = wiki / "reputation.md"
    markdown = """---
id: reputation
title: Reputation
type: llm_wiki
status: reviewed
protocol: bisq_easy
source_refs:
  - wiki:Reputation
reviewed_by: reviewer
reviewed_at: '2026-09-25'
---
## Canonical Support Answer

Buyers do not need reputation. Seller reputation is a safety signal.
"""
    path.write_text(markdown)
    settings = SimpleNamespace(
        DATA_DIR=str(tmp_path), QDRANT_COLLECTION="test", LLM_WIKI_DIR_PATH=wiki
    )
    client = QdrantClient(":memory:")
    client.create_collection(
        "build",
        vectors_config=models.VectorParams(size=1, distance=models.Distance.COSINE),
    )
    manager = QdrantIndexManager(settings, client=client)
    client.update_collection_aliases(
        [
            models.CreateAliasOperation(
                create_alias=models.CreateAlias(
                    collection_name="build", alias_name=manager.collection_name
                )
            )
        ]
    )
    rag = SimpleNamespace(
        settings=settings,
        llm_wiki_loader=LLMWikiLoader(),
        document_processor=DocumentProcessor(chunk_size=100, chunk_overlap=10),
        index_manager=manager,
    )
    proposal = SimpleNamespace(
        status="approved",
        target_page_id="reputation",
        candidate_id=3,
        approved_markdown=markdown,
    )
    yield proposal, rag, path
    client.close()


def _index_page(rag):
    documents = rag.llm_wiki_loader.load_documents(rag.settings.LLM_WIKI_DIR_PATH)
    chunks = rag.document_processor.split_documents(documents)
    rag.index_manager.client.upsert(
        "build",
        [
            models.PointStruct(
                id=i,
                vector=[1.0],
                payload={"content": chunk.page_content, **chunk.metadata},
            )
            for i, chunk in enumerate(chunks)
        ],
    )


def test_saved_is_not_indexed_until_every_current_chunk_matches(publication):
    proposal, rag, _ = publication
    result = check_publication_status(proposal, rag)
    assert result["saved"] is True
    assert result["index_status"] == "pending"
    _index_page(rag)
    result = check_publication_status(proposal, rag)
    assert result["index_status"] == "indexed"
    assert result["answer_check"] == "not_run"


def test_stale_extra_chunk_prevents_index_success(publication):
    proposal, rag, _ = publication
    _index_page(rag)
    rag.index_manager.client.upsert(
        "build",
        [
            models.PointStruct(
                id=999,
                vector=[1.0],
                payload={
                    "type": "llm_wiki",
                    "id": "reputation",
                    "content": "Obsolete guidance",
                },
            )
        ],
    )
    assert check_publication_status(proposal, rag)["index_status"] == "pending"


def test_later_page_revision_does_not_validate_older_approval(publication):
    proposal, rag, path = publication
    path.write_text(path.read_text().replace("a safety signal", "one safety signal"))
    _index_page(rag)
    result = check_publication_status(proposal, rag)
    assert result["index_status"] == "pending"
    assert "changed after" in result["detail"]


def test_failed_or_racing_readback_remains_unknown(publication, monkeypatch):
    proposal, rag, _ = publication
    _index_page(rag)
    aliases = iter(["build", "new-build"])
    monkeypatch.setattr(
        rag.index_manager, "_get_alias_target_strict", lambda: next(aliases)
    )
    assert check_publication_status(proposal, rag)["index_status"] == "unknown"
    monkeypatch.setattr(rag.index_manager, "_get_alias_target_strict", lambda: 1 / 0)
    assert check_publication_status(proposal, rag)["index_status"] == "unknown"


def test_missing_or_unapproved_proposal_does_not_touch_index(publication):
    proposal, _, _ = publication
    assert check_publication_status(None, None)["index_status"] == "not_saved"
    proposal.status = "pending"
    assert check_publication_status(proposal, None)["saved"] is False

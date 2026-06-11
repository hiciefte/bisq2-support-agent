from pathlib import Path
from unittest.mock import MagicMock

import pytest
from app.core.config import Settings
from app.services.rag.qdrant_index_manager import QdrantIndexManager
from app.services.simplified_rag_service import SimplifiedRAGService
from langchain_core.documents import Document


def _write_reviewed_playbook(data_dir: Path) -> Path:
    llm_wiki_dir = data_dir / "knowledge" / "llm_wiki" / "pages"
    llm_wiki_dir.mkdir(parents=True)
    path = llm_wiki_dir / "deposit-limits.md"
    path.write_text(
        """---
id: deposit-limits
title: Bisq Easy deposit limits
type: llm_wiki
page_type: support_playbook
status: reviewed
protocol: bisq_easy
reviewed_by: support-admin
reviewed_at: "2026-05-12"
source_refs:
  - wiki:bisq-easy
risk_level: low
---
## Canonical Support Answer
Bisq Easy trades have limits that depend on the user's account state.
""",
        encoding="utf-8",
    )
    return path


def test_index_metadata_tracks_internal_llm_wiki(tmp_path: Path) -> None:
    _write_reviewed_playbook(tmp_path)
    settings = Settings(DATA_DIR=str(tmp_path))

    manager = QdrantIndexManager(settings=settings, client=MagicMock())
    metadata = manager.collect_source_metadata()

    llm_wiki_source = metadata["sources"]["llm_wiki"]
    assert llm_wiki_source["path"] == str(tmp_path / "knowledge" / "llm_wiki")
    assert llm_wiki_source["file_count"] == 1
    assert llm_wiki_source["size"] > 0
    assert len(llm_wiki_source["content_hash"]) == 64


@pytest.mark.asyncio
async def test_rag_setup_includes_internal_llm_wiki(tmp_path: Path) -> None:
    _write_reviewed_playbook(tmp_path)
    settings = Settings(DATA_DIR=str(tmp_path))
    wiki_service = MagicMock()
    wiki_service.load_wiki_data.return_value = [
        Document(page_content="wiki", metadata={"type": "wiki", "protocol": "all"})
    ]
    faq_service = MagicMock()
    faq_service.load_faq_data.return_value = [
        Document(page_content="faq", metadata={"type": "faq", "protocol": "all"})
    ]

    service = SimplifiedRAGService(
        settings=settings,
        wiki_service=wiki_service,
        faq_service=faq_service,
    )
    service.index_manager = MagicMock()
    service.index_manager.rebuild_index.return_value = {"rebuilt": True}
    service.document_processor = MagicMock()
    service.document_processor.split_documents.side_effect = lambda docs: docs
    service.initialize_embeddings = MagicMock()
    service._initialize_retriever = MagicMock()
    service.initialize_llm = MagicMock()
    service.prompt_manager.create_rag_prompt = MagicMock(return_value="prompt")
    service.prompt_manager.create_rag_chain = MagicMock(return_value=MagicMock())

    assert await service.setup(force_rebuild=True) is True

    indexed_docs = service.index_manager.rebuild_index.call_args.kwargs["documents"]
    assert [doc.metadata["type"] for doc in indexed_docs] == [
        "wiki",
        "faq",
        "llm_wiki",
    ]

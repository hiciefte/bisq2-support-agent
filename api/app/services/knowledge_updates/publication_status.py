"""Read back reviewed knowledge from the active index without generating answers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from qdrant_client.http import models

MAX_PAGE_CHUNKS = 256


def saved_publication_status(page_id: str) -> dict[str, Any]:
    return {
        "saved": True,
        "page_id": page_id,
        "index_status": "pending",
        "answer_check": "not_run",
        "detail": "Wiki change saved. Check the index after refreshing retrieval.",
    }


def _chunk_signature(content: str, metadata: dict[str, Any]) -> str:
    return json.dumps(
        {"content": content, **metadata}, sort_keys=True, ensure_ascii=False
    )


def check_publication_status(proposal: Any, rag_service: Any) -> dict[str, Any]:
    """Compare every expected page chunk with a pinned active collection.

    No embeddings or model calls are made. A successful index readback establishes
    content availability, not retrieval ranking or answer quality. Older approvals
    whose page has since changed are never reported as the current indexed version.
    """
    if proposal is None or proposal.status != "approved":
        return {
            "saved": False,
            "page_id": None,
            "index_status": "not_saved",
            "answer_check": "not_run",
            "detail": "This proposal has not been approved and saved.",
        }

    page_id = proposal.target_page_id or f"candidate-{proposal.candidate_id}"
    result = saved_publication_status(page_id)
    try:
        documents = rag_service.llm_wiki_loader.load_documents(
            rag_service.settings.LLM_WIKI_DIR_PATH
        )
        page = next(
            (doc for doc in documents if doc.metadata.get("id") == page_id), None
        )
        if page is None:
            result["detail"] = "The saved page is missing or no longer indexable."
            return result
        current_markdown = Path(page.metadata["source"]).read_text(encoding="utf-8")
        if current_markdown.strip() != (proposal.approved_markdown or "").strip():
            result["detail"] = (
                "The page changed after this approval; review its newer revision."
            )
            return result

        chunks = rag_service.document_processor.split_documents([page])
        if not chunks or len(chunks) > MAX_PAGE_CHUNKS:
            raise ValueError("Page exceeds bounded readback")
        expected = {
            _chunk_signature(chunk.page_content, chunk.metadata) for chunk in chunks
        }
        manager = rag_service.index_manager
        collection = manager._get_alias_target_strict()
        if collection is None:
            result["detail"] = "No active retrieval index is available."
            return result
        points, next_offset = manager.client.scroll(
            collection_name=collection,
            scroll_filter=models.Filter(
                must=[
                    models.FieldCondition(
                        key="type", match=models.MatchValue(value="llm_wiki")
                    ),
                    models.FieldCondition(
                        key="id", match=models.MatchValue(value=page_id)
                    ),
                ]
            ),
            limit=MAX_PAGE_CHUNKS + 1,
            with_payload=True,
            with_vectors=False,
        )
        if next_offset is not None or len(points) > MAX_PAGE_CHUNKS:
            raise ValueError("Index exceeds bounded readback")
        if manager._get_alias_target_strict() != collection:
            raise ValueError("Index changed during readback")
        # Recheck the on-disk revision after the read to avoid a racing approval.
        if (
            Path(page.metadata["source"]).read_text(encoding="utf-8")
            != current_markdown
        ):
            raise ValueError("Wiki changed during readback")
        actual = set()
        for point in points:
            payload = dict(point.payload or {})
            content = payload.pop("content", "")
            actual.add(_chunk_signature(content, payload))
        if actual == expected and len(points) == len(expected):
            result.update(
                index_status="indexed",
                detail="Saved wiki content verified in the active index. Answer quality has not been checked.",
            )
        else:
            result["detail"] = (
                "The active index does not yet match the saved wiki content."
            )
    except Exception:
        # Do not turn a transport/loader failure into a successful empty read or
        # expose private paths and service diagnostics through the admin response.
        result.update(
            index_status="unknown",
            detail="Index verification could not complete. No answer check was run.",
        )
    return result

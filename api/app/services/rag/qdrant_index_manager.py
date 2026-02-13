"""Qdrant index management (build, rebuild, and change detection)."""

import hashlib
import json
import logging
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from app.core.config import Settings
from app.services.rag.bm25_tokenizer import BM25SparseTokenizer
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from qdrant_client import QdrantClient
from qdrant_client.http import models as rest
from qdrant_client.http.exceptions import ResponseHandlingException
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

logger = logging.getLogger(__name__)


def _stable_int_id(key: str) -> int:
    """Generate a deterministic 63-bit int ID from an arbitrary string key."""
    digest = hashlib.sha256(key.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], byteorder="big", signed=False) & ((1 << 63) - 1)


class QdrantIndexManager:
    """Manage the Qdrant collection used for RAG retrieval."""

    def __init__(self, settings: Settings, client: Optional[QdrantClient] = None):
        self.settings = settings
        self.data_dir = Path(settings.DATA_DIR)
        self.collection_name = settings.QDRANT_COLLECTION
        self.metadata_path = self.data_dir / "qdrant_index_metadata.json"
        self.vocab_path = self.data_dir / getattr(
            settings, "BM25_VOCABULARY_FILE", "bm25_vocabulary.json"
        )

        self._client = client or QdrantClient(
            host=settings.QDRANT_HOST,
            port=settings.QDRANT_PORT,
            prefer_grpc=False,
            timeout=60,
        )

    @property
    def client(self) -> QdrantClient:
        return self._client

    @retry(
        reraise=True,
        stop=stop_after_attempt(10),
        wait=wait_exponential(multiplier=0.5, min=0.5, max=10),
        retry=retry_if_exception_type((ResponseHandlingException, OSError)),
    )
    def wait_until_ready(self) -> None:
        """Block until Qdrant is reachable (or we exhaust retries)."""
        self._client.get_collections()

    def load_metadata(self) -> Dict[str, Any]:
        if not self.metadata_path.exists():
            return {}
        try:
            return json.loads(self.metadata_path.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning(
                f"Failed to read index metadata at {self.metadata_path}: {e}"
            )
            return {}

    def save_metadata(self, metadata: Dict[str, Any]) -> None:
        try:
            self.metadata_path.parent.mkdir(parents=True, exist_ok=True)
            self.metadata_path.write_text(
                json.dumps(metadata, indent=2, sort_keys=True),
                encoding="utf-8",
            )
        except Exception as e:
            logger.warning(
                f"Failed to write index metadata at {self.metadata_path}: {e}"
            )

    def collect_source_metadata(self) -> Dict[str, Any]:
        sources: Dict[str, Dict[str, Any]] = {}
        meta: Dict[str, Any] = {"last_build": time.time(), "sources": sources}

        wiki_file = self.data_dir / "wiki" / "processed_wiki.jsonl"
        if wiki_file.exists():
            st = wiki_file.stat()
            sources["wiki"] = {
                "path": str(wiki_file),
                "mtime": st.st_mtime,
                "size": st.st_size,
            }

        faq_db = self.data_dir / "faqs.db"
        if faq_db.exists():
            st = faq_db.stat()
            sources["faq"] = {
                "path": str(faq_db),
                "mtime": st.st_mtime,
                "size": st.st_size,
            }

        # Also track the vocabulary file so query-side sparse vectorization matches index.
        if self.vocab_path.exists():
            st = self.vocab_path.stat()
            sources["bm25_vocab"] = {
                "path": str(self.vocab_path),
                "mtime": st.st_mtime,
                "size": st.st_size,
            }

        return meta

    def collection_exists(self) -> bool:
        try:
            cols = self._client.get_collections()
            return any(c.name == self.collection_name for c in cols.collections)
        except Exception:
            return False

    def get_collection_info(self) -> Optional[Dict[str, Any]]:
        try:
            info = self._client.get_collection(self.collection_name)
            return {
                "name": self.collection_name,
                "points_count": info.points_count,
                "indexed_vectors_count": info.indexed_vectors_count,
                "status": getattr(info, "status", None),
            }
        except Exception:
            return None

    def should_rebuild(self) -> bool:
        metadata = self.load_metadata()
        if not metadata:
            return True

        if not self.collection_exists():
            return True

        current = self.collect_source_metadata()
        for source_name, current_info in current.get("sources", {}).items():
            old_info = metadata.get("sources", {}).get(source_name, {})
            if not old_info:
                return True
            if current_info.get("mtime", 0) > old_info.get("mtime", 0):
                return True
            if current_info.get("size", 0) != old_info.get("size", 0):
                return True

        old_sources = set(metadata.get("sources", {}).keys())
        current_sources = set(current.get("sources", {}).keys())
        if old_sources - current_sources:
            return True

        return False

    def get_rebuild_reason(self) -> Optional[str]:
        metadata = self.load_metadata()
        if not metadata:
            return "No index metadata found"
        if not self.collection_exists():
            return "Qdrant collection missing"
        current = self.collect_source_metadata()
        for source_name, current_info in current.get("sources", {}).items():
            old_info = metadata.get("sources", {}).get(source_name, {})
            if not old_info:
                return f"New source detected: {source_name}"
            if current_info.get("mtime", 0) > old_info.get("mtime", 0):
                return f"Source modified: {source_name}"
            if current_info.get("size", 0) != old_info.get("size", 0):
                return f"Source size changed: {source_name}"
        old_sources = set(metadata.get("sources", {}).keys())
        current_sources = set(current.get("sources", {}).keys())
        removed = old_sources - current_sources
        if removed:
            return f"Source removed: {', '.join(sorted(removed))}"
        return None

    def _iter_batches(self, items: List[Any], batch_size: int) -> Iterable[List[Any]]:
        for i in range(0, len(items), batch_size):
            yield items[i : i + batch_size]

    def _ensure_collection(self, vector_size: int, recreate: bool) -> None:
        if recreate and self.collection_exists():
            logger.warning(
                f"Deleting existing Qdrant collection: {self.collection_name}"
            )
            self._client.delete_collection(self.collection_name)

        if self.collection_exists():
            return

        logger.info(
            f"Creating Qdrant collection '{self.collection_name}' (dense_size={vector_size})"
        )
        # Some qdrant-client versions may not expose Modifier.NONE explicitly.
        modifier_none = getattr(rest.Modifier, "NONE", None)
        self._client.create_collection(
            collection_name=self.collection_name,
            vectors_config={
                "dense": rest.VectorParams(
                    size=vector_size, distance=rest.Distance.COSINE
                ),
            },
            # Sparse vectors are provided by the app (BM25SparseTokenizer).
            sparse_vectors_config={
                "sparse": (
                    rest.SparseVectorParams(modifier=modifier_none)
                    if modifier_none is not None
                    else rest.SparseVectorParams()
                ),
            },
            optimizers_config=rest.OptimizersConfigDiff(indexing_threshold=10000),
        )

        # Payload indexes used by protocol-aware retrieval filters.
        self._client.create_payload_index(
            collection_name=self.collection_name,
            field_name="protocol",
            field_schema=rest.PayloadSchemaType.KEYWORD,
        )
        self._client.create_payload_index(
            collection_name=self.collection_name,
            field_name="type",
            field_schema=rest.PayloadSchemaType.KEYWORD,
        )

    def _build_doc_key(self, doc: Document) -> str:
        md = doc.metadata or {}
        doc_type = md.get("type", "doc")
        if md.get("id"):
            base = f"{doc_type}:{md['id']}"
        else:
            title = md.get("title", "")
            section = md.get("section", "")
            protocol = md.get("protocol", "all")
            base = f"{doc_type}:{title}:{section}:{protocol}"
        content_hash = hashlib.sha1(
            (doc.page_content or "").encode("utf-8")
        ).hexdigest()
        return f"{base}:{content_hash}"

    def rebuild_index(
        self,
        documents: List[Document],
        embeddings: Embeddings,
        force: bool = False,
        embed_batch_size: int = 64,
        upsert_batch_size: int = 64,
    ) -> Dict[str, Any]:
        """(Re)build the Qdrant index from provided documents."""
        if not documents:
            raise ValueError("No documents provided for indexing")

        self.wait_until_ready()

        rebuild_needed = force or self.should_rebuild()
        reason = self.get_rebuild_reason() if rebuild_needed else None

        if not rebuild_needed:
            info = self.get_collection_info()
            return {"rebuilt": False, "reason": None, "collection": info}

        logger.info(f"Rebuilding Qdrant index (reason={reason})")

        texts = [d.page_content or "" for d in documents]

        # Build a stable BM25 vocabulary/stats from the full corpus, and persist it.
        tokenizer = BM25SparseTokenizer(corpus=texts)
        self.vocab_path.parent.mkdir(parents=True, exist_ok=True)
        self.vocab_path.write_text(tokenizer.export_vocabulary(), encoding="utf-8")
        logger.info(
            f"BM25 vocabulary saved to {self.vocab_path} "
            f"(vocab_size={tokenizer.vocabulary_size}, num_docs={tokenizer.get_statistics().get('num_documents')})"
        )

        # Determine dense vector size.
        probe = embeddings.embed_query(texts[0] if texts[0] else "probe")
        vector_size = len(probe)
        if vector_size <= 0:
            raise ValueError("Failed to determine embedding vector size")

        # Create/recreate collection and upsert all points.
        self._ensure_collection(vector_size=vector_size, recreate=True)

        total = len(documents)
        upserted = 0
        start = time.time()

        for batch_docs in self._iter_batches(documents, embed_batch_size):
            batch_texts = [d.page_content or "" for d in batch_docs]
            batch_dense = embeddings.embed_documents(batch_texts)

            points: List[rest.PointStruct] = []
            for doc, dense_vec in zip(batch_docs, batch_dense, strict=True):
                content = doc.page_content or ""
                md = dict(doc.metadata) if doc.metadata else {}

                # Sparse vector using frozen corpus stats (no mutation).
                sparse_idx, sparse_val = tokenizer.vectorize_document_static(content)
                point_id = _stable_int_id(self._build_doc_key(doc))

                points.append(
                    rest.PointStruct(
                        id=point_id,
                        vector={
                            "dense": dense_vec,
                            "sparse": rest.SparseVector(
                                indices=sparse_idx, values=sparse_val
                            ),
                        },
                        payload={
                            "content": content,
                            **md,
                        },
                    )
                )

            for upsert_points in self._iter_batches(points, upsert_batch_size):
                self._client.upsert(
                    collection_name=self.collection_name, points=upsert_points
                )
                upserted += len(upsert_points)

            logger.info(f"Upserted {upserted}/{total} indexed chunks...")

        duration = time.time() - start
        info = self.get_collection_info()

        # Persist metadata after successful build for change detection.
        meta = self.collect_source_metadata()
        meta["qdrant"] = {
            "collection": self.collection_name,
            "points_upserted": upserted,
            "duration_seconds": duration,
            "embedding_model": getattr(self.settings, "EMBEDDING_MODEL", None),
            "embedding_dimensions": vector_size,
        }
        self.save_metadata(meta)

        logger.info(
            f"Qdrant index rebuild complete in {duration:.2f}s (points={upserted})"
        )
        return {
            "rebuilt": True,
            "reason": reason,
            "duration_seconds": duration,
            "points_upserted": upserted,
            "collection": info,
        }

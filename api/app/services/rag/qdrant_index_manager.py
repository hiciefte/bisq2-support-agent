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


def active_collection_alias(base_collection_name: str) -> str:
    """Return the stable alias used by all live Qdrant reads and writes."""
    return f"{base_collection_name}__active"


def _stable_int_id(key: str) -> int:
    """Generate a deterministic 63-bit int ID from an arbitrary string key."""
    digest = hashlib.sha256(key.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], byteorder="big", signed=False) & ((1 << 63) - 1)


def _file_source_metadata(path: Path) -> Dict[str, Any]:
    st = path.stat()
    return {
        "path": str(path),
        "mtime": st.st_mtime,
        "size": st.st_size,
    }


def _directory_source_metadata(path: Path, pattern: str) -> Dict[str, Any]:
    files = sorted(p for p in path.rglob(pattern) if p.is_file())
    digest = hashlib.sha256()
    total_size = 0
    latest_mtime = 0.0

    for file_path in files:
        relative_path = file_path.relative_to(path).as_posix()
        data = file_path.read_bytes()
        stat = file_path.stat()
        digest.update(relative_path.encode("utf-8"))
        digest.update(b"\0")
        digest.update(hashlib.sha256(data).digest())
        total_size += stat.st_size
        latest_mtime = max(latest_mtime, stat.st_mtime)

    return {
        "path": str(path),
        "mtime": latest_mtime,
        "size": total_size,
        "file_count": len(files),
        "content_hash": digest.hexdigest(),
    }


class QdrantIndexManager:
    """Manage the Qdrant collection used for RAG retrieval."""

    def __init__(self, settings: Settings, client: Optional[QdrantClient] = None):
        self.settings = settings
        self.data_dir = Path(settings.DATA_DIR)
        self.base_collection_name = settings.QDRANT_COLLECTION
        self.collection_name = active_collection_alias(self.base_collection_name)
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
            sources["wiki"] = _file_source_metadata(wiki_file)

        faq_db = self.data_dir / "faqs.db"
        if faq_db.exists():
            sources["faq"] = _file_source_metadata(faq_db)

        llm_wiki_dir = self.data_dir / "knowledge" / "llm_wiki"
        if llm_wiki_dir.exists():
            sources["llm_wiki"] = _directory_source_metadata(llm_wiki_dir, "*.md")

        # Also track the vocabulary file so query-side sparse vectorization matches index.
        if self.vocab_path.exists():
            sources["bm25_vocab"] = _file_source_metadata(self.vocab_path)

        return meta

    def collection_exists(self) -> bool:
        return self._get_alias_target() is not None

    def _physical_collection_exists(self, collection_name: str) -> bool:
        try:
            cols = self._client.get_collections()
            return any(c.name == collection_name for c in cols.collections)
        except Exception:
            return False

    def _get_alias_target(self) -> Optional[str]:
        try:
            return self._get_alias_target_strict()
        except Exception:
            return None

    def _get_alias_target_strict(self) -> Optional[str]:
        """Resolve the active alias without hiding transport failures."""
        aliases = self._client.get_aliases().aliases
        for alias in aliases:
            if alias.alias_name == self.collection_name:
                return str(alias.collection_name)
        return None

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
            if current_info.get("file_count") != old_info.get("file_count"):
                return True
            if current_info.get("content_hash") != old_info.get("content_hash"):
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
            if current_info.get("file_count") != old_info.get("file_count"):
                return f"Source file count changed: {source_name}"
            if current_info.get("content_hash") != old_info.get("content_hash"):
                return f"Source content changed: {source_name}"
        old_sources = set(metadata.get("sources", {}).keys())
        current_sources = set(current.get("sources", {}).keys())
        removed = old_sources - current_sources
        if removed:
            return f"Source removed: {', '.join(sorted(removed))}"
        return None

    def _iter_batches(self, items: List[Any], batch_size: int) -> Iterable[List[Any]]:
        for i in range(0, len(items), batch_size):
            yield items[i : i + batch_size]

    def _create_collection(self, collection_name: str, vector_size: int) -> None:
        logger.info(
            f"Creating Qdrant collection '{collection_name}' (dense_size={vector_size})"
        )
        # Some qdrant-client versions may not expose Modifier.NONE explicitly.
        modifier_none = getattr(rest.Modifier, "NONE", None)
        self._client.create_collection(
            collection_name=collection_name,
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
            collection_name=collection_name,
            field_name="protocol",
            field_schema=rest.PayloadSchemaType.KEYWORD,
        )
        self._client.create_payload_index(
            collection_name=collection_name,
            field_name="type",
            field_schema=rest.PayloadSchemaType.KEYWORD,
        )

    def _swap_active_alias(self, new_collection: str) -> Optional[str]:
        """Atomically point the stable read alias at ``new_collection``."""
        old_collection = self._get_alias_target()
        operations: List[rest.AliasOperations] = []
        if old_collection is not None:
            operations.append(
                rest.DeleteAliasOperation(
                    delete_alias=rest.DeleteAlias(alias_name=self.collection_name)
                )
            )
        operations.append(
            rest.CreateAliasOperation(
                create_alias=rest.CreateAlias(
                    collection_name=new_collection,
                    alias_name=self.collection_name,
                )
            )
        )
        self._client.update_collection_aliases(operations)
        return old_collection

    def _restore_active_alias(self, previous_collection: Optional[str]) -> None:
        """Restore the pre-build alias target after a commit-side failure."""
        operations: List[rest.AliasOperations] = [
            rest.DeleteAliasOperation(
                delete_alias=rest.DeleteAlias(alias_name=self.collection_name)
            )
        ]
        if previous_collection is not None:
            operations.append(
                rest.CreateAliasOperation(
                    create_alias=rest.CreateAlias(
                        collection_name=previous_collection,
                        alias_name=self.collection_name,
                    )
                )
            )
        try:
            self._client.update_collection_aliases(operations)
        except Exception as rollback_error:
            try:
                current_target = self._get_alias_target_strict()
            except Exception as reconciliation_error:
                raise rollback_error from reconciliation_error
            if current_target != previous_collection:
                raise

    def _verify_built_collection(
        self, collection_name: str, expected_points: int
    ) -> None:
        info = self._client.get_collection(collection_name)
        if info.points_count != expected_points:
            raise RuntimeError(
                f"Qdrant build verification failed: expected {expected_points} "
                f"points, found {info.points_count}"
            )
        status = getattr(info, "status", None)
        status_value = getattr(status, "value", status)
        if str(status_value).lower() == "red":
            raise RuntimeError("Qdrant build verification failed: collection is red")

    def _faq_point_id(self, faq_id: str, chunk_index: int) -> int:
        """Deterministic point ID for a FAQ chunk (re-upsert overwrites)."""
        return _stable_int_id(f"faq:{faq_id}:chunk:{chunk_index}")

    def _faq_points_filter(self, faq_id: str) -> rest.Filter:
        """Payload filter matching every indexed point of one FAQ."""
        return rest.Filter(
            must=[
                rest.FieldCondition(key="type", match=rest.MatchValue(value="faq")),
                rest.FieldCondition(key="id", match=rest.MatchValue(value=faq_id)),
            ]
        )

    def _load_sparse_tokenizer(self) -> Optional[BM25SparseTokenizer]:
        """Load the frozen BM25 vocabulary persisted by the last full rebuild.

        Incremental upserts must vectorize with the same corpus statistics the
        query side uses, otherwise sparse scores drift. Returns None when no
        vocabulary exists yet (dense-only points are still retrievable).
        """
        if not self.vocab_path.exists():
            return None
        try:
            tokenizer = BM25SparseTokenizer()
            tokenizer.load_vocabulary(self.vocab_path.read_text(encoding="utf-8"))
            return tokenizer
        except Exception as e:
            logger.warning(
                f"Failed to load BM25 vocabulary from {self.vocab_path} for "
                f"incremental upsert: {e}"
            )
            return None

    def delete_faq_points(self, faq_id: str) -> None:
        """Remove all indexed points belonging to a FAQ.

        Deletes by payload filter (type=faq, id=faq_id) so points created by
        either the full rebuild (content-hash IDs) or the incremental path
        (deterministic chunk IDs) are removed.
        """
        if not faq_id:
            raise ValueError("faq_id is required to delete FAQ points")

        self._client.delete(
            collection_name=self.collection_name,
            points_selector=rest.FilterSelector(filter=self._faq_points_filter(faq_id)),
            wait=True,
        )
        logger.info(f"Deleted indexed points for FAQ {faq_id}")

    def upsert_faq_documents(
        self,
        faq_id: str,
        documents: List[Document],
        embeddings: Embeddings,
        upsert_batch_size: int = 64,
    ) -> int:
        """Incrementally upsert one FAQ's documents into the live collection.

        Point IDs are derived deterministically from the FAQ id and chunk
        index, so re-upserting the same FAQ overwrites its points in place.
        Stale points (from a previous version with more chunks, or from a
        full rebuild that used content-hash IDs) are removed only AFTER the
        new points are live, so concurrent queries never observe a window
        where the FAQ has zero indexed points.

        Returns:
            Number of points upserted.

        Raises:
            ValueError: If faq_id or documents are missing.
            RuntimeError: If the collection does not exist yet (a full
                rebuild is required to create it).
        """
        if not faq_id:
            raise ValueError("faq_id is required to upsert FAQ documents")
        if not documents:
            raise ValueError("No documents provided for FAQ upsert")

        self.wait_until_ready()
        if not self.collection_exists():
            raise RuntimeError(
                f"Qdrant collection '{self.collection_name}' does not exist; "
                "a full index rebuild is required before incremental updates"
            )

        tokenizer = self._load_sparse_tokenizer()

        # Embed before deleting so an embedding failure leaves the previously
        # indexed points untouched.
        texts = [d.page_content or "" for d in documents]
        dense_vectors = embeddings.embed_documents(texts)

        points: List[rest.PointStruct] = []
        for chunk_index, (doc, dense_vec) in enumerate(
            zip(documents, dense_vectors, strict=True)
        ):
            content = doc.page_content or ""
            md = dict(doc.metadata) if doc.metadata else {}

            if tokenizer is not None:
                sparse_idx, sparse_val = tokenizer.vectorize_document_static(content)
            else:
                sparse_idx, sparse_val = [], []

            points.append(
                rest.PointStruct(
                    id=self._faq_point_id(faq_id, chunk_index),
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
                collection_name=self.collection_name,
                points=upsert_points,
                wait=True,
            )
        keep_ids: List[rest.ExtendedPointId] = [p.id for p in points]
        self._delete_stale_faq_points(faq_id, keep_ids=keep_ids)

        logger.info(f"Incrementally upserted {len(points)} point(s) for FAQ {faq_id}")
        return len(points)

    def _delete_stale_faq_points(
        self, faq_id: str, keep_ids: List[rest.ExtendedPointId]
    ) -> None:
        """Remove a FAQ's leftover points while keeping the ones just written.

        Runs after the new points are upserted; excluding ``keep_ids`` via
        ``must_not`` makes the cleanup safe to run against the live index.
        """
        base = self._faq_points_filter(faq_id)
        stale_filter = rest.Filter(
            must=base.must,
            must_not=[rest.HasIdCondition(has_id=keep_ids)],
        )
        self._client.delete(
            collection_name=self.collection_name,
            points_selector=rest.FilterSelector(filter=stale_filter),
            wait=True,
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

        # Qdrant upserts replace points that share an ID. Deduplicate the same
        # stable document key before embedding so verification counts the points
        # that can actually exist in the physical collection.
        unique_documents: List[Document] = []
        seen_document_keys: set[str] = set()
        for document in documents:
            document_key = self._build_doc_key(document)
            if document_key in seen_document_keys:
                continue
            seen_document_keys.add(document_key)
            unique_documents.append(document)
        if len(unique_documents) != len(documents):
            logger.info(
                "Deduplicated %s identical Qdrant chunk(s) before rebuild",
                len(documents) - len(unique_documents),
            )

        texts = [d.page_content or "" for d in unique_documents]

        # Build a stable BM25 vocabulary/stats from the full corpus. Persist it only
        # after the dense rebuild succeeds so failed embedding calls do not leave
        # query-side sparse state out of sync with the live Qdrant collection.
        tokenizer = BM25SparseTokenizer(corpus=texts)

        # Determine dense vector size.
        probe = embeddings.embed_query(texts[0] if texts[0] else "probe")
        vector_size = len(probe)
        if vector_size <= 0:
            raise ValueError("Failed to determine embedding vector size")

        # Build into a unique physical collection. Live reads continue through
        # the stable alias until this collection has been fully verified.
        build_collection = f"{self.base_collection_name}__build_{time.time_ns()}"
        old_collection = self._get_alias_target()
        if old_collection is None and self._physical_collection_exists(
            self.base_collection_name
        ):
            # First blue/green rebuild after upgrading from the legacy layout.
            old_collection = self.base_collection_name
        total = len(unique_documents)
        upserted = 0
        start = time.time()
        staged_vocab_path = self.vocab_path.with_name(
            f".{self.vocab_path.name}.{build_collection}.tmp"
        )
        alias_committed = False

        try:
            self._create_collection(build_collection, vector_size=vector_size)
            for batch_docs in self._iter_batches(unique_documents, embed_batch_size):
                batch_texts = [d.page_content or "" for d in batch_docs]
                batch_dense = embeddings.embed_documents(batch_texts)

                points: List[rest.PointStruct] = []
                for doc, dense_vec in zip(batch_docs, batch_dense, strict=True):
                    content = doc.page_content or ""
                    md = dict(doc.metadata) if doc.metadata else {}

                    # Sparse vector using frozen corpus stats (no mutation).
                    sparse_idx, sparse_val = tokenizer.vectorize_document_static(
                        content
                    )
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
                        collection_name=build_collection,
                        points=upsert_points,
                        wait=True,
                    )
                    upserted += len(upsert_points)

                logger.info(f"Upserted {upserted}/{total} indexed chunks...")

            self._verify_built_collection(build_collection, upserted)
            self.vocab_path.parent.mkdir(parents=True, exist_ok=True)
            staged_vocab_path.write_text(
                tokenizer.export_vocabulary(), encoding="utf-8"
            )
            try:
                alias_old_collection = self._swap_active_alias(build_collection)
            except Exception as swap_error:
                # Qdrant may commit the atomic alias update and then time out while
                # returning the response. Reconcile that ambiguous result before
                # deciding whether the build succeeded or is safe to delete.
                try:
                    current_target = self._get_alias_target_strict()
                except Exception as reconciliation_error:
                    logger.error(
                        "Unable to reconcile Qdrant alias after swap failure; "
                        "preserving both collections",
                        exc_info=True,
                    )
                    raise swap_error from reconciliation_error
                if current_target != build_collection:
                    raise
                logger.warning(
                    "Qdrant alias swap response failed, but alias '%s' is active; "
                    "completing rebuild commit",
                    build_collection,
                )
                alias_old_collection = old_collection
            alias_committed = True
            if alias_old_collection is not None:
                old_collection = alias_old_collection
        except Exception:
            staged_vocab_path.unlink(missing_ok=True)
            # Delete only when a strict alias read proves the build is not live.
            try:
                current_target = self._get_alias_target_strict()
            except Exception:
                logger.error(
                    "Unable to verify Qdrant alias after rebuild failure; "
                    "preserving incomplete build '%s'",
                    build_collection,
                    exc_info=True,
                )
            else:
                if current_target != build_collection:
                    try:
                        self._client.delete_collection(build_collection)
                    except Exception:
                        logger.warning(
                            "Failed to clean up incomplete Qdrant build '%s'",
                            build_collection,
                            exc_info=True,
                        )
            raise

        if not alias_committed:
            raise RuntimeError("Qdrant rebuild ended without committing active alias")

        # The staged file is on the same filesystem, so promotion is atomic. It is
        # committed before a new retriever is constructed by service setup.
        try:
            staged_vocab_path.replace(self.vocab_path)
        except Exception as promotion_error:
            try:
                self._restore_active_alias(old_collection)
            except Exception as rollback_error:
                logger.critical(
                    "Failed to restore Qdrant alias after BM25 vocabulary "
                    "promotion failure; preserving both collections",
                    exc_info=True,
                )
                raise promotion_error from rollback_error
            logger.error(
                "Restored Qdrant alias to '%s' after BM25 vocabulary "
                "promotion failure; preserving build '%s' for diagnosis",
                old_collection,
                build_collection,
            )
            raise
        logger.info(
            f"BM25 vocabulary saved to {self.vocab_path} "
            f"(vocab_size={tokenizer.vocabulary_size}, num_docs={tokenizer.get_statistics().get('num_documents')})"
        )

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

        # Retire the previous physical collection only after alias, vocabulary,
        # and metadata commit-side state have all completed.
        if old_collection and old_collection != build_collection:
            try:
                self._client.delete_collection(old_collection)
            except Exception:
                logger.warning(
                    "Failed to delete retired Qdrant collection '%s'",
                    old_collection,
                    exc_info=True,
                )

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

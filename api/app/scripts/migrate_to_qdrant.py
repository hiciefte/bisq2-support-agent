#!/usr/bin/env python3
"""
Migrate documents from ChromaDB to Qdrant with hybrid indexing.

This script:
1. Reads existing documents from ChromaDB vector store
2. Creates a Qdrant collection with hybrid (dense + sparse) vectors
3. Upserts all documents with both vector types
4. Verifies document count matches

Usage:
    python -m api.app.scripts.migrate_to_qdrant [--dry-run] [--force]

Options:
    --dry-run   Show what would be migrated without making changes
    --force     Overwrite existing Qdrant collection if it exists
"""

import argparse
import logging
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

# Add project root to path for imports
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from app.core.config import get_settings  # noqa: E402
from qdrant_client import QdrantClient  # noqa: E402
from qdrant_client.http import models as rest  # noqa: E402
from qdrant_client.http.exceptions import UnexpectedResponse  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


class ChromaToQdrantMigrator:
    """Migrates documents from ChromaDB to Qdrant with hybrid indexing."""

    def __init__(
        self,
        settings=None,
        dry_run: bool = False,
        force: bool = False,
    ):
        """Initialize the migrator.

        Args:
            settings: Application settings (uses get_settings() if None)
            dry_run: If True, show what would be done without making changes
            force: If True, overwrite existing Qdrant collection
        """
        self.settings = settings or get_settings()
        self.dry_run = dry_run
        self.force = force

        # Qdrant client
        self._qdrant_client = None

        # Embedding model
        self._embeddings = None

    @property
    def qdrant_client(self) -> QdrantClient:
        """Get or create Qdrant client."""
        if self._qdrant_client is None:
            self._qdrant_client = QdrantClient(
                host=self.settings.QDRANT_HOST,
                port=self.settings.QDRANT_PORT,
                timeout=60,
            )
        return self._qdrant_client

    @property
    def embeddings(self):
        """Get or create embeddings model."""
        if self._embeddings is None:
            try:
                from llama_index.embeddings.openai import OpenAIEmbedding

                self._embeddings = OpenAIEmbedding(
                    model=self.settings.OPENAI_EMBEDDING_MODEL,
                    api_key=self.settings.OPENAI_API_KEY,
                )
            except ImportError:
                from langchain_openai import OpenAIEmbeddings

                self._embeddings = OpenAIEmbeddings(
                    model=self.settings.OPENAI_EMBEDDING_MODEL,
                    openai_api_key=self.settings.OPENAI_API_KEY,
                )
        return self._embeddings

    def load_chromadb_documents(self) -> List[Dict[str, Any]]:
        """Load all documents from ChromaDB.

        Returns:
            List of document dictionaries with content, metadata, and embeddings
        """
        from langchain_chroma import Chroma

        vectorstore_path = self.settings.VECTOR_STORE_DIR_PATH

        if not Path(vectorstore_path).exists():
            logger.error(f"ChromaDB vectorstore not found at {vectorstore_path}")
            return []

        logger.info(f"Loading documents from ChromaDB: {vectorstore_path}")

        # Initialize ChromaDB
        from app.services.rag.embeddings_provider import LiteLLMEmbeddings

        embeddings = LiteLLMEmbeddings(self.settings)
        vectorstore = Chroma(
            persist_directory=vectorstore_path,
            embedding_function=embeddings,
            collection_name="bisq_support",
        )

        # Get the underlying collection
        collection = vectorstore._collection

        # Fetch all documents
        results = collection.get(
            include=["documents", "metadatas", "embeddings"],
        )

        documents = []
        ids = results.get("ids", [])
        texts = results.get("documents", [])
        metadatas = results.get("metadatas", [])
        embeddings_list = results.get("embeddings", [])

        for i, doc_id in enumerate(ids):
            doc = {
                "id": doc_id,
                "content": texts[i] if i < len(texts) else "",
                "metadata": metadatas[i] if i < len(metadatas) else {},
                "embedding": (
                    embeddings_list[i]
                    if embeddings_list and i < len(embeddings_list)
                    else None
                ),
            }
            documents.append(doc)

        logger.info(f"Loaded {len(documents)} documents from ChromaDB")
        return documents

    def create_qdrant_collection(self, vector_size: int = 1536) -> bool:
        """Create Qdrant collection with hybrid indexing.

        Args:
            vector_size: Dimension of dense vectors (default: 1536 for text-embedding-3-small)

        Returns:
            True if collection was created, False if it already existed
        """
        collection_name = self.settings.QDRANT_COLLECTION

        # Check if collection exists
        try:
            existing = self.qdrant_client.get_collection(collection_name)
            if existing:
                if self.force:
                    logger.warning(f"Deleting existing collection: {collection_name}")
                    if not self.dry_run:
                        self.qdrant_client.delete_collection(collection_name)
                else:
                    logger.info(f"Collection {collection_name} already exists")
                    return False
        except UnexpectedResponse:
            # Collection doesn't exist
            pass

        if self.dry_run:
            logger.info(f"[DRY RUN] Would create collection: {collection_name}")
            return True

        logger.info(f"Creating Qdrant collection: {collection_name}")

        # Create collection with hybrid vectors
        self.qdrant_client.create_collection(
            collection_name=collection_name,
            vectors_config={
                "dense": rest.VectorParams(
                    size=vector_size,
                    distance=rest.Distance.COSINE,
                ),
            },
            sparse_vectors_config={
                "sparse": rest.SparseVectorParams(
                    modifier=rest.Modifier.IDF,
                ),
            },
            optimizers_config=rest.OptimizersConfigDiff(
                indexing_threshold=10000,  # Start indexing after 10k points
            ),
        )

        # Create payload indexes for filtering
        self.qdrant_client.create_payload_index(
            collection_name=collection_name,
            field_name="protocol",
            field_schema=rest.PayloadSchemaType.KEYWORD,
        )
        self.qdrant_client.create_payload_index(
            collection_name=collection_name,
            field_name="type",
            field_schema=rest.PayloadSchemaType.KEYWORD,
        )

        logger.info(
            f"Created Qdrant collection with hybrid indexing: {collection_name}"
        )
        return True

    def _tokenize_for_sparse(self, text: str) -> Tuple[List[int], List[float]]:
        """Tokenize text for sparse (BM25-style) vector.

        Args:
            text: Document text

        Returns:
            Tuple of (indices, values) for sparse vector
        """
        # Simple whitespace tokenization with hash-based indexing
        # Production would use proper vocabulary and TF-IDF/BM25 weighting
        tokens = text.lower().split()
        token_counts: Dict[int, int] = {}

        for token in tokens:
            # Skip very short tokens
            if len(token) < 2:
                continue
            idx = hash(token) % 30000
            token_counts[idx] = token_counts.get(idx, 0) + 1

        indices = list(token_counts.keys())
        # Simple TF weighting (production would use proper BM25)
        values = [float(count) for count in token_counts.values()]

        return indices, values

    def _get_embedding(self, text: str) -> List[float]:
        """Get embedding for text.

        Args:
            text: Text to embed

        Returns:
            Embedding vector
        """
        if hasattr(self.embeddings, "get_text_embedding"):
            return self.embeddings.get_text_embedding(text)
        elif hasattr(self.embeddings, "embed_query"):
            return self.embeddings.embed_query(text)
        else:
            raise ValueError("Embeddings model does not support text embedding")

    def migrate_documents(self, documents: List[Dict[str, Any]]) -> int:
        """Migrate documents to Qdrant.

        Args:
            documents: List of document dictionaries

        Returns:
            Number of documents migrated
        """
        collection_name = self.settings.QDRANT_COLLECTION
        batch_size = 100
        migrated = 0

        logger.info(f"Migrating {len(documents)} documents to Qdrant...")

        for i in range(0, len(documents), batch_size):
            batch = documents[i : i + batch_size]
            points = []

            for doc in batch:
                doc_id = doc["id"]
                content = doc["content"]
                metadata = doc["metadata"]

                # Get or compute dense embedding
                if doc.get("embedding"):
                    dense_vector = doc["embedding"]
                else:
                    dense_vector = self._get_embedding(content)

                # Compute sparse vector
                sparse_indices, sparse_values = self._tokenize_for_sparse(content)

                # Create point
                point = rest.PointStruct(
                    id=hash(doc_id) % (2**63),  # Convert string ID to int
                    vector={
                        "dense": dense_vector,
                        "sparse": rest.SparseVector(
                            indices=sparse_indices,
                            values=sparse_values,
                        ),
                    },
                    payload={
                        "content": content,
                        "original_id": doc_id,
                        **metadata,
                    },
                )
                points.append(point)

            if self.dry_run:
                logger.info(
                    f"[DRY RUN] Would upsert batch {i//batch_size + 1}: {len(points)} points"
                )
            else:
                self.qdrant_client.upsert(
                    collection_name=collection_name,
                    points=points,
                )

            migrated += len(points)
            logger.info(f"Migrated {migrated}/{len(documents)} documents...")

        return migrated

    def verify_migration(self, expected_count: int) -> bool:
        """Verify migration was successful.

        Args:
            expected_count: Expected number of documents

        Returns:
            True if verification passed
        """
        collection_name = self.settings.QDRANT_COLLECTION

        if self.dry_run:
            logger.info(
                f"[DRY RUN] Would verify {expected_count} documents in {collection_name}"
            )
            return True

        try:
            info = self.qdrant_client.get_collection(collection_name)
            actual_count = info.points_count

            if actual_count == expected_count:
                logger.info(f"Verification passed: {actual_count} documents in Qdrant")
                return True
            else:
                logger.warning(
                    f"Document count mismatch: expected {expected_count}, found {actual_count}"
                )
                return False

        except Exception as e:
            logger.error(f"Verification failed: {e}")
            return False

    def run(self) -> bool:
        """Run the full migration process.

        Returns:
            True if migration was successful
        """
        logger.info("=" * 60)
        logger.info("Starting ChromaDB to Qdrant migration")
        if self.dry_run:
            logger.info("DRY RUN MODE - No changes will be made")
        logger.info("=" * 60)

        # Step 1: Load documents from ChromaDB
        documents = self.load_chromadb_documents()
        if not documents:
            logger.error("No documents found in ChromaDB")
            return False

        # Step 2: Create Qdrant collection
        try:
            self.create_qdrant_collection()
        except Exception as e:
            logger.error(f"Failed to create Qdrant collection: {e}")
            return False

        # Step 3: Migrate documents
        try:
            migrated = self.migrate_documents(documents)
            logger.info(f"Migrated {migrated} documents to Qdrant")
        except Exception as e:
            logger.error(f"Migration failed: {e}", exc_info=True)
            return False

        # Step 4: Verify migration
        if not self.verify_migration(len(documents)):
            logger.warning("Migration verification failed - please check manually")
            return False

        logger.info("=" * 60)
        logger.info("Migration completed successfully!")
        logger.info(f"Collection: {self.settings.QDRANT_COLLECTION}")
        logger.info(f"Documents: {len(documents)}")
        logger.info("=" * 60)

        return True


def main():
    """Main entry point for migration script."""
    parser = argparse.ArgumentParser(
        description="Migrate documents from ChromaDB to Qdrant"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without making changes",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing Qdrant collection",
    )

    args = parser.parse_args()

    migrator = ChromaToQdrantMigrator(
        dry_run=args.dry_run,
        force=args.force,
    )

    success = migrator.run()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()

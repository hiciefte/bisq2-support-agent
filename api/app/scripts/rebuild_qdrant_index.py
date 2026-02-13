#!/usr/bin/env python3
"""
Rebuild the Qdrant index from the authoritative sources (wiki + verified FAQs).

Usage:
  python -m api.app.scripts.rebuild_qdrant_index [--force]
"""

import argparse
import logging
import sys
from pathlib import Path

# Add project root to path for imports
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from app.core.config import get_settings  # noqa: E402
from app.services.faq_service import FAQService  # noqa: E402
from app.services.rag.document_processor import DocumentProcessor  # noqa: E402
from app.services.rag.llm_provider import LLMProvider  # noqa: E402
from app.services.rag.qdrant_index_manager import QdrantIndexManager  # noqa: E402
from app.services.wiki_service import WikiService  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def main() -> int:
    parser = argparse.ArgumentParser(description="Rebuild the Qdrant RAG index.")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force rebuild even if metadata indicates index is up-to-date.",
    )
    args = parser.parse_args()

    settings = get_settings()

    wiki = WikiService(settings=settings)
    faq = FAQService(settings=settings)

    docs = wiki.load_wiki_data() + faq.load_faq_data()
    if not docs:
        logger.error("No documents loaded; aborting.")
        return 2

    processor = DocumentProcessor(chunk_size=2000, chunk_overlap=500)
    splits = processor.split_documents(docs)

    llm_provider = LLMProvider(settings=settings)
    embeddings = llm_provider.initialize_embeddings()

    manager = QdrantIndexManager(settings=settings)
    result = manager.rebuild_index(splits, embeddings=embeddings, force=args.force)
    logger.info(f"Rebuild result: {result}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

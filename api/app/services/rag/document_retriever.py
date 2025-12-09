"""
Document Retriever for version-aware RAG retrieval.

This module handles intelligent document retrieval with:
- Multi-stage version-priority retrieval (Bisq 2 > General > Bisq 1)
- Document formatting with version context
- Source deduplication
"""

import logging
import re
from typing import Dict, List, Set, Tuple

from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_core.vectorstores import VectorStoreRetriever

logger = logging.getLogger(__name__)


# Type alias for document with similarity score
DocumentWithScore = Tuple[Document, float]


class DocumentRetriever:
    """Retriever for version-aware document retrieval in RAG system.

    This class handles:
    - Multi-stage retrieval prioritizing Bisq 2 content
    - Version-aware document formatting
    - Source deduplication to prevent repetitive results
    """

    def __init__(
        self, vectorstore: Chroma, retriever: VectorStoreRetriever | None = None
    ):
        """Initialize the document retriever.

        Args:
            vectorstore: ChromaDB vectorstore instance
            retriever: LangChain VectorStoreRetriever instance (optional, defaults to vectorstore.as_retriever())
        """
        self.vectorstore = vectorstore
        self.retriever = retriever or vectorstore.as_retriever()

    def retrieve_with_version_priority(self, query: str) -> List[Document]:
        """Multi-stage retrieval that adapts to version-specific queries.

        For Bisq 2 queries (default):
            Stage 1: Search for Bisq 2 content (k=6, highest priority)
            Stage 2: Add General content if needed (k=4)
            Stage 3: Only add Bisq 1 content if insufficient results (k=2, lowest priority)

        For explicit Bisq 1 queries:
            Stage 1: Search for Bisq 1 content (k=4, primary)
            Stage 2: Add General/Both content (k=2, secondary)
            Stage 3: Skip Bisq 2 content (comparison queries use Bisq 2-first flow)

        Args:
            query: The search query

        Returns:
            List of documents prioritized by version relevance
        """
        all_docs = []

        # Detect version from query using word boundaries to avoid false positives
        query_lower = query.lower()
        is_bisq1_query = bool(re.search(r"\bbisq\s*1\b|\bbisq1\b", query_lower))
        mentions_bisq2 = bool(re.search(r"\bbisq\s*2\b|\bbisq2\b", query_lower))
        comparison_tokens = re.compile(
            r"\b(compare|comparison|different|difference|diff|versus|vs|both\s+versions)\b"
        )
        is_comparison_query = (is_bisq1_query and mentions_bisq2) or bool(
            comparison_tokens.search(query_lower)
        )

        try:
            if is_bisq1_query and not is_comparison_query:
                # User explicitly asked about Bisq 1
                logger.info(
                    "Detected explicit Bisq 1 query - prioritizing Bisq 1 content"
                )

                # Stage 1: Prioritize Bisq 1 content (k=4 for better coverage)
                logger.info("Stage 1: Searching for Bisq 1 content...")
                bisq1_docs = self.vectorstore.similarity_search(
                    query, k=4, filter={"bisq_version": "Bisq 1"}
                )
                logger.info(f"Found {len(bisq1_docs)} Bisq 1 documents")
                all_docs.extend(bisq1_docs)

                # Stage 2: Add General/Both content as supplementary
                if len(all_docs) < 3:
                    logger.info("Stage 2: Searching for General content...")
                    general_docs = self.vectorstore.similarity_search(
                        query, k=2, filter={"bisq_version": "General"}
                    )
                    logger.info(f"Found {len(general_docs)} General documents")
                    all_docs.extend(general_docs)

                # Stage 3: Skip Bisq 2 content for pure Bisq 1 queries
                logger.info("Skipping Bisq 2 content for explicit Bisq 1 query")

            else:
                # Default Bisq 2 priority OR comparison query
                if is_comparison_query:
                    logger.info("Detected comparison query - retrieving both versions")

                # Stage 1: Prioritize Bisq 2 content
                logger.info("Stage 1: Searching for Bisq 2 content...")
                bisq2_docs = self.vectorstore.similarity_search(
                    query, k=6, filter={"bisq_version": "Bisq 2"}
                )
                logger.info(f"Found {len(bisq2_docs)} Bisq 2 documents")
                all_docs.extend(bisq2_docs)

                # Stage 2: Add general content if we don't have enough Bisq 2 content
                # Threshold of 4 ensures we have sufficient Bisq 2 context before adding general docs
                if len(all_docs) < 4:
                    logger.info("Stage 2: Searching for General content...")
                    general_docs = self.vectorstore.similarity_search(
                        query, k=4, filter={"bisq_version": "General"}
                    )
                    logger.info(f"Found {len(general_docs)} General documents")
                    all_docs.extend(general_docs)

                # Stage 3: Only add Bisq 1 content if we still don't have enough
                # Threshold of 3 ensures Bisq 1 content is truly a last resort
                if len(all_docs) < 3:
                    logger.info("Stage 3: Searching for Bisq 1 content (fallback)...")
                    bisq1_docs = self.vectorstore.similarity_search(
                        query, k=2, filter={"bisq_version": "Bisq 1"}
                    )
                    logger.info(f"Found {len(bisq1_docs)} Bisq 1 documents")
                    all_docs.extend(bisq1_docs)
        except Exception as e:
            logger.error(f"Error in version-priority retrieval: {e!s}", exc_info=True)
            # Fallback: retrieve documents and post-sort by version priority
            # to maintain Bisq 2 > General > Bisq 1 ordering
            logger.warning(
                "Metadata filtering failed, falling back to post-retrieval sorting"
            )
            fallback_docs = self.retriever.invoke(query)

            # Define version priority based on query type (higher number = higher priority)
            if is_bisq1_query and not is_comparison_query:
                # For Bisq 1 queries, prioritize Bisq 1 content
                version_priority = {"Bisq 1": 2, "General": 1, "Bisq 2": 0}
            else:
                # Default: prioritize Bisq 2 content
                version_priority = {"Bisq 2": 2, "General": 1, "Bisq 1": 0}

            # Sort by version priority while preserving retrieval order within each version
            sorted_docs = sorted(
                fallback_docs,
                key=lambda doc: version_priority.get(
                    doc.metadata.get("bisq_version", "General"), 1
                ),
                reverse=True,
            )

            logger.info(
                f"Fallback retrieved {len(sorted_docs)} documents, sorted by version priority"
            )
            return sorted_docs
        else:
            # De-duplicate while preserving order
            seen: set[tuple[str, str]] = set()
            unique_docs: list[Document] = []
            for d in all_docs:
                key = (
                    d.metadata.get("title", "Unknown"),
                    d.metadata.get("section", ""),
                )
                if key not in seen:
                    seen.add(key)
                    unique_docs.append(d)

            logger.info(
                f"Total documents retrieved: {len(unique_docs)} (deduped from {len(all_docs)})"
            )
            return unique_docs

    def format_documents(self, docs: List[Document]) -> str:
        """Format retrieved documents with version-aware processing.

        Args:
            docs: List of retrieved documents

        Returns:
            Formatted string with version context and source attribution
        """
        if not docs:
            return ""

        # Sort documents by version weight and relevance
        # Use bisq_version metadata (matches retrieval filter key)
        # Define version priority (higher number = higher priority; matches reverse=True)
        version_priority = {"Bisq 2": 2, "General": 1, "Bisq 1": 0}

        sorted_docs = sorted(
            docs,
            key=lambda x: (
                x.metadata.get("source_weight", 1.0),
                version_priority.get(x.metadata.get("bisq_version", "General"), 1),
            ),
            reverse=True,
        )

        formatted_docs = []
        for doc in sorted_docs:
            # Extract metadata
            title = doc.metadata.get("title", "Unknown")
            section = doc.metadata.get("section", "")
            source_type = doc.metadata.get("type", "wiki")

            # Determine version from metadata and content
            bisq_version = doc.metadata.get("bisq_version", "General")
            if bisq_version == "General":
                # Check content for version-specific information
                content = doc.page_content.lower()
                if "bisq 2" in content or "bisq2" in content:
                    bisq_version = "Bisq 2"
                elif "bisq 1" in content or "bisq1" in content:
                    bisq_version = "Bisq 1"

            # Format the entry with version context and source attribution
            entry = f"[{bisq_version}] [{source_type.upper()}] {title}"
            if section:
                entry += f" - {section}"
            entry += f"\n{doc.page_content}\n"
            formatted_docs.append(entry)

        return "\n\n".join(formatted_docs)

    def deduplicate_sources(self, sources: List[Dict]) -> List[Dict]:
        """Deduplicate sources to prevent multiple identical or very similar sources.

        Args:
            sources: List of source dictionaries

        Returns:
            List of deduplicated sources
        """
        if not sources:
            return []

        # Use a set to track unique sources
        seen_sources: Set[str] = set()
        unique_sources = []

        for source in sources:
            # Create a key based on title and type (primary deduplication)
            source_key = (
                f"{source.get('title', 'Unknown')}:{source.get('type', 'unknown')}"
            )

            # Only include the source if we haven't seen this key before
            if source_key not in seen_sources:
                seen_sources.add(source_key)
                unique_sources.append(source)

        logger.info(
            f"Deduplicated sources from {len(sources)} to {len(unique_sources)}"
        )
        return unique_sources

    def retrieve_with_scores(
        self, query: str, detected_version: str = "Bisq 2"
    ) -> Tuple[List[Document], List[float]]:
        """Retrieve documents with similarity scores for confidence calculation.

        This method uses similarity_search_with_score() to return both documents
        and their relevance scores, which are used by the confidence scorer.

        Args:
            query: The search query
            detected_version: Detected Bisq version from user context

        Returns:
            Tuple of (documents, scores) where scores are similarity values (0-1)
        """
        all_docs_with_scores: List[DocumentWithScore] = []

        # Detect version from query
        query_lower = query.lower()
        is_bisq1_query = bool(re.search(r"\bbisq\s*1\b|\bbisq1\b", query_lower))
        mentions_bisq2 = bool(re.search(r"\bbisq\s*2\b|\bbisq2\b", query_lower))
        comparison_tokens = re.compile(
            r"\b(compare|comparison|different|difference|diff|versus|vs|both\s+versions)\b"
        )
        is_comparison_query = (is_bisq1_query and mentions_bisq2) or bool(
            comparison_tokens.search(query_lower)
        )

        # Override with detected version if not explicit in query
        if not is_bisq1_query and not mentions_bisq2 and detected_version == "Bisq 1":
            is_bisq1_query = True
            logger.info("Using detected version context: Bisq 1")

        try:
            if is_bisq1_query and not is_comparison_query:
                logger.info("Retrieving with scores for Bisq 1 query")

                # Stage 1: Bisq 1 content
                bisq1_results = self.vectorstore.similarity_search_with_score(
                    query, k=4, filter={"bisq_version": "Bisq 1"}
                )
                all_docs_with_scores.extend(bisq1_results)

                # Stage 2: General content
                if len(all_docs_with_scores) < 3:
                    general_results = self.vectorstore.similarity_search_with_score(
                        query, k=2, filter={"bisq_version": "General"}
                    )
                    all_docs_with_scores.extend(general_results)
            else:
                logger.info("Retrieving with scores for Bisq 2 query")

                # Stage 1: Bisq 2 content
                bisq2_results = self.vectorstore.similarity_search_with_score(
                    query, k=6, filter={"bisq_version": "Bisq 2"}
                )
                all_docs_with_scores.extend(bisq2_results)

                # Stage 2: General content
                if len(all_docs_with_scores) < 4:
                    general_results = self.vectorstore.similarity_search_with_score(
                        query, k=4, filter={"bisq_version": "General"}
                    )
                    all_docs_with_scores.extend(general_results)

                # Stage 3: Bisq 1 fallback
                if len(all_docs_with_scores) < 3:
                    bisq1_results = self.vectorstore.similarity_search_with_score(
                        query, k=2, filter={"bisq_version": "Bisq 1"}
                    )
                    all_docs_with_scores.extend(bisq1_results)

        except Exception as e:
            logger.error(f"Error in score-based retrieval: {e!s}", exc_info=True)
            # Fallback to standard retrieval without scores
            docs = self.retrieve_with_version_priority(query)
            # Return neutral scores for fallback
            return docs, [0.5] * len(docs)

        # De-duplicate while preserving scores
        seen: set[tuple[str, str]] = set()
        unique_docs: List[Document] = []
        unique_scores: List[float] = []

        for doc, score in all_docs_with_scores:
            key = (
                doc.metadata.get("title", "Unknown"),
                doc.metadata.get("section", ""),
            )
            if key not in seen:
                seen.add(key)
                unique_docs.append(doc)
                # ChromaDB returns distance (lower is better), convert to similarity
                # Distance is typically 0-2 for cosine, normalize to 0-1 similarity
                similarity = max(0, 1 - (score / 2))
                unique_scores.append(similarity)

        logger.info(
            f"Retrieved {len(unique_docs)} docs with scores "
            f"(avg similarity: {sum(unique_scores)/len(unique_scores) if unique_scores else 0:.3f})"
        )

        return unique_docs, unique_scores

    def get_retrieval_confidence(self, scores: List[float]) -> float:
        """Calculate retrieval confidence from similarity scores.

        Args:
            scores: List of similarity scores (0-1)

        Returns:
            Retrieval confidence score (0-1)
        """
        if not scores:
            return 0.0

        # Use weighted average: top results matter more
        weights = [1.0 / (i + 1) for i in range(len(scores))]
        weighted_sum = sum(s * w for s, w in zip(scores, weights))
        total_weight = sum(weights)

        return weighted_sum / total_weight if total_weight > 0 else 0.0

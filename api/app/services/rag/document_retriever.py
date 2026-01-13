"""
Document Retriever for protocol-aware RAG retrieval.

This module handles intelligent document retrieval with:
- Multi-stage protocol-priority retrieval (bisq_easy > all > multisig_v1)
- Document formatting with protocol context
- Source deduplication

Protocol values:
- bisq_easy: Bisq Easy protocol (formerly Bisq 2)
- multisig_v1: Bisq 1 multisig protocol (formerly Bisq 1)
- musig: MuSig protocol (future)
- all: Applies to all protocols (formerly General)
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
    """Retriever for protocol-aware document retrieval in RAG system.

    This class handles:
    - Multi-stage retrieval prioritizing Bisq Easy content
    - Protocol-aware document formatting
    - Source deduplication to prevent repetitive results

    Protocol mapping:
    - bisq_easy: Bisq Easy protocol (priority for most queries)
    - multisig_v1: Bisq 1 multisig protocol
    - musig: MuSig protocol (future)
    - all: Applies to all protocols
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

    def retrieve_with_version_priority(
        self, query: str, detected_version: str | None = None
    ) -> List[Document]:
        """Multi-stage retrieval that adapts to protocol-specific queries.

        For Bisq Easy queries (default):
            Stage 1: Search for bisq_easy content (k=6, highest priority)
            Stage 2: Add 'all' content if needed (k=4)
            Stage 3: Only add multisig_v1 content if insufficient results (k=2, lowest priority)

        For explicit multisig_v1 (Bisq 1) queries:
            Stage 1: Search for multisig_v1 content (k=4, primary)
            Stage 2: Add 'all' content (k=2, secondary)
            Stage 3: Skip bisq_easy content (comparison queries use bisq_easy-first flow)

        Args:
            query: The search query
            detected_version: Optional explicitly detected version ("Bisq 1", "Bisq 2", or "Unknown")
                             Overrides query text pattern matching when provided.
                             Maps to protocols: Bisq 1 -> multisig_v1, Bisq 2 -> bisq_easy

        Returns:
            List of documents prioritized by protocol relevance
        """
        all_docs = []

        # Use explicit detected_version if provided, otherwise detect from query text
        if detected_version:
            logger.info(
                f"Using explicitly detected version: {detected_version} (ignoring query text patterns)"
            )
            # Map detected version to query classification
            # Accepts both version names (Bisq 1, Bisq 2) and protocol names (multisig_v1, bisq_easy)
            if detected_version in ("Bisq 1", "multisig_v1"):
                is_multisig_query = True
                mentions_bisq_easy = False
                is_comparison_query = False
            elif detected_version in ("Bisq 2", "bisq_easy"):
                is_multisig_query = False
                mentions_bisq_easy = True
                is_comparison_query = False
            else:  # "Unknown", "all", or other - default to Bisq Easy priority
                is_multisig_query = False
                mentions_bisq_easy = True
                is_comparison_query = False
        else:
            # Detect version from query using word boundaries to avoid false positives
            logger.info("No explicit version provided, detecting from query text...")
            query_lower = query.lower()
            is_multisig_query = bool(re.search(r"\bbisq\s*1\b|\bbisq1\b", query_lower))
            mentions_bisq_easy = bool(re.search(r"\bbisq\s*2\b|\bbisq2\b", query_lower))
            comparison_tokens = re.compile(
                r"\b(compare|comparison|different|difference|diff|versus|vs|both\s+versions)\b"
            )
            is_comparison_query = (is_multisig_query and mentions_bisq_easy) or bool(
                comparison_tokens.search(query_lower)
            )

        try:
            if is_multisig_query and not is_comparison_query:
                # User explicitly asked about Bisq 1 / multisig
                logger.info(
                    "Detected explicit Bisq 1 query - prioritizing multisig_v1 content"
                )

                # Stage 1: Prioritize multisig_v1 content (k=4 for better coverage)
                logger.info("Stage 1: Searching for multisig_v1 content...")
                multisig_docs = self.vectorstore.similarity_search(
                    query, k=4, filter={"protocol": "multisig_v1"}
                )
                logger.info(f"Found {len(multisig_docs)} multisig_v1 documents")
                all_docs.extend(multisig_docs)

                # Stage 2: Add 'all' content as supplementary
                if len(all_docs) < 3:
                    logger.info("Stage 2: Searching for 'all' protocol content...")
                    all_protocol_docs = self.vectorstore.similarity_search(
                        query, k=2, filter={"protocol": "all"}
                    )
                    logger.info(f"Found {len(all_protocol_docs)} 'all' documents")
                    all_docs.extend(all_protocol_docs)

                # Stage 3: Skip bisq_easy content for pure multisig queries
                logger.info("Skipping bisq_easy content for explicit Bisq 1 query")

            else:
                # Default Bisq Easy priority OR comparison query
                if is_comparison_query:
                    logger.info("Detected comparison query - retrieving both protocols")

                # Stage 1: Prioritize bisq_easy content
                logger.info("Stage 1: Searching for bisq_easy content...")
                bisq_easy_docs = self.vectorstore.similarity_search(
                    query, k=6, filter={"protocol": "bisq_easy"}
                )
                logger.info(f"Found {len(bisq_easy_docs)} bisq_easy documents")
                all_docs.extend(bisq_easy_docs)

                # Stage 2: Add 'all' content if we don't have enough bisq_easy content
                # Threshold of 4 ensures we have sufficient bisq_easy context before adding general docs
                if len(all_docs) < 4:
                    logger.info("Stage 2: Searching for 'all' protocol content...")
                    all_protocol_docs = self.vectorstore.similarity_search(
                        query, k=4, filter={"protocol": "all"}
                    )
                    logger.info(f"Found {len(all_protocol_docs)} 'all' documents")
                    all_docs.extend(all_protocol_docs)

                # Stage 3: Only add multisig_v1 content if we still don't have enough
                # Threshold of 3 ensures multisig_v1 content is truly a last resort
                if len(all_docs) < 3:
                    logger.info(
                        "Stage 3: Searching for multisig_v1 content (fallback)..."
                    )
                    multisig_docs = self.vectorstore.similarity_search(
                        query, k=2, filter={"protocol": "multisig_v1"}
                    )
                    logger.info(f"Found {len(multisig_docs)} multisig_v1 documents")
                    all_docs.extend(multisig_docs)
        except Exception as e:
            logger.error(f"Error in protocol-priority retrieval: {e!s}", exc_info=True)
            # Fallback: retrieve documents and post-sort by protocol priority
            # to maintain bisq_easy > all > multisig_v1 ordering
            logger.warning(
                "Metadata filtering failed, falling back to post-retrieval sorting"
            )
            fallback_docs = self.retriever.invoke(query)

            # Define protocol priority based on query type (higher number = higher priority)
            if is_multisig_query and not is_comparison_query:
                # For Bisq 1 / multisig queries, prioritize multisig_v1 content
                protocol_priority = {"multisig_v1": 2, "all": 1, "bisq_easy": 0}
            else:
                # Default: prioritize bisq_easy content
                protocol_priority = {"bisq_easy": 2, "all": 1, "multisig_v1": 0}

            # Sort by protocol priority while preserving retrieval order within each protocol
            sorted_docs = sorted(
                fallback_docs,
                key=lambda doc: protocol_priority.get(
                    doc.metadata.get("protocol", "all"), 1
                ),
                reverse=True,
            )

            logger.info(
                f"Fallback retrieved {len(sorted_docs)} documents, sorted by protocol priority"
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
        """Format retrieved documents with protocol-aware processing.

        Args:
            docs: List of retrieved documents

        Returns:
            Formatted string with protocol context and source attribution
        """
        if not docs:
            return ""

        # Sort documents by protocol weight and relevance
        # Use protocol metadata (matches retrieval filter key)
        # Define protocol priority (higher number = higher priority; matches reverse=True)
        protocol_priority = {"bisq_easy": 2, "all": 1, "multisig_v1": 0}

        sorted_docs = sorted(
            docs,
            key=lambda x: (
                x.metadata.get("source_weight", 1.0),
                protocol_priority.get(x.metadata.get("protocol", "all"), 1),
            ),
            reverse=True,
        )

        formatted_docs = []
        for doc in sorted_docs:
            # Extract metadata
            title = doc.metadata.get("title", "Unknown")
            section = doc.metadata.get("section", "")
            source_type = doc.metadata.get("type", "wiki")

            # Determine protocol from metadata and content
            protocol = doc.metadata.get("protocol", "all")
            if protocol == "all":
                # Check content for protocol-specific information
                content = doc.page_content.lower()
                if "bisq 2" in content or "bisq2" in content or "bisq easy" in content:
                    protocol = "bisq_easy"
                elif "bisq 1" in content or "bisq1" in content or "multisig" in content:
                    protocol = "multisig_v1"

            # Map protocol to display name for formatting
            protocol_display = {
                "bisq_easy": "Bisq Easy",
                "multisig_v1": "Multisig v1",
                "musig": "MuSig",
                "all": "General",
            }.get(protocol, "General")

            # Format the entry with protocol context and source attribution
            entry = f"[{protocol_display}] [{source_type.upper()}] {title}"
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
            detected_version: Detected Bisq version from user context.
                             Maps to protocols: Bisq 1 -> multisig_v1, Bisq 2 -> bisq_easy

        Returns:
            Tuple of (documents, scores) where scores are similarity values (0-1)
        """
        all_docs_with_scores: List[DocumentWithScore] = []

        # Detect version from query
        query_lower = query.lower()
        is_multisig_query = bool(re.search(r"\bbisq\s*1\b|\bbisq1\b", query_lower))
        mentions_bisq_easy = bool(re.search(r"\bbisq\s*2\b|\bbisq2\b", query_lower))
        comparison_tokens = re.compile(
            r"\b(compare|comparison|different|difference|diff|versus|vs|both\s+versions)\b"
        )
        is_comparison_query = (is_multisig_query and mentions_bisq_easy) or bool(
            comparison_tokens.search(query_lower)
        )

        # Override with detected version if not explicit in query
        if (
            not is_multisig_query
            and not mentions_bisq_easy
            and detected_version == "Bisq 1"
        ):
            is_multisig_query = True
            logger.info("Using detected version context: Bisq 1 (multisig_v1)")

        try:
            if is_multisig_query and not is_comparison_query:
                logger.info("Retrieving with scores for Bisq 1 / multisig_v1 query")

                # Stage 1: multisig_v1 content
                multisig_results = self.vectorstore.similarity_search_with_score(
                    query, k=4, filter={"protocol": "multisig_v1"}
                )
                all_docs_with_scores.extend(multisig_results)

                # Stage 2: 'all' content
                if len(all_docs_with_scores) < 3:
                    all_results = self.vectorstore.similarity_search_with_score(
                        query, k=2, filter={"protocol": "all"}
                    )
                    all_docs_with_scores.extend(all_results)
            else:
                logger.info("Retrieving with scores for Bisq Easy query")

                # Stage 1: bisq_easy content
                bisq_easy_results = self.vectorstore.similarity_search_with_score(
                    query, k=6, filter={"protocol": "bisq_easy"}
                )
                all_docs_with_scores.extend(bisq_easy_results)

                # Stage 2: 'all' content
                if len(all_docs_with_scores) < 4:
                    all_results = self.vectorstore.similarity_search_with_score(
                        query, k=4, filter={"protocol": "all"}
                    )
                    all_docs_with_scores.extend(all_results)

                # Stage 3: multisig_v1 fallback
                if len(all_docs_with_scores) < 3:
                    multisig_results = self.vectorstore.similarity_search_with_score(
                        query, k=2, filter={"protocol": "multisig_v1"}
                    )
                    all_docs_with_scores.extend(multisig_results)

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

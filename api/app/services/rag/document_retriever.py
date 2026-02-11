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

from app.services.rag.interfaces import RetrievedDocument, RetrieverProtocol
from langchain_core.documents import Document

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
        self,
        retriever: RetrieverProtocol,
    ):
        """Initialize the document retriever.

        Args:
            retriever: Retriever backend (Qdrant-only in the current architecture)
        """
        self.retriever = retriever

    def _to_langchain_documents(self, docs: List[RetrievedDocument]) -> List[Document]:
        # Preserve backend IDs (e.g. Qdrant point ID) in metadata so dedupe can be
        # chunk-level rather than page-level. Avoid "id" because FAQ docs already
        # use it for the FAQ identifier.
        out: list[Document] = []
        for d in docs:
            lc = d.to_langchain_document()
            if d.id and "_retrieved_id" not in lc.metadata:
                lc.metadata["_retrieved_id"] = d.id
            out.append(lc)
        return out

    def _dedupe_langchain_docs(self, docs: List[Document]) -> List[Document]:
        # De-duplicate while preserving order.
        # Prefer a stable per-chunk identifier when available. This avoids collapsing
        # all chunks from the same page (title/section) down to a single chunk.
        seen: set[tuple[str, str]] = set()
        unique_docs: list[Document] = []
        for d in docs:
            retrieved_id = d.metadata.get("_retrieved_id")
            if retrieved_id:
                key = ("_retrieved_id", str(retrieved_id))
            else:
                key = (
                    d.metadata.get("title", "Unknown"),
                    d.metadata.get("section", ""),
                )
            if key not in seen:
                seen.add(key)
                unique_docs.append(d)
        return unique_docs

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
        all_docs: List[Document] = []

        # Use explicit detected_version if provided, otherwise detect from query text.
        #
        # Important: even when an upstream component provides detected_version, the *query*
        # may still explicitly request a comparison ("Bisq 1 vs Bisq 2"). In that case we
        # must retrieve both protocols; otherwise we'd bias to the detected version and the
        # prompt won't have enough context to produce a comparison answer.
        if detected_version:
            logger.info(
                f"Using explicitly detected version: {detected_version} (ignoring query text patterns)"
            )
            query_lower = query.lower()
            query_mentions_bisq1 = bool(
                re.search(r"\bbisq\s*1\b|\bbisq1\b", query_lower)
            )
            query_mentions_bisq2 = bool(
                re.search(r"\bbisq\s*2\b|\bbisq2\b", query_lower)
            )
            comparison_tokens = re.compile(
                r"\b(compare|comparison|different|difference|diff|versus|vs|both\s+versions)\b"
            )
            query_is_comparison = (
                query_mentions_bisq1 and query_mentions_bisq2
            ) or bool(comparison_tokens.search(query_lower))

            # Comparison intent in the question overrides version-based routing.
            if query_is_comparison:
                is_multisig_query = True
                mentions_bisq_easy = True
                is_comparison_query = True
            else:
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
                multisig_docs = self.retriever.retrieve(
                    query, k=4, filter_dict={"protocol": "multisig_v1"}
                )
                multisig_lc = self._to_langchain_documents(multisig_docs)
                logger.info(f"Found {len(multisig_lc)} multisig_v1 documents")
                all_docs.extend(multisig_lc)

                # Stage 2: Add 'all' content as supplementary
                if len(all_docs) < 3:
                    logger.info("Stage 2: Searching for 'all' protocol content...")
                    all_protocol_docs = self.retriever.retrieve(
                        query, k=2, filter_dict={"protocol": "all"}
                    )
                    all_protocol_lc = self._to_langchain_documents(all_protocol_docs)
                    logger.info(f"Found {len(all_protocol_lc)} 'all' documents")
                    all_docs.extend(all_protocol_lc)

                # Stage 3: Skip bisq_easy content for pure multisig queries
                logger.info("Skipping bisq_easy content for explicit Bisq 1 query")

            else:
                # Default Bisq Easy priority OR comparison query.
                #
                # For comparison queries, always retrieve from both protocols so the prompt can
                # label differences explicitly, even if one side would have been "good enough".
                if is_comparison_query:
                    logger.info("Detected comparison query - retrieving both protocols")

                    logger.info(
                        "Stage 1: Searching for bisq_easy content (comparison)..."
                    )
                    bisq_easy_docs = self.retriever.retrieve(
                        query, k=5, filter_dict={"protocol": "bisq_easy"}
                    )
                    bisq_easy_lc = self._to_langchain_documents(bisq_easy_docs)
                    logger.info(f"Found {len(bisq_easy_lc)} bisq_easy documents")
                    all_docs.extend(bisq_easy_lc)

                    logger.info(
                        "Stage 2: Searching for multisig_v1 content (comparison)..."
                    )
                    multisig_docs = self.retriever.retrieve(
                        query, k=5, filter_dict={"protocol": "multisig_v1"}
                    )
                    multisig_lc = self._to_langchain_documents(multisig_docs)
                    logger.info(f"Found {len(multisig_lc)} multisig_v1 documents")
                    all_docs.extend(multisig_lc)

                    logger.info(
                        "Stage 3: Searching for 'all' protocol content (comparison)..."
                    )
                    all_protocol_docs = self.retriever.retrieve(
                        query, k=4, filter_dict={"protocol": "all"}
                    )
                    all_protocol_lc = self._to_langchain_documents(all_protocol_docs)
                    logger.info(f"Found {len(all_protocol_lc)} 'all' documents")
                    all_docs.extend(all_protocol_lc)
                else:
                    # Stage 1: Prioritize bisq_easy content
                    logger.info("Stage 1: Searching for bisq_easy content...")
                    bisq_easy_docs = self.retriever.retrieve(
                        query, k=6, filter_dict={"protocol": "bisq_easy"}
                    )
                    bisq_easy_lc = self._to_langchain_documents(bisq_easy_docs)
                    logger.info(f"Found {len(bisq_easy_lc)} bisq_easy documents")
                    all_docs.extend(bisq_easy_lc)

                    # Stage 2: Add 'all' content if we don't have enough bisq_easy content
                    # Threshold of 4 ensures we have sufficient bisq_easy context before adding general docs
                    if len(all_docs) < 4:
                        logger.info("Stage 2: Searching for 'all' protocol content...")
                        all_protocol_docs = self.retriever.retrieve(
                            query, k=4, filter_dict={"protocol": "all"}
                        )
                        all_protocol_lc = self._to_langchain_documents(
                            all_protocol_docs
                        )
                        logger.info(f"Found {len(all_protocol_lc)} 'all' documents")
                        all_docs.extend(all_protocol_lc)

                    # Stage 3: Only add multisig_v1 content if we still don't have enough
                    # Threshold of 3 ensures multisig_v1 content is truly a last resort
                    if len(all_docs) < 3:
                        logger.info(
                            "Stage 3: Searching for multisig_v1 content (fallback)..."
                        )
                        multisig_docs = self.retriever.retrieve(
                            query, k=2, filter_dict={"protocol": "multisig_v1"}
                        )
                        multisig_lc = self._to_langchain_documents(multisig_docs)
                        logger.info(f"Found {len(multisig_lc)} multisig_v1 documents")
                        all_docs.extend(multisig_lc)
        except Exception as e:
            logger.error(f"Error in protocol-priority retrieval: {e!s}", exc_info=True)
            logger.warning("Retrieval failed, falling back to unfiltered retrieval")
            fallback = self.retriever.retrieve(query, k=8, filter_dict=None)
            fallback_docs = self._to_langchain_documents(fallback)

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
            unique_docs = self._dedupe_langchain_docs(all_docs)

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
        all_docs_with_scores: List[Tuple[Document, float]] = []

        def _lc_with_retrieved_id(r: RetrievedDocument) -> Document:
            lc = r.to_langchain_document()
            if r.id and "_retrieved_id" not in lc.metadata:
                lc.metadata["_retrieved_id"] = r.id
            return lc

        # Detect version from query and incorporate detected_version unless the query itself
        # signals a comparison. Bisq 1 is actively used and heavily represented in the wiki,
        # so we must not over-bias to Bisq Easy for comparison/ambiguous queries.
        query_lower = query.lower()
        is_multisig_query = bool(re.search(r"\bbisq\s*1\b|\bbisq1\b", query_lower))
        mentions_bisq_easy = bool(re.search(r"\bbisq\s*2\b|\bbisq2\b", query_lower))
        comparison_tokens = re.compile(
            r"\b(compare|comparison|different|difference|diff|versus|vs|both\s+versions)\b"
        )
        is_comparison_query = (is_multisig_query and mentions_bisq_easy) or bool(
            comparison_tokens.search(query_lower)
        )

        if not is_comparison_query:
            # Override with detected version if not explicit in query.
            if (
                not is_multisig_query
                and not mentions_bisq_easy
                and detected_version in ("Bisq 1", "multisig_v1")
            ):
                is_multisig_query = True
                logger.info("Using detected version context: Bisq 1 (multisig_v1)")
            elif (
                not is_multisig_query
                and not mentions_bisq_easy
                and detected_version in ("Bisq 2", "bisq_easy")
            ):
                mentions_bisq_easy = True
                logger.info("Using detected version context: Bisq 2 (bisq_easy)")

        try:
            if is_comparison_query:
                logger.info(
                    "Retrieving with scores for comparison query (bisq_easy + multisig_v1 + all)"
                )

                bisq_easy_results = self.retriever.retrieve_with_scores(
                    query, k=5, filter_dict={"protocol": "bisq_easy"}
                )
                for r in bisq_easy_results:
                    all_docs_with_scores.append(
                        (_lc_with_retrieved_id(r), float(r.score))
                    )

                multisig_results = self.retriever.retrieve_with_scores(
                    query, k=5, filter_dict={"protocol": "multisig_v1"}
                )
                for r in multisig_results:
                    all_docs_with_scores.append(
                        (_lc_with_retrieved_id(r), float(r.score))
                    )

                all_results = self.retriever.retrieve_with_scores(
                    query, k=4, filter_dict={"protocol": "all"}
                )
                for r in all_results:
                    all_docs_with_scores.append(
                        (_lc_with_retrieved_id(r), float(r.score))
                    )

            elif is_multisig_query:
                logger.info("Retrieving with scores for Bisq 1 / multisig_v1 query")

                # Stage 1: multisig_v1 content
                multisig_results = self.retriever.retrieve_with_scores(
                    query, k=4, filter_dict={"protocol": "multisig_v1"}
                )
                for r in multisig_results:
                    all_docs_with_scores.append(
                        (_lc_with_retrieved_id(r), float(r.score))
                    )

                # Stage 2: 'all' content (always). Many Bisq 1 wiki pages are categorized
                # as 'general' in our processed dump, so we must include them for Bisq 1 queries.
                all_results = self.retriever.retrieve_with_scores(
                    query, k=6, filter_dict={"protocol": "all"}
                )
                for r in all_results:
                    all_docs_with_scores.append(
                        (_lc_with_retrieved_id(r), float(r.score))
                    )
            else:
                logger.info("Retrieving with scores for Bisq Easy query")

                # Stage 1: bisq_easy content
                bisq_easy_results = self.retriever.retrieve_with_scores(
                    query, k=6, filter_dict={"protocol": "bisq_easy"}
                )
                for r in bisq_easy_results:
                    all_docs_with_scores.append(
                        (_lc_with_retrieved_id(r), float(r.score))
                    )

                # Stage 2: 'all' content
                if len(all_docs_with_scores) < 4:
                    all_results = self.retriever.retrieve_with_scores(
                        query, k=4, filter_dict={"protocol": "all"}
                    )
                    for r in all_results:
                        all_docs_with_scores.append(
                            (_lc_with_retrieved_id(r), float(r.score))
                        )

                # Stage 3: multisig_v1 fallback
                if len(all_docs_with_scores) < 3:
                    multisig_results = self.retriever.retrieve_with_scores(
                        query, k=2, filter_dict={"protocol": "multisig_v1"}
                    )
                    for r in multisig_results:
                        all_docs_with_scores.append(
                            (_lc_with_retrieved_id(r), float(r.score))
                        )

        except Exception as e:
            logger.error(f"Error in score-based retrieval: {e!s}", exc_info=True)
            # Fallback to standard retrieval without scores
            docs = self.retrieve_with_version_priority(query)
            # Return neutral scores for fallback
            return docs, [0.5] * len(docs)

        # De-duplicate while preserving scores.
        # Prefer chunk-level identifiers to avoid collapsing multiple chunks per page.
        seen: set[tuple[str, str]] = set()
        unique_docs: List[Document] = []
        unique_scores: List[float] = []

        for doc, score in all_docs_with_scores:
            retrieved_id = doc.metadata.get("_retrieved_id")
            if retrieved_id:
                key = ("_retrieved_id", str(retrieved_id))
            else:
                key = (
                    doc.metadata.get("title", "Unknown"),
                    doc.metadata.get("section", ""),
                )
            if key not in seen:
                seen.add(key)
                unique_docs.append(doc)
                # Qdrant returns similarity-like scores (higher is better). Keep a safe clamp.
                similarity = max(0.0, min(1.0, float(score)))
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

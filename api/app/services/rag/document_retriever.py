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
from typing import Any, Dict, List, Set, Tuple

from app.services.rag.bisq_entities import BISQ1_STRONG_KEYWORDS, BISQ2_STRONG_KEYWORDS
from app.services.rag.interfaces import (
    RerankerProtocol,
    RetrievedDocument,
    RetrieverProtocol,
)
from langchain_core.documents import Document

logger = logging.getLogger(__name__)


# Type alias for document with similarity score
DocumentWithScore = Tuple[Document, float]
_BISQ1_VERSION_RE = re.compile(r"\bbisq\s*1\b|\bbisq1\b")
_BISQ2_VERSION_RE = re.compile(r"\bbisq\s*2\b|\bbisq2\b")
_COMPARISON_TOKEN_RE = re.compile(
    r"\b(compare|comparison|different|difference|diff|versus|vs|both\s+versions)\b"
)
# Explicit version/protocol tokens required for a comparison token to count
# as a Bisq 1 vs Bisq 2 comparison (instead of e.g. comparing payment methods
# or generic app/wallet versions). A bare "version(s)" token is intentionally
# NOT enough - only Bisq-specific or Bisq-adjacent version phrases qualify.
_VERSION_CONTEXT_TOKEN_RE = re.compile(
    r"\bbisq\s*1\b|\bbisq1\b|\bbisq\s*2\b|\bbisq2\b|\bbisq\s+easy\b|\bmultisig\b"
    r"|\bboth\s+versions\b|\bversions?\s+of\s+bisq\b"
    r"|\b(?:the\s+)?(?:two\s+)?bisq\s+versions?\b"
)


def is_bisq_version_comparison_query(query: str) -> bool:
    """Return True when the query asks to compare Bisq 1 and Bisq 2.

    A comparison requires either explicit mentions of BOTH versions, or a
    comparison token combined with an explicit version/protocol token.
    A comparison token alone (e.g. "difference between SEPA and SEPA Instant
    in Bisq") must not trigger version-comparison handling.

    Shared by DocumentRetriever routing and SimplifiedRAGService so both
    classify comparison intent consistently.
    """
    query_lower = query.lower()
    mentions_bisq1 = bool(_BISQ1_VERSION_RE.search(query_lower))
    mentions_bisq2 = bool(_BISQ2_VERSION_RE.search(query_lower))
    if mentions_bisq1 and mentions_bisq2:
        return True
    return bool(
        _COMPARISON_TOKEN_RE.search(query_lower)
        and _VERSION_CONTEXT_TOKEN_RE.search(query_lower)
    )


def _keyword_score(query_lower: str, keywords: List[str]) -> int:
    return sum(1 for keyword in keywords if keyword in query_lower)


def _classify_query_protocol(
    query: str, detected_version: str | None = None
) -> tuple[bool, bool, bool]:
    """Classify retrieval protocol intent without duplicating routing heuristics.

    Returns:
        (is_multisig_query, mentions_bisq_easy, is_comparison_query)

    ``detected_version`` may come from heuristic conversation state. Unknown
    values intentionally fall through to the product default instead of raising
    into the user-facing retrieval path.
    """
    query_lower = query.lower()
    query_mentions_bisq1 = bool(_BISQ1_VERSION_RE.search(query_lower))
    query_mentions_bisq2 = bool(_BISQ2_VERSION_RE.search(query_lower))
    is_comparison_query = is_bisq_version_comparison_query(query)

    if is_comparison_query:
        return True, True, True

    if query_mentions_bisq1:
        return True, False, False
    if query_mentions_bisq2:
        return False, True, False

    bisq1_score = _keyword_score(query_lower, BISQ1_STRONG_KEYWORDS)
    bisq2_score = _keyword_score(query_lower, BISQ2_STRONG_KEYWORDS)
    if bisq1_score > bisq2_score and bisq1_score > 0:
        return True, False, False
    if bisq2_score > bisq1_score and bisq2_score > 0:
        return False, True, False

    if detected_version:
        normalized_version = detected_version.strip()
        if normalized_version in ("Bisq 1", "multisig_v1"):
            return True, False, False
        if normalized_version in ("Bisq 2", "bisq_easy"):
            return False, True, False

    # Default product bias remains Bisq Easy for truly ambiguous questions.
    return False, True, False


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
        reranker: RerankerProtocol | None = None,
        rerank_top_n: int | None = None,
    ):
        """Initialize the document retriever.

        Args:
            retriever: Retriever backend (Qdrant-only in the current architecture)
            reranker: Optional reranker applied after protocol-aware retrieval
            rerank_top_n: Optional number of docs to keep after reranking
        """
        self.retriever = retriever
        self.reranker = reranker
        self.rerank_top_n = rerank_top_n

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

    @staticmethod
    def _dedupe_key_from_metadata(metadata: dict[str, Any]) -> tuple[str, str]:
        retrieved_id = metadata.get("_retrieved_id")
        if retrieved_id:
            return ("_retrieved_id", str(retrieved_id))
        return (
            str(metadata.get("title", "Unknown")),
            str(metadata.get("section", "")),
        )

    @classmethod
    def _dedupe_key_from_retrieved(cls, document: RetrievedDocument) -> tuple[str, str]:
        if document.id:
            return ("_retrieved_id", str(document.id))
        return cls._dedupe_key_from_metadata(document.metadata)

    @staticmethod
    def _clamp_unit_interval(score: float) -> float:
        return max(0.0, min(1.0, float(score)))

    @staticmethod
    def _numeric_metadata(value: Any) -> float | None:
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _protocol_priority_for_version(
        detected_version: str | None = None,
    ) -> dict[str, int]:
        normalized = str(detected_version or "").strip()
        if normalized in ("Bisq 1", "multisig_v1"):
            return {"multisig_v1": 2, "all": 1, "bisq_easy": 0}
        return {"bisq_easy": 2, "all": 1, "multisig_v1": 0}

    @staticmethod
    def _tag_retrieval_ranks(docs: List[Document]) -> List[Document]:
        for rank, doc in enumerate(docs):
            metadata = dict(doc.metadata or {})
            metadata.setdefault("_retrieval_rank", rank)
            doc.metadata = metadata
        return docs

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
            logger.info("Using explicitly detected version: %s", detected_version)
        else:
            logger.info("No explicit version provided, detecting from query text...")
        is_multisig_query, _mentions_bisq_easy, is_comparison_query = (
            _classify_query_protocol(query, detected_version)
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
            return self._tag_retrieval_ranks(sorted_docs)
        else:
            unique_docs = self._dedupe_langchain_docs(all_docs)

            logger.info(
                f"Total documents retrieved: {len(unique_docs)} (deduped from {len(all_docs)})"
            )
            return self._tag_retrieval_ranks(unique_docs)

    def format_documents(
        self, docs: List[Document], detected_version: str | None = None
    ) -> str:
        """Format retrieved documents with protocol-aware processing.

        Args:
            docs: List of retrieved documents
            detected_version: Optional Bisq version used to break ties when
                              documents do not already carry retrieval ranks

        Returns:
            Formatted string with protocol context and source attribution
        """
        if not docs:
            return ""

        protocol_priority = self._protocol_priority_for_version(detected_version)

        def sort_key(doc: Document) -> tuple[float, float, float, float]:
            # When retrieval already provided a rank, preserve it. Re-sorting
            # high-weight Bisq Easy docs ahead of Bisq 1 hits is what caused
            # Bisq 1 context to be truncated out of the prompt window.
            retrieval_rank = self._numeric_metadata(doc.metadata.get("_retrieval_rank"))
            if retrieval_rank is not None:
                return (0.0, retrieval_rank, 0.0, 0.0)

            retrieval_score = self._numeric_metadata(
                doc.metadata.get("_retrieval_score")
            )
            protocol = str(doc.metadata.get("protocol", "all"))
            source_weight = self._numeric_metadata(
                doc.metadata.get("source_weight", 1.0)
            )
            if source_weight is None:
                source_weight = 1.0

            if retrieval_score is not None:
                return (
                    1.0,
                    -retrieval_score,
                    -float(protocol_priority.get(protocol, 1)),
                    -source_weight,
                )

            return (
                2.0,
                -float(protocol_priority.get(protocol, 1)),
                -source_weight,
                0.0,
            )

        sorted_docs = sorted(docs, key=sort_key)

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

        def _absolute_scores(
            k: int, filter_dict: dict[str, Any] | None = None
        ) -> dict[tuple[str, str], float]:
            semantic_retrieve = getattr(
                self.retriever, "retrieve_semantic_with_scores", None
            )
            if not callable(semantic_retrieve):
                return {}

            try:
                results = semantic_retrieve(query, k=k, filter_dict=filter_dict)
            except Exception:
                logger.debug(
                    "Absolute semantic score lookup failed; falling back to rank scores",
                    exc_info=True,
                )
                return {}
            if not isinstance(results, list):
                return {}

            return {
                self._dedupe_key_from_retrieved(result): self._clamp_unit_interval(
                    result.score
                )
                for result in results
            }

        def _lc_with_retrieval_metadata(
            r: RetrievedDocument,
            *,
            retrieval_score: float,
            absolute_score: float | None,
            retrieval_rank: int,
        ) -> Document:
            lc = r.to_langchain_document()
            metadata = dict(lc.metadata or {})
            if r.id and "_retrieved_id" not in metadata:
                metadata["_retrieved_id"] = r.id
            metadata["_retrieval_score"] = self._clamp_unit_interval(retrieval_score)
            metadata["_relative_rank_score"] = self._clamp_unit_interval(
                retrieval_score
            )
            metadata["_retrieval_rank"] = retrieval_rank
            if absolute_score is not None:
                metadata["_absolute_similarity_score"] = self._clamp_unit_interval(
                    absolute_score
                )
                metadata["_score_type"] = "absolute_cosine"
            else:
                metadata["_score_type"] = "relative_rank"
            lc.metadata = metadata
            return lc

        def _score_for_display(doc: Document, fallback_score: float) -> float:
            absolute_score = self._numeric_metadata(
                doc.metadata.get("_absolute_similarity_score")
            )
            if absolute_score is not None:
                return self._clamp_unit_interval(absolute_score)
            return self._clamp_unit_interval(fallback_score)

        def _append_stage(k: int, filter_dict: dict[str, Any] | None) -> None:
            results = self.retriever.retrieve_with_scores(
                query, k=k, filter_dict=filter_dict
            )
            for r in results:
                retrieval_score = self._clamp_unit_interval(float(r.score))
                all_docs_with_scores.append(
                    (
                        _lc_with_retrieval_metadata(
                            r,
                            retrieval_score=retrieval_score,
                            absolute_score=None,
                            retrieval_rank=len(all_docs_with_scores),
                        ),
                        retrieval_score,
                    )
                )

        # Detect version from query and incorporate detected_version unless the query itself
        # signals a comparison. Bisq 1 is actively used and heavily represented in the wiki,
        # so we must not over-bias to Bisq Easy for comparison/ambiguous queries.
        is_multisig_query, _mentions_bisq_easy, is_comparison_query = (
            _classify_query_protocol(query, detected_version)
        )

        try:
            if is_comparison_query:
                logger.info(
                    "Retrieving with scores for comparison query (bisq_easy + multisig_v1 + all)"
                )

                _append_stage(k=5, filter_dict={"protocol": "bisq_easy"})
                _append_stage(k=5, filter_dict={"protocol": "multisig_v1"})
                _append_stage(k=4, filter_dict={"protocol": "all"})

            elif is_multisig_query:
                logger.info("Retrieving with scores for Bisq 1 / multisig_v1 query")

                # Stage 1: multisig_v1 content
                _append_stage(k=4, filter_dict={"protocol": "multisig_v1"})

                # Stage 2: 'all' content (always). Many Bisq 1 wiki pages are categorized
                # as 'general' in our processed dump, so we must include them for Bisq 1 queries.
                _append_stage(k=6, filter_dict={"protocol": "all"})
            else:
                logger.info("Retrieving with scores for Bisq Easy query")

                # Stage 1: bisq_easy content
                _append_stage(k=6, filter_dict={"protocol": "bisq_easy"})

                # Stage 2: 'all' content
                if len(all_docs_with_scores) < 4:
                    _append_stage(k=4, filter_dict={"protocol": "all"})

                # Stage 3: multisig_v1 fallback
                if len(all_docs_with_scores) < 3:
                    _append_stage(k=2, filter_dict={"protocol": "multisig_v1"})

        except Exception as e:
            logger.error(f"Error in score-based retrieval: {e!s}", exc_info=True)
            # Fallback to standard retrieval without scores
            docs = self.retrieve_with_version_priority(query, detected_version)
            # Return neutral scores for fallback
            return docs, [0.5] * len(docs)

        # De-duplicate while preserving scores.
        # Prefer chunk-level identifiers to avoid collapsing multiple chunks per page.
        seen: set[tuple[str, str]] = set()
        unique_docs: List[Document] = []
        retrieval_scores: List[float] = []

        for doc, score in all_docs_with_scores:
            key = self._dedupe_key_from_metadata(doc.metadata)
            if key not in seen:
                seen.add(key)
                unique_docs.append(doc)
                retrieval_scores.append(self._clamp_unit_interval(float(score)))

        if unique_docs:
            absolute_lookup = _absolute_scores(k=max(len(unique_docs), 10))
            for doc in unique_docs:
                absolute_score = absolute_lookup.get(
                    self._dedupe_key_from_metadata(doc.metadata)
                )
                if absolute_score is None:
                    continue
                metadata = dict(doc.metadata or {})
                metadata["_absolute_similarity_score"] = self._clamp_unit_interval(
                    absolute_score
                )
                metadata["_score_type"] = "absolute_cosine"
                doc.metadata = metadata

        if self.reranker and unique_docs:
            try:
                rerank_top_n = (
                    self.rerank_top_n
                    if self.rerank_top_n is not None
                    else len(unique_docs)
                )
                rerank_candidates = [
                    RetrievedDocument.from_langchain_document(doc, score=score)
                    for doc, score in zip(unique_docs, retrieval_scores, strict=True)
                ]
                reranked = self.reranker.rerank(
                    query, rerank_candidates, top_n=rerank_top_n
                )
                reranked_docs: List[Document] = []
                retrieval_score_lookup = {
                    self._dedupe_key_from_retrieved(candidate): candidate.score
                    for candidate in rerank_candidates
                }
                for reranked_doc in reranked:
                    lc_doc = reranked_doc.to_langchain_document()
                    metadata = dict(lc_doc.metadata or {})
                    if reranked_doc.id and "_retrieved_id" not in metadata:
                        metadata["_retrieved_id"] = reranked_doc.id
                    metadata["_reranked"] = True
                    metadata["_colbert_score"] = float(reranked_doc.score)
                    metadata["_retrieval_rank"] = len(reranked_docs)
                    lc_doc.metadata = metadata
                    reranked_docs.append(lc_doc)

                unique_docs = reranked_docs
                retrieval_scores = []
                for doc in unique_docs:
                    fallback_score = self._numeric_metadata(
                        doc.metadata.get("_retrieval_score")
                    )
                    if fallback_score is None:
                        fallback_score = 0.5
                    retrieval_scores.append(
                        self._clamp_unit_interval(
                            retrieval_score_lookup.get(
                                self._dedupe_key_from_metadata(doc.metadata),
                                fallback_score,
                            )
                        )
                    )
            except Exception:
                logger.warning(
                    "Reranking failed; returning protocol-ranked retrieval results",
                    exc_info=True,
                )

        unique_scores = [
            _score_for_display(doc, score)
            for doc, score in zip(unique_docs, retrieval_scores, strict=True)
        ]

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

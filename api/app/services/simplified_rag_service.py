"""
Simplified RAG-based Bisq 2 support assistant using LangChain.
This implementation combines wiki documentation from XML dump and FAQ data
for accurate and context-aware responses, with easy switching between OpenAI and xAI.

File Naming Conventions:
- Feedback files: feedback_YYYY-MM.jsonl (e.g., feedback_2025-03.jsonl)
  Stored in the DATA_DIR/feedback directory
- Legacy formats supported for reading (but not writing):
  - feedback_YYYYMMDD.jsonl (day-based naming)
  - feedback.jsonl (in root DATA_DIR)
  - negative_feedback.jsonl (special purpose file)
"""

import asyncio
import logging
import math
import re
import time
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from typing import Any, AsyncIterator, Callable, Dict, List, Optional

from app.channels.traits import get_channel_traits
from app.core.config import get_settings
from app.core.pii_utils import redact_for_logs
from app.prompts import error_messages
from app.prompts.runtime_policy import SAFETY_REFLEX_WARNING, should_apply_safety_reflex
from app.services.bisq_mcp_service import Bisq2MCPService
from app.services.faq.slug_manager import SlugManager
from app.services.rag.auto_send_router import AutoSendRouter
from app.services.rag.canonical_fixes import (
    canonical_url_for_metadata,
    find_canonical_fix,
)
from app.services.rag.confidence_scorer import ConfidenceScorer
from app.services.rag.document_processor import DocumentProcessor
from app.services.rag.document_retriever import (
    DocumentRetriever,
    is_bisq_version_comparison_query,
)
from app.services.rag.faq_index_sync import FAQIndexSyncManager
from app.services.rag.index_state_manager import IndexStateManager
from app.services.rag.language_pipeline import QueryLanguageHandler
from app.services.rag.llm_provider import LLMProvider, needs_live_data
from app.services.rag.llm_wiki_loader import LLMWikiLoader
from app.services.rag.mcp_reconciliation import (
    extract_last_tool_result,
    live_data_tool_calls_failed,
    reconcile_live_data_fallbacks,
    strip_bracket_wrapper,
)
from app.services.rag.nli_validator import NLIValidator
from app.services.rag.prompt_manager import PromptManager
from app.services.rag.protocol_detector import ProtocolDetector
from app.services.rag.qdrant_index_manager import QdrantIndexManager
from app.services.rag.routing_reason_generator import RoutingReasonGenerator
from app.services.translation import TranslationService
from app.utils.instrumentation import (
    RAG_REQUEST_RATE,
    instrument_stage,
    track_tokens_and_cost,
    update_error_rate,
)
from app.utils.wiki_url_generator import generate_wiki_url
from fastapi import Request

# Core LangChain imports
from langchain_core.documents import Document

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

_GROUP_CHANNEL_MAX_ANSWER_LENGTH = 500
_CONTEXT_LLM_FALLBACK_WORKERS = 4
_READINESS_CACHE_TTL_SECONDS = 5.0
_STATIC_SAFETY_WARNING_PATTERN = re.compile(
    r"\s+".join(re.escape(part) for part in SAFETY_REFLEX_WARNING.split())
)
_DEFINITION_QUESTION_PATTERNS = (
    r"^\s*what\s+is\b",
    r"^\s*what'?s\b",
    r"^\s*who\s+is\b",
)


def _normalize_support_answer_text(answer_text: str) -> str:
    text = (answer_text or "").strip()
    if not text:
        return ""

    text = re.sub(r"(?m)^\s{0,3}#{1,6}\s*", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text


def _is_definition_question(question_text: Optional[str]) -> bool:
    question = str(question_text or "").strip().lower()
    if not question:
        return False
    return any(
        re.search(pattern, question) for pattern in _DEFINITION_QUESTION_PATTERNS
    )


def _compress_simple_fact_answer(answer_text: str) -> str:
    text = _normalize_support_answer_text(answer_text)
    if not text:
        return ""
    if "\n" in text or re.search(r"(?m)^\s*\d+\.\s", text):
        return text

    sentences = re.split(r"(?<=[.!?])\s+", text)
    sentences = [sentence.strip() for sentence in sentences if sentence.strip()]
    if len(sentences) <= 2 and len(text) <= 280:
        return text

    compact = " ".join(sentences[:2]).strip() if sentences else text
    if len(compact) > 280:
        compact = compact[:277].rstrip(" ,;:\n") + "..."
    return compact


def apply_support_answer_style(
    answer_text: str,
    *,
    question_text: Optional[str] = None,
    detection_source: Optional[str],
) -> str:
    """Normalize support answers for concise, readable delivery."""
    text = _normalize_support_answer_text(answer_text)
    if _is_definition_question(question_text):
        text = _compress_simple_fact_answer(text)

    traits = get_channel_traits(detection_source)
    if not traits.group_room:
        return text

    max_answer_length = traits.max_answer_length or _GROUP_CHANNEL_MAX_ANSWER_LENGTH
    if len(text) <= max_answer_length:
        return text

    limit = max_answer_length - 3
    clipped = text[:limit]
    preferred_break = max(
        clipped.rfind(". "),
        clipped.rfind("! "),
        clipped.rfind("? "),
        clipped.rfind("\n"),
    )
    if preferred_break > 220:
        clipped = clipped[:preferred_break]

    return clipped.rstrip(" ,;:\n") + "..."


def _without_static_safety_warning(answer_text: str) -> str:
    """Remove whitespace-equivalent copies before applying warning policy."""
    return _STATIC_SAFETY_WARNING_PATTERN.sub("", str(answer_text or "")).strip()


def _with_static_safety_warning(answer_text: str) -> str:
    """Lead with the unchanged human-curated warning exactly once."""
    body = _without_static_safety_warning(answer_text)
    if not body:
        return SAFETY_REFLEX_WARNING
    return f"{SAFETY_REFLEX_WARNING}\n\n{body}"


def _apply_static_safety_warning_policy(
    answer_text: str,
    *,
    required: bool,
) -> str:
    """Make the classifier authoritative over the exact static warning."""
    if required:
        return _with_static_safety_warning(answer_text)
    return _without_static_safety_warning(answer_text)


def apply_group_channel_answer_style(
    answer_text: str,
    detection_source: Optional[str],
) -> str:
    """Backward-compatible wrapper for existing group-room tests/callers."""
    return apply_support_answer_style(
        answer_text,
        question_text=None,
        detection_source=detection_source,
    )


class SimplifiedRAGService:
    """Simplified RAG-based support assistant for Bisq 2."""

    def __init__(
        self,
        settings=None,
        feedback_service=None,
        wiki_service=None,
        faq_service=None,
        bisq_mcp_service: Optional[Bisq2MCPService] = None,
        translation_service: Optional[TranslationService] = None,
    ):
        """Initialize the RAG service.

        Args:
            settings: Application settings
            feedback_service: Optional FeedbackService instance for feedback operations
            wiki_service: Optional WikiService instance for wiki operations
            faq_service: Optional FAQService instance for FAQ operations
            bisq_mcp_service: Optional Bisq2MCPService for live data integration
            translation_service: Optional TranslationService for multilingual support
        """
        if settings is None:
            settings = get_settings()
        self.settings = settings
        self.feedback_service = feedback_service
        self.wiki_service = wiki_service
        self.faq_service = faq_service
        self.llm_wiki_loader = LLMWikiLoader()
        self.bisq_mcp_service = bisq_mcp_service
        self.translation_service = translation_service
        self.language_handler = QueryLanguageHandler(translation_service)

        # MCP is now handled via HTTP transport in LLM provider
        # The LLM wrapper connects to MCP server at mcp_url
        self.mcp_enabled = (
            self.bisq_mcp_service is not None
            and self.settings.ENABLE_BISQ_MCP_INTEGRATION
        )
        if self.mcp_enabled:
            logger.info("MCP integration enabled (via HTTP transport)")

        # Qdrant index management (single source of truth for vector search)
        self.index_manager = QdrantIndexManager(settings=self.settings)
        self.state_manager = IndexStateManager()

        # Initialize document processor for text splitting
        self.document_processor = DocumentProcessor(
            chunk_size=2000,  # Increased from 1500 to preserve more context per chunk
            chunk_overlap=500,  # Maintains good overlap for context preservation
        )

        # Initialize LLM provider for embeddings and model initialization
        self.llm_provider = LLMProvider(settings=self.settings)

        # Initialize prompt manager for prompt templates and chat formatting
        self.prompt_manager = PromptManager(
            settings=self.settings, feedback_service=self.feedback_service
        )

        # Configure retriever
        self.retriever_config = {
            "k": 4,  # Number of documents to retrieve
        }

        # Initialize components
        self.embeddings = None
        self.retriever = None
        self.document_retriever = None  # Will be initialized after retriever
        self._retriever_lease_counts: dict[int, int] = {}
        self._retriever_idle_events: dict[int, asyncio.Event] = {}
        self._background_tasks: set[asyncio.Task[Any]] = set()
        self._readiness_probe_task: Optional[asyncio.Task[bool]] = None
        self._readiness_probe_retriever: Any = None
        self._readiness_cached_retriever: Any = None
        self._readiness_cached_result = False
        self._readiness_checked_at = 0.0
        self._context_llm_executor: Optional[ThreadPoolExecutor] = ThreadPoolExecutor(
            max_workers=_CONTEXT_LLM_FALLBACK_WORKERS,
            thread_name_prefix="context-llm-fallback",
        )
        self.llm = None
        self.rag_chain = None
        self.prompt = None

        # Optional reranking components
        self.colbert_reranker = None

        # Initialize lock for rebuild serialization to prevent concurrent rebuilds
        self._setup_lock = asyncio.Lock()
        self._embeddings_init_lock = asyncio.Lock()
        self._faq_index_locks: dict[str, asyncio.Lock] = {}
        self._faq_index_lock_refs: dict[str, int] = {}
        self._faq_index_locks_guard = asyncio.Lock()
        self.faq_index_sync = FAQIndexSyncManager(self)

        # Initialize confidence scoring components
        self.nli_validator = NLIValidator()
        self.confidence_scorer = ConfidenceScorer(self.nli_validator)
        self.auto_send_router = AutoSendRouter()
        self.routing_reason_generator = RoutingReasonGenerator()

        # Initialize query rewriter (feature-flagged)
        self.query_rewriter = None
        if self.settings.ENABLE_QUERY_REWRITE:
            from app.services.rag.query_rewriter import QueryRewriter

            self.query_rewriter = QueryRewriter(
                settings=self.settings,
                ai_client=self.llm_provider.ai_client,
            )

        # Initialize Phase 1 components
        self.version_detector = ProtocolDetector()

        # Initialize source weights
        # If feedback_service is provided, use its weights, otherwise use defaults
        if self.feedback_service:
            self.source_weights = self.feedback_service.get_source_weights()
        else:
            # Default source weights for different document types
            self.source_weights = {
                "faq": 1.2,  # Prioritize FAQ content
                "wiki": 1.1,  # Slightly increased weight for wiki content
                "llm_wiki": 1.25,  # Human-reviewed compiled support knowledge
            }
        self._apply_source_weights_to_loaders()

        # Register with FAQ service for FAQ updates (manual rebuild mode)
        if self.faq_service:
            self.faq_service.register_update_callback(self._handle_faq_update)
            logger.info("Registered FAQ service update callback (manual rebuild mode)")

        logger.info("Simplified RAG service initialized")

    def _apply_source_weights_to_loaders(self) -> None:
        """Apply current source weights to all document loaders."""
        if self.wiki_service:
            self.wiki_service.update_source_weights(self.source_weights)
        if self.faq_service:
            self.faq_service.update_source_weights(self.source_weights)
        self.llm_wiki_loader.update_source_weights(self.source_weights)

    def _refresh_source_weights(self) -> None:
        """Refresh learned weights from feedback."""
        if self.feedback_service:
            try:
                self.source_weights = self.feedback_service.get_source_weights()
            except Exception:
                logger.exception("Failed to refresh source weights from feedback")

    def _refresh_source_weights_for_rebuild(self) -> None:
        """Refresh learned weights and push them into document loaders."""
        self._refresh_source_weights()
        self._apply_source_weights_to_loaders()

    def _source_type_for_document(self, doc: Document) -> str:
        source_type = doc.metadata.get("type")
        if source_type:
            return str(source_type)
        source_value = str(doc.metadata.get("source", ""))
        if "faq" in source_value:
            return "faq"
        if "llm_wiki" in source_value:
            return "llm_wiki"
        return "wiki"

    def _apply_runtime_source_weights(
        self, docs: List[Document], doc_scores: List[float]
    ) -> tuple[List[Document], List[float]]:
        """Apply current learned source weights to retrieved documents.

        The vector index stores source weights in payload metadata from the
        last rebuild. Refreshing here lets feedback-driven weight changes
        affect prompt ordering, confidence scoring, and routing immediately.
        """
        if not docs:
            return docs, doc_scores

        self._refresh_source_weights()
        buckets: list[list[tuple[float, int, Document, float]]] = []
        current_protocol: str | None = None
        for index, doc in enumerate(docs):
            source_type = self._source_type_for_document(doc)
            source_weight = float(self.source_weights.get(source_type, 1.0))
            doc.metadata["source_weight"] = source_weight
            score = doc_scores[index] if index < len(doc_scores) else 0.0
            weighted_score = float(score) * source_weight
            doc.metadata["_source_weighted_score"] = weighted_score
            protocol = str(doc.metadata.get("protocol", "all"))
            if not buckets or protocol != current_protocol:
                buckets.append([])
                current_protocol = protocol
            buckets[-1].append((weighted_score, index, doc, score))

        reordered_docs: list[Document] = []
        reordered_scores: list[float] = []
        for bucket in buckets:
            for _, _, doc, score in sorted(
                bucket, key=lambda item: (-item[0], item[1])
            ):
                doc.metadata["_retrieval_rank"] = len(reordered_docs)
                reordered_docs.append(doc)
                reordered_scores.append(score)
        return reordered_docs, reordered_scores

    @staticmethod
    def _inject_canonical_fix(
        docs: List[Document],
        doc_scores: List[float],
        question: str,
        detected_version: Optional[str],
    ) -> tuple[List[Document], List[float]]:
        """Prepend at most one locally verified canonical fix document."""
        fix = find_canonical_fix(question, detected_version)
        if fix is None:
            return docs, doc_scores

        paired = [
            (doc, doc_scores[index] if index < len(doc_scores) else 0.0)
            for index, doc in enumerate(docs)
        ]
        for index, (doc, score) in enumerate(paired):
            if (
                doc.metadata.get("canonical_fix_id") == fix.key
                and doc.metadata.get("url") == fix.url
            ):
                paired.insert(0, paired.pop(index))
                for rank, (ranked_doc, _) in enumerate(paired):
                    ranked_doc.metadata["_retrieval_rank"] = rank
                return [item[0] for item in paired], [item[1] for item in paired]

        injected_fix = fix.to_document()
        injected_fix.metadata["_canonical_fix_injected"] = True
        paired.insert(0, (injected_fix, 0.0))
        for rank, (ranked_doc, _) in enumerate(paired):
            ranked_doc.metadata["_retrieval_rank"] = rank
        return [item[0] for item in paired], [item[1] for item in paired]

    def _handle_faq_update(
        self,
        rebuild: bool,
        operation: str,
        faq_id: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Handle FAQ updates with incremental indexing or full rebuild."""
        self.faq_index_sync.handle_update(rebuild, operation, faq_id, metadata)

    async def _ensure_embeddings_initialized(self) -> None:
        """Initialize embeddings once across concurrent incremental workers."""
        await self.faq_index_sync.ensure_embeddings_initialized()

    async def _acquire_faq_index_lock(self, faq_id: str) -> asyncio.Lock:
        return await self.faq_index_sync.acquire_lock(faq_id)

    async def _release_faq_index_lock(self, faq_id: str, lock: asyncio.Lock) -> None:
        await self.faq_index_sync.release_lock(faq_id, lock)

    def _can_apply_incremental_faq_update(self, operation: str, faq_id: str) -> bool:
        """Return True when a change can be applied point-by-point."""
        return self.faq_index_sync.can_apply_incremental_update(operation, faq_id)

    def _mark_faq_change(
        self,
        operation: str,
        faq_id: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Record a FAQ change that requires a manual index rebuild."""
        self.faq_index_sync.mark_change(operation, faq_id, metadata)

    async def _apply_incremental_faq_update(
        self,
        operation: str,
        faq_id: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Apply a single FAQ change to the live Qdrant index off-loop."""
        await self.faq_index_sync.apply_incremental_update(operation, faq_id, metadata)

    def _sync_faq_in_index(self, faq_id: str) -> None:
        """Blocking worker: reconcile one FAQ's points in the Qdrant index."""
        self.faq_index_sync.sync_faq_in_index(faq_id)

    async def _handle_source_update(self, source_name: str) -> None:
        """Handle runtime updates to source files (FAQ or wiki).

        This callback is triggered when source files are updated at runtime
        (e.g., new FAQs extracted, wiki updated). It rebuilds the vector store
        to ensure new content is searchable.

        Args:
            source_name: Name of the source that was updated ("faq" or "wiki")
        """
        logger.info(
            f"Source '{source_name}' updated at runtime, triggering vector store rebuild..."
        )
        try:
            # Trigger a rebuild by calling setup again
            # This will detect changes and rebuild the vector store
            await self.setup()
            logger.info(f"Vector store successfully rebuilt after {source_name} update")
        except Exception as e:
            logger.error(
                f"Failed to rebuild vector store after {source_name} update: {e}",
                exc_info=True,
            )

    def initialize_embeddings(self) -> None:
        """Delegate to LLM provider for embeddings initialization."""
        self.embeddings = self.llm_provider.initialize_embeddings()

    def initialize_llm(self) -> None:
        """Delegate to LLM provider for model initialization.

        If MCP integration is enabled, passes the MCP HTTP URL to the LLM wrapper
        for native AISuite MCP support.
        """
        # Use configured MCP HTTP URL for AISuite MCP integration
        self.llm = self.llm_provider.initialize_llm(mcp_url=self.settings.MCP_HTTP_URL)

    def _create_qdrant_retriever(self, embeddings: Any) -> Any:
        """Build and validate a Qdrant retriever without changing live state."""
        from app.services.rag.qdrant_hybrid_retriever import QdrantHybridRetriever

        retriever = QdrantHybridRetriever(
            settings=self.settings,
            embeddings=embeddings,
        )

        if not retriever.health_check():
            self._close_retriever(retriever)
            raise RuntimeError("Qdrant retriever health check failed")

        return retriever

    @staticmethod
    def _close_retriever(retriever: Any) -> None:
        """Best-effort release of a retriever that is no longer live."""
        if retriever is None:
            return
        close = getattr(retriever, "close", None)
        if not callable(close):
            return
        try:
            close()
        except Exception:
            logger.exception("Failed to close outgoing Qdrant retriever")

    def _start_retriever_call(
        self,
        retriever: Any,
        func: Callable[..., Any],
        *args: Any,
        **kwargs: Any,
    ) -> asyncio.Future[Any]:
        """Run a blocking retrieval while keeping its backend leased."""
        loop = asyncio.get_running_loop()
        retriever_key = id(retriever)
        idle_event = self._retriever_idle_events.setdefault(
            retriever_key, asyncio.Event()
        )
        idle_event.clear()
        self._retriever_lease_counts[retriever_key] = (
            self._retriever_lease_counts.get(retriever_key, 0) + 1
        )
        operation = partial(func, *args, **kwargs)

        def run() -> Any:
            try:
                return operation()
            finally:
                loop.call_soon_threadsafe(self._release_retriever_lease, retriever_key)

        try:
            future = loop.run_in_executor(None, run)
        except Exception:
            self._release_retriever_lease(retriever_key)
            raise
        future.add_done_callback(self._consume_future_exception)
        return future

    async def _run_retriever_call(
        self,
        retriever: Any,
        func: Callable[..., Any],
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        """Await a leased call without cancellation stranding its lease."""
        future = self._start_retriever_call(retriever, func, *args, **kwargs)
        return await asyncio.shield(future)

    async def _probe_retriever_readiness(self, retriever: Any) -> bool:
        """Run one leased backend probe and contain dependency failures."""
        try:
            return bool(
                await self._run_retriever_call(
                    retriever,
                    retriever.health_check,
                )
            )
        except Exception:
            logger.warning("RAG vector-store readiness check failed", exc_info=True)
            return False

    def _finish_readiness_probe(
        self,
        retriever: Any,
        task: asyncio.Task[bool],
    ) -> None:
        """Cache a completed single-flight probe without leaking exceptions."""
        if self._readiness_probe_task is not task:
            return

        self._readiness_probe_task = None
        self._readiness_probe_retriever = None
        self._readiness_cached_retriever = retriever
        self._readiness_checked_at = time.monotonic()
        try:
            self._readiness_cached_result = bool(task.result())
        except (asyncio.CancelledError, Exception):
            self._readiness_cached_result = False

    async def check_readiness(self) -> bool:
        """Check live reader state with a cached, single-flight backend probe."""
        retriever = self.retriever
        if (
            self.rag_chain is None
            or self.document_retriever is None
            or retriever is None
        ):
            return False

        if (
            self._readiness_cached_retriever is retriever
            and time.monotonic() - self._readiness_checked_at
            < _READINESS_CACHE_TTL_SECONDS
        ):
            return self._readiness_cached_result

        task = self._readiness_probe_task
        if task is None or self._readiness_probe_retriever is not retriever:
            task = asyncio.create_task(self._probe_retriever_readiness(retriever))
            self._readiness_probe_task = task
            self._readiness_probe_retriever = retriever
            task.add_done_callback(
                lambda completed: self._finish_readiness_probe(retriever, completed)
            )

        return bool(await asyncio.shield(task))

    def _release_retriever_lease(self, retriever_key: int) -> None:
        """Release a completed blocking retrieval on the event-loop thread."""
        remaining = self._retriever_lease_counts.get(retriever_key, 0) - 1
        if remaining > 0:
            self._retriever_lease_counts[retriever_key] = remaining
            return

        self._retriever_lease_counts.pop(retriever_key, None)
        idle_event = self._retriever_idle_events.get(retriever_key)
        if idle_event is not None:
            idle_event.set()

    @staticmethod
    def _consume_future_exception(future: asyncio.Future[Any]) -> None:
        """Retrieve a detached future exception to avoid an event-loop warning."""
        if not future.cancelled():
            future.exception()

    async def _close_retriever_when_idle(self, retriever: Any) -> None:
        """Close a retired retriever after its captured calls finish."""
        if retriever is None:
            return

        retriever_key = id(retriever)
        idle_event = self._retriever_idle_events.get(retriever_key)
        if self._retriever_lease_counts.get(retriever_key, 0) > 0:
            if idle_event is None:  # pragma: no cover - defensive invariant
                raise RuntimeError("Active retriever lease has no idle event")
            await idle_event.wait()

        self._retriever_idle_events.pop(retriever_key, None)
        await asyncio.to_thread(self._close_retriever, retriever)

    def _forget_background_task(self, task: asyncio.Task[Any]) -> None:
        """Drop a completed owned task after observing its result."""
        self._background_tasks.discard(task)
        if task.cancelled():
            return
        error = task.exception()
        if error is not None:
            logger.error("Background retriever retirement failed: %s", error)

    async def _retire_retriever(self, retriever: Any) -> None:
        """Own retriever retirement so caller cancellation cannot abandon it."""
        if retriever is None:
            return
        retirement_task = asyncio.create_task(
            self._close_retriever_when_idle(retriever)
        )
        self._background_tasks.add(retirement_task)
        retirement_task.add_done_callback(self._forget_background_task)
        await asyncio.shield(retirement_task)

    def _initialize_retriever(self) -> None:
        """Initialize the Qdrant retriever (single backend)."""
        self.retriever = self._create_qdrant_retriever(self.embeddings)

        # Optional ColBERT reranker initialization (lazy loading).
        if self.settings.ENABLE_COLBERT_RERANK:
            try:
                from app.services.rag.colbert_reranker import ColBERTReranker

                self.colbert_reranker = ColBERTReranker(settings=self.settings)
                logger.info("ColBERT reranker initialized (lazy loading)")
            except Exception as e:
                logger.warning(f"ColBERT reranker initialization failed: {e}")
                self.colbert_reranker = None

    @instrument_stage("retrieval")
    def _retrieve_with_version_priority(
        self, query: str, detected_version: str | None = None
    ) -> List[Document]:
        """Delegate to document retriever for version-aware retrieval.

        Args:
            query: The search query
            detected_version: Optional explicitly detected version to pass through

        Returns:
            List of documents prioritized by version relevance
        """
        return self.document_retriever.retrieve_with_version_priority(
            query, detected_version
        )

    def _format_docs(
        self, docs: List[Document], detected_version: Optional[str] = None
    ) -> str:
        """Delegate to document retriever for document formatting.

        Args:
            docs: List of documents to format
            detected_version: Optional version context for protocol tie-breaks

        Returns:
            Formatted string with version context
        """
        return self.document_retriever.format_documents(docs, detected_version)

    def _sync_language_handler(self) -> None:
        """Keep delegated language handling aligned with mutable service wiring."""
        self.language_handler.translation_service = self.translation_service

    @staticmethod
    def _normalize_language_code(value: Any) -> Optional[str]:
        return QueryLanguageHandler.normalize_language_code(value)

    def _extract_prior_language_from_history(
        self, chat_history: list[Any]
    ) -> Optional[str]:
        self._sync_language_handler()
        return self.language_handler.extract_prior_language_from_history(chat_history)

    def _build_live_index(self, *, force_rebuild: bool) -> Optional[tuple[Any, Any]]:
        """Build the next Qdrant index and retriever without replacing live state."""
        logger.info("Loading documents for live Qdrant rebuild...")
        self._refresh_source_weights_for_rebuild()

        wiki_docs = self.wiki_service.load_wiki_data() if self.wiki_service else []
        if not self.wiki_service:
            logger.warning("WikiService not provided, skipping wiki data loading")

        faq_docs = self.faq_service.load_faq_data() if self.faq_service else []
        if not self.faq_service:
            logger.warning("FAQService not provided, skipping FAQ data loading")

        llm_wiki_docs = self.llm_wiki_loader.load_documents(
            self.settings.LLM_WIKI_DIR_PATH
        )
        all_docs = wiki_docs + faq_docs + llm_wiki_docs
        logger.info(
            "Loaded %d wiki documents, %d FAQ documents, and %d LLM Wiki pages",
            len(wiki_docs),
            len(faq_docs),
            len(llm_wiki_docs),
        )
        if not all_docs:
            logger.warning("No documents loaded. Check your data paths.")
            return None

        splits = self.document_processor.split_documents(all_docs)
        embeddings = self.embeddings or self.llm_provider.initialize_embeddings()
        index_result = self.index_manager.rebuild_index(
            documents=splits,
            embeddings=embeddings,
            force=force_rebuild,
        )
        logger.info("Qdrant live index ready: %s", index_result)

        # The new retriever loads the vocabulary committed with the new physical
        # collection. The stable Qdrant alias keeps the existing retriever usable
        # until this replacement is ready.
        retriever = self._create_qdrant_retriever(embeddings)
        return embeddings, retriever

    async def rebuild_live_index(self, force_rebuild: bool = True) -> bool:
        """Rebuild Qdrant off the public event loop and atomically refresh reads."""
        async with self._setup_lock:
            try:
                async with self.faq_index_sync.rebuild_guard():
                    rebuilt = await asyncio.to_thread(
                        self._build_live_index,
                        force_rebuild=force_rebuild,
                    )
                if rebuilt is None:
                    return False

                embeddings, retriever = rebuilt
                try:
                    document_retriever = DocumentRetriever(
                        retriever=retriever,
                        reranker=self.colbert_reranker,
                        rerank_top_n=self.settings.COLBERT_TOP_N,
                    )
                except Exception:
                    self._close_retriever(retriever)
                    raise

                # No await occurs during this state replacement, so requests see
                # either the previous complete reader set or the new one.
                outgoing_retriever = self.retriever
                self.embeddings = embeddings
                self.retriever = retriever
                self.document_retriever = document_retriever
                if outgoing_retriever is not retriever:
                    await self._retire_retriever(outgoing_retriever)
                logger.info("Live Qdrant reader state refreshed")
                return True
            except Exception as error:
                logger.error(
                    "Live Qdrant rebuild failed: %s",
                    error,
                    exc_info=True,
                )
                raise

    async def setup(self, force_rebuild: bool = False):
        """Set up the complete system.

        Args:
            force_rebuild: If True, force rebuilding the Qdrant index from scratch.
                          Otherwise, reuse existing index if up-to-date.
        """
        # Acquire lock to prevent concurrent rebuilds
        async with self._setup_lock:
            try:
                logger.info("Starting simplified RAG service setup...")

                # Exclude point updates from the FAQ snapshot through alias swap.
                # The writer-preferred guard also prevents a rebuild from starving
                # under a steady stream of unrelated FAQ updates.
                async with self.faq_index_sync.rebuild_guard():
                    # Load documents
                    logger.info("Loading documents...")
                    self._refresh_source_weights_for_rebuild()

                    # Load wiki data from WikiService
                    wiki_docs = []
                    if self.wiki_service:
                        wiki_docs = self.wiki_service.load_wiki_data()
                    else:
                        logger.warning(
                            "WikiService not provided, skipping wiki data loading"
                        )

                    # Load FAQ data from FAQService
                    faq_docs = []
                    if self.faq_service:
                        faq_docs = self.faq_service.load_faq_data()
                    else:
                        logger.warning(
                            "FAQService not provided, skipping FAQ data loading"
                        )

                    llm_wiki_docs = self.llm_wiki_loader.load_documents(
                        self.settings.LLM_WIKI_DIR_PATH
                    )

                    # Combine all documents
                    all_docs = wiki_docs + faq_docs + llm_wiki_docs
                    logger.info(
                        "Loaded %d wiki documents, %d FAQ documents, "
                        "and %d LLM Wiki pages",
                        len(wiki_docs),
                        len(faq_docs),
                        len(llm_wiki_docs),
                    )

                    if not all_docs:
                        logger.warning("No documents loaded. Check your data paths.")
                        return False

                    # Split documents using document processor
                    splits = self.document_processor.split_documents(all_docs)

                    # Initialize embeddings
                    logger.info("Initializing embedding model...")
                    self.initialize_embeddings()

                    # Ensure Qdrant index exists and is up-to-date.
                    logger.info("Ensuring Qdrant index is up-to-date...")
                    index_result = self.index_manager.rebuild_index(
                        documents=splits,
                        embeddings=self.embeddings,
                        force=force_rebuild,
                    )
                    logger.info(f"Qdrant index ready: {index_result}")

                # Initialize retriever (Qdrant-only).
                self._initialize_retriever()

                # Initialize document retriever for protocol-aware retrieval
                self.document_retriever = DocumentRetriever(
                    retriever=self.retriever,
                    reranker=self.colbert_reranker,
                    rerank_top_n=self.settings.COLBERT_TOP_N,
                )
                logger.info("Document retriever initialized (Qdrant-only)")

                # Initialize language model
                logger.info("Initializing language model...")
                self.initialize_llm()

                # Create RAG chain
                logger.info("Creating RAG chain...")
                # Create prompt template
                self.prompt = self.prompt_manager.create_rag_prompt()
                # Create RAG chain with dependencies
                self.rag_chain = self.prompt_manager.create_rag_chain(
                    llm=self.llm,
                    retrieve_func=self._retrieve_with_version_priority,
                    format_docs_func=self._format_docs,
                )

                logger.info("Simplified RAG service setup complete")
                return True
            except Exception as e:
                logger.error(
                    f"Error during simplified RAG service setup: {e!s}", exc_info=True
                )
                raise

    async def cleanup(self):
        """Clean up resources."""
        logger.info("Cleaning up simplified RAG service resources...")
        context_llm_executor = self._context_llm_executor
        self._context_llm_executor = None
        if context_llm_executor is not None:
            context_llm_executor.shutdown(wait=False, cancel_futures=True)
        retriever = self.retriever
        self.retriever = None
        self.document_retriever = None
        self.rag_chain = None
        self.llm = None
        await self._retire_retriever(retriever)
        logger.info("Simplified RAG service cleanup complete")

    async def manual_rebuild(self) -> Dict[str, Any]:
        """
        Manually triggered vector store rebuild.

        Returns:
            Dictionary with rebuild results (success, duration, changes applied)
        """
        logger.info("Manual rebuild requested")

        # Use state manager to coordinate rebuild
        return await self.state_manager.execute_rebuild(
            rebuild_callback=self._perform_rebuild
        )

    async def _perform_rebuild(self) -> None:
        """
        Internal method to perform actual vector store rebuild.

        Called by state_manager.execute_rebuild() with proper state tracking.
        """
        await self.setup(force_rebuild=True)

    def get_rebuild_status(self) -> Dict[str, Any]:
        """Get current rebuild status for API consumption."""
        return self.state_manager.get_status()

    def get_rebuild_summary(self) -> Dict[str, Any]:
        """Get lightweight rebuild status for polling."""
        return self.state_manager.get_summary_status()

    @instrument_stage("generation")
    async def _answer_from_context(
        self,
        question: str,
        chat_history: List[Dict[str, str]],
        detected_version: Optional[str] = None,
    ) -> dict:
        """Try to answer a question using only conversation history.

        This method is called when no relevant documents are found, but conversation
        history exists that might contain the answer.

        Args:
            question: The user's question
            chat_history: List of previous conversation exchanges
            detected_version: Version detected upstream (e.g. "Bisq 1"), so the
                context-only prompt policy matches the detected version even
                when the current question doesn't mention it

        Returns:
            dict: Response with answer, metadata, and answer source tracking
        """
        start_time = time.time()

        try:
            logger.info(
                "Attempting to answer from conversation context (no documents found)"
            )

            # Format chat history using prompt manager
            chat_history_str = self.prompt_manager.format_chat_history(chat_history)

            # Create context-only prompt using prompt manager, split into
            # system-level guardrails and the user-level question
            system_content, user_content = (
                self.prompt_manager.create_context_only_prompt_messages(
                    question, chat_history_str, detected_version
                )
            )

            # The provider exposes a synchronous invoke API. Keep it off the event
            # loop and bound the no-document fallback so one slow provider call
            # cannot stall unrelated requests indefinitely.
            context_llm_executor = self._context_llm_executor
            if context_llm_executor is None:
                raise RuntimeError("Context LLM executor has been shut down")

            response_text = await asyncio.wait_for(
                asyncio.get_running_loop().run_in_executor(
                    context_llm_executor,
                    partial(
                        self.llm.invoke,
                        user_content,
                        system_content=system_content,
                    ),
                ),
                timeout=self.settings.CONTEXT_LLM_TIMEOUT_SECONDS,
            )
            response_content = (
                response_text.content
                if hasattr(response_text, "content")
                else str(response_text)
            )
            response_content = _apply_static_safety_warning_policy(
                response_content,
                required=False,
            )

            # Track token usage and cost
            if hasattr(response_text, "usage") and response_text.usage:
                track_tokens_and_cost(
                    input_tokens=response_text.usage.get("prompt_tokens", 0),
                    output_tokens=response_text.usage.get("completion_tokens", 0),
                    input_cost_per_token=self.settings.OPENAI_INPUT_COST_PER_TOKEN,
                    output_cost_per_token=self.settings.OPENAI_OUTPUT_COST_PER_TOKEN,
                )

            logger.info(f"Generated context-based answer: {response_content[:100]}...")

            return {
                "answer": response_content,
                "sources": [],  # No document sources for context-based answers
                "response_time": time.time() - start_time,
                "answered_from": "context",  # Metadata flag
                "context_fallback": True,
                "confidence": 0.0,
                "routing_action": "needs_human",
                "routing_reason": "Context-only answer requires human review.",
                "requires_human": True,
                "forwarded_to_human": True,
            }

        except Exception as e:
            logger.error(f"Error answering from context: {e!s}", exc_info=True)
            # Fall back to "no information" response
            return {
                "answer": error_messages.INSUFFICIENT_INFO,
                "sources": [],
                "response_time": time.time() - start_time,
                "forwarded_to_human": True,
                "context_fallback_failed": True,
                "confidence": 0.0,
                "routing_action": "needs_human",
                "routing_reason": "Context-only answer generation failed.",
                "requires_human": True,
            }

    @staticmethod
    def _best_calibrated_retrieval_score(
        docs: List[Document], doc_scores: List[float]
    ) -> Optional[float]:
        """Return the best absolute semantic score, or None when uncalibrated."""
        calibrated_scores: list[float] = []
        for index, doc in enumerate(docs):
            if doc.metadata.get("_score_type") != "absolute_cosine":
                continue
            if index >= len(doc_scores):
                continue
            try:
                score = float(doc_scores[index])
            except (TypeError, ValueError):
                continue
            if math.isfinite(score):
                calibrated_scores.append(max(0.0, min(1.0, score)))
        return max(calibrated_scores) if calibrated_scores else None

    def _resolve_source_default_version(
        self, question: str, detection_source: Optional[str]
    ) -> Optional[tuple[str, float]]:
        """Resolve a version fallback from channel source when text is ambiguous."""
        source = str(detection_source or "").strip().lower()
        if not source:
            return None

        detect_with_default = getattr(
            self.version_detector, "detect_protocol_with_source_default", None
        )
        if not callable(detect_with_default):
            return None

        try:
            protocol, confidence = detect_with_default(
                question,
                source=source,
                return_confidence=True,
            )
        except Exception:
            logger.debug(
                "Source-default protocol detection failed for source=%s",
                source,
                exc_info=True,
            )
            return None

        if protocol is None:
            return None

        display_name = self.version_detector.protocol_to_display_name(protocol)
        if display_name == "Unknown":
            return None
        return display_name, float(confidence)

    @staticmethod
    def _is_short_ambiguous_follow_up(question: str) -> bool:
        """Return True for short follow-ups where language detection is often ambiguous."""
        return QueryLanguageHandler.is_short_ambiguous_follow_up(question)

    @staticmethod
    def _extract_last_tool_result(
        tool_calls: Optional[List[Dict[str, Any]]],
        tool_name: str,
    ) -> str:
        """Return the most recent non-empty result for a given tool name."""
        return extract_last_tool_result(tool_calls, tool_name)

    @staticmethod
    def _strip_bracket_wrapper(text: str) -> str:
        return strip_bracket_wrapper(text)

    def _reconcile_live_data_fallbacks(
        self,
        response_text: str,
        tool_calls: Optional[List[Dict[str, Any]]],
    ) -> str:
        """Prevent contradiction: successful/no-offer tool results vs fetch-failure text."""
        return reconcile_live_data_fallbacks(response_text, tool_calls)

    @staticmethod
    def _normalize_chat_entry(entry: Any) -> Optional[Dict[str, str]]:
        """Normalize one chat history entry to a plain role/content dict."""
        if isinstance(entry, dict):
            role = str(entry.get("role", "") or "").strip().lower()
            content = str(entry.get("content", "") or "").strip()
        else:
            role = str(getattr(entry, "role", "") or "").strip().lower()
            content = str(getattr(entry, "content", "") or "").strip()
        if not role or not content:
            return None
        return {"role": role, "content": content}

    def _normalize_chat_history(
        self,
        question: str,
        chat_history: Optional[List[Dict[str, str]]],
    ) -> List[Dict[str, str]]:
        """Normalize history and drop duplicated trailing current user turn.

        Some clients include the current question in `chat_history`. The current
        question is already passed separately, so keeping it in history causes
        follow-up rewriting/language inference to look at the wrong turn.
        """
        normalized_question = str(question or "").strip()
        normalized: List[Dict[str, str]] = []
        for raw_entry in chat_history or []:
            entry = self._normalize_chat_entry(raw_entry)
            if entry is not None:
                normalized.append(entry)

        if not normalized:
            return []

        last = normalized[-1]
        if (
            normalized_question
            and last.get("role") == "user"
            and last.get("content", "").strip().casefold()
            == normalized_question.casefold()
        ):
            return normalized[:-1]
        return normalized

    async def _infer_language_hint_from_chat_history(
        self, chat_history: List[Dict[str, str]]
    ) -> Optional[str]:
        """Infer a non-English language hint from recent user turns."""
        self._sync_language_handler()
        return await self.language_handler.infer_language_hint_from_chat_history(
            chat_history
        )

    def _generate_streamed_rag_response(
        self,
        *,
        question: str,
        chat_history: Optional[List[Dict[str, str]]],
        docs: List[Document],
        detected_version: str,
        token_callback: Callable[[str], None],
    ) -> str:
        if self.llm is None:
            logger.warning("LLM not initialized for streaming response")
            return error_messages.GENERATION_FAILED

        chat_history_str = self.prompt_manager.format_chat_history(chat_history)
        context = self._format_docs(docs, detected_version)
        system_content, user_content = self.prompt_manager.format_prompt_messages(
            question=question,
            chat_history_str=chat_history_str,
            context=context,
        )

        chunks: list[str] = []
        for token in self.llm.stream(user_content, system_content=system_content):
            chunks.append(token)
            token_callback(token)

        response_text = "".join(chunks).strip()
        if not response_text:
            logger.warning("Empty streamed response received from LLM")
            return error_messages.GENERATION_FAILED
        return response_text

    async def stream_query(
        self,
        question: str,
        chat_history: Optional[List[Dict[str, str]]] = None,
        override_version: Optional[str] = None,
        detection_source: Optional[str] = None,
        language_hint: Optional[str] = None,
        language_hint_confidence: Optional[float] = None,
    ) -> AsyncIterator[Dict[str, Any]]:
        queue: asyncio.Queue[Dict[str, Any]] = asyncio.Queue()
        loop = asyncio.get_running_loop()

        def enqueue_token(token: str) -> None:
            loop.call_soon_threadsafe(
                queue.put_nowait,
                {"event": "token", "data": token},
            )

        async def run_query() -> None:
            try:
                result = await self.query(
                    question=question,
                    chat_history=chat_history,
                    override_version=override_version,
                    detection_source=detection_source,
                    language_hint=language_hint,
                    language_hint_confidence=language_hint_confidence,
                    token_callback=enqueue_token,
                )
                if result.get("error"):
                    await queue.put({"event": "error", "data": str(result["error"])})
                    return
                await queue.put({"event": "final", "data": result})
            except Exception as exc:
                logger.exception("Streaming RAG query failed")
                await queue.put({"event": "error", "data": str(exc)})
            finally:
                await queue.put({"event": "done", "data": None})

        task = asyncio.create_task(run_query())
        try:
            while True:
                event = await queue.get()
                if event["event"] == "done":
                    break
                yield event
        finally:
            if not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

    async def query(
        self,
        question: str,
        chat_history: Optional[List[Dict[str, str]]] = None,
        override_version: Optional[str] = None,
        detection_source: Optional[str] = None,
        language_hint: Optional[str] = None,
        language_hint_confidence: Optional[float] = None,
        token_callback: Optional[Callable[[str], None]] = None,
    ) -> Dict[str, Any]:
        """Process a query and return a response with metadata.

        Args:
            question: The query to process
            chat_history: Optional list of chat messages with 'role' and 'content' keys
            override_version: Optional version to use instead of auto-detection (for Shadow Mode)
            detection_source: Optional channel/source hint (e.g. bisq2, matrix, web)

        Returns:
            Dict containing:
                - answer: The response text
                - sources: List of source documents used
                - response_time: Time taken to process the query
                - error: Error message (if any)
        """
        start_time = time.time()

        # Track request rate
        RAG_REQUEST_RATE.inc()
        chat_history = self._normalize_chat_history(question, chat_history)
        initial_safety_inputs = [question]
        prior_user_inputs = [
            entry.get("content", "")
            for entry in chat_history
            if entry.get("role") == "user"
        ]
        if prior_user_inputs:
            initial_safety_inputs.append(prior_user_inputs[-1])
        needs_safety_reflex = any(
            should_apply_safety_reflex(text) for text in initial_safety_inputs
        )

        try:
            # Used for feedback entries created by this service when no upstream message_id exists.
            import uuid

            if not self.rag_chain:
                logger.error("RAG chain not initialized. Call setup() first.")
                return {
                    "answer": (
                        SAFETY_REFLEX_WARNING
                        if needs_safety_reflex
                        else error_messages.NOT_INITIALIZED
                    ),
                    "sources": [],
                    "response_time": time.time() - start_time,
                    "error": "RAG chain not initialized",
                    "forwarded_to_human": needs_safety_reflex,
                }

            # Log the question with privacy protection
            logger.info(f"Processing question: {redact_for_logs(question)}")

            self._sync_language_handler()
            language_state = await self.language_handler.prepare_question(
                question,
                chat_history,
                language_hint,
            )
            localized_question = language_state.localized_question
            preprocessed_question = language_state.preprocessed_question
            safety_question_before_rewrite = preprocessed_question
            canonical_question_en = language_state.canonical_question_en
            original_language = language_state.original_language
            was_translated = language_state.was_translated

            # --- Query Rewrite (feature-flagged) ---
            rewrite_metadata = {"rewritten": False}
            if (
                self.settings.ENABLE_QUERY_REWRITE
                and chat_history
                and self.query_rewriter
            ):
                try:
                    rewrite_result = await self.query_rewriter.rewrite(
                        query=preprocessed_question,
                        chat_history=chat_history,
                    )
                    if rewrite_result.rewritten:
                        preprocessed_question = rewrite_result.rewritten_query
                        rewrite_metadata = {
                            "rewritten": True,
                            "strategy": rewrite_result.strategy,
                            "original_query": rewrite_result.original_query,
                            "latency_ms": rewrite_result.latency_ms,
                        }
                except Exception as e:
                    logger.warning(f"Query rewrite failed, using original: {e}")

            safety_inputs = [safety_question_before_rewrite, preprocessed_question]
            prior_user_inputs = [
                entry.get("content", "")
                for entry in chat_history
                if entry.get("role") == "user"
            ]
            if prior_user_inputs:
                safety_inputs.append(prior_user_inputs[-1])
            needs_safety_reflex = needs_safety_reflex or any(
                should_apply_safety_reflex(text) for text in safety_inputs
            )

            # Detect version from question and chat history (unless overridden)
            if override_version:
                detected_version = override_version
                version_confidence = 1.0  # Override has 100% confidence
                clarifying_question = None
                logger.info(
                    f"Using override version: {detected_version} (Shadow Mode confirmed)"
                )
            else:
                detected_version, version_confidence, clarifying_question = (
                    await self.version_detector.detect_version(
                        preprocessed_question, chat_history
                    )
                )
                logger.info(
                    f"Detected version: {detected_version} (confidence: {version_confidence:.2f})"
                )

                # A version question must never displace the higher-priority
                # scam-safety warning. Continue to retrieval so the prompt can
                # answer from evidence, or use the static no-document fallback.
                if needs_safety_reflex and clarifying_question:
                    clarifying_question = None
                    logger.info("Skipping version clarification for safety reflex")

                # If clarifying question needed and confidence is low, return it immediately
                if clarifying_question and version_confidence < 0.5:
                    source_default = self._resolve_source_default_version(
                        preprocessed_question,
                        detection_source,
                    )
                    if source_default is not None:
                        detected_version, version_confidence = source_default
                        clarifying_question = None
                        logger.info(
                            "Using source-based default version: %s (source=%s, confidence=%.2f)",
                            detected_version,
                            str(detection_source or "").strip().lower() or "unknown",
                            version_confidence,
                        )
                    else:
                        final_clarification = (
                            await self.language_handler.translate_text_for_user(
                                clarifying_question,
                                original_language,
                                label="clarification",
                            )
                        )

                        logger.info(
                            f"Requesting clarification from user: {clarifying_question[:50]}..."
                        )
                        return {
                            "answer": final_clarification,
                            "sources": [],
                            "response_time": time.time() - start_time,
                            "needs_clarification": True,
                            "detected_version": detected_version,
                            "version_confidence": version_confidence,
                            "routing_action": "needs_clarification",
                            "forwarded_to_human": False,
                            "feedback_created": False,
                            "canonical_question_en": canonical_question_en,
                            "localized_question": localized_question,
                            "original_language": original_language,
                            "translated": was_translated,
                        }

            # Get relevant documents with version priority and similarity scores
            # Pass detected_version to ensure correct version-specific retrieval
            document_retriever = self.document_retriever
            docs, doc_scores = await self._run_retriever_call(
                document_retriever.retriever,
                document_retriever.retrieve_with_scores,
                preprocessed_question,
                detected_version,
            )

            logger.info(
                f"Retrieved {len(docs)} relevant documents (for version: {detected_version})"
            )
            docs, doc_scores = self._apply_runtime_source_weights(docs, doc_scores)

            # Safety: if the user explicitly asks about Bisq 1 but retrieval doesn't return
            # any Bisq 1-specific documents, avoid answering with Bisq Easy (Bisq 2) content.
            #
            # Exception: comparison questions ("Bisq 1 vs Bisq 2") should be allowed through
            # even if we have no Bisq 1 docs, otherwise we can't produce a comparison response.
            # Shared classifier keeps this mirror consistent with the
            # DocumentRetriever routing: generic comparison wording without an
            # explicit version/protocol token is NOT a Bisq 1 vs Bisq 2
            # comparison (e.g. "difference between SEPA and SEPA Instant").
            is_comparison_question = is_bisq_version_comparison_query(
                preprocessed_question
            )

            if (
                detected_version in ("Bisq 1", "multisig_v1")
                and not is_comparison_question
            ):
                # We consider either explicit protocol tagging OR strong content evidence.
                # Many Bisq 1 pages are categorized "general" in the processed wiki dump,
                # so relying solely on metadata would incorrectly discard relevant wiki docs.
                has_multisig_docs = False
                for doc in docs:
                    protocol = doc.metadata.get("protocol")
                    if protocol == "multisig_v1":
                        has_multisig_docs = True
                        break
                    content_lower = (doc.page_content or "").lower()
                    if (
                        ("bisq 1" in content_lower)
                        or ("bisq1" in content_lower)
                        or ("multisig" in content_lower)
                    ):
                        has_multisig_docs = True
                        break
                if not has_multisig_docs:
                    logger.info(
                        "Bisq 1 question but no multisig_v1 docs retrieved; forcing context-only fallback"
                    )
                    docs = []
                    doc_scores = []

            docs, doc_scores = self._inject_canonical_fix(
                docs,
                doc_scores,
                preprocessed_question,
                detected_version,
            )

            has_canonical_fix = any(
                doc.metadata.get("_canonical_fix_injected") is True for doc in docs
            )
            noncanonical_docs = [
                doc
                for doc in docs
                if doc.metadata.get("_canonical_fix_injected") is not True
            ]
            noncanonical_scores = [
                score
                for doc, score in zip(docs, doc_scores, strict=True)
                if doc.metadata.get("_canonical_fix_injected") is not True
            ]
            best_retrieval_score = self._best_calibrated_retrieval_score(
                noncanonical_docs,
                noncanonical_scores,
            )
            retrieval_requires_review = (
                bool(noncanonical_docs)
                and not has_canonical_fix
                and (
                    best_retrieval_score is None
                    or best_retrieval_score
                    < self.settings.RAG_RETRIEVAL_RELEVANCE_FLOOR
                )
            )

            # If no documents were retrieved, check if we can answer from conversation context
            if not docs:
                logger.info("No relevant documents found for the query")

                if needs_safety_reflex:
                    return {
                        "answer": SAFETY_REFLEX_WARNING,
                        "sources": [],
                        "response_time": time.time() - start_time,
                        "forwarded_to_human": True,
                        "feedback_created": False,
                    }

                # Check if we have conversation history to potentially answer from
                if chat_history and len(chat_history) > 0:
                    logger.info(
                        f"Attempting context-aware fallback with {len(chat_history)} messages in history"
                    )
                    return await self._answer_from_context(
                        preprocessed_question,
                        chat_history,
                        detected_version,
                    )

                # No conversation history either - create feedback entry and return "no info" message
                logger.info("No conversation history available for context fallback")

                # Create feedback entry for missing FAQ
                if self.feedback_service:
                    try:
                        await self.feedback_service.store_feedback(
                            {
                                "message_id": f"rag_{uuid.uuid4()}",
                                "question": preprocessed_question,
                                "answer": "",
                                "feedback_type": "missing_faq",
                                "explanation": "No relevant documents found for this query. This question should be added to the FAQ database.",
                                "metadata": {
                                    "source": "rag_service",
                                    "action_required": "create_faq",
                                    "priority": "high",
                                },
                            }
                        )
                        logger.info("Created feedback entry for missing FAQ")
                    except Exception as e:
                        logger.error(
                            f"Error creating feedback entry: {e!s}", exc_info=True
                        )

                return {
                    "answer": error_messages.INSUFFICIENT_INFO,
                    "sources": [],
                    "response_time": time.time() - start_time,
                    "forwarded_to_human": True,
                    "feedback_created": True,
                }

            # Log document details at DEBUG level
            for i, doc in enumerate(docs):
                logger.debug(f"Document {i + 1}:")
                logger.debug(f"  Title: {doc.metadata.get('title', 'N/A')}")
                logger.debug(f"  Type: {doc.metadata.get('type', 'N/A')}")
                logger.debug(f"  Content: {doc.page_content[:200]}...")

            # Generate response - use MCP tools if enabled for autonomous tool calling
            # The LLM uses MCP HTTP transport to access tools at mcp_url
            mcp_tools_used: list[dict[str, str]] | None = None
            mcp_invocation_succeeded = False
            live_data_required = needs_live_data(preprocessed_question)
            live_data_failed = False
            use_mcp_invocation = self.mcp_enabled and (
                token_callback is None or live_data_required
            )
            if self.mcp_enabled and not use_mcp_invocation:
                logger.info(
                    "MCP enabled, but streaming standard RAG response for non-live-data query"
                )
            if use_mcp_invocation:
                logger.info(
                    "MCP enabled, using tool-enabled invocation via HTTP transport"
                )
                try:
                    # Build prompt with context from retrieved documents,
                    # split into system-level guardrails/context and the
                    # user-level question
                    context = self._format_docs(docs, detected_version)
                    chat_history_str = self.prompt_manager.format_chat_history(
                        chat_history
                    )
                    system_content, user_content = (
                        self.prompt_manager.format_prompt_messages(
                            question=preprocessed_question,
                            chat_history_str=chat_history_str,
                            context=context,
                        )
                    )

                    # Invoke LLM with MCP tools via AISuite native HTTP transport
                    # The LLM autonomously decides when to call tools
                    # (no tools parameter - MCP config is baked into the wrapper)
                    tool_result = await asyncio.to_thread(
                        self.llm.invoke_with_tools,
                        prompt=user_content,
                        max_turns=5,
                        system_content=system_content,
                    )

                    # Check if tool invocation actually succeeded
                    if not tool_result.success:
                        logger.warning(
                            f"MCP tool infrastructure failed, falling back: {tool_result.content[:100]}"
                        )
                        raise RuntimeError("MCP tool invocation failed")

                    if live_data_required and live_data_tool_calls_failed(
                        tool_result.tool_calls_made
                    ):
                        logger.error(
                            "MCP live-data tool returned an unavailable result; "
                            "routing to human review"
                        )
                        response_text = error_messages.LIVE_DATA_UNAVAILABLE
                        live_data_failed = True
                    else:
                        response_text = tool_result.content
                        response_text = self._reconcile_live_data_fallbacks(
                            response_text=response_text,
                            tool_calls=tool_result.tool_calls_made,
                        )
                        mcp_invocation_succeeded = True

                    if mcp_invocation_succeeded:
                        # Return detailed tool usage info if the LLM called tools.
                        if tool_result.tool_calls_made:
                            from datetime import datetime, timezone

                            timestamp = datetime.now(timezone.utc).isoformat()
                            mcp_tools_used = [
                                {
                                    "tool": tc["tool"],
                                    "timestamp": timestamp,
                                    "result": tc.get("result"),
                                }
                                for tc in tool_result.tool_calls_made
                            ]
                            logger.info(
                                "MCP tool calls made: %s",
                                [tc["tool"] for tc in tool_result.tool_calls_made],
                            )
                        else:
                            logger.info(
                                "LLM processed with tools available but didn't use any"
                            )
                except Exception as e:
                    if live_data_required:
                        logger.error(
                            "MCP live-data invocation failed; routing to human review",
                            exc_info=True,
                        )
                        response_text = error_messages.LIVE_DATA_UNAVAILABLE
                        live_data_failed = True
                    else:
                        logger.warning(
                            "MCP tool invocation failed, falling back to static RAG: %s",
                            e,
                        )

            if not mcp_invocation_succeeded and not live_data_failed:
                # Standard RAG chain invocation (no MCP tools available).
                # Pass the already-retrieved, version-aware documents so the
                # chain does not re-retrieve with a version-blind default and
                # the generation context matches the reported sources.
                if token_callback is not None and not needs_safety_reflex:
                    response_text = await asyncio.to_thread(
                        self._generate_streamed_rag_response,
                        question=preprocessed_question,
                        chat_history=chat_history,
                        docs=docs,
                        detected_version=detected_version,
                        token_callback=token_callback,
                    )
                else:
                    response_text = await asyncio.to_thread(
                        self.rag_chain,
                        preprocessed_question,
                        chat_history,
                        docs=docs,
                    )

            response_text = _apply_static_safety_warning_policy(
                response_text,
                required=needs_safety_reflex,
            )

            # Calculate response time
            response_time = time.time() - start_time

            # Log response details at INFO level
            logger.info(
                f"Response generated in {response_time:.2f}s, length: {len(response_text)}"
            )

            # Log sample in non-production
            is_production = self.settings.ENVIRONMENT.lower() == "production"
            if not is_production:
                sample = (
                    response_text[: self.settings.MAX_SAMPLE_LOG_LENGTH] + "..."
                    if len(response_text) > self.settings.MAX_SAMPLE_LOG_LENGTH
                    else response_text
                )
                logger.info(f"Content sample: {redact_for_logs(sample)}")

            # Extract sources for the response with wiki URLs and similarity scores
            sources = []
            slug_manager = SlugManager()  # Initialize once for all FAQ slugs
            for i, doc in enumerate(docs):
                # Get similarity score for this document
                similarity_score = (
                    None
                    if doc.metadata.get("_canonical_fix_injected") is True
                    else (doc_scores[i] if i < len(doc_scores) else None)
                )

                # Truncate content
                content = (
                    doc.page_content[:500] + "..."
                    if len(doc.page_content) > 500
                    else doc.page_content
                )

                title = doc.metadata.get("title", "Unknown")
                section = doc.metadata.get("section")
                protocol = doc.metadata.get("protocol", "all")

                if doc.metadata.get("type") == "wiki":
                    # Generate wiki URL for wiki sources
                    canonical_url = canonical_url_for_metadata(doc.metadata)
                    wiki_url = canonical_url or generate_wiki_url(
                        title=title,
                        section=section,
                    )

                    sources.append(
                        {
                            "title": title,
                            "type": "wiki",
                            "content": content,
                            "protocol": protocol,
                            "url": wiki_url,
                            "section": section,
                            "similarity_score": (
                                round(similarity_score, 4)
                                if similarity_score is not None
                                else None
                            ),
                        }
                    )
                elif doc.metadata.get("type") == "faq":
                    # Generate FAQ URL using slug from document ID and full question
                    faq_url = None
                    faq_slug = None
                    faq_id = doc.metadata.get("id")
                    # Use full question from metadata if available, otherwise use title
                    faq_question = doc.metadata.get("question") or title
                    if faq_id and faq_question:
                        # Generate slug from question and ID
                        faq_slug = slug_manager.generate_slug(faq_question, str(faq_id))
                        faq_url = f"/faq/{faq_slug}"

                    sources.append(
                        {
                            "title": title,
                            "type": "faq",
                            "content": content,
                            "protocol": protocol,
                            "id": str(faq_id) if faq_id is not None else None,
                            "faq_id": str(faq_id) if faq_id is not None else None,
                            "question": faq_question,
                            "slug": faq_slug,
                            "url": faq_url,
                            "section": section,
                            "similarity_score": (
                                round(similarity_score, 4)
                                if similarity_score is not None
                                else None
                            ),
                        }
                    )
                elif doc.metadata.get("type") == "llm_wiki":
                    sources.append(
                        {
                            "title": title,
                            "type": "llm_wiki",
                            "category": "llm_wiki",
                            "content": content,
                            "protocol": protocol,
                            "url": None,
                            "section": section,
                            "source_refs": doc.metadata.get("source_refs", []),
                            "page_type": doc.metadata.get("page_type"),
                            "similarity_score": (
                                round(similarity_score, 4)
                                if similarity_score is not None
                                else None
                            ),
                        }
                    )

            # Deduplicate sources
            sources = self._deduplicate_sources(sources)

            # Calculate confidence score
            confidence = await self.confidence_scorer.calculate_confidence(
                answer=response_text,
                sources=docs,
                question=preprocessed_question,
            )

            if retrieval_requires_review:
                logger.warning(
                    "Retrieval relevance is below the autonomous-delivery floor "
                    "(best=%s, floor=%.2f); routing to human review",
                    (
                        f"{best_retrieval_score:.3f}"
                        if best_retrieval_score is not None
                        else "uncalibrated"
                    ),
                    self.settings.RAG_RETRIEVAL_RELEVANCE_FLOOR,
                )
                confidence = 0.0
            if live_data_failed:
                confidence = 0.0

            # Get routing decision based on confidence
            routing_action = await self.auto_send_router.route_response(
                confidence=confidence,
                question=preprocessed_question,
                answer=response_text,
                sources=docs,
            )

            # Generate human-readable routing reason
            routing_reason = self.routing_reason_generator.generate(
                confidence=confidence,
                action=routing_action.action,
                # Keep routing explanation aligned with user-visible source badges.
                num_sources=len(sources),
                detected_version=detected_version,
                version_confidence=version_confidence,
            )
            if retrieval_requires_review:
                routing_reason = (
                    "Retrieval relevance is below the autonomous-delivery floor. "
                    + routing_reason
                )
            if live_data_failed:
                routing_reason = (
                    "Live data is temporarily unavailable; human review required."
                )

            # Translate response back to user's language if needed
            final_response = response_text
            if (
                self.translation_service
                and was_translated
                and original_language != "en"
            ):
                translation_input = (
                    _without_static_safety_warning(response_text)
                    if needs_safety_reflex
                    else response_text
                )
                if translation_input:
                    final_response = (
                        await self.language_handler.translate_text_for_user(
                            translation_input,
                            original_language,
                            label="response",
                        )
                    )
                else:
                    final_response = ""

            # Stabilize version comparison questions for downstream consumers (including E2E).
            # This is content-neutral: we only add a heading if the model didn't include
            # any comparison phrasing, without inventing facts.
            if original_language == "en":
                if is_comparison_question:
                    response_lower = final_response.lower()
                    has_bisq1 = (
                        re.search(r"\bbisq\s*1\b|\bbisq1\b", response_lower) is not None
                    )
                    has_bisq2 = (
                        re.search(
                            r"\bbisq\s*2\b|\bbisq2\b|\bbisq easy\b", response_lower
                        )
                        is not None
                    )
                    has_comparison_marker = any(
                        marker in response_lower
                        for marker in (
                            "difference",
                            "compared",
                            "whereas",
                            "contrast",
                            "unlike",
                            "on the other hand",
                            "rather",
                            "upgrade",
                            "successor",
                            "evolution",
                        )
                    )

                    # If the model didn't clearly frame a comparison (or didn't mention both),
                    # prepend a stable heading that includes both versions and the word "difference".
                    if not (has_bisq1 and has_bisq2 and has_comparison_marker):
                        final_response = (
                            "Difference between Bisq 1 and Bisq 2:\n\n" + final_response
                        )

            final_response = apply_support_answer_style(
                final_response,
                question_text=preprocessed_question,
                detection_source=detection_source,
            )
            final_response = _apply_static_safety_warning_policy(
                final_response,
                required=needs_safety_reflex,
            )

            # Update error rate (success)
            update_error_rate(is_error=False)

            return {
                "answer": final_response,
                "sources": sources,
                "response_time": response_time,
                "answered_from": "documents",  # Metadata flag
                "forwarded_to_human": routing_action.queue_for_review,
                "feedback_created": False,
                "confidence": confidence,
                "routing_action": routing_action.action,
                "routing_reason": routing_reason,
                "requires_human": routing_action.action == "needs_human",
                "detected_version": detected_version,
                "version_confidence": version_confidence,
                "mcp_tools_used": mcp_tools_used,
                "original_language": original_language,
                "translated": was_translated,
                "canonical_question_en": canonical_question_en,
                "canonical_answer_en": response_text,
                "localized_question": localized_question,
                "localized_answer": final_response,
                "query_rewrite": rewrite_metadata,
            }

        except Exception as e:
            error_time = time.time() - start_time
            logger.error(f"Error processing query: {e!s}", exc_info=True)

            # Update error rate (failure)
            update_error_rate(is_error=True)

            return {
                "answer": (
                    SAFETY_REFLEX_WARNING
                    if needs_safety_reflex
                    else error_messages.QUERY_ERROR
                ),
                "sources": [],
                "response_time": error_time,
                "error": str(e),
                "forwarded_to_human": needs_safety_reflex,
                "feedback_created": False,
            }

    async def search_faq_similarity(
        self,
        question: str,
        threshold: float = 0.65,
        limit: int = 5,
        exclude_id: Optional[int] = None,
        timeout: float = 5.0,
    ) -> List[Dict[str, Any]]:
        """Search for similar FAQs using vector similarity.

        Uses the Qdrant retriever to find FAQ documents semantically similar to the
        given question. Only searches FAQ documents (excludes wiki).

        Args:
            question: The question to find similar FAQs for
            threshold: Minimum similarity score (0.0-1.0). Default 0.65 (65%)
            limit: Maximum number of results to return. Default 5
            exclude_id: FAQ ID to exclude from results (for edit mode). Default None
            timeout: Maximum time to wait for search in seconds. Default 5.0

        Returns:
            List of similar FAQs sorted by similarity (highest first), each with:
            - id: FAQ ID
            - question: FAQ question text
            - answer: FAQ answer (truncated to 200 chars)
            - similarity: Similarity score (0.0-1.0)
            - category: FAQ category (or None)
            - protocol: Trade protocol (or None)

        Notes:
            - Uses retrieve_semantic_with_scores() so `similarity` is the raw
              cosine similarity (absolute, calibrated) rather than a min-max
              normalized fusion score where the best hit is always 1.0. This
              matters because `threshold` is an absolute cutoff used for
              duplicate detection.
            - Uses filter_dict={"type": "faq"} to exclude wiki documents
            - Over-fetches to ensure enough results after filtering/deduplication
            - Returns empty list on errors (graceful degradation)
        """
        retriever = self.retriever
        if retriever is None:
            logger.warning("Retriever not initialized, cannot search for similar FAQs")
            return []

        try:
            # Over-fetch to compensate for chunk-level results and filtering.
            k = max(10, limit * 4)

            # The retriever is synchronous; run it in a thread pool with timeout.
            retrieval_future = self._start_retriever_call(
                retriever,
                retriever.retrieve_semantic_with_scores,
                question,
                k=k,
                filter_dict={"type": "faq"},
            )
            try:
                retrieved = await asyncio.wait_for(
                    asyncio.shield(retrieval_future),
                    timeout=timeout,
                )
            except asyncio.TimeoutError:
                logger.warning(f"FAQ similarity search timed out after {timeout}s")
                return []

            # Deduplicate by FAQ id, keeping the best similarity.
            best: Dict[str, Dict[str, Any]] = {}
            for doc in retrieved:
                similarity = float(doc.score or 0.0)
                if similarity < threshold:
                    continue

                faq_id = doc.metadata.get("id")
                if faq_id is None:
                    continue

                faq_id_str = str(faq_id)
                if exclude_id is not None and str(exclude_id) == faq_id_str:
                    continue

                answer = doc.metadata.get("answer", "") or ""
                if len(answer) > 200:
                    answer = answer[:200]

                candidate = {
                    "id": faq_id,
                    "question": doc.metadata.get("question", "") or "",
                    "answer": answer,
                    "similarity": similarity,
                    "category": doc.metadata.get("category"),
                    "protocol": doc.metadata.get("protocol"),
                }

                prev = best.get(faq_id_str)
                if prev is None or similarity > float(prev.get("similarity", 0.0)):
                    best[faq_id_str] = candidate

            similar_faqs = sorted(
                best.values(), key=lambda x: x["similarity"], reverse=True
            )
            return similar_faqs[:limit]

        except Exception as e:
            logger.error(f"Error searching for similar FAQs: {e}", exc_info=True)
            return []

    def _deduplicate_sources(
        self, sources: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Delegate to document retriever for source deduplication.

        Args:
            sources: List of source dictionaries

        Returns:
            List of deduplicated sources
        """
        return self.document_retriever.deduplicate_sources(sources)


def get_rag_service(request: Request) -> SimplifiedRAGService:
    """Get the RAG service from the request state."""
    return request.app.state.rag_service

import asyncio
import json
import logging
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Literal, Optional, Tuple, cast

from app.channels.escalation_localization import normalize_language_code
from app.channels.gateway import ChannelGateway
from app.channels.models import ChannelType
from app.channels.models import ChatMessage as ChannelChatMessage
from app.channels.models import GatewayError, IncomingMessage, UserContext
from app.channels.plugins.web.identity import derive_web_user_context
from app.channels.translations import get_chat_ui_labels
from app.core.config import Settings, get_settings
from app.core.exceptions import BaseAppException, ValidationError
from app.services.feedback_service import FeedbackService
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse
from prometheus_client import Counter, Gauge, Histogram
from pydantic import BaseModel

router = APIRouter()
logger = logging.getLogger(__name__)

# Prometheus metrics for chat/query tracking
QUERY_TOTAL = Counter("bisq_queries_total", "Total number of queries processed")
QUERY_RESPONSE_TIME_HISTOGRAM = Histogram(
    "bisq_query_response_time_seconds",
    "Response time distribution for chat queries",
    buckets=[0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0],
)
CURRENT_RESPONSE_TIME = Gauge(
    "bisq_current_response_time_seconds", "Latest query response time"
)
QUERY_ERRORS = Counter(
    "bisq_query_errors_total", "Total number of query errors", ["error_type"]
)


class ChatMessageRequest(BaseModel):
    role: str
    content: str


class Source(BaseModel):
    """Source document metadata with wiki URL support."""

    title: str
    type: str
    content: str
    protocol: str = "all"
    # Wiki source link fields (optional for backward compatibility)
    url: Optional[str] = None
    section: Optional[str] = None
    similarity_score: Optional[float] = None


class McpToolUsage(BaseModel):
    """Details about MCP tool usage for live Bisq 2 data."""

    tool: str
    timestamp: str
    # Raw result from the MCP tool (contains structured data like prices/offers)
    result: Optional[str] = None


class QueryRequest(BaseModel):
    question: str
    chat_history: Optional[List[ChatMessageRequest]] = None

    model_config = {"extra": "allow"}  # Allow extra fields in the request payload


class QueryResponse(BaseModel):
    answer: str
    sources: List[Source]
    response_time: float
    # Message tracking for feedback correlation
    message_id: Optional[str] = None
    # Phase 1 metadata fields
    confidence: Optional[float] = None
    routing_action: Optional[str] = None
    detected_version: Optional[str] = None
    version_confidence: Optional[float] = None
    forwarded_to_human: bool = False
    # Fields consumed by the web frontend for escalation polling
    requires_human: bool = False
    escalation_message_id: Optional[str] = None
    user_language: Optional[str] = None
    ui_labels: Optional[dict[str, str]] = None
    # MCP tools metadata - detailed info about tools used for live Bisq 2 data
    mcp_tools_used: Optional[List[McpToolUsage]] = None


def _gateway_error_to_status(error: GatewayError) -> int:
    """Convert GatewayError to HTTP status code."""
    from app.channels.models import ErrorCode

    error_status_map = {
        ErrorCode.RATE_LIMIT_EXCEEDED: 429,
        ErrorCode.AUTHENTICATION_FAILED: 401,
        ErrorCode.AUTHORIZATION_FAILED: 403,
        ErrorCode.INVALID_MESSAGE: 400,
        ErrorCode.VALIDATION_ERROR: 400,
        ErrorCode.PII_DETECTED: 400,
        ErrorCode.MESSAGE_TOO_LARGE: 413,
        ErrorCode.CHANNEL_UNAVAILABLE: 503,
        ErrorCode.SERVICE_UNAVAILABLE: 503,
        ErrorCode.REQUIRES_HUMAN_ESCALATION: 503,
        ErrorCode.RAG_SERVICE_ERROR: 500,
        ErrorCode.INTERNAL_ERROR: 500,
    }
    return error_status_map.get(error.error_code, 500)


def _format_mcp_tools_used(
    tools_used: Optional[List[Dict[str, Any]]],
) -> Optional[List[McpToolUsage]]:
    if not tools_used:
        return None
    return [McpToolUsage.model_validate(tool) for tool in tools_used]


def _normalize_chat_role(role: str) -> Literal["user", "assistant", "system"]:
    """Normalize incoming chat roles to supported channel model roles."""
    if role in ("user", "assistant", "system"):
        return cast(Literal["user", "assistant", "system"], role)
    logger.warning("Unknown chat role '%s' normalized to 'assistant'", role)
    return "assistant"


@router.api_route("/query", methods=["POST"])
async def query(
    request: Request,
    settings: Settings = Depends(get_settings),
):
    """Process a query through the Channel Gateway and return a response with sources."""
    logger.info("Received request to /query endpoint")
    # SECURITY: Only log safe headers, not all headers which may contain tokens
    logger.info(
        "Request received: method=%s content_type=%s",
        request.method,
        request.headers.get("content-type"),
    )

    # Start timing for Prometheus metrics
    start_time = time.time()

    try:
        # Get gateway from app state
        gateway = getattr(request.app.state, "channel_gateway", None)
        if gateway is None:
            logger.error("Channel gateway not initialized")
            QUERY_ERRORS.labels(error_type="service_unavailable").inc()
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Channel gateway not initialized",
            )
        gateway = cast(ChannelGateway, gateway)

        # Use the automatically parsed payload from Body
        data = await request.json()
        # SECURITY: Only log metadata, not the full data which may contain sensitive user queries
        logger.debug(
            "Parsed data keys: %s",
            list(data.keys()) if isinstance(data, dict) else [],
        )

        # Validate against our model
        try:
            logger.debug("Attempting to validate request data...")
            expected_fields = list(
                QueryRequest.model_json_schema()["properties"].keys()
            )
            logger.debug("Expected model fields: %s", expected_fields)
            logger.debug(
                "Received fields: %s",
                list(data.keys()) if isinstance(data, dict) else [],
            )

            query_request = QueryRequest.model_validate(data)
            # SECURITY: Do not log the full request which contains user queries
            logger.info("Successfully validated request structure")
        except Exception as e:
            logger.warning("Validation error: %s", e)
            QUERY_ERRORS.labels(error_type="validation").inc()
            raise ValidationError(detail=str(e)) from e

        # Optional: allow bypassing specific gateway hooks for local evaluation.
        # This is useful for RAGAS runs where we want to score the raw RAG answer
        # rather than an escalation placeholder message.
        bypass_hooks: list[str] = []
        if isinstance(data, dict) and isinstance(data.get("bypass_hooks"), list):
            bypass_hooks = [
                str(x)
                for x in data.get("bypass_hooks", [])
                if isinstance(x, str) and x.strip()
            ][:10]

        # Never allow hook bypass in production.
        if settings.ENVIRONMENT.lower() == "production":
            bypass_hooks = []

        # Log chat history info
        logger.info(f"Chat history type: {type(query_request.chat_history)}")
        if query_request.chat_history:
            logger.info(
                f"Number of messages in chat history: {len(query_request.chat_history)}"
            )
            # SECURITY: Log message roles only, not content which may contain sensitive user data
            for i, msg in enumerate(query_request.chat_history):
                logger.info(f"Message {i}: role={msg.role}")
        else:
            logger.info("No chat history provided in the request")

        # Convert to channel message format
        chat_history = None
        if query_request.chat_history:
            chat_history = [
                ChannelChatMessage(
                    role=_normalize_chat_role(msg.role),
                    content=msg.content,
                )
                for msg in query_request.chat_history
            ]

        # Create incoming message for gateway
        user_id, session_id = derive_web_user_context(request)
        incoming = IncomingMessage(
            message_id=f"web_{uuid.uuid4()}",
            channel=ChannelType.WEB,
            question=query_request.question,
            chat_history=chat_history,
            user=UserContext(
                user_id=user_id,
                session_id=session_id,
                channel_user_id=None,
                auth_token=None,
            ),
            bypass_hooks=bypass_hooks,
            channel_signature=None,
            channel_metadata={},
        )

        # Process through gateway
        result = await gateway.process_message(incoming)

        # Handle gateway error
        if isinstance(result, GatewayError):
            logger.warning(f"Gateway returned error: {result.error_code}")
            QUERY_ERRORS.labels(error_type=result.error_code.value).inc()
            return JSONResponse(
                status_code=_gateway_error_to_status(result),
                content={
                    "detail": result.error_message,
                    "error_code": result.error_code.value,
                    "details": result.details,
                },
            )

        # Convert OutgoingMessage to QueryResponse format (backward compatibility)
        formatted_sources = [
            Source(
                title=source.title,
                type=source.category or "wiki",
                content=source.content or "",
                protocol=source.protocol or "all",
                url=source.url,
                section=source.section,
                similarity_score=source.relevance_score,
            )
            for source in result.sources
        ]

        metadata = result.metadata
        user_language = normalize_language_code(
            metadata.original_language if metadata else None
        )

        response_data = QueryResponse(
            answer=result.answer,
            sources=formatted_sources,
            response_time=(
                (metadata.processing_time_ms / 1000.0)
                if metadata and metadata.processing_time_ms is not None
                else 0.0
            ),
            message_id=incoming.message_id,
            # Phase 1 metadata from gateway metadata
            confidence=metadata.confidence_score if metadata else None,
            routing_action=metadata.routing_action if metadata else None,
            detected_version=metadata.detected_version if metadata else None,
            version_confidence=metadata.version_confidence if metadata else None,
            forwarded_to_human=result.requires_human,
            requires_human=result.requires_human,
            escalation_message_id=(
                incoming.message_id if result.requires_human else None
            ),
            user_language=user_language,
            ui_labels=get_chat_ui_labels(user_language),
            mcp_tools_used=(
                _format_mcp_tools_used(metadata.mcp_tools_used) if metadata else None
            ),
        )

        # Log response size and validate JSON serializability
        response_dict = response_data.model_dump()
        try:
            response_json = json.dumps(response_dict)
            logger.info(
                f"Response prepared: answer_length={len(result.answer)}, "
                f"sources_count={len(formatted_sources)}, "
                f"total_size={len(response_json)} bytes"
            )
        except (TypeError, ValueError) as e:
            logger.error(f"Response is not JSON serializable: {e}", exc_info=True)
            raise BaseAppException(
                detail="Failed to serialize response",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                error_code="RESPONSE_SERIALIZATION_FAILED",
            ) from e

        # Track sent message for web reaction correlation
        try:
            tracker = getattr(request.app.state, "sent_message_tracker", None)
            if tracker:
                tracker.track(
                    channel_id="web",
                    external_message_id=incoming.message_id,
                    internal_message_id=incoming.message_id,
                    question=query_request.question,
                    answer=result.answer,
                    user_id=user_id,
                    sources=[
                        {
                            "title": s.title,
                            "content": s.content or "",
                            "url": s.url,
                        }
                        for s in result.sources
                    ],
                    confidence_score=metadata.confidence_score if metadata else None,
                    routing_action=metadata.routing_action if metadata else None,
                    requires_human=result.requires_human,
                    delivery_target=incoming.message_id,
                    user_language=metadata.original_language if metadata else None,
                )
        except Exception:
            logger.warning("Failed to track web message for reactions", exc_info=True)

        return JSONResponse(content=response_dict)
    except (ValidationError, BaseAppException, HTTPException):
        raise
    except Exception:
        logger.exception("Unexpected error processing /query")
        QUERY_ERRORS.labels(error_type="internal_error").inc()
        return JSONResponse(
            status_code=500, content={"detail": "Internal server error"}
        )
    finally:
        # Record metrics to Prometheus - always executed regardless of success/failure
        total_time = time.time() - start_time
        QUERY_TOTAL.inc()
        QUERY_RESPONSE_TIME_HISTOGRAM.observe(total_time)
        CURRENT_RESPONSE_TIME.set(total_time)


# Memoization for /stats: FeedbackService caches raw rows for 300s, but the
# aggregation below still iterates every row. The endpoint is public and hit
# on each chat page load, so cache the derived dict for a short TTL.
# Stored as a single (monotonic_timestamp, payload) tuple so reads/writes are
# atomic without locking; a rare concurrent recompute is benign.
_CHAT_STATS_TTL_SECONDS = 60.0
_chat_stats_cache: Optional[Tuple[float, Dict[str, Any]]] = None

# Default average response time (seconds) when no data is available: 5 minutes
_DEFAULT_AVERAGE_RESPONSE_TIME = 300.0


def reset_chat_stats_cache() -> None:
    """Clear the memoized chat stats payload (used by tests)."""
    global _chat_stats_cache
    _chat_stats_cache = None


def compute_chat_stats(
    feedback: List[Dict[str, Any]], now: Optional[datetime] = None
) -> Dict[str, Any]:
    """Aggregate response-time statistics from feedback rows.

    Pure, synchronous function so it can run in a worker thread and be
    unit-tested directly.

    Args:
        feedback: Raw feedback rows from FeedbackService.load_feedback()
        now: Reference time for the 24h window (defaults to the current UTC
            time; naive values are interpreted as UTC)

    Returns:
        Stats payload with total_queries, average_response_time and
        last_24h_average_response_time (schema consumed by the web frontend).
    """
    stats: Dict[str, Any] = {
        "total_queries": 0,
        "average_response_time": _DEFAULT_AVERAGE_RESPONSE_TIME,
        "last_24h_average_response_time": _DEFAULT_AVERAGE_RESPONSE_TIME,
    }

    # FeedbackService writes UTC ISO timestamps, so fromisoformat() yields
    # AWARE datetimes. Normalize both comparison sides to UTC-aware values;
    # a naive/aware mix would raise TypeError and silently drop recent
    # feedback out of the 24h window via the tolerant except below.
    reference_time = now or datetime.now(timezone.utc)
    if reference_time.tzinfo is None:
        reference_time = reference_time.replace(tzinfo=timezone.utc)
    cutoff_time = reference_time - timedelta(hours=24)

    total_queries = 0
    total_response_time = 0.0
    recent_queries = 0
    recent_response_time = 0.0

    for item in feedback:
        metadata = item.get("metadata") or {}
        response_time = metadata.get("response_time")
        if not response_time:
            continue

        total_queries += 1
        total_response_time += response_time

        timestamp_raw = item.get("timestamp")
        if timestamp_raw:
            try:
                parsed = datetime.fromisoformat(timestamp_raw)
                if parsed.tzinfo is None:
                    # Legacy naive timestamps are treated as UTC.
                    parsed = parsed.replace(tzinfo=timezone.utc)
                if parsed > cutoff_time:
                    recent_queries += 1
                    recent_response_time += response_time
            except (ValueError, TypeError):
                # If timestamp parsing fails, skip the 24h-window check
                pass

    if total_queries > 0:
        stats["total_queries"] = total_queries
        stats["average_response_time"] = total_response_time / total_queries

    if recent_queries > 0:
        stats["last_24h_average_response_time"] = recent_response_time / recent_queries
    else:
        # If no recent queries, use the overall average
        stats["last_24h_average_response_time"] = stats["average_response_time"]

    return stats


def _load_and_compute_chat_stats(feedback_service: FeedbackService) -> Dict[str, Any]:
    """Load feedback rows and aggregate them (runs in a worker thread)."""
    return compute_chat_stats(feedback_service.load_feedback())


@router.get("/stats")
async def get_chat_stats(settings: Settings = Depends(get_settings)):
    """Get statistics about chat responses including average response time.

    Statistics are sourced from the SQLite-backed FeedbackService (the
    authoritative feedback store), computed in a worker thread, and memoized
    for a short TTL so the endpoint never blocks the event loop.
    """
    global _chat_stats_cache

    try:
        cached = _chat_stats_cache
        if cached is not None:
            cached_at, payload = cached
            if time.monotonic() - cached_at < _CHAT_STATS_TTL_SECONDS:
                return payload

        feedback_service = FeedbackService(settings=settings)
        stats = await asyncio.to_thread(_load_and_compute_chat_stats, feedback_service)
        _chat_stats_cache = (time.monotonic(), stats)

        logger.info(f"Calculated chat stats: {stats}")
        return stats

    except Exception as e:
        logger.error(f"Error getting chat stats: {str(e)}")
        logger.exception("Full error details:")
        raise BaseAppException(
            detail="An error occurred while retrieving chat statistics",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            error_code="CHAT_STATS_FAILED",
        ) from e

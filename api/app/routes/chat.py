import json
import logging
import time
import uuid
from pathlib import Path
from typing import List, Optional

from app.channels.gateway import ChannelGateway
from app.channels.models import ChannelType
from app.channels.models import ChatMessage as ChannelChatMessage
from app.channels.models import GatewayError, IncomingMessage, UserContext
from app.core.config import Settings, get_settings
from app.core.exceptions import BaseAppException, ValidationError
from fastapi import APIRouter, Depends, Request, status
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


class ChatMessage(BaseModel):
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
    chat_history: Optional[List[ChatMessage]] = None

    model_config = {"extra": "allow"}  # Allow extra fields in the request payload


class QueryResponse(BaseModel):
    answer: str
    sources: List[Source]
    response_time: float
    # Phase 1 metadata fields
    confidence: Optional[float] = None
    routing_action: Optional[str] = None
    detected_version: Optional[str] = None
    version_confidence: Optional[float] = None
    emotion: Optional[str] = None
    emotion_intensity: Optional[float] = None
    forwarded_to_human: bool = False
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
        ErrorCode.CHANNEL_UNAVAILABLE: 503,
        ErrorCode.RAG_SERVICE_ERROR: 500,
        ErrorCode.INTERNAL_ERROR: 500,
    }
    return error_status_map.get(error.error_code, 500)


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
        gateway: ChannelGateway = request.app.state.channel_gateway

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
                    role="user" if msg.role == "user" else "assistant",
                    content=msg.content,
                )
                for msg in query_request.chat_history
            ]

        # Create incoming message for gateway
        incoming = IncomingMessage(
            message_id=f"web_{uuid.uuid4()}",
            channel=ChannelType.WEB,
            question=query_request.question,
            chat_history=chat_history,
            user=UserContext(
                user_id="web_anonymous",
                session_id=None,
                channel_user_id=None,
                auth_token=None,
            ),
            channel_signature=None,
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
                content="",  # OutgoingMessage uses DocumentReference without content
                protocol="all",
                url=source.url,
                section=None,
                similarity_score=source.relevance_score,
            )
            for source in result.sources
        ]

        response_data = QueryResponse(
            answer=result.answer,
            sources=formatted_sources,
            response_time=result.metadata.processing_time_ms
            / 1000.0,  # Convert to seconds
            # Phase 1 metadata from gateway metadata
            confidence=result.metadata.confidence_score,
            routing_action=None,  # Not tracked in gateway yet
            detected_version=None,  # Not tracked in gateway yet
            version_confidence=None,  # Not tracked in gateway yet
            emotion=None,  # Not tracked in gateway yet
            emotion_intensity=None,  # Not tracked in gateway yet
            forwarded_to_human=result.requires_human,
            mcp_tools_used=None,  # Not tracked in gateway yet
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

        return JSONResponse(content=response_dict)
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


@router.get("/stats")
async def get_chat_stats(settings: Settings = Depends(get_settings)):
    """Get statistics about chat responses including average response time."""
    try:
        # Get the feedback directory from settings
        feedback_dir = Path(settings.FEEDBACK_DIR_PATH)

        # Default values if no data is available
        stats = {
            "total_queries": 0,
            "average_response_time": 300.0,  # Default to 5 minutes
            "last_24h_average_response_time": 300.0,
        }

        if not feedback_dir.exists():
            return stats

        total_queries = 0
        total_response_time = 0

        # For tracking recent queries (last 24 hours)
        import datetime

        recent_queries = 0
        recent_response_time = 0
        cutoff_time = datetime.datetime.now() - datetime.timedelta(hours=24)

        # Process all feedback files
        for feedback_file in feedback_dir.glob("feedback_*.jsonl"):
            if not feedback_file.exists():
                continue

            with open(feedback_file) as f:
                for line in f:
                    try:
                        feedback = json.loads(line)

                        # Check if metadata and response_time exist
                        if feedback.get("metadata") and feedback["metadata"].get(
                            "response_time"
                        ):
                            total_queries += 1
                            response_time = feedback["metadata"]["response_time"]
                            total_response_time += response_time

                            # Check if this is a recent query
                            if "timestamp" in feedback:
                                try:
                                    timestamp = datetime.datetime.fromisoformat(
                                        feedback["timestamp"]
                                    )
                                    if timestamp > cutoff_time:
                                        recent_queries += 1
                                        recent_response_time += response_time
                                except (ValueError, TypeError):
                                    # If timestamp parsing fails, skip this check
                                    pass
                    except json.JSONDecodeError:
                        logger.warning(
                            f"Invalid JSON in feedback file: {feedback_file}"
                        )
                        continue

        # Calculate averages if we have data
        if total_queries > 0:
            stats["total_queries"] = total_queries
            stats["average_response_time"] = total_response_time / total_queries

        if recent_queries > 0:
            stats["last_24h_average_response_time"] = (
                recent_response_time / recent_queries
            )
        else:
            # If no recent queries, use the overall average
            stats["last_24h_average_response_time"] = stats["average_response_time"]

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

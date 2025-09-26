import json
import logging
import time
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from prometheus_client import Counter, Gauge, Histogram

from app.core.config import get_settings, Settings

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
    title: str
    type: str
    content: str


class QueryRequest(BaseModel):
    question: str
    chat_history: Optional[List[ChatMessage]] = None

    model_config = {"extra": "allow"}  # Allow extra fields in the request payload


class QueryResponse(BaseModel):
    answer: str
    sources: List[Source]
    response_time: float


@router.api_route("/query", methods=["POST"])
async def query(
    request: Request,
    settings: Settings = Depends(get_settings),
):
    """Process a query and return a response with sources."""
    logger.info("Received request to /query endpoint")
    logger.info(f"Request headers: {dict(request.headers)}")
    logger.info(f"Request content type: {request.headers.get('content-type')}")
    logger.info(f"Request method: {request.method}")

    # Start timing for Prometheus metrics
    start_time = time.time()

    try:
        # Get RAG service from app state
        rag_service = request.app.state.rag_service

        # Use the automatically parsed payload from Body
        data = await request.json()
        logger.info(f"Automatically parsed JSON data: {json.dumps(data, indent=2)}")
        logger.info(f"Parsed data type: {type(data)}")
        logger.info(
            f"Parsed data keys: {list(data.keys()) if isinstance(data, dict) else 'Not a dict'}"
        )

        # Validate against our model
        try:
            logger.info("Attempting to validate request data...")
            # Get field names using model_json_schema instead of model_fields.keys()
            expected_fields = list(
                QueryRequest.model_json_schema()["properties"].keys()
            )
            logger.info(f"Expected model fields: {expected_fields}")
            logger.info(
                f"Received fields: {list(data.keys()) if isinstance(data, dict) else []}"
            )
            logger.info(f"Model validation about to start with data: {data}")

            query_request = QueryRequest.model_validate(data)
            logger.info(f"Successfully validated request: {query_request}")
        except Exception as e:
            logger.error("Validation error occurred")
            logger.error(f"Input data: {data}")
            logger.error(f"Validation error details: {str(e)}")
            # Use model_json_schema instead of model_fields
            logger.error(
                f"Model fields: {QueryRequest.model_json_schema()['properties']}"
            )
            QUERY_ERRORS.labels(error_type="validation").inc()
            raise HTTPException(status_code=422, detail=str(e)) from e

        # Get response from simplified RAG service
        logger.info(f"Chat history type: {type(query_request.chat_history)}")
        if query_request.chat_history:
            logger.info(
                f"Number of messages in chat history: {len(query_request.chat_history)}"
            )
            for i, msg in enumerate(query_request.chat_history):
                logger.info(
                    f"Message {i}: role={msg.role}, content={msg.content[:30]}..."
                )
        else:
            logger.info("No chat history provided in the request")

        result = await rag_service.query(
            query_request.question, query_request.chat_history
        )

        # Convert sources to the expected format
        formatted_sources = [
            Source(
                title=source["title"], type=source["type"], content=source["content"]
            )
            for source in result["sources"]
        ]

        response_data = QueryResponse(
            answer=result["answer"],
            sources=formatted_sources,
            response_time=result["response_time"],
        )

        # Record metrics to Prometheus
        total_time = time.time() - start_time
        QUERY_TOTAL.inc()
        QUERY_RESPONSE_TIME_HISTOGRAM.observe(total_time)
        CURRENT_RESPONSE_TIME.set(total_time)

        return JSONResponse(content=response_data.model_dump())
    except Exception as e:
        logger.error(f"Unexpected error processing request: {str(e)}")
        logger.error("Full error details:", exc_info=True)
        QUERY_ERRORS.labels(error_type="internal_error").inc()
        return JSONResponse(
            status_code=500, content={"detail": "Internal server error"}
        )


@router.get("/stats")
async def get_chat_stats(settings: Settings = Depends(get_settings)):
    """Get statistics about chat responses including average response time."""
    try:
        # Get the feedback directory from settings
        feedback_dir = Path(settings.FEEDBACK_DIR_PATH)

        # Default values if no data is available
        stats = {
            "total_queries": 0,
            "average_response_time": 300,  # Default to 5 minutes
            "last_24h_average_response_time": 300,
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
        raise HTTPException(
            status_code=500, detail="An error occurred while retrieving chat statistics"
        )

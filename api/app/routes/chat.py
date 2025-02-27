import json
import logging
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Request, Body
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.core.config import get_settings, Settings
from app.services.rag_service import get_rag_service, RAGService

router = APIRouter()
logger = logging.getLogger(__name__)


class Source(BaseModel):
    title: str
    type: str
    content: str


class QueryRequest(BaseModel):
    question: str

    model_config = {"extra": "allow"}  # Allow extra fields in the request payload


class QueryResponse(BaseModel):
    answer: str
    sources: List[Source]
    response_time: float


@router.api_route("/query", methods=["POST"])
async def query(
        request: Request,
        settings: Settings = Depends(get_settings),
        rag_service: RAGService = Depends(get_rag_service),
        body_payload: dict = Body(...)
):
    """Process a query and return a response with sources."""
    logger.info("Received request to /query endpoint")
    logger.info(f"Request headers: {dict(request.headers)}")
    logger.info(f"Request content type: {request.headers.get('content-type')}")
    logger.info(f"Request method: {request.method}")

    try:
        # Use the automatically parsed payload from Body
        data = body_payload
        logger.info(f"Automatically parsed JSON data: {json.dumps(data, indent=2)}")
        logger.info(f"Parsed data type: {type(data)}")
        logger.info(f"Parsed data keys: {list(data.keys()) if isinstance(data, dict) else 'Not a dict'}")

        # Validate against our model
        try:
            logger.info("Attempting to validate request data...")
            # Get field names using model_json_schema instead of model_fields.keys()
            expected_fields = list(QueryRequest.model_json_schema()["properties"].keys())
            logger.info(f"Expected model fields: {expected_fields}")
            logger.info(f"Received fields: {list(data.keys()) if isinstance(data, dict) else []}")
            logger.info(f"Model validation about to start with data: {data}")

            query_request = QueryRequest.model_validate(data)
            logger.info(f"Successfully validated request: {query_request}")
        except Exception as e:
            logger.error("Validation error occurred")
            logger.error(f"Input data: {data}")
            logger.error(f"Validation error details: {str(e)}")
            # Use model_json_schema instead of model_fields
            logger.error(f"Model fields: {QueryRequest.model_json_schema()['properties']}")
            raise HTTPException(status_code=422, detail=str(e))

        # Get response from RAG service
        result = rag_service.query(query_request.question, None)

        # Convert sources to the expected format
        formatted_sources = [
            Source(
                title=source["title"],
                type=source["type"],
                content=source["content"]
            )
            for source in result["sources"]
        ]

        response_data = QueryResponse(
            answer=result["answer"],
            sources=formatted_sources,
            response_time=result["response_time"]
        )

        return JSONResponse(content=response_data.model_dump())

    except Exception as e:
        logger.error(f"Unexpected error processing request: {str(e)}")
        logger.error("Full error details:", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={"detail": str(e)}
        )

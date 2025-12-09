"""Shadow Mode API endpoints for two-phase workflow."""

import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.core.config import get_settings
from app.integrations.matrix_shadow_mode import MatrixShadowModeService
from app.models.shadow_response import ShadowResponse, ShadowStatus
from app.services.shadow_mode.repository import ShadowModeRepository
from app.services.shadow_mode_processor import ShadowModeProcessor
from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, field_validator, model_validator

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/admin/shadow-mode",
    tags=["shadow-mode"],
)


# Request/Response Models
class ConfirmVersionRequest(BaseModel):
    """Request body for confirming version."""

    confirmed_version: str
    version_change_reason: Optional[str] = None
    training_version: Optional[str] = None  # Required when confirmed_version="Unknown"
    custom_clarifying_question: Optional[str] = None  # Optional custom question

    @model_validator(mode="after")
    def validate_training_version_for_unknown(self):
        """Require training_version when confirmed_version is Unknown."""
        if self.confirmed_version == "Unknown" and not self.training_version:
            raise ValueError(
                "training_version required when confirmed_version is Unknown"
            )
        if self.training_version and self.training_version not in ["Bisq 1", "Bisq 2"]:
            raise ValueError("training_version must be 'Bisq 1' or 'Bisq 2'")
        return self


class EditResponseRequest(BaseModel):
    """Request body for editing response."""

    edited_response: str


class SkipResponseRequest(BaseModel):
    """Request body for skipping response."""

    skip_reason: Optional[str] = None


class StatsResponse(BaseModel):
    """Statistics response."""

    total: int
    pending_version_review: int
    pending_response_review: int
    rag_failed: int
    approved: int
    edited: int
    rejected: int
    skipped: int
    avg_confidence: float


# Repository singleton
_data_dir = os.environ.get("DATA_DIR", "/data")
_db_path = os.path.join(_data_dir, "shadow_mode.db")
_repository: Optional[ShadowModeRepository] = None


def _get_repository() -> ShadowModeRepository:
    """Get or create repository instance."""
    global _repository
    if _repository is None:
        _repository = ShadowModeRepository(_db_path)
    return _repository


def _response_to_dict(resp: ShadowResponse) -> Dict[str, Any]:
    """Convert ShadowResponse to dict for JSON serialization."""
    return {
        "id": resp.id,
        "channel_id": resp.channel_id,
        "user_id": resp.user_id,
        "messages": resp.messages,
        "synthesized_question": resp.synthesized_question,
        "detected_version": resp.detected_version,
        "version_confidence": resp.version_confidence,
        "detection_signals": resp.detection_signals,
        "confirmed_version": resp.confirmed_version,
        "version_change_reason": resp.version_change_reason,
        "training_version": resp.training_version,
        "requires_clarification": resp.requires_clarification,
        "clarifying_question": resp.clarifying_question,
        "source": resp.source,
        "clarification_answer": resp.clarification_answer,
        "generated_response": resp.generated_response,
        "sources": resp.sources,
        "edited_response": resp.edited_response,
        "confidence": resp.confidence,
        "routing_action": resp.routing_action,
        "status": (
            resp.status.value if isinstance(resp.status, ShadowStatus) else resp.status
        ),
        "rag_error": resp.rag_error,
        "retry_count": resp.retry_count,
        "skip_reason": resp.skip_reason,
        "created_at": resp.created_at.isoformat() if resp.created_at else None,
        "updated_at": resp.updated_at.isoformat() if resp.updated_at else None,
        "version_confirmed_at": (
            resp.version_confirmed_at.isoformat() if resp.version_confirmed_at else None
        ),
        "response_generated_at": (
            resp.response_generated_at.isoformat()
            if resp.response_generated_at
            else None
        ),
    }


@router.get("/responses")
async def get_responses_v2(
    status: Optional[str] = Query(None, description="Filter by status"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> List[Dict[str, Any]]:
    """Get shadow responses with optional filtering."""
    repo = _get_repository()
    responses = repo.get_responses(status=status, limit=limit, offset=offset)
    return [_response_to_dict(r) for r in responses]


@router.get("/responses/{response_id}")
async def get_response_v2(response_id: str) -> Dict[str, Any]:
    """Get a specific shadow response."""
    repo = _get_repository()
    response = repo.get_response(response_id)
    if not response:
        raise HTTPException(status_code=404, detail=f"Response {response_id} not found")
    return _response_to_dict(response)


@router.get("/stats", response_model=StatsResponse)
async def get_stats_v2() -> Dict[str, Any]:
    """Get shadow mode statistics."""
    repo = _get_repository()
    return repo.get_stats()


@router.post("/responses/{response_id}/confirm-version")
async def confirm_version(
    response_id: str, body: ConfirmVersionRequest, request: Request
) -> Dict[str, str]:
    """Confirm version and trigger RAG generation."""
    repo = _get_repository()

    try:
        # First get the response to access the question
        response = repo.get_response(response_id)
        if not response:
            raise HTTPException(
                status_code=404, detail=f"Response {response_id} not found"
            )

        # Determine which version to use for RAG generation
        rag_version = (
            body.training_version
            if body.confirmed_version == "Unknown"
            else body.confirmed_version
        )

        # Confirm the version with enhanced fields
        success = repo.confirm_version(
            response_id,
            confirmed_version=body.confirmed_version,
            change_reason=body.version_change_reason,
            training_version=body.training_version,
            requires_clarification=(body.confirmed_version == "Unknown"),
            clarifying_question=body.custom_clarifying_question,
        )
        if not success:
            raise HTTPException(
                status_code=404, detail=f"Response {response_id} not found"
            )

        # Get RAG service from app state
        rag_service = request.app.state.rag_service

        # Generate response using RAG with training version for Unknown cases
        try:
            rag_result = await rag_service.query(
                question=response.synthesized_question,
                chat_history=[],
                override_version=rag_version,  # Use training_version for Unknown
            )

            # Extract sources from RAG result
            sources = []
            if rag_result.get("sources"):
                for source in rag_result["sources"]:
                    sources.append(
                        {
                            "title": source.get("title", "Unknown"),
                            "type": source.get("type", "unknown"),
                            "content": source.get("content", ""),
                            "bisq_version": source.get("bisq_version", "General"),
                            "relevance": source.get("relevance", 0.0),
                        }
                    )

            # Update response with generated content including confidence and routing
            repo.update_response(
                response_id,
                {
                    "generated_response": rag_result.get("answer", ""),
                    "sources": sources,
                    "confidence": rag_result.get("confidence"),
                    "routing_action": rag_result.get("routing_action"),
                    "response_generated_at": datetime.now(timezone.utc).isoformat(),
                    "status": ShadowStatus.PENDING_RESPONSE_REVIEW.value,
                },
            )

            logger.info(
                f"Version confirmed and RAG generated for {response_id}: {body.confirmed_version}"
            )
            return {"message": "Version confirmed, response generated successfully"}

        except Exception as e:
            # Mark as RAG failed and increment retry count
            repo.update_response(
                response_id,
                {
                    "status": ShadowStatus.RAG_FAILED.value,
                    "rag_error": str(e),
                    "retry_count": (response.retry_count or 0) + 1,
                },
            )
            logger.error(f"RAG generation failed for {response_id}: {e}")
            raise HTTPException(
                status_code=500, detail=f"RAG generation failed: {str(e)}"
            )

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/responses/{response_id}/skip")
async def skip_response(
    response_id: str, request: Optional[SkipResponseRequest] = None
) -> Dict[str, str]:
    """Skip a response with optional reason for ML training."""
    repo = _get_repository()

    updates = {
        "status": ShadowStatus.SKIPPED.value,
    }
    if request and request.skip_reason:
        updates["skip_reason"] = request.skip_reason

    if not repo.update_response(response_id, updates):
        raise HTTPException(status_code=404, detail=f"Response {response_id} not found")

    reason_msg = (
        f" (reason: {request.skip_reason})" if request and request.skip_reason else ""
    )
    logger.info(f"Response {response_id} skipped{reason_msg}")
    return {"message": f"Response {response_id} skipped"}


@router.post("/responses/{response_id}/approve")
async def approve_response(response_id: str) -> Dict[str, str]:
    """Approve a response."""
    repo = _get_repository()
    success = repo.update_response(response_id, {"status": ShadowStatus.APPROVED.value})
    if not success:
        raise HTTPException(status_code=404, detail=f"Response {response_id} not found")

    logger.info(f"Response {response_id} approved")
    return {"message": f"Response {response_id} approved"}


@router.post("/responses/{response_id}/edit")
async def edit_response(
    response_id: str, request: EditResponseRequest
) -> Dict[str, str]:
    """Edit and save a response."""
    repo = _get_repository()
    success = repo.update_response(
        response_id,
        {
            "edited_response": request.edited_response,
            "status": ShadowStatus.EDITED.value,
        },
    )
    if not success:
        raise HTTPException(status_code=404, detail=f"Response {response_id} not found")

    logger.info(f"Response {response_id} edited")
    return {"message": f"Response {response_id} edited"}


@router.post("/responses/{response_id}/reject")
async def reject_response(response_id: str) -> Dict[str, str]:
    """Reject a response."""
    repo = _get_repository()
    success = repo.update_response(response_id, {"status": ShadowStatus.REJECTED.value})
    if not success:
        raise HTTPException(status_code=404, detail=f"Response {response_id} not found")

    logger.info(f"Response {response_id} rejected")
    return {"message": f"Response {response_id} rejected"}


@router.post("/responses/{response_id}/retry-rag")
async def retry_rag(response_id: str, request: Request) -> Dict[str, str]:
    """Retry RAG generation for a failed response."""
    repo = _get_repository()
    response = repo.get_response(response_id)

    if not response:
        raise HTTPException(status_code=404, detail=f"Response {response_id} not found")

    if response.status != ShadowStatus.RAG_FAILED:
        raise HTTPException(
            status_code=400,
            detail=f"Can only retry RAG for failed responses, current status: {response.status.value}",
        )

    # Get RAG service from app state
    rag_service = request.app.state.rag_service

    # Use confirmed version if available, otherwise use detected version
    version = response.confirmed_version or response.detected_version

    try:
        rag_result = await rag_service.query(
            question=response.synthesized_question,
            chat_history=[],
        )

        # Extract sources from RAG result
        sources = []
        if rag_result.get("sources"):
            for source in rag_result["sources"]:
                sources.append(
                    {
                        "title": source.get("title", "Unknown"),
                        "type": source.get("type", "unknown"),
                        "relevance": source.get("relevance", 0.0),
                    }
                )

        # Update response with generated content including confidence and routing
        repo.update_response(
            response_id,
            {
                "generated_response": rag_result.get("answer", ""),
                "sources": sources,
                "confidence": rag_result.get("confidence"),
                "routing_action": rag_result.get("routing_action"),
                "response_generated_at": datetime.now(timezone.utc).isoformat(),
                "status": ShadowStatus.PENDING_RESPONSE_REVIEW.value,
                "rag_error": None,
            },
        )

        logger.info(f"RAG retry successful for {response_id}")
        return {"message": f"RAG retry successful for {response_id}"}

    except Exception as e:
        # Update retry count and error message
        repo.update_response(
            response_id,
            {
                "rag_error": str(e),
                "retry_count": (response.retry_count or 0) + 1,
            },
        )
        logger.error(f"RAG retry failed for {response_id}: {e}")
        raise HTTPException(status_code=500, detail=f"RAG retry failed: {str(e)}")


@router.get("/version-changes")
async def get_version_changes() -> List[Dict[str, Any]]:
    """Get all version change events for training data."""
    repo = _get_repository()
    return repo.get_version_changes()


@router.get("/skip-patterns")
async def get_skip_patterns() -> List[Dict[str, Any]]:
    """Get all skipped entries with reasons for question detection ML training."""
    repo = _get_repository()
    return repo.get_skip_patterns()


@router.post("/responses/clarification")
async def save_clarification(
    channel_id: str = Query(..., description="Channel/conversation ID"),
    user_id: str = Query(..., description="User ID"),
    question: str = Query(..., description="User's original question"),
    clarifying_question: str = Query(
        ..., description="Question asked for clarification"
    ),
    user_answer: str = Query(..., description="User's answer to clarification"),
    detected_version: str = Query(..., description="Version detected from answer"),
) -> Dict[str, str]:
    """Save user clarification as high-confidence training data.

    When RAG bot asks clarifying question and user responds, this endpoint
    saves the interaction as training data with source="rag_bot_clarification"
    and higher source weight (1.5x) for ML training.

    Flow:
    1. RAG bot detects low version confidence
    2. RAG bot asks clarifying question
    3. User answers (e.g., "I'm using Bisq 2")
    4. RAG bot calls this endpoint to save as training data
    5. Data used for improving version detection patterns
    """
    repo = _get_repository()

    try:
        # Create shadow response from clarification interaction
        response = ShadowResponse(
            id=f"clarification_{channel_id}_{datetime.now(timezone.utc).timestamp()}",
            channel_id=channel_id,
            user_id=user_id,
            messages=[
                {
                    "content": question,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "sender_type": "user",
                    "message_id": f"q_{channel_id}",
                },
                {
                    "content": clarifying_question,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "sender_type": "bot",
                    "message_id": f"cq_{channel_id}",
                },
                {
                    "content": user_answer,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "sender_type": "user",
                    "message_id": f"ans_{channel_id}",
                },
            ],
            synthesized_question=question,
            detected_version=detected_version,
            version_confidence=0.95,  # High confidence from direct user answer
            confirmed_version=detected_version,  # Auto-confirm from user answer
            requires_clarification=False,  # Already clarified
            clarifying_question=clarifying_question,
            source="rag_bot_clarification",  # High-value source (1.5x weight)
            clarification_answer=user_answer,
            status=ShadowStatus.PENDING_RESPONSE_REVIEW,  # Still needs admin review
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            version_confirmed_at=datetime.now(timezone.utc),
        )

        # Save to repository
        repo.add_response(response)

        logger.info(
            f"Saved clarification training data: {channel_id} -> {detected_version}"
        )
        return {
            "message": "Clarification saved as training data",
            "response_id": response.id,
            "source_weight": "1.5x (high-value direct answer)",
        }

    except Exception as e:
        logger.error(f"Failed to save clarification: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to save clarification: {str(e)}"
        )


@router.delete("/responses/{response_id}")
async def delete_response(response_id: str) -> Dict[str, str]:
    """Delete a shadow response."""
    repo = _get_repository()
    if not repo.delete_response(response_id):
        raise HTTPException(status_code=404, detail=f"Response {response_id} not found")

    logger.info(f"Deleted shadow response {response_id}")
    return {"message": f"Response {response_id} deleted"}


@router.post("/test/create-response")
async def create_test_response(
    channel_id: str = Query(default="test-channel"),
    user_id: str = Query(default="test-user"),
    question: str = Query(default="Test question about trading?"),
    detected_version: Optional[str] = Query(default="unknown"),
    confidence: float = Query(default=0.3),
) -> Dict[str, str]:
    """Create a test shadow mode response (for E2E testing only)."""
    import uuid

    settings = get_settings()

    # Only allow in non-production environments
    if settings.ENVIRONMENT.lower() == "production":
        raise HTTPException(
            status_code=403, detail="Test endpoint not available in production"
        )

    repo = _get_repository()

    # Create ShadowResponse instance with proper structure
    response = ShadowResponse(
        id=str(uuid.uuid4()),
        channel_id=channel_id,
        user_id=user_id,
        messages=[
            {
                "content": question,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "sender_type": "user",
                "message_id": str(uuid.uuid4()),
            }
        ],
        synthesized_question=question,
        detected_version=detected_version,
        version_confidence=confidence,
        status=ShadowStatus.PENDING_VERSION_REVIEW,
        source="e2e_test",
    )

    # Add response to database
    repo.add_response(response)

    logger.info(f"Created test shadow response {response.id}")
    return {"message": "Test response created", "response_id": response.id}


@router.post("/poll")
async def poll_matrix_messages() -> Dict[str, Any]:
    """Poll Matrix room for new support questions and process them."""
    settings = get_settings()

    # Check if Matrix credentials are configured
    if not all(
        [
            settings.MATRIX_HOMESERVER_URL,
            settings.MATRIX_USER,
            settings.MATRIX_TOKEN,
            settings.MATRIX_ROOMS,
        ]
    ):
        raise HTTPException(
            status_code=400,
            detail="Matrix credentials not configured. Set MATRIX_HOMESERVER_URL, MATRIX_USER, MATRIX_TOKEN, and MATRIX_ROOMS",
        )

    # Get first room ID from list
    room_id = (
        settings.MATRIX_ROOMS[0]
        if isinstance(settings.MATRIX_ROOMS, list)
        else settings.MATRIX_ROOMS
    )

    try:
        # Initialize Matrix service with password-based auth (recommended)
        # Falls back to token if password not available
        matrix_service = MatrixShadowModeService(
            homeserver=settings.MATRIX_HOMESERVER_URL,
            user_id=settings.MATRIX_USER,
            password=settings.MATRIX_PASSWORD or None,
            access_token=settings.MATRIX_TOKEN or None,
            room_id=room_id,
        )

        # Connect and poll
        await matrix_service.connect()

        repo = _get_repository()
        settings = get_settings()

        # Get processor and process questions (with LLM classification if enabled)
        processor = ShadowModeProcessor(repository=repo, settings=settings)
        processed_count = await matrix_service.process_with_shadow_mode(processor)

        # Disconnect
        await matrix_service.disconnect()

        logger.info(f"Polled Matrix room, processed {processed_count} questions")
        return {
            "message": f"Processed {processed_count} questions",
            "processed_count": processed_count,
        }

    except Exception as e:
        logger.error(f"Error polling Matrix: {e}")
        raise HTTPException(status_code=500, detail=str(e))

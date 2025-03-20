import json
import logging
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Dict, Any

from fastapi import APIRouter, HTTPException, Request, Body
from pydantic import BaseModel

from app.core.config import get_settings
from app.services.simplified_rag_service import get_rag_service

router = APIRouter()
logger = logging.getLogger(__name__)


class FeedbackRequest(BaseModel):
    message_id: str
    question: str
    answer: str
    rating: int
    sources: Optional[List[Dict[str, str]]] = None
    metadata: Optional[Dict[str, Any]] = None


@router.post("/feedback/submit")
async def submit_feedback(feedback: FeedbackRequest):
    """
    Submit feedback for a chat response.
    """
    try:
        # Get settings for data directory
        settings = get_settings()
        # Use the configured DATA_DIR and store feedback in a subdirectory
        feedback_dir = Path(settings.DATA_DIR) / "feedback"
        feedback_dir.mkdir(parents=True, exist_ok=True)

        # Create feedback file for current month
        current_month = datetime.now().strftime("%Y-%m")
        feedback_file = feedback_dir / f"feedback_{current_month}.jsonl"

        # Add timestamp to feedback
        feedback_data = feedback.model_dump()
        feedback_data["timestamp"] = datetime.now().isoformat()

        # Append feedback to file
        with open(feedback_file, "a") as f:
            f.write(json.dumps(feedback_data) + "\n")

        return {"status": "success", "message": "Feedback recorded successfully"}

    except Exception as e:
        logger.error(f"Error recording feedback: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail="An error occurred while recording your feedback"
        )


@router.get("/feedback/stats")
async def get_feedback_stats():
    """
    Get aggregated feedback statistics.
    """
    try:
        settings = get_settings()
        feedback_dir = Path(settings.DATA_DIR) / "feedback"
        if not feedback_dir.exists():
            return {
                "total_feedback": 0,
                "average_rating": 0,
                "positive_ratio": 0
            }

        total_feedback = 0
        total_rating = 0
        positive_ratings = 0

        # Process all feedback files
        for feedback_file in feedback_dir.glob("feedback_*.jsonl"):
            with open(feedback_file) as f:
                for line in f:
                    feedback = json.loads(line)
                    total_feedback += 1
                    total_rating += feedback["rating"]
                    if feedback["rating"] > 0:
                        positive_ratings += 1

        average_rating = total_rating / total_feedback if total_feedback > 0 else 0
        positive_ratio = positive_ratings / total_feedback if total_feedback > 0 else 0

        return {
            "total_feedback": total_feedback,
            "average_rating": average_rating,
            "positive_ratio": positive_ratio
        }

    except Exception as e:
        logger.error(f"Error getting feedback stats: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail="An error occurred while retrieving feedback statistics"
        )


@router.post("/feedback", response_model=Dict[str, Any])
async def submit_chat_feedback(
        request: Request,
        feedback_data: Dict[str, Any] = Body(...),
):
    """Submit feedback for a previous chat response."""
    rag_service = get_rag_service(request)

    # Extract required fields
    message_id = feedback_data.get("message_id")
    rating = feedback_data.get("rating")  # 1 = helpful, 0 = unhelpful

    if message_id is None or rating is None:
        return {"success": False, "error": "Missing required fields"}

    # Process the feedback
    await rag_service.store_feedback(feedback_data)

    # Add needs_feedback_followup flag for negative feedback
    needs_followup = rating == 0

    return {
        "success": True,
        "message": "Feedback submitted successfully",
        "needs_feedback_followup": needs_followup
    }


@router.post("/feedback/explanation", response_model=Dict[str, Any])
async def submit_feedback_explanation(
        request: Request,
        explanation_data: Dict[str, Any] = Body(...),
):
    """Submit explanation for negative feedback.
    
    This endpoint receives explanations about why an answer was unhelpful.
    It updates the existing feedback with the explanation and categorizes issues.
    """
    rag_service = get_rag_service(request)

    # Extract required fields
    message_id = explanation_data.get("message_id")
    explanation = explanation_data.get("explanation")

    if message_id is None or not explanation:
        return {"success": False, "error": "Missing required fields"}

    # Extract any specific issues mentioned by the user
    issues = explanation_data.get("issues", [])

    # Get current feedback entry - load_feedback is synchronous, not async
    all_feedback = rag_service.load_feedback()
    feedback_entry = None

    for item in all_feedback:
        if item.get("message_id") == message_id:
            feedback_entry = item
            break

    if not feedback_entry:
        return {"success": False, "error": "Feedback entry not found"}

    # Update feedback with explanation
    if not feedback_entry.get("metadata"):
        feedback_entry["metadata"] = {}

    feedback_entry["metadata"]["explanation"] = explanation

    # Add issues if explicitly provided
    if issues:
        if not feedback_entry["metadata"].get("issues"):
            feedback_entry["metadata"]["issues"] = []

        feedback_entry["metadata"]["issues"].extend(issues)

    # Analyze explanation text for common issues if no specific issues provided
    if not issues and explanation:
        detected_issues = await rag_service.analyze_feedback_text(explanation)

        if detected_issues:
            if not feedback_entry["metadata"].get("issues"):
                feedback_entry["metadata"]["issues"] = []

            feedback_entry["metadata"]["issues"].extend(detected_issues)

    # Update the feedback entry
    await rag_service.update_feedback_entry(message_id, feedback_entry)

    return {
        "success": True,
        "message": "Feedback explanation received",
        "detected_issues": feedback_entry["metadata"].get("issues", [])
    }

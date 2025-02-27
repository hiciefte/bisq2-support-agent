import json
import logging
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Dict, Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.core.config import get_settings

router = APIRouter()
logger = logging.getLogger(__name__)


class FeedbackRequest(BaseModel):
    message_id: str
    question: str
    answer: str
    rating: int
    sources: Optional[List[Dict[str, str]]] = None
    metadata: Optional[Dict[str, Any]] = None


@router.post("/submit")
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


@router.get("/stats")
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

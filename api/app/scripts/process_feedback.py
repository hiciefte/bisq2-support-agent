"""
Process user feedback to improve RAG system performance.
"""

import logging
import os
import sys
from typing import Dict, Optional

# Add parent directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from app.core.config import get_settings  # noqa: E402
from app.services.feedback_service import FeedbackService  # noqa: E402
from app.utils.task_metrics import instrument_feedback_processing  # noqa: E402

# Configure logging
logging.basicConfig(level=logging.INFO)  # type: ignore[attr-defined]
logger = logging.getLogger(__name__)  # type: ignore[attr-defined]


@instrument_feedback_processing
async def main() -> Optional[Dict[str, int]]:
    """Main function to process feedback.

    Returns:
        Dict with metrics if successful (entries_processed), None otherwise
    """
    logger.info("Starting feedback processing")

    try:
        # Initialize settings and FeedbackService directly
        settings = get_settings()
        feedback_service = FeedbackService(settings)

        # Load feedback to count entries processed
        feedback = feedback_service.load_feedback()
        entries_processed = len(feedback)

        # Update weights and prompts based on feedback
        logger.info("Updating source weights based on feedback")
        await feedback_service.apply_feedback_weights_async()

        logger.info("Updating prompt guidance based on feedback")
        await feedback_service.update_prompt_based_on_feedback_async()

        logger.info(
            f"Feedback processing completed successfully. Processed {entries_processed} entries."
        )

        # Return metrics for Prometheus instrumentation
        return {"entries_processed": entries_processed}
    except Exception as e:
        logger.error(f"Error processing feedback: {str(e)}", exc_info=True)
        raise


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())

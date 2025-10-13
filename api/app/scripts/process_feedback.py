"""
Process user feedback to improve RAG system performance.
"""

import logging
import os
import sys

# Add parent directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from app.core.config import get_settings  # noqa: E402
from app.services.feedback_service import FeedbackService  # noqa: E402

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def main():
    """Main function to process feedback."""
    logger.info("Starting feedback processing")

    try:
        # Initialize settings and FeedbackService directly
        settings = get_settings()
        feedback_service = FeedbackService(settings)

        # Update weights and prompts based on feedback
        logger.info("Updating source weights based on feedback")
        await feedback_service.apply_feedback_weights_async()

        logger.info("Updating prompt guidance based on feedback")
        await feedback_service.update_prompt_based_on_feedback_async()

        logger.info("Feedback processing completed successfully")
    except Exception as e:
        logger.error(f"Error processing feedback: {str(e)}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())

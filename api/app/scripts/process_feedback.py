"""
Process user feedback to improve RAG system performance.
"""

import logging
import os
import sys

# Add parent directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from app.core.config import get_settings
from app.services.simplified_rag_service import SimplifiedRAGService

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def main():
    """Main function to process feedback."""
    logger.info("Starting feedback processing")

    try:
        # Initialize settings and RAG service
        settings = get_settings()
        service = SimplifiedRAGService(settings)

        # Process feedback to generate new FAQs
        logger.info("Generating new FAQs from feedback data")
        # Use async version if available, or run in executor
        await service.generate_feedback_faqs_async()

        # Update weights and prompts based on feedback
        logger.info("Updating source weights based on feedback")
        await service.apply_feedback_weights_async()

        logger.info("Updating prompt guidance based on feedback")
        await service.update_prompt_based_on_feedback_async()

        logger.info("Feedback processing completed successfully")
    except Exception as e:
        logger.error(f"Error processing feedback: {str(e)}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())

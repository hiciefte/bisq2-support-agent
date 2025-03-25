"""
Script to extract FAQs from Bisq support chat conversations.
Runs as a scheduled task to update the FAQ database.

This script is a thin wrapper around the FAQService class. It:
1. Fetches new support chat messages from the Bisq API
2. Processes these messages into conversation threads
3. Extracts FAQs using OpenAI
4. Saves the extracted FAQs to a JSONL file

For detailed documentation, see docs/faq_extraction.md.

Example usage:
    $ python -m app.scripts.extract_faqs

Environment variables:
    BISQ_API_URL: URL to the Bisq API (required)
    OPENAI_API_KEY: API key for OpenAI (required)
    OPENAI_MODEL: Model to use for FAQ extraction (default: o3-mini)
    DATA_DIR: Directory for data files (default: api/data)
"""

import logging
from asyncio import get_event_loop

from app.core.config import get_settings
from app.integrations.bisq_api import Bisq2API
from app.services.faq_service import FAQService

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


async def main(force_reprocess=False):
    """Run the FAQ extraction process using FAQService.
    
    This function orchestrates the full extraction process:
    1. Initialize the required services
    2. Fetch and process support chat messages
    3. Extract FAQs using OpenAI
    4. Save the results
    
    Args:
        force_reprocess: If True, ignores the processed_conv_ids and reprocesses all conversations.
            This is useful for regenerating FAQs after prompt improvements.
    
    Returns:
        None
    """
    try:
        # Get application settings
        settings = get_settings()
        
        # Initialize Bisq API for data fetching
        bisq_api = Bisq2API(settings)
        
        # Initialize the FAQ Service
        faq_service = FAQService(settings)
        
        # Clear processed conversation IDs if force_reprocess is True
        if force_reprocess:
            logger.info("Force reprocessing all conversations")
            faq_service.processed_conv_ids.clear()
        
        # Run the extraction process using the service
        logger.info("Starting FAQ extraction process...")
        new_faqs = await faq_service.extract_and_save_faqs(bisq_api)
        
        logger.info(f"FAQ extraction completed. Generated {len(new_faqs)} new FAQ entries.")
        
    except Exception as e:
        logger.error(f"Error during FAQ extraction: {str(e)}", exc_info=True)
        raise


if __name__ == "__main__":
    # Run the extraction process with force_reprocess set to False by default
    # To force reprocessing all conversations, run:
    # python -m app.scripts.extract_faqs force_reprocess=True
    force_reprocess = False
    
    loop = get_event_loop()
    try:
        loop.run_until_complete(main(force_reprocess=force_reprocess))
    finally:
        loop.close()

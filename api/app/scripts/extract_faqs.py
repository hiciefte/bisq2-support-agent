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
    $ python -m app.scripts.extract_faqs --force-reprocess

Environment variables:
    BISQ_API_URL: URL to the Bisq API (required)
    OPENAI_API_KEY: API key for OpenAI (required)
    OPENAI_MODEL: Model to use for FAQ extraction (default: openai:gpt-4o-mini)
    DATA_DIR: Directory for data files (default: api/data)
"""

import argparse
import asyncio
import logging
from asyncio import get_event_loop
from typing import Any, Dict, List, Optional

from app.core.config import get_settings
from app.integrations.bisq_api import Bisq2API
from app.services.faq_service import FAQService

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Constants for retry mechanism
MAX_RETRIES = 3
RETRY_DELAY = 5  # seconds
RETRY_BACKOFF_FACTOR = 2  # exponential backoff


async def main(force_reprocess=False) -> Optional[List[Dict[str, Any]]]:
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
        List of new FAQ entries if successful, None otherwise
    """
    retry_count = 0
    new_faqs = None
    last_error: Optional[Exception] = None

    while retry_count < MAX_RETRIES:
        try:
            # Get application settings
            settings = get_settings()

            # Initialize Bisq API for data fetching
            bisq_api = Bisq2API(settings)

            # Initialize the FAQ Service
            faq_service = FAQService(settings)

            # Run the extraction process using the service
            if retry_count > 0:
                logger.info(f"Retry attempt {retry_count}/{MAX_RETRIES}...")

            logger.info("Starting FAQ extraction process...")

            # Handle force reprocessing by temporarily clearing the processed conversation IDs
            if force_reprocess:
                logger.info("Force reprocessing all conversations")
                faq_service.processed_conv_ids = set()
                faq_service.save_processed_conv_ids()

            new_faqs = await faq_service.extract_and_save_faqs(bisq_api)

            logger.info(
                f"FAQ extraction completed. Generated {len(new_faqs)} new FAQ entries."
            )
            return new_faqs

        except (ConnectionError, TimeoutError, asyncio.TimeoutError) as e:
            # Transient network errors - good candidates for retry
            retry_count += 1
            last_error = e
            if retry_count < MAX_RETRIES:
                wait_time = RETRY_DELAY * (RETRY_BACKOFF_FACTOR ** (retry_count - 1))
                logger.warning(
                    f"Transient error occurred: {str(e)}. Retrying in {wait_time} seconds..."
                )
                await asyncio.sleep(wait_time)
            else:
                logger.error(
                    f"Max retries ({MAX_RETRIES}) exceeded. Last error: {str(e)}",
                    exc_info=True,
                )
                break

        except Exception as e:
            # For other exceptions, we'll retry once but log as error
            retry_count += 1
            last_error = e
            if retry_count < MAX_RETRIES:
                wait_time = RETRY_DELAY * (RETRY_BACKOFF_FACTOR ** (retry_count - 1))
                logger.error(
                    f"Error during FAQ extraction: {str(e)}. Retrying in {wait_time} seconds...",
                    exc_info=True,
                )
                await asyncio.sleep(wait_time)
            else:
                logger.error(
                    f"Max retries ({MAX_RETRIES}) exceeded. Last error: {str(e)}",
                    exc_info=True,
                )
                break

    # If we reached here, all retries failed
    if last_error:
        logger.error(
            f"FAQ extraction failed after {retry_count} attempts. Last error: {str(last_error)}",
            exc_info=True,
        )

    return None


if __name__ == "__main__":
    # Set up command line argument parsing
    parser = argparse.ArgumentParser(
        description="Extract FAQs from Bisq support chat conversations",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--force-reprocess",
        action="store_true",
        help="Reprocess all conversations, ignoring previously processed IDs",
    )
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    args = parser.parse_args()

    # Configure logging based on debug flag
    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)
        logger.debug("Debug logging enabled")

    # Run the extraction process
    loop = get_event_loop()
    try:
        loop.run_until_complete(main(force_reprocess=args.force_reprocess))
    finally:
        loop.close()

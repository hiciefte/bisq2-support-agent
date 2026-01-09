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
import json
import logging
from typing import Any, Dict, Optional

from app.core.config import get_settings
from app.integrations.bisq_api import Bisq2API
from app.services.faq_service import FAQService
from app.services.simplified_rag_service import SimplifiedRAGService
from app.services.wiki_service import WikiService
from app.utils.task_metrics import instrument_faq_extraction

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Constants for retry mechanism
MAX_RETRIES = 3
RETRY_DELAY = 5  # seconds
RETRY_BACKOFF_FACTOR = 2  # exponential backoff


@instrument_faq_extraction
async def main(force_reprocess=False) -> Optional[Dict[str, Any]]:
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
        Dict with metrics if successful (messages_processed, faqs_generated), None otherwise
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

            # Initialize RAG service for semantic duplicate detection (Phase 6)
            logger.info("Initializing RAG service for semantic duplicate detection...")
            wiki_service = WikiService(settings)
            rag_service = SimplifiedRAGService(
                settings=settings,
                wiki_service=wiki_service,
                faq_service=faq_service,  # Needed to load FAQs into vector store
            )
            # Initialize vector store for semantic duplicate checking
            await rag_service.setup()

            # Run the extraction process using the service
            if retry_count > 0:
                logger.info(f"Retry attempt {retry_count}/{MAX_RETRIES}...")

            logger.info("Starting FAQ extraction process...")

            # Handle force reprocessing by temporarily clearing the processed conversation IDs
            if force_reprocess:
                logger.info("Force reprocessing all conversations")
                faq_service.processed_conv_ids = set()
                faq_service.save_processed_conv_ids()

            # Track initial processed message count before extraction
            initial_processed_count = len(faq_service.load_processed_msg_ids())

            new_faqs = await faq_service.extract_and_save_faqs(bisq_api, rag_service)

            count = len(new_faqs) if new_faqs is not None else 0
            logger.info(f"FAQ extraction completed. Generated {count} new FAQ entries.")

            # Calculate newly processed messages from this run
            if not hasattr(faq_service, "processed_msg_ids"):
                raise AttributeError(
                    "FAQService missing 'processed_msg_ids' attribute after extraction"
                )
            final_processed_count = len(faq_service.processed_msg_ids)
            messages_processed = final_processed_count - initial_processed_count

            # Return metrics for Prometheus instrumentation
            return {"messages_processed": messages_processed, "faqs_generated": count}

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
        raise last_error

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
    parser.add_argument(
        "--json-output",
        action="store_true",
        help="Output metrics as JSON for easier parsing by bash scripts",
    )
    args = parser.parse_args()

    # Configure logging based on debug flag
    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)
        logger.debug("Debug logging enabled")

    # Run the extraction process
    result = asyncio.run(main(force_reprocess=args.force_reprocess))

    # Output metrics in JSON format if requested
    if args.json_output and result:
        print(json.dumps(result))
    elif result:
        # Default human-readable output for backward compatibility
        print(f"messages_processed: {result['messages_processed']}")
        print(f"faqs_generated: {result['faqs_generated']}")

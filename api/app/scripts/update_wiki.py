"""
Unified wrapper for wiki update process with Prometheus instrumentation.

This script orchestrates the complete wiki update workflow:
1. Download latest Bisq MediaWiki dump
2. Process the downloaded dump into clean JSONL format
3. Return metrics for Prometheus monitoring

The actual processing logic lives in download_bisq2_media_wiki.py and process_wiki_dump.py.
This wrapper provides unified metrics collection and error handling.
"""

import argparse
import asyncio
import json
import logging
import os
from typing import Dict, Optional

from app.scripts.download_bisq2_media_wiki import main as download_main
from app.scripts.process_wiki_dump import WikiDumpProcessor
from app.utils.task_metrics import instrument_wiki_update

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


@instrument_wiki_update
async def main() -> Optional[Dict[str, int]]:
    """
    Run the complete wiki update process with metrics collection.

    Returns:
        Dict with metrics if successful (pages_processed), None otherwise
    """
    try:
        # Get project root directory
        project_root = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "..")
        )
        wiki_data_dir = os.path.join(project_root, "data", "wiki")
        input_file = os.path.join(wiki_data_dir, "bisq2_dump.xml")
        output_file = os.path.join(wiki_data_dir, "processed_wiki.jsonl")

        # Step 1: Download latest wiki dump
        logger.info("Step 1: Downloading latest Bisq MediaWiki dump...")
        await asyncio.to_thread(download_main, output_dir=wiki_data_dir)
        logger.info("Wiki dump downloaded successfully")

        # Step 2: Process the dump
        logger.info("Step 2: Processing wiki dump...")
        if not os.path.exists(input_file):
            logger.error(f"Input file not found after download: {input_file}")
            raise FileNotFoundError(f"Wiki dump file not found: {input_file}")

        # Process with metrics collection
        processor = WikiDumpProcessor(str(input_file), str(output_file))

        # Run processing
        await asyncio.to_thread(processor.process_dump)

        # Calculate total pages processed from all categories
        pages_processed = sum(len(entries) for entries in processor.context.values())

        logger.info(f"Wiki update completed. Processed {pages_processed} pages.")

        # Return metrics for Prometheus instrumentation
        return {"pages_processed": pages_processed}

    except Exception as e:
        logger.error(f"Error during wiki update: {str(e)}", exc_info=True)
        raise


if __name__ == "__main__":
    # Set up command line argument parsing
    parser = argparse.ArgumentParser(
        description="Download and process Bisq MediaWiki dump",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--json-output",
        action="store_true",
        help="Output metrics as JSON for easier parsing by bash scripts",
    )
    args = parser.parse_args()

    # Run the wiki update process
    result = asyncio.run(main())

    # Output metrics in JSON format if requested
    if args.json_output and result:
        print(json.dumps(result))
    elif result:
        # Default human-readable output for backward compatibility
        print(f"pages_processed: {result['pages_processed']}")

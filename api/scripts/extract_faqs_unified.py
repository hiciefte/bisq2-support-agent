#!/usr/bin/env python3
"""
Extract FAQs from support chat messages using single-pass LLM extraction.

This script uses the UnifiedFAQExtractor for efficient FAQ extraction from
both Bisq 2 and Matrix chat exports. It provides:
- 98% reduction in API calls vs multi-pass approach
- 85% token reduction
- 95% cost savings (~$0.15/100 msgs vs ~$3.10/100 msgs)

Usage:
    python -m scripts.extract_faqs_unified <input_file> [--source bisq2|matrix]

Examples:
    # Extract from Bisq 2 messages
    python -m scripts.extract_faqs_unified data/sample_bisq2_messages.json --source bisq2

    # Extract from Matrix export
    python -m scripts.extract_faqs_unified ~/Downloads/matrix-export.json --source matrix
"""

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

import aisuite as ai  # type: ignore[import-untyped]

# Add api to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.core.config import Settings  # noqa: E402
from app.services.training.unified_faq_extractor import (  # noqa: E402
    FAQExtractionResult,
    UnifiedFAQExtractor,
)

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def load_messages(filepath: Path, source: str) -> list[dict]:
    """Load messages from JSON file.

    Args:
        filepath: Path to the JSON file
        source: "bisq2" or "matrix" to determine parsing format

    Returns:
        List of message dictionaries
    """
    with open(filepath) as f:
        data = json.load(f)

    if source == "bisq2":
        return data.get("messages", [])
    elif source == "matrix":
        # Matrix exports may have different structure
        messages = data.get("messages", data.get("chunk", []))
        # Filter to only m.room.message events
        return [msg for msg in messages if msg.get("type") == "m.room.message"]

    return data if isinstance(data, list) else data.get("messages", [])


def save_results(result: FAQExtractionResult, output_path: Path, source: str) -> None:
    """Save extraction results to JSON file.

    Args:
        result: The extraction result
        output_path: Where to save the results
        source: Source identifier
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)

    output = {
        "metadata": {
            "source": source,
            "total_messages": result.total_messages,
            "extracted_count": result.extracted_count,
            "processing_time_ms": result.processing_time_ms,
            "error": result.error,
        },
        "faqs": [
            {
                "question_text": faq.question_text,
                "answer_text": faq.answer_text,
                "question_msg_id": faq.question_msg_id,
                "answer_msg_id": faq.answer_msg_id,
                "confidence": faq.confidence,
                "has_correction": faq.has_correction,
            }
            for faq in result.faqs
        ],
        "pipeline_format": result.to_pipeline_format(),
    }

    with open(output_path, "w") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    logger.info(f"Saved {len(result.faqs)} FAQs to {output_path}")


def print_summary(result: FAQExtractionResult, source: str) -> None:
    """Print extraction summary to console."""
    print(f"\n{'='*60}")
    print("FAQ EXTRACTION SUMMARY")
    print(f"{'='*60}")
    print(f"Source: {source}")
    print(f"Total messages: {result.total_messages}")
    print(f"FAQs extracted: {result.extracted_count}")
    print(f"Processing time: {result.processing_time_ms}ms")

    if result.error:
        print(f"Error: {result.error}")

    corrections = sum(1 for faq in result.faqs if faq.has_correction)
    high_confidence = sum(1 for faq in result.faqs if faq.confidence >= 0.9)

    print("\nQuality metrics:")
    print(f"  High confidence (>=0.9): {high_confidence}")
    print(f"  With corrections: {corrections}")

    # Print sample FAQs
    if result.faqs:
        print(f"\n{'='*60}")
        print("SAMPLE EXTRACTED FAQs")
        print(f"{'='*60}")

        for i, faq in enumerate(result.faqs[:3]):
            print(f"\n--- FAQ {i+1} (confidence: {faq.confidence:.2f}) ---")
            print(f"Q: {faq.question_text[:150]}...")
            print(f"A: {faq.answer_text[:150]}...")
            if faq.has_correction:
                print("  [Contains correction - using final answer]")


async def main(
    input_file: str,
    source: str,
    output_file: str | None = None,
) -> FAQExtractionResult | None:
    """Run FAQ extraction pipeline.

    Args:
        input_file: Path to input JSON file
        source: "bisq2" or "matrix"
        output_file: Optional output path (defaults to data/extracted_faqs_{source}.json)

    Returns:
        FAQExtractionResult if successful
    """
    print(f"\n{'='*60}")
    print("UNIFIED FAQ EXTRACTOR")
    print(f"{'='*60}\n")

    # Initialize
    settings = Settings()
    aisuite_client = ai.Client()
    extractor = UnifiedFAQExtractor(
        aisuite_client=aisuite_client,
        settings=settings,
    )

    # Load messages
    input_path = Path(input_file)
    if not input_path.exists():
        logger.error(f"Input file not found: {input_path}")
        return None

    logger.info(f"Loading messages from {input_path}")
    messages = load_messages(input_path, source)
    logger.info(f"Loaded {len(messages)} messages")

    if not messages:
        logger.error("No messages found in input file")
        return None

    # Extract FAQs
    logger.info("Extracting FAQs using single-pass LLM extraction...")
    result = await extractor.extract_faqs(messages=messages, source=source)

    # Print summary
    print_summary(result, source)

    # Save results
    if output_file:
        output_path = Path(output_file)
    else:
        data_dir = Path(__file__).parent.parent / "data"
        output_path = data_dir / f"extracted_faqs_{source}.json"

    save_results(result, output_path, source)

    print(f"\n{'='*60}")
    print(f"Done! Results saved to: {output_path}")
    print(f"{'='*60}\n")

    return result


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Extract FAQs from support chat messages using single-pass LLM extraction"
    )
    parser.add_argument(
        "input_file",
        help="Path to input JSON file (Bisq 2 or Matrix export)",
    )
    parser.add_argument(
        "--source",
        choices=["bisq2", "matrix"],
        default="bisq2",
        help="Source format (default: bisq2)",
    )
    parser.add_argument(
        "--output",
        "-o",
        help="Output file path (default: data/extracted_faqs_{source}.json)",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    asyncio.run(main(args.input_file, args.source, args.output))

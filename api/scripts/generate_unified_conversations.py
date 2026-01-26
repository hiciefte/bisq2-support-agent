#!/usr/bin/env python3
"""
Generate unified conversation output from sample Bisq 2 messages.

This script demonstrates the unified multi-turn conversation pipeline
by loading sample messages and extracting conversations using the
ConversationHandler's unified extraction capability.

Usage:
    python -m scripts.generate_unified_conversations
"""

import json
import logging
from pathlib import Path

from app.services.training.conversation_handler import ConversationHandler

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Known staff IDs from Bisq 2 support (usernames)
BISQ2_STAFF_IDS = {
    "suddenwhipvapor",  # Main support moderator
    "strayorigin",  # Support staff
}


def load_bisq2_sample_messages(filepath: Path) -> list[dict]:
    """Load sample Bisq 2 messages from JSON file."""
    with open(filepath) as f:
        data = json.load(f)
    return data.get("messages", [])


def save_conversations(conversations: list[dict], output_path: Path) -> None:
    """Save extracted conversations to JSON file."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(conversations, f, indent=2, default=str)
    logger.info(f"Saved {len(conversations)} conversations to {output_path}")


def main() -> None:
    """Run the unified conversation extraction pipeline."""
    # Paths
    data_dir = Path(__file__).parent.parent / "data"
    bisq2_sample_path = data_dir / "sample_bisq2_messages.json"
    output_path = data_dir / "unified_conversations_output.json"

    # Initialize handler
    handler = ConversationHandler()

    # Load Bisq 2 sample messages
    if not bisq2_sample_path.exists():
        logger.error(f"Sample file not found: {bisq2_sample_path}")
        return

    logger.info(f"Loading messages from {bisq2_sample_path}")
    bisq2_messages = load_bisq2_sample_messages(bisq2_sample_path)
    logger.info(f"Loaded {len(bisq2_messages)} Bisq 2 messages")

    # Extract conversations using unified pipeline (with temporal proximity)
    logger.info("Extracting conversations using unified pipeline...")
    logger.info(
        f"Temporal proximity threshold: {handler.temporal_proximity_threshold_ms}ms (5 minutes)"
    )
    conversations = handler.extract_conversations_unified(
        messages=bisq2_messages,
        source="bisq2",
        staff_ids=BISQ2_STAFF_IDS,
        apply_temporal_proximity=True,  # Enable temporal proximity grouping
    )

    # Print summary
    logger.info(f"\n{'='*60}")
    logger.info("EXTRACTION SUMMARY")
    logger.info(f"{'='*60}")
    logger.info(f"Total messages: {len(bisq2_messages)}")
    logger.info(f"Extracted conversations: {len(conversations)}")

    multi_turn = sum(1 for c in conversations if c["is_multi_turn"])
    corrections = sum(1 for c in conversations if c["has_correction"])

    logger.info(f"Multi-turn conversations: {multi_turn}")
    logger.info(f"Conversations with corrections: {corrections}")

    # Print first few conversations for review
    logger.info(f"\n{'='*60}")
    logger.info("SAMPLE EXTRACTED CONVERSATIONS")
    logger.info(f"{'='*60}")

    for i, conv in enumerate(conversations[:5]):
        logger.info(f"\n--- Conversation {i+1} ---")
        logger.info(f"Source: {conv['source']}")
        logger.info(f"Messages: {conv['message_count']}")
        logger.info(f"Multi-turn: {conv['is_multi_turn']}")
        logger.info(f"Has correction: {conv['has_correction']}")
        logger.info(f"Question: {conv['question_text'][:100]}...")
        answer = conv["staff_answer"] or ""
        logger.info(f"Answer: {answer[:100]}...")

    # Save to output file
    # Convert messages to serializable format (remove complex objects)
    output_conversations = []
    for conv in conversations:
        output_conv = {
            "source": conv["source"],
            "conversation_id": conv["conversation_id"],
            "question_text": conv["question_text"],
            "staff_answer": conv["staff_answer"],
            "message_count": conv["message_count"],
            "is_multi_turn": conv["is_multi_turn"],
            "has_correction": conv["has_correction"],
        }
        output_conversations.append(output_conv)

    save_conversations(output_conversations, output_path)

    logger.info(f"\n{'='*60}")
    logger.info("Done! Review the output at:")
    logger.info(f"  {output_path}")


if __name__ == "__main__":
    main()

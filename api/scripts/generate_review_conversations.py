#!/usr/bin/env python3
"""
Generate conversation outputs for manual review from both Bisq 2 and Matrix sources.

This script uses the unified multi-turn conversation pipeline to extract
conversations with temporal proximity grouping enabled, producing outputs
that can be manually verified for quality improvement.

Output files:
- data/sample_bisq2_conversations_review.json
- data/sample_matrix_conversations_review.json

Usage:
    python -m scripts.generate_review_conversations
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from app.services.training.conversation_handler import ConversationHandler

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Known staff IDs
BISQ2_STAFF_IDS = {
    "suddenwhipvapor",
    "strayorigin",
}

MATRIX_STAFF_IDS = {
    "@suddenwhipvapor:matrix.org",
    "@strayorigin:matrix.org",
    "@mwithm:matrix.org",
    "@pazza83:matrix.org",
    "@luis3672:matrix.org",
    "@darawhelan:matrix.org",
}


def load_bisq2_messages(filepath: Path) -> list[dict]:
    """Load Bisq 2 messages from JSON file."""
    with open(filepath) as f:
        data = json.load(f)
    return data.get("messages", [])


def load_matrix_messages(filepath: Path) -> list[dict]:
    """Load Matrix messages (only m.room.message type)."""
    with open(filepath) as f:
        data = json.load(f)
    return [
        msg for msg in data.get("messages", []) if msg.get("type") == "m.room.message"
    ]


def format_conversation_for_review(
    conv: dict[str, Any], index: int, source: str
) -> dict[str, Any]:
    """Format a conversation for human review with additional context.

    Returns a dict with:
    - review_id: Sequential ID for easy reference
    - source: bisq2 or matrix
    - conversation_id: Original ID from the pipeline
    - message_count: Number of messages in the conversation
    - is_multi_turn: Whether it has more than 2 messages
    - has_correction: Whether a correction was detected
    - grouping_method: How the messages were grouped (linked/temporal/single)
    - question_text: The extracted question(s)
    - staff_answer: The final staff answer
    - raw_messages: List of individual messages for detailed review
    - review_status: Placeholder for manual review (pending/approved/needs_improvement)
    - review_notes: Placeholder for reviewer comments
    """
    # Determine grouping method
    messages = conv.get("messages", [])
    has_linked = False
    for msg in messages:
        content = msg.get("content", {})
        if isinstance(content, dict):
            relates_to = content.get("m.relates_to", {})
            in_reply_to = relates_to.get("m.in_reply_to", {})
            if in_reply_to.get("event_id"):
                has_linked = True
                break

    if len(messages) == 1:
        grouping_method = "single_message"
    elif has_linked:
        grouping_method = "linked_reply_chain"
    else:
        grouping_method = "temporal_proximity"

    # Format raw messages for review
    raw_messages = []
    for msg in messages:
        content = msg.get("content", {})
        if isinstance(content, dict):
            body = content.get("body", "")
        else:
            body = str(content)

        raw_messages.append(
            {
                "event_id": msg.get("event_id", ""),
                "sender": msg.get("sender", ""),
                "text": body,
                "timestamp": msg.get("origin_server_ts", 0),
                "has_reply_link": bool(
                    isinstance(content, dict)
                    and content.get("m.relates_to", {})
                    .get("m.in_reply_to", {})
                    .get("event_id")
                ),
            }
        )

    return {
        "review_id": f"{source}_{index + 1:03d}",
        "source": source,
        "conversation_id": conv.get("conversation_id", ""),
        "message_count": conv.get("message_count", 0),
        "is_multi_turn": conv.get("is_multi_turn", False),
        "has_correction": conv.get("has_correction", False),
        "grouping_method": grouping_method,
        "question_text": conv.get("question_text", ""),
        "staff_answer": conv.get("staff_answer", ""),
        "raw_messages": raw_messages,
        "review_status": "pending",
        "review_notes": "",
    }


def generate_review_output(
    handler: ConversationHandler,
    messages: list[dict],
    source: str,
    staff_ids: set[str],
    output_path: Path,
) -> dict[str, Any]:
    """Generate review output for a single source."""
    logger.info(f"Processing {len(messages)} {source} messages...")

    # Extract with temporal proximity enabled
    conversations = handler.extract_conversations_unified(
        messages=messages,
        source=source,
        staff_ids=staff_ids,
        apply_temporal_proximity=True,
    )

    logger.info(f"Extracted {len(conversations)} conversations from {source}")

    # Format for review
    review_conversations = [
        format_conversation_for_review(conv, i, source)
        for i, conv in enumerate(conversations)
    ]

    # Calculate statistics
    multi_turn_count = sum(1 for c in review_conversations if c["is_multi_turn"])
    correction_count = sum(1 for c in review_conversations if c["has_correction"])
    grouping_stats = {}
    for c in review_conversations:
        method = c["grouping_method"]
        grouping_stats[method] = grouping_stats.get(method, 0) + 1

    # Build output
    output = {
        "metadata": {
            "source": source,
            "generated_at": datetime.now().isoformat(),
            "extraction_method": "unified_pipeline_with_temporal_proximity",
            "temporal_proximity_threshold_ms": handler.temporal_proximity_threshold_ms,
            "total_input_messages": len(messages),
            "total_conversations": len(conversations),
        },
        "statistics": {
            "multi_turn_conversations": multi_turn_count,
            "conversations_with_corrections": correction_count,
            "grouping_methods": grouping_stats,
        },
        "conversations": review_conversations,
    }

    # Save
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(output, f, indent=2, ensure_ascii=False, default=str)

    logger.info(f"Saved review output to {output_path}")

    return output


def print_summary(source: str, output: dict[str, Any]) -> None:
    """Print a summary of the extraction results."""
    metadata = output["metadata"]
    stats = output["statistics"]

    print(f"\n{'='*60}")
    print(f"  {source.upper()} EXTRACTION SUMMARY")
    print(f"{'='*60}")
    print(f"  Input messages:           {metadata['total_input_messages']}")
    print(f"  Conversations extracted:  {metadata['total_conversations']}")
    print(f"  Multi-turn conversations: {stats['multi_turn_conversations']}")
    print(f"  With corrections:         {stats['conversations_with_corrections']}")
    print("  Grouping methods:")
    for method, count in stats["grouping_methods"].items():
        print(f"    - {method}: {count}")
    print(f"{'='*60}\n")


def main() -> None:
    """Run the review conversation generation."""
    # Paths
    data_dir = Path(__file__).parent.parent / "data"
    bisq2_input = data_dir / "sample_bisq2_messages.json"
    matrix_input = data_dir / "sample_matrix_messages.json"
    bisq2_output = data_dir / "sample_bisq2_conversations_review.json"
    matrix_output = data_dir / "sample_matrix_conversations_review.json"

    # Initialize handler
    handler = ConversationHandler()
    logger.info(
        f"Temporal proximity threshold: {handler.temporal_proximity_threshold_ms}ms "
        f"({handler.temporal_proximity_threshold_ms / 1000 / 60:.1f} minutes)"
    )

    # Process Bisq 2 messages
    if bisq2_input.exists():
        bisq2_messages = load_bisq2_messages(bisq2_input)
        bisq2_result = generate_review_output(
            handler=handler,
            messages=bisq2_messages,
            source="bisq2",
            staff_ids=BISQ2_STAFF_IDS,
            output_path=bisq2_output,
        )
        print_summary("Bisq 2", bisq2_result)
    else:
        logger.warning(f"Bisq 2 input not found: {bisq2_input}")

    # Process Matrix messages
    if matrix_input.exists():
        matrix_messages = load_matrix_messages(matrix_input)
        matrix_result = generate_review_output(
            handler=handler,
            messages=matrix_messages,
            source="matrix",
            staff_ids=MATRIX_STAFF_IDS,
            output_path=matrix_output,
        )
        print_summary("Matrix", matrix_result)
    else:
        logger.warning(f"Matrix input not found: {matrix_input}")

    # Print review instructions
    print("\n" + "=" * 60)
    print("  REVIEW INSTRUCTIONS")
    print("=" * 60)
    print("""
To review the generated conversations:

1. Open the output files:
   - data/sample_bisq2_conversations_review.json
   - data/sample_matrix_conversations_review.json

2. For each conversation, check:
   - Is the question_text correctly extracted?
   - Is the staff_answer the correct final response?
   - Did the grouping_method make sense?
   - For corrections, was the right answer selected?

3. Update review_status to:
   - "approved" if correct
   - "needs_improvement" if there are issues

4. Add review_notes explaining any problems

5. Common issues to look for:
   - Orphan messages incorrectly grouped
   - Multi-turn conversations missing messages
   - Wrong answer selected (should be final/corrected)
   - Question context missing important follow-ups
""")


if __name__ == "__main__":
    main()

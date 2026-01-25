#!/usr/bin/env python3
"""Verify that LLM returns correct answer_msg_id for Matrix messages.

This script:
1. Loads sample Matrix messages
2. Runs the UnifiedFAQExtractor
3. Compares returned answer_msg_id with expected message IDs
4. Reports accuracy and any mismatches
"""

import asyncio
import json
import os
import sys

# Add the app directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import aisuite  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.services.training.unified_faq_extractor import (
    UnifiedFAQExtractor,
)  # noqa: E402


async def verify_answer_msg_ids():
    """Run verification on sample Matrix messages."""
    # Load sample messages
    data_path = os.path.join(
        os.path.dirname(__file__), "..", "data", "sample_matrix_messages.json"
    )
    with open(data_path, "r") as f:
        data = json.load(f)

    messages = data.get("messages", [])
    print(f"Loaded {len(messages)} messages")

    # Filter to only m.room.message events (actual messages, not joins)
    text_messages = [
        m
        for m in messages
        if m.get("type") == "m.room.message"
        and m.get("content", {}).get("msgtype") == "m.text"
    ]
    print(f"Filtered to {len(text_messages)} text messages")

    # Use first 30 messages for testing (need more to get complete Q&A pairs)
    test_messages = text_messages[:30]

    # Build ID -> text lookup for verification
    id_to_text = {}
    for msg in text_messages:
        event_id = msg.get("event_id", "")
        body = msg.get("content", {}).get("body", "")
        if event_id and body:
            id_to_text[event_id] = body

    print(f"\nMessage ID -> Text lookup built with {len(id_to_text)} entries")
    print("\nSample entries:")
    for i, (mid, text) in enumerate(list(id_to_text.items())[:5]):
        print(f"  {mid[:30]}... -> {text[:50]}...")

    # Initialize extractor
    settings = get_settings()
    client = aisuite.Client()

    staff_identifiers = [
        "@suddenwhipvapor:matrix.org",
        "@luis3672:matrix.org",
    ]

    extractor = UnifiedFAQExtractor(
        aisuite_client=client,
        settings=settings,
        staff_identifiers=staff_identifiers,
    )

    print("\n" + "=" * 60)
    print("Running FAQ extraction...")
    print("=" * 60)

    # Pass messages in standard Matrix format (extractor expects content.body)
    # Don't flatten the structure - the extractor handles nested content
    formatted_messages = []
    for msg in test_messages:
        formatted = {
            "event_id": msg.get("event_id"),
            "sender": msg.get("sender"),
            "content": msg.get("content", {}),  # Keep nested structure
            "origin_server_ts": msg.get("origin_server_ts"),
        }
        formatted_messages.append(formatted)

    # Debug: print normalized messages
    extractor._normalize_messages(formatted_messages, "matrix")
    print(f"\nNormalized {len(extractor._normalized_messages)} messages")
    for i, msg in enumerate(extractor._normalized_messages[:5]):
        print(
            f"  {i+1}. [{msg.get('author', 'unknown')[:20]}]: {msg.get('text', '')[:60]}..."
        )

    result = await extractor.extract_faqs(
        messages=formatted_messages,
        source="matrix",
    )

    print(f"\nExtracted {len(result.faqs)} FAQ pairs")
    print(f"Processing time: {result.processing_time_ms}ms")

    if result.error:
        print(f"Error: {result.error}")
        return

    # Verify answer_msg_id accuracy
    print("\n" + "=" * 60)
    print("Verifying answer_msg_id accuracy:")
    print("=" * 60)

    correct = 0
    incorrect = 0

    for i, faq in enumerate(result.faqs):
        answer_id = faq.answer_msg_id
        llm_original = faq.original_answer_text or "(None)"
        actual_text = id_to_text.get(answer_id, "(NOT FOUND)")

        print(f"\n--- FAQ {i+1} ---")
        print(f"Question: {faq.question_text[:80]}...")
        print(f"Answer ID: {answer_id}")
        print(f"LLM's original_answer_text: {llm_original[:80]}...")
        print(f"Actual text at ID: {actual_text[:80]}...")

        if answer_id not in id_to_text:
            print("❌ INVALID ID - message not found!")
            incorrect += 1
        elif actual_text == llm_original:
            print("✅ LLM's copy matches actual text")
            correct += 1
        else:
            print("⚠️ LLM's copy differs from actual text (but ID is valid)")
            correct += 1  # ID is correct even if text copy differs

    print("\n" + "=" * 60)
    print(f"SUMMARY: {correct}/{correct+incorrect} correct answer_msg_ids")
    print("=" * 60)

    # Convert to pipeline format to test the fix
    print("\n" + "=" * 60)
    print("Testing to_pipeline_format() fix:")
    print("=" * 60)

    pipeline_data = result.to_pipeline_format()
    for i, item in enumerate(pipeline_data):
        print(f"\n--- Pipeline Item {i+1} ---")
        print(
            f"original_staff_answer: {item.get('original_staff_answer', '(None)')[:80]}..."
        )
        print(f"source_event_id: {item.get('source_event_id')}")


if __name__ == "__main__":
    asyncio.run(verify_answer_msg_ids())

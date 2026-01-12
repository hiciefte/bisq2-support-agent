#!/usr/bin/env python3
"""Test script to verify Matrix message classification improvements."""

import asyncio
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.services.shadow_mode_processor import ShadowModeProcessor  # noqa: E402

# Sample Matrix messages from previous production data
SAMPLE_MESSAGES = [
    # TRUE POSITIVES (Should be accepted as questions)
    {
        "sender": "@user1:matrix.org",
        "body": "Have been restarting and resyncing for 6 hours, and my bsq-wallet is still empty",
    },
    {
        "sender": "@user2:matrix.org",
        "body": "Hello, if I only use the Bisq daemon, how can I check if the DAO is synchronized?",
    },
    {
        "sender": "@user3:matrix.org",
        "body": "I performed a BSQ Swap, but I can't see any BSQ anywhere in my wallet",
    },
    {
        "sender": "@user4:matrix.org",
        "body": "I'm getting this error with my offers when someone tries to accept them",
    },
    {
        "sender": "@user5:matrix.org",
        "body": "Hi, I moved my bisq to another computer. It seems okay, but I don't see any offers",
    },
    # FALSE POSITIVES (Should be filtered out)
    {
        "sender": "@pazza83:matrix.org",
        "body": "If there is an issue with the seed nodes it can prevent traders from seeing offers",
    },
    {
        "sender": "@suddenwhipvapor:matrix.org",
        "body": "Are seeing no offers in any market or just specific ones?",
    },
    {
        "sender": "@strayorigin:matrix.org",
        "body": "Sometimes if the pricenodes are off then the error can also appear",
    },
    {
        "sender": "@user6:matrix.org",
        "body": "alrighty no problem, i was tryna make an offer",
    },
    {
        "sender": "@user7:matrix.org",
        "body": "Scammers set up similar names to support agents and monitor this chat",
    },
    {
        "sender": "@user8:matrix.org",
        "body": "https://bisq.community/t/psa-ongoing-dao-sync-issue/13399/3",
    },
    {
        "sender": "@pazza83:matrix.org",
        "body": "You can also check your logs at the time the offer was taken",
    },
    {
        "sender": "@user9:matrix.org",
        "body": "Indeed, I don't have that problem at the moment.",
    },
]


async def test_classification():
    """Test message classification with sample data."""
    print("\n" + "=" * 80)
    print("MATRIX MESSAGE CLASSIFICATION TEST")
    print("=" * 80)
    print(f"\nTesting {len(SAMPLE_MESSAGES)} sample messages from production data\n")

    # Statistics
    accepted_count = 0
    filtered_count = 0
    true_positives = 0
    false_positives = 0
    true_negatives = 0
    false_negatives = 0

    # Expected results (ground truth)
    expected_questions = 5  # First 5 messages are genuine questions
    expected_filtered = 8  # Last 8 messages should be filtered

    print("Classification Results:")
    print("-" * 80)

    for i, msg in enumerate(SAMPLE_MESSAGES, 1):
        sender = msg["sender"]
        body = msg["body"]
        is_expected_question = i <= expected_questions

        # Test classification
        is_question = ShadowModeProcessor.is_support_question(body, sender=sender)

        # Determine result type
        if is_question:
            accepted_count += 1
            result = "✅ ACCEPTED"
            if is_expected_question:
                true_positives += 1
                correctness = "✓ Correct (TP)"
            else:
                false_positives += 1
                correctness = "✗ ERROR (FP)"
        else:
            filtered_count += 1
            result = "❌ FILTERED"
            if not is_expected_question:
                true_negatives += 1
                correctness = "✓ Correct (TN)"
            else:
                false_negatives += 1
                correctness = "✗ ERROR (FN)"

        # Display result
        sender_short = sender.split(":")[0]
        body_preview = body[:60] + "..." if len(body) > 60 else body
        print(f"{i:2d}. {result} - {correctness}")
        print(f"    From: {sender_short}")
        print(f"    Text: {body_preview}")
        print()

    # Summary statistics
    print("=" * 80)
    print("SUMMARY STATISTICS")
    print("=" * 80)

    total = len(SAMPLE_MESSAGES)
    accuracy = ((true_positives + true_negatives) / total) * 100

    if (true_positives + false_positives) > 0:
        precision = (true_positives / (true_positives + false_positives)) * 100
    else:
        precision = 0

    if (true_positives + false_negatives) > 0:
        recall = (true_positives / (true_positives + false_negatives)) * 100
    else:
        recall = 0

    if (precision + recall) > 0:
        f1_score = 2 * (precision * recall) / (precision + recall)
    else:
        f1_score = 0

    print("\nConfusion Matrix:")
    print(f"  True Positives (Correct questions):     {true_positives:2d}")
    print(f"  True Negatives (Correct filtering):     {true_negatives:2d}")
    print(f"  False Positives (Incorrectly accepted): {false_positives:2d}")
    print(f"  False Negatives (Incorrectly filtered): {false_negatives:2d}")

    print("\nPerformance Metrics:")
    print(
        f"  Accuracy:  {accuracy:.1f}% ({true_positives + true_negatives}/{total} correct)"
    )
    print(
        f"  Precision: {precision:.1f}% (of accepted, {true_positives}/{true_positives + false_positives} were questions)"
    )
    print(
        f"  Recall:    {recall:.1f}% (of questions, {true_positives}/{true_positives + false_negatives} were found)"
    )
    print(f"  F1 Score:  {f1_score:.1f}%")

    print("\nMessage Flow:")
    print(f"  Total messages:     {total}")
    print(
        f"  Accepted (questions): {accepted_count} ({(accepted_count/total)*100:.1f}%)"
    )
    print(
        f"  Filtered (non-questions): {filtered_count} ({(filtered_count/total)*100:.1f}%)"
    )

    print("\nExpected vs Actual:")
    print(f"  Expected questions: {expected_questions}")
    print(f"  Actual questions:   {accepted_count}")
    print(f"  Expected filtered:  {expected_filtered}")
    print(f"  Actual filtered:    {filtered_count}")

    # Compare to baseline
    baseline_fp_rate = 67.0  # 67% false positive rate before
    current_fp_rate = (
        (false_positives / expected_filtered * 100) if expected_filtered > 0 else 0
    )
    improvement = baseline_fp_rate - current_fp_rate

    print("\nImprovement vs Baseline:")
    print(f"  Baseline FP rate: {baseline_fp_rate:.1f}%")
    print(f"  Current FP rate:  {current_fp_rate:.1f}%")
    print(f"  Improvement:      {improvement:.1f}% reduction")

    # Status
    print("\n" + "=" * 80)
    if accuracy >= 85 and precision >= 85:
        print("✅ TEST PASSED - Classifier performing as expected!")
    elif accuracy >= 70 and precision >= 70:
        print("⚠️  TEST PARTIALLY PASSED - Acceptable performance, room for improvement")
    else:
        print("❌ TEST FAILED - Classifier needs tuning")
    print("=" * 80 + "\n")

    return accuracy >= 70


if __name__ == "__main__":
    result = asyncio.run(test_classification())
    sys.exit(0 if result else 1)

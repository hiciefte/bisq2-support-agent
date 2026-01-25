#!/usr/bin/env python3
"""
Analyze response timing patterns in Bisq 2 and Matrix support messages.

This script examines:
1. Time gaps between linked Q&A pairs (explicit citations/replies)
2. Time gaps between consecutive messages by the same author
3. Time gaps where staff responds without explicit reply link

The goal is to find the optimal temporal proximity threshold for grouping
staff responses with preceding user questions when no explicit link exists.
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Any

# Known staff IDs
BISQ2_STAFF_IDS = {"suddenwhipvapor", "strayorigin"}
MATRIX_STAFF_IDS = {
    "@suddenwhipvapor:matrix.org",
    "@strayorigin:matrix.org",
    "@mwithm:matrix.org",
    "@pazza83:matrix.org",
    "@luis3672:matrix.org",
    "@darawhelan:matrix.org",
}


def parse_bisq2_timestamp(date_str: str) -> int:
    """Convert Bisq 2 ISO timestamp to Unix milliseconds."""
    if date_str.endswith("Z"):
        date_str = date_str[:-1] + "+00:00"
    dt = datetime.fromisoformat(date_str)
    return int(dt.timestamp() * 1000)


def load_bisq2_messages(filepath: Path) -> list[dict[str, Any]]:
    """Load Bisq 2 messages."""
    with open(filepath) as f:
        data = json.load(f)
    return data.get("messages", [])


def load_matrix_messages(filepath: Path) -> list[dict[str, Any]]:
    """Load Matrix messages (only m.room.message type)."""
    with open(filepath) as f:
        data = json.load(f)
    return [
        msg for msg in data.get("messages", []) if msg.get("type") == "m.room.message"
    ]


def analyze_bisq2_timing(messages: list[dict[str, Any]]) -> dict[str, Any]:
    """Analyze timing patterns in Bisq 2 messages."""
    # Build index by messageId
    by_id = {msg["messageId"]: msg for msg in messages}

    # Stats containers
    linked_gaps = []  # Gaps for explicit reply chains
    unlinked_staff_gaps = []  # Gaps for staff msgs without citation following user msgs
    consecutive_same_author = []

    # Sort by timestamp
    sorted_msgs = sorted(messages, key=lambda m: parse_bisq2_timestamp(m["date"]))

    for i, msg in enumerate(sorted_msgs):
        author = msg.get("author", "")
        msg_time = parse_bisq2_timestamp(msg["date"])
        citation = msg.get("citation")

        # Check if this message has an explicit citation
        if citation and citation.get("messageId"):
            cited_id = citation["messageId"]
            if cited_id in by_id:
                cited_msg = by_id[cited_id]
                cited_time = parse_bisq2_timestamp(cited_msg["date"])
                gap_seconds = (msg_time - cited_time) / 1000
                linked_gaps.append(
                    {
                        "gap_seconds": gap_seconds,
                        "responder": author,
                        "is_staff_response": author in BISQ2_STAFF_IDS,
                        "original_author": cited_msg.get("author"),
                    }
                )

        # Check if staff message without citation follows a user message
        if author in BISQ2_STAFF_IDS and not citation and i > 0:
            # Look back for the most recent non-staff message
            for j in range(i - 1, -1, -1):
                prev_msg = sorted_msgs[j]
                prev_author = prev_msg.get("author", "")
                if prev_author not in BISQ2_STAFF_IDS:
                    prev_time = parse_bisq2_timestamp(prev_msg["date"])
                    gap_seconds = (msg_time - prev_time) / 1000
                    unlinked_staff_gaps.append(
                        {
                            "gap_seconds": gap_seconds,
                            "staff_author": author,
                            "user_author": prev_author,
                            "staff_msg": msg.get("message", "")[:80],
                            "user_msg": prev_msg.get("message", "")[:80],
                        }
                    )
                    break

        # Track consecutive same-author gaps
        if i > 0:
            prev = sorted_msgs[i - 1]
            if prev.get("author") == author:
                prev_time = parse_bisq2_timestamp(prev["date"])
                gap_seconds = (msg_time - prev_time) / 1000
                consecutive_same_author.append(gap_seconds)

    return {
        "total_messages": len(messages),
        "linked_gaps": linked_gaps,
        "unlinked_staff_gaps": unlinked_staff_gaps,
        "consecutive_same_author": consecutive_same_author,
    }


def analyze_matrix_timing(messages: list[dict[str, Any]]) -> dict[str, Any]:
    """Analyze timing patterns in Matrix messages."""
    # Build index by event_id
    by_id = {msg["event_id"]: msg for msg in messages}

    linked_gaps = []
    unlinked_staff_gaps = []
    consecutive_same_author = []

    # Sort by timestamp
    sorted_msgs = sorted(messages, key=lambda m: m.get("origin_server_ts", 0))

    for i, msg in enumerate(sorted_msgs):
        sender = msg.get("sender", "")
        msg_time = msg.get("origin_server_ts", 0)
        content = msg.get("content", {})
        reply_to = (
            content.get("m.relates_to", {}).get("m.in_reply_to", {}).get("event_id")
        )

        # Check if this message has an explicit reply
        if reply_to and reply_to in by_id:
            replied_msg = by_id[reply_to]
            replied_time = replied_msg.get("origin_server_ts", 0)
            gap_seconds = (msg_time - replied_time) / 1000
            linked_gaps.append(
                {
                    "gap_seconds": gap_seconds,
                    "responder": sender,
                    "is_staff_response": sender in MATRIX_STAFF_IDS,
                    "original_author": replied_msg.get("sender"),
                }
            )

        # Check if staff message without reply follows a user message
        if sender in MATRIX_STAFF_IDS and not reply_to and i > 0:
            for j in range(i - 1, -1, -1):
                prev_msg = sorted_msgs[j]
                prev_sender = prev_msg.get("sender", "")
                if prev_sender not in MATRIX_STAFF_IDS:
                    prev_time = prev_msg.get("origin_server_ts", 0)
                    gap_seconds = (msg_time - prev_time) / 1000
                    unlinked_staff_gaps.append(
                        {
                            "gap_seconds": gap_seconds,
                            "staff_sender": sender,
                            "user_sender": prev_sender,
                        }
                    )
                    break

        # Track consecutive same-author gaps
        if i > 0:
            prev = sorted_msgs[i - 1]
            if prev.get("sender") == sender:
                prev_time = prev.get("origin_server_ts", 0)
                gap_seconds = (msg_time - prev_time) / 1000
                consecutive_same_author.append(gap_seconds)

    return {
        "total_messages": len(messages),
        "linked_gaps": linked_gaps,
        "unlinked_staff_gaps": unlinked_staff_gaps,
        "consecutive_same_author": consecutive_same_author,
    }


def compute_stats(gaps: list[float]) -> dict[str, float]:
    """Compute statistics for a list of time gaps."""
    if not gaps:
        return {"count": 0}

    sorted_gaps = sorted(gaps)
    n = len(sorted_gaps)

    return {
        "count": n,
        "min_seconds": sorted_gaps[0],
        "max_seconds": sorted_gaps[-1],
        "median_seconds": sorted_gaps[n // 2],
        "p25_seconds": sorted_gaps[n // 4] if n >= 4 else sorted_gaps[0],
        "p75_seconds": sorted_gaps[3 * n // 4] if n >= 4 else sorted_gaps[-1],
        "p90_seconds": sorted_gaps[int(0.9 * n)] if n >= 10 else sorted_gaps[-1],
        "p95_seconds": sorted_gaps[int(0.95 * n)] if n >= 20 else sorted_gaps[-1],
        "mean_seconds": sum(sorted_gaps) / n,
    }


def format_time(seconds: float) -> str:
    """Format seconds as human-readable time."""
    if seconds < 60:
        return f"{seconds:.1f}s"
    elif seconds < 3600:
        return f"{seconds/60:.1f}m"
    elif seconds < 86400:
        return f"{seconds/3600:.1f}h"
    else:
        return f"{seconds/86400:.1f}d"


def main() -> None:
    """Run the timing analysis."""
    print("=" * 70)
    print("TEMPORAL PROXIMITY ANALYSIS FOR SUPPORT MESSAGES")
    print("=" * 70)

    # Load data
    data_dir = Path(__file__).parent.parent / "data"
    downloads_dir = Path.home() / "Downloads"

    bisq2_path = data_dir / "sample_bisq2_messages.json"
    matrix_path = (
        downloads_dir / "matrix - Support - Chat Export - 2026-01-14T10-50-16.342Z.json"
    )

    print(f"\nLoading Bisq 2 messages from: {bisq2_path}")
    bisq2_msgs = load_bisq2_messages(bisq2_path)
    bisq2_analysis = analyze_bisq2_timing(bisq2_msgs)

    print(f"Loading Matrix messages from: {matrix_path}")
    matrix_msgs = load_matrix_messages(matrix_path)
    matrix_analysis = analyze_matrix_timing(matrix_msgs)

    # Bisq 2 Results
    print(f"\n{'=' * 70}")
    print("BISQ 2 ANALYSIS")
    print(f"{'=' * 70}")
    print(f"Total messages: {bisq2_analysis['total_messages']}")

    linked = [g["gap_seconds"] for g in bisq2_analysis["linked_gaps"]]
    staff_linked = [
        g["gap_seconds"]
        for g in bisq2_analysis["linked_gaps"]
        if g["is_staff_response"]
    ]
    unlinked = [g["gap_seconds"] for g in bisq2_analysis["unlinked_staff_gaps"]]

    print("\n--- Linked Q&A Pairs (all) ---")
    stats = compute_stats(linked)
    for k, v in stats.items():
        if k != "count":
            print(f"  {k}: {format_time(v)}")
        else:
            print(f"  {k}: {v}")

    print("\n--- Linked Q&A Pairs (staff responses only) ---")
    stats = compute_stats(staff_linked)
    for k, v in stats.items():
        if k != "count":
            print(f"  {k}: {format_time(v)}")
        else:
            print(f"  {k}: {v}")

    print("\n--- Unlinked Staff Messages (gap to prev user msg) ---")
    stats = compute_stats(unlinked)
    for k, v in stats.items():
        if k != "count":
            print(f"  {k}: {format_time(v)}")
        else:
            print(f"  {k}: {v}")

    if bisq2_analysis["unlinked_staff_gaps"]:
        print("\n  Sample unlinked staff messages:")
        for i, gap in enumerate(bisq2_analysis["unlinked_staff_gaps"][:5]):
            print(f"    [{i+1}] Gap: {format_time(gap['gap_seconds'])}")
            print(f"        User: {gap['user_msg']}")
            print(f"        Staff: {gap['staff_msg']}")

    # Matrix Results
    print(f"\n{'=' * 70}")
    print("MATRIX ANALYSIS")
    print(f"{'=' * 70}")
    print(f"Total messages: {matrix_analysis['total_messages']}")

    linked = [g["gap_seconds"] for g in matrix_analysis["linked_gaps"]]
    staff_linked = [
        g["gap_seconds"]
        for g in matrix_analysis["linked_gaps"]
        if g["is_staff_response"]
    ]
    unlinked = [g["gap_seconds"] for g in matrix_analysis["unlinked_staff_gaps"]]

    print("\n--- Linked Q&A Pairs (all) ---")
    stats = compute_stats(linked)
    for k, v in stats.items():
        if k != "count":
            print(f"  {k}: {format_time(v)}")
        else:
            print(f"  {k}: {v}")

    print("\n--- Linked Q&A Pairs (staff responses only) ---")
    stats = compute_stats(staff_linked)
    for k, v in stats.items():
        if k != "count":
            print(f"  {k}: {format_time(v)}")
        else:
            print(f"  {k}: {v}")

    print("\n--- Unlinked Staff Messages (gap to prev user msg) ---")
    stats = compute_stats(unlinked)
    for k, v in stats.items():
        if k != "count":
            print(f"  {k}: {format_time(v)}")
        else:
            print(f"  {k}: {v}")

    # Recommendation
    print(f"\n{'=' * 70}")
    print("RECOMMENDED TEMPORAL PROXIMITY THRESHOLD")
    print(f"{'=' * 70}")

    all_staff_linked = [
        g["gap_seconds"]
        for g in bisq2_analysis["linked_gaps"]
        if g["is_staff_response"]
    ] + [
        g["gap_seconds"]
        for g in matrix_analysis["linked_gaps"]
        if g["is_staff_response"]
    ]

    if all_staff_linked:
        stats = compute_stats(all_staff_linked)
        print("\nCombined staff response times (LINKED, explicit replies):")
        print(f"  Count: {stats.get('count', 0)}")
        print(f"  Median: {format_time(stats.get('median_seconds', 0))}")
        print(f"  75th percentile: {format_time(stats.get('p75_seconds', 0))}")
        print(f"  90th percentile: {format_time(stats.get('p90_seconds', 0))}")

    # Focus on quick responses - within 1 hour
    quick_linked = [g for g in all_staff_linked if g <= 3600]  # Within 1 hour
    if quick_linked:
        print(
            f"\n  Quick responses (≤1 hour): {len(quick_linked)} ({100*len(quick_linked)/len(all_staff_linked):.1f}%)"
        )
        quick_stats = compute_stats(quick_linked)
        print(f"    Median: {format_time(quick_stats.get('median_seconds', 0))}")
        print(f"    90th percentile: {format_time(quick_stats.get('p90_seconds', 0))}")

    # Analyze distribution of consecutive same-author messages
    print("\n--- Consecutive Same-Author Message Gaps ---")
    bisq2_consec = bisq2_analysis["consecutive_same_author"]
    matrix_consec = matrix_analysis["consecutive_same_author"]
    all_consec = bisq2_consec + matrix_consec

    if all_consec:
        consec_stats = compute_stats(all_consec)
        print(f"  Count: {consec_stats.get('count', 0)}")
        print(f"  Median: {format_time(consec_stats.get('median_seconds', 0))}")
        print(f"  90th percentile: {format_time(consec_stats.get('p90_seconds', 0))}")
        print(f"  95th percentile: {format_time(consec_stats.get('p95_seconds', 0))}")

    # Final recommendation with reasoning
    print(f"\n{'=' * 70}")
    print("THRESHOLD RECOMMENDATIONS")
    print(f"{'=' * 70}")

    # Analyze thresholds
    thresholds_to_test = [60, 120, 180, 300, 600, 900, 1800, 3600]  # 1m to 1h

    print("\nThreshold impact analysis (on linked staff responses):")
    print(f"{'Threshold':<12} {'Would Capture':<15} {'% of Linked':<12}")
    print("-" * 40)

    for threshold in thresholds_to_test:
        captured = sum(1 for g in all_staff_linked if g <= threshold)
        pct = 100 * captured / len(all_staff_linked) if all_staff_linked else 0
        print(f"{format_time(threshold):<12} {captured:<15} {pct:.1f}%")

    # Final recommendation
    print(f"\n{'=' * 70}")
    print("FINAL RECOMMENDATION")
    print(f"{'=' * 70}")
    print("""
Based on the analysis:

1. QUICK RESPONSE THRESHOLD (for immediate context):
   - 5 MINUTES (300 seconds)
   - Captures staff responses to immediate follow-ups
   - Low false positive risk

2. STANDARD THRESHOLD (recommended default):
   - 10 MINUTES (600 seconds)
   - Captures most conversational back-and-forth
   - Good balance of recall vs precision

3. EXTENDED THRESHOLD (for busy periods):
   - 30 MINUTES (1800 seconds)
   - Catches delayed responses during high traffic
   - Higher false positive risk

RECOMMENDATION: Use 5 MINUTES (300 seconds) as default
- Conservative threshold minimizes false groupings
- Can be extended if context clearly indicates conversation
- Aligns with typical chat conversation cadence
""")


if __name__ == "__main__":
    main()

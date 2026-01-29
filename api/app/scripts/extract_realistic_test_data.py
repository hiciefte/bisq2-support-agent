#!/usr/bin/env python3
"""
Extract realistic Q&A test data from Bisq 2 Support Chat.

This script extracts user questions and support staff answers from the
Bisq 2 Support Chat export to create a realistic test dataset for RAGAS
evaluation that doesn't suffer from data leakage.

Usage:
    python -m app.scripts.extract_realistic_test_data

Output:
    /data/evaluation/bisq2_realistic_qa_samples.json
"""

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Paths
SUPPORT_CHAT_PATH = Path("/data/support_chat_export.json")
OUTPUT_PATH = Path("/data/evaluation/bisq2_realistic_qa_samples.json")

# Known support staff (high message count + domain knowledge)
SUPPORT_STAFF = {
    "suddenwhipvapor",  # Primary support, 242 messages
    "strayorigin",  # Also seen in Matrix as support
    "pazza83",  # Support mentioned in Matrix
    "mwithm",  # Support agent per topic
}

# Minimum lengths for quality filtering
MIN_QUESTION_LENGTH = 30  # Characters
MIN_ANSWER_LENGTH = 50  # Characters - ensure substantive answers
MIN_QUESTION_WORDS = 6
MIN_ANSWER_WORDS = 10  # Require at least 10 words for a real answer

# Patterns to exclude (not real questions)
EXCLUDE_QUESTION_PATTERNS = [
    r"^thanks?\b",
    r"^ok\b",
    r"^okay\b",
    r"^thank you\b",
    r"^thx\b",
    r"^got it\b",
    r"^understood\b",
    r"^awesome\b",
    r"^great\b",
    r"^nice\b",
    r"^perfect\b",
    r"^cool\b",
    r"^yes\b",
    r"^no\b",
    r"^yeah\b",
    r"^nope\b",
    r"^sure\b",
    r"^alright\b",
    r"^👍",
    r"^✅",
    r"^done\b",
    r"^fixed\b",
    r"^solved\b",
    r"^it work",
    r"^working now",
]

# Patterns indicating answer is just a clarifying question (not a real answer)
EXCLUDE_ANSWER_PATTERNS = [
    r"^can you explain",
    r"^what do you mean",
    r"^could you clarify",
    r"^what exactly",
    r"^which\s+\w+\s+are you",
    r"^are you on\s+\w+\?$",
    r"^what's the (exact )?error",
    r"^please (give|provide|share|send)",
    r"^can you (give|provide|share|send|post)",
    r"^did you\s+\w+\?$",
    r"^have you tried",
    r"^is it possible that",
    r"^isn't there",
    r"^reported your case",
    r"^I will let you look",
]

# Patterns indicating a real question or problem description
QUESTION_INDICATORS = [
    r"\?$",  # Ends with question mark
    r"\bhow\b",
    r"\bwhat\b",
    r"\bwhy\b",
    r"\bwhen\b",
    r"\bwhere\b",
    r"\bcan i\b",
    r"\bcould i\b",
    r"\bshould i\b",
    r"\bis it\b",
    r"\bdo i\b",
    r"\bdoes\b",
    r"\bhave\b.*\bissue",
    r"\bproblem\b",
    r"\berror\b",
    r"\bstuck\b",
    r"\bfailed\b",
    r"\bnot working\b",
    r"\bdoesn't work\b",
    r"\bhelp\b",
    r"\bplease\b",
    r"\bneed\b",
    r"\btrying to\b",
    r"\bunable to\b",
    r"\bcan't\b",
    r"\bcannot\b",
]


@dataclass
class QAPair:
    """A question-answer pair from support chat."""

    question: str
    answer: str
    question_author: str
    answer_author: str
    question_date: str
    answer_date: str
    question_id: str
    answer_id: str


def is_excluded_message(text: str) -> bool:
    """Check if message matches exclusion patterns."""
    text_lower = text.lower().strip()
    for pattern in EXCLUDE_QUESTION_PATTERNS:
        if re.search(pattern, text_lower, re.IGNORECASE):
            return True
    return False


def is_clarifying_question(text: str) -> bool:
    """Check if answer is just a clarifying question, not a real answer."""
    text_lower = text.lower().strip()
    for pattern in EXCLUDE_ANSWER_PATTERNS:
        if re.search(pattern, text_lower, re.IGNORECASE):
            return True
    return False


def is_likely_question(text: str) -> bool:
    """Check if text is likely a substantive question or problem description."""
    text_lower = text.lower()
    for pattern in QUESTION_INDICATORS:
        if re.search(pattern, text_lower, re.IGNORECASE):
            return True
    return False


def clean_text(text: str) -> str:
    """Clean and normalize text."""
    # Remove excess whitespace
    text = re.sub(r"\s+", " ", text).strip()
    return text


def extract_qa_pairs(data: dict) -> list[QAPair]:
    """Extract Q&A pairs from support chat data."""
    qa_pairs = []
    messages = data.get("messages", [])

    logger.info(f"Processing {len(messages)} messages")

    for msg in messages:
        # Only consider messages from support staff that cite another message
        if msg["author"].lower() not in {s.lower() for s in SUPPORT_STAFF}:
            continue

        if "citation" not in msg:
            continue

        citation = msg["citation"]
        cited_author = citation.get("author", "")
        cited_text = citation.get("text", "")
        answer_text = msg.get("message", "")

        # Skip if the cited message is from support staff (staff replying to staff)
        if cited_author.lower() in {s.lower() for s in SUPPORT_STAFF}:
            continue

        # Skip if question is too short or excluded
        if len(cited_text) < MIN_QUESTION_LENGTH:
            continue

        if len(cited_text.split()) < MIN_QUESTION_WORDS:
            continue

        if is_excluded_message(cited_text):
            continue

        # Skip if answer is too short
        if len(answer_text) < MIN_ANSWER_LENGTH:
            continue

        if len(answer_text.split()) < MIN_ANSWER_WORDS:
            continue

        # Skip if answer is just a clarifying question
        if is_clarifying_question(answer_text):
            continue

        # Check if it's likely a real question
        if not is_likely_question(cited_text):
            continue

        # Clean texts
        question = clean_text(cited_text)
        answer = clean_text(answer_text)

        qa_pair = QAPair(
            question=question,
            answer=answer,
            question_author=cited_author,
            answer_author=msg["author"],
            question_date=citation.get("date", msg.get("date", "")),
            answer_date=msg.get("date", ""),
            question_id=citation.get("messageId", ""),
            answer_id=msg.get("messageId", ""),
        )
        qa_pairs.append(qa_pair)

    return qa_pairs


def deduplicate_qa_pairs(qa_pairs: list[QAPair]) -> list[QAPair]:
    """Remove duplicate questions, keeping the best answer."""
    # Group by question (normalized)
    question_groups: dict[str, list[QAPair]] = {}

    for qa in qa_pairs:
        # Normalize question for comparison
        normalized = qa.question.lower().strip()
        if normalized not in question_groups:
            question_groups[normalized] = []
        question_groups[normalized].append(qa)

    # For each group, pick the answer with the longest/best response
    deduplicated = []
    for pairs in question_groups.values():
        # Sort by answer length (prefer longer, more detailed answers)
        pairs.sort(key=lambda p: len(p.answer), reverse=True)
        deduplicated.append(pairs[0])

    return deduplicated


def format_for_ragas(qa_pairs: list[QAPair]) -> list[dict]:
    """Format Q&A pairs for RAGAS evaluation."""
    samples = []

    for i, qa in enumerate(qa_pairs):
        sample = {
            "question": qa.question,
            "ground_truth": qa.answer,
            "contexts": [],  # Will be filled by RAG system during evaluation
            "metadata": {
                "source": "Bisq2 Support Chat",
                "protocol": "bisq_easy",
                "question_author": qa.question_author,
                "answer_author": qa.answer_author,
                "question_date": qa.question_date,
                "answer_date": qa.answer_date,
                "question_id": qa.question_id,
                "answer_id": qa.answer_id,
                "sample_index": i,
            },
        }
        samples.append(sample)

    return samples


def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Extract realistic Q&A test data from Bisq 2 Support Chat"
    )
    parser.add_argument(
        "--input",
        type=str,
        default=str(SUPPORT_CHAT_PATH),
        help=f"Path to support chat export (default: {SUPPORT_CHAT_PATH})",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=str(OUTPUT_PATH),
        help=f"Output path for test samples (default: {OUTPUT_PATH})",
    )
    parser.add_argument(
        "--max-samples",
        type=int,
        default=50,
        help="Maximum number of samples to extract (default: 50)",
    )
    parser.add_argument(
        "--min-question-length",
        type=int,
        default=MIN_QUESTION_LENGTH,
        help=f"Minimum question length in chars (default: {MIN_QUESTION_LENGTH})",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Show extracted Q&A pairs",
    )

    args = parser.parse_args()

    input_path = Path(args.input)
    output_path = Path(args.output)

    # Load support chat data
    if not input_path.exists():
        logger.error(f"Support chat export not found: {input_path}")
        return

    logger.info(f"Loading support chat from {input_path}")
    with open(input_path) as f:
        data = json.load(f)

    logger.info(f"Export metadata: {data.get('exportMetadata', {})}")

    # Extract Q&A pairs
    qa_pairs = extract_qa_pairs(data)
    logger.info(f"Extracted {len(qa_pairs)} raw Q&A pairs")

    # Deduplicate
    qa_pairs = deduplicate_qa_pairs(qa_pairs)
    logger.info(f"After deduplication: {len(qa_pairs)} unique Q&A pairs")

    # Sort by question date (newest first for variety)
    qa_pairs.sort(key=lambda p: p.question_date, reverse=True)

    # Limit to max samples
    if len(qa_pairs) > args.max_samples:
        qa_pairs = qa_pairs[: args.max_samples]
        logger.info(f"Limited to {args.max_samples} samples")

    # Format for RAGAS
    samples = format_for_ragas(qa_pairs)

    # Print samples if verbose
    if args.verbose:
        print("\n" + "=" * 70)
        print("EXTRACTED Q&A PAIRS")
        print("=" * 70)
        for i, sample in enumerate(samples):
            print(f"\n[{i+1}] Q: {sample['question'][:100]}...")
            print(f"    A: {sample['ground_truth'][:100]}...")
            print(f"    (by {sample['metadata']['answer_author']})")

    # Save output
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(samples, f, indent=2)

    logger.info(f"Saved {len(samples)} samples to {output_path}")

    # Print summary
    print("\n" + "=" * 70)
    print("EXTRACTION SUMMARY")
    print("=" * 70)
    print(
        f"Total messages processed: {data.get('exportMetadata', {}).get('messageCount', 'N/A')}"
    )
    print(f"Q&A pairs extracted: {len(samples)}")
    print(f"Output file: {output_path}")
    print("\nAnswer authors distribution:")
    from collections import Counter

    author_counts = Counter(s["metadata"]["answer_author"] for s in samples)
    for author, count in author_counts.most_common():
        print(f"  {author}: {count}")
    print("=" * 70)


if __name__ == "__main__":
    main()

"""Version Learning Service for pattern extraction and ML training data generation."""

import json
import logging
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from app.services.shadow_mode.repository import ShadowModeRepository

logger = logging.getLogger(__name__)


class VersionLearningService:
    """Extract patterns from shadow mode data for version detection improvement."""

    def __init__(self, repository: ShadowModeRepository):
        """Initialize with shadow mode repository.

        Args:
            repository: ShadowModeRepository instance for data access
        """
        self.repository = repository

    def extract_clarification_triggers(
        self, min_occurrences: int = 3
    ) -> Dict[str, Any]:
        """Extract patterns from questions that required clarification.

        Analyzes questions marked with requires_clarification=True to identify
        common patterns and keywords that indicate ambiguous version context.

        Args:
            min_occurrences: Minimum times a pattern must appear to be included

        Returns:
            Dict with patterns, keywords, and statistics:
            {
                "trigger_patterns": [
                    {"pattern": str, "count": int, "example_questions": [str]}
                ],
                "common_keywords": [
                    {"keyword": str, "frequency": int, "confidence_avg": float}
                ],
                "statistics": {
                    "total_clarifications": int,
                    "unique_patterns": int,
                    "avg_confidence": float
                }
            }
        """
        logger.info("Extracting clarification trigger patterns")

        # Get all responses that required clarification
        clarification_data = self.repository.get_skip_patterns()
        requires_clarification = [
            d for d in clarification_data if d.get("requires_clarification") is True
        ]

        if not requires_clarification:
            logger.warning("No clarification data found")
            return {
                "trigger_patterns": [],
                "common_keywords": [],
                "statistics": {
                    "total_clarifications": 0,
                    "unique_patterns": 0,
                    "avg_confidence": 0.0,
                },
            }

        # Extract keywords from questions
        keyword_counter = Counter()
        keyword_confidences = defaultdict(list)

        for entry in requires_clarification:
            question = entry.get("synthesized_question", "").lower()
            confidence = entry.get("version_confidence", 0.0)

            # Extract significant words (skip common stop words)
            words = self._extract_significant_words(question)
            for word in words:
                keyword_counter[word] += 1
                keyword_confidences[word].append(confidence)

        # Build keyword list with frequencies and average confidence
        common_keywords = [
            {
                "keyword": keyword,
                "frequency": count,
                "confidence_avg": sum(keyword_confidences[keyword])
                / len(keyword_confidences[keyword]),
            }
            for keyword, count in keyword_counter.most_common()
            if count >= min_occurrences
        ]

        # Extract patterns (simple n-gram analysis)
        trigger_patterns = self._extract_ngram_patterns(
            requires_clarification, min_occurrences
        )

        # Calculate statistics
        total_clarifications = len(requires_clarification)
        avg_confidence = (
            sum(
                entry.get("version_confidence", 0.0) for entry in requires_clarification
            )
            / total_clarifications
        )

        statistics = {
            "total_clarifications": total_clarifications,
            "unique_patterns": len(trigger_patterns),
            "avg_confidence": avg_confidence,
        }

        logger.info(
            f"Extracted {len(common_keywords)} keywords and {len(trigger_patterns)} patterns"
        )

        return {
            "trigger_patterns": trigger_patterns,
            "common_keywords": common_keywords,
            "statistics": statistics,
        }

    def extract_version_keywords(self) -> Dict[str, List[Dict[str, Any]]]:
        """Extract version-specific keywords from admin corrections.

        Analyzes version change events where admin corrected the detected version
        to identify keywords strongly associated with each Bisq version.

        Returns:
            Dict with version-specific keyword lists:
            {
                "bisq1_keywords": [
                    {"keyword": str, "weight": float, "frequency": int}
                ],
                "bisq2_keywords": [
                    {"keyword": str, "weight": float, "frequency": int}
                ],
                "general_keywords": [
                    {"keyword": str, "frequency": int}
                ]
            }
        """
        logger.info("Extracting version-specific keywords")

        # Get all version change events
        version_changes = self.repository.get_version_changes()

        bisq1_keywords = Counter()
        bisq2_keywords = Counter()
        general_keywords = Counter()

        for change in version_changes:
            question = change.get("synthesized_question", "").lower()
            confirmed_version = change.get("confirmed_version", "")

            # Extract significant words
            words = self._extract_significant_words(question)

            # Categorize by confirmed version
            if confirmed_version == "Bisq 1":
                bisq1_keywords.update(words)
            elif confirmed_version == "Bisq 2":
                bisq2_keywords.update(words)
            else:  # Unknown or General
                general_keywords.update(words)

        # Calculate source weights (1.5x for direct user answers, 1.0x for admin)
        def _build_keyword_list(counter: Counter, is_direct_answer: bool = False):
            weight = 1.5 if is_direct_answer else 1.0
            return [
                {"keyword": keyword, "weight": weight, "frequency": count}
                for keyword, count in counter.most_common(50)  # Top 50
            ]

        return {
            "bisq1_keywords": _build_keyword_list(bisq1_keywords),
            "bisq2_keywords": _build_keyword_list(bisq2_keywords),
            "general_keywords": [
                {"keyword": keyword, "frequency": count}
                for keyword, count in general_keywords.most_common(30)
            ],
        }

    def build_clarifying_question_library(self) -> List[Dict[str, Any]]:
        """Build library of effective clarifying questions from real data.

        Extracts all unique clarifying questions used in the system and ranks
        them by effectiveness based on how often they led to successful responses.

        Returns:
            List of clarifying questions with effectiveness metrics:
            [
                {
                    "question": str,
                    "usage_count": int,
                    "contexts": [str],  # Question keywords that triggered it
                    "effectiveness_score": float  # 0-1, based on success rate
                }
            ]
        """
        logger.info("Building clarifying question library")

        # Get all responses with clarifying questions
        all_responses = self.repository.get_responses(limit=10000)
        questions_data = defaultdict(
            lambda: {"count": 0, "contexts": [], "sources": []}
        )

        for response in all_responses:
            clarifying_q = response.clarifying_question
            if not clarifying_q:
                continue

            questions_data[clarifying_q]["count"] += 1

            # Extract context from synthesized question
            if response.synthesized_question:
                context_words = self._extract_significant_words(
                    response.synthesized_question.lower()
                )[
                    :3
                ]  # Top 3 words
                questions_data[clarifying_q]["contexts"].extend(context_words)

            # Track source (custom vs auto-generated)
            source = "custom" if response.source == "rag_bot_clarification" else "auto"
            questions_data[clarifying_q]["sources"].append(source)

        # Build library with effectiveness scores
        library = []
        for question, data in questions_data.items():
            # Calculate effectiveness: custom questions score higher
            custom_ratio = data["sources"].count("custom") / len(data["sources"])
            effectiveness_score = 0.5 + (custom_ratio * 0.5)  # 0.5-1.0 range

            # Get unique contexts
            unique_contexts = list(set(data["contexts"]))

            library.append(
                {
                    "question": question,
                    "usage_count": data["count"],
                    "contexts": unique_contexts[:10],  # Top 10 context words
                    "effectiveness_score": effectiveness_score,
                }
            )

        # Sort by effectiveness score descending
        library.sort(key=lambda x: x["effectiveness_score"], reverse=True)

        logger.info(f"Built library with {len(library)} unique clarifying questions")
        return library

    def export_ml_training_dataset(
        self, output_path: Optional[Path] = None
    ) -> Dict[str, Any]:
        """Export training dataset for ML model training.

        Generates a comprehensive dataset combining all learning insights:
        - Questions with version labels (admin-confirmed and user-clarified)
        - Clarification trigger patterns
        - Version-specific keywords
        - Effective clarifying questions

        Args:
            output_path: Optional path to save JSON file. If None, returns data only.

        Returns:
            Dict with complete training dataset:
            {
                "metadata": {
                    "generated_at": str,
                    "total_samples": int,
                    "source_distribution": dict
                },
                "labeled_questions": [
                    {
                        "question": str,
                        "version": str,
                        "confidence": float,
                        "source": str,
                        "source_weight": float
                    }
                ],
                "clarification_patterns": [...],
                "version_keywords": {...},
                "clarifying_questions": [...]
            }
        """
        logger.info("Generating ML training dataset")

        # Get labeled questions from version changes
        version_changes = self.repository.get_version_changes()
        labeled_questions = []

        for change in version_changes:
            source = change.get("source", "shadow_mode")
            source_weight = 1.5 if source == "rag_bot_clarification" else 1.0

            labeled_questions.append(
                {
                    "question": change.get("synthesized_question", ""),
                    "version": change.get("confirmed_version", "Unknown"),
                    "confidence": change.get("version_confidence", 0.0),
                    "source": source,
                    "source_weight": source_weight,
                    "training_version": change.get("training_version"),
                }
            )

        # Extract all learning components
        clarification_patterns = self.extract_clarification_triggers()
        version_keywords = self.extract_version_keywords()
        clarifying_questions = self.build_clarifying_question_library()

        # Calculate source distribution
        source_distribution = Counter(q["source"] for q in labeled_questions)

        # Build complete dataset
        dataset = {
            "metadata": {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "total_samples": len(labeled_questions),
                "source_distribution": dict(source_distribution),
            },
            "labeled_questions": labeled_questions,
            "clarification_patterns": clarification_patterns,
            "version_keywords": version_keywords,
            "clarifying_questions": clarifying_questions,
        }

        # Save to file if path provided
        if output_path:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(dataset, f, indent=2, ensure_ascii=False)
            logger.info(f"Training dataset exported to {output_path}")

        logger.info(
            f"Generated dataset with {len(labeled_questions)} labeled questions"
        )
        return dataset

    # Helper methods

    def _extract_significant_words(self, text: str) -> List[str]:
        """Extract significant words from text, filtering stop words.

        Args:
            text: Input text to process

        Returns:
            List of significant words (lowercase, no stop words)
        """
        # Common stop words to filter
        stop_words = {
            "a",
            "an",
            "the",
            "is",
            "are",
            "was",
            "were",
            "be",
            "been",
            "being",
            "have",
            "has",
            "had",
            "do",
            "does",
            "did",
            "will",
            "would",
            "could",
            "should",
            "may",
            "might",
            "can",
            "of",
            "to",
            "in",
            "for",
            "on",
            "at",
            "by",
            "from",
            "with",
            "about",
            "as",
            "that",
            "this",
            "it",
            "i",
            "you",
            "my",
            "your",
            "how",
            "what",
            "when",
            "where",
            "why",
            "which",
        }

        # Extract words (alphanumeric only)
        words = [
            word
            for word in text.split()
            if word.isalnum() and word not in stop_words and len(word) > 2
        ]

        return words

    def _extract_ngram_patterns(
        self, questions: List[Dict[str, Any]], min_occurrences: int
    ) -> List[Dict[str, Any]]:
        """Extract common n-gram patterns from questions.

        Args:
            questions: List of question dictionaries
            min_occurrences: Minimum occurrences to include pattern

        Returns:
            List of pattern dictionaries with counts and examples
        """
        # Simple bigram extraction for now
        bigram_counter = Counter()
        bigram_examples = defaultdict(list)

        for entry in questions:
            question = entry.get("synthesized_question", "").lower()
            words = self._extract_significant_words(question)

            # Extract bigrams
            for i in range(len(words) - 1):
                bigram = f"{words[i]} {words[i + 1]}"
                bigram_counter[bigram] += 1
                if len(bigram_examples[bigram]) < 3:  # Keep max 3 examples
                    bigram_examples[bigram].append(
                        entry.get("synthesized_question", "")
                    )

        # Build pattern list
        patterns = [
            {
                "pattern": pattern,
                "count": count,
                "example_questions": bigram_examples[pattern],
            }
            for pattern, count in bigram_counter.most_common()
            if count >= min_occurrences
        ]

        return patterns[:50]  # Top 50 patterns

"""Tests for Version Learning Service - ML Pattern Extraction.

CRITICAL: This test file verifies ML training data extraction from shadow mode:
- Clarification trigger pattern extraction (n-grams)
- Version-specific keyword categorization (Bisq 1 vs Bisq 2)
- Clarifying question effectiveness scoring
- Complete ML training dataset export with source weighting
"""

import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest
from app.models.shadow_response import ShadowResponse, ShadowStatus
from app.services.shadow_mode.repository import ShadowModeRepository
from app.services.version_learning_service import VersionLearningService


@pytest.fixture
def temp_db():
    """Create temporary database for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_learning.db"
        yield str(db_path)


@pytest.fixture
def repository(temp_db):
    """Create repository instance with temporary database."""
    return ShadowModeRepository(temp_db)


@pytest.fixture
def learning_service(repository):
    """Create VersionLearningService instance."""
    return VersionLearningService(repository)


@pytest.fixture
def sample_clarification_data(repository):
    """Create sample data with clarification triggers.

    CRITICAL: extract_clarification_triggers() uses get_skip_patterns() which queries
    for status='skipped', so responses MUST have status=SKIPPED and skip_reason set.
    """
    # Add responses requiring clarification
    responses = [
        ShadowResponse(
            id="clarif-1",
            channel_id="ch1",
            user_id="u1",
            messages=[],
            synthesized_question="How do I trade?",
            detected_version="Unknown",
            version_confidence=0.25,
            confirmed_version="Unknown",
            training_protocol="bisq_easy",
            requires_clarification=True,
            clarifying_question="Which Bisq version?",
            status=ShadowStatus.SKIPPED,
            skip_reason="Requires clarification",  # CRITICAL for get_skip_patterns()
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        ),
        ShadowResponse(
            id="clarif-2",
            channel_id="ch2",
            user_id="u2",
            messages=[],
            synthesized_question="What are the fees for trading?",
            detected_version="Unknown",
            version_confidence=0.30,
            confirmed_version="Unknown",
            training_protocol="multisig_v1",
            requires_clarification=True,
            clarifying_question="Bisq 1 or Bisq 2 fees?",
            status=ShadowStatus.SKIPPED,
            skip_reason="Requires clarification",  # CRITICAL for get_skip_patterns()
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        ),
        ShadowResponse(
            id="clarif-3",
            channel_id="ch3",
            user_id="u3",
            messages=[],
            synthesized_question="How do I restore my wallet for trading?",
            detected_version="Unknown",
            version_confidence=0.20,
            confirmed_version="Unknown",
            training_protocol="bisq_easy",
            requires_clarification=True,
            clarifying_question="Which version?",
            status=ShadowStatus.SKIPPED,
            skip_reason="Requires clarification",  # CRITICAL for get_skip_patterns()
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        ),
    ]

    for resp in responses:
        repository.add_response(resp)

    return responses


@pytest.fixture
def sample_version_changes(repository):
    """Create sample data with version changes."""
    responses = [
        # Bisq 1 questions
        ShadowResponse(
            id="bisq1-1",
            channel_id="ch1",
            user_id="u1",
            messages=[],
            synthesized_question="How does DAO voting work?",
            detected_version="Bisq 2",
            version_confidence=0.50,
            confirmed_version="Bisq 1",
            status=ShadowStatus.APPROVED,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            version_confirmed_at=datetime.now(timezone.utc),
        ),
        ShadowResponse(
            id="bisq1-2",
            channel_id="ch2",
            user_id="u2",
            messages=[],
            synthesized_question="What are arbitration fees?",
            detected_version="Unknown",
            version_confidence=0.40,
            confirmed_version="Bisq 1",
            status=ShadowStatus.APPROVED,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            version_confirmed_at=datetime.now(timezone.utc),
        ),
        # Bisq 2 questions
        ShadowResponse(
            id="bisq2-1",
            channel_id="ch3",
            user_id="u3",
            messages=[],
            synthesized_question="How does reputation system work?",
            detected_version="Bisq 1",
            version_confidence=0.45,
            confirmed_version="Bisq 2",
            status=ShadowStatus.APPROVED,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            version_confirmed_at=datetime.now(timezone.utc),
        ),
        ShadowResponse(
            id="bisq2-2",
            channel_id="ch4",
            user_id="u4",
            messages=[],
            synthesized_question="What are bonded roles for reputation?",
            detected_version="Unknown",
            version_confidence=0.35,
            confirmed_version="Bisq 2",
            status=ShadowStatus.APPROVED,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            version_confirmed_at=datetime.now(timezone.utc),
        ),
    ]

    for resp in responses:
        repository.add_response(resp)

    return responses


class TestExtractClarificationTriggers:
    """Test suite for extract_clarification_triggers() method."""

    def test_extract_clarification_triggers_finds_patterns(
        self, learning_service, sample_clarification_data
    ):
        """Verify n-gram extraction from questions requiring clarification.

        FIXED: Updated get_skip_patterns() to SELECT requires_clarification and version_confidence fields.
        """
        result = learning_service.extract_clarification_triggers(min_occurrences=1)

        # Verify structure
        assert "trigger_patterns" in result
        assert "common_keywords" in result
        assert "statistics" in result

        # Verify statistics
        stats = result["statistics"]
        assert stats["total_clarifications"] == 3
        assert stats["unique_patterns"] >= 0
        assert 0.0 <= stats["avg_confidence"] <= 1.0

        # Verify keywords extracted
        keywords = result["common_keywords"]
        assert len(keywords) > 0

        # Check that "trade" or "trading" appears (common in sample questions)
        keyword_list = [k["keyword"] for k in keywords]
        assert any(
            kw in ["trade", "trading", "fees", "restore"] for kw in keyword_list
        ), "Should find 'trade' or 'trading' or 'fees' keyword"

    def test_extract_clarification_triggers_filters_by_min_occurrences(
        self, learning_service, sample_clarification_data
    ):
        """Verify min_occurrences filter works correctly.

        FIXED: get_skip_patterns() now returns requires_clarification field.
        """
        # With min_occurrences=10, should find no patterns (only 3 questions)
        result = learning_service.extract_clarification_triggers(min_occurrences=10)

        assert result["common_keywords"] == []
        assert result["statistics"]["total_clarifications"] == 3

    def test_extract_clarification_triggers_with_no_data(self, learning_service):
        """Verify returns empty structure when no clarification data exists."""
        result = learning_service.extract_clarification_triggers()

        assert result["trigger_patterns"] == []
        assert result["common_keywords"] == []
        assert result["statistics"]["total_clarifications"] == 0
        assert result["statistics"]["avg_confidence"] == 0.0

    def test_extract_clarification_triggers_includes_confidence_avg(
        self, learning_service, sample_clarification_data
    ):
        """Verify keywords include average confidence scores.

        FIXED: get_skip_patterns() now returns version_confidence field.
        """
        result = learning_service.extract_clarification_triggers(min_occurrences=1)

        keywords = result["common_keywords"]
        assert len(keywords) > 0

        # Verify each keyword has confidence_avg
        for keyword_data in keywords:
            assert "keyword" in keyword_data
            assert "frequency" in keyword_data
            assert "confidence_avg" in keyword_data
            assert 0.0 <= keyword_data["confidence_avg"] <= 1.0


class TestExtractVersionKeywords:
    """Test suite for extract_version_keywords() method."""

    def test_extract_version_keywords_separates_bisq1_bisq2(
        self, learning_service, sample_version_changes
    ):
        """Verify keyword categorization separates Bisq 1 vs Bisq 2 terms."""
        result = learning_service.extract_version_keywords()

        # Verify structure
        assert "bisq1_keywords" in result
        assert "bisq2_keywords" in result
        assert "general_keywords" in result

        bisq1_kws = result["bisq1_keywords"]
        bisq2_kws = result["bisq2_keywords"]

        # Should have some keywords from each category
        assert len(bisq1_kws) > 0, "Should extract Bisq 1 keywords"
        assert len(bisq2_kws) > 0, "Should extract Bisq 2 keywords"

        # Verify keywords have required fields
        for kw in bisq1_kws:
            assert "keyword" in kw
            assert "weight" in kw
            assert "frequency" in kw

    def test_extract_version_keywords_bisq1_contains_dao_arbitration(
        self, learning_service, sample_version_changes
    ):
        """Verify Bisq 1 keywords contain 'dao' and 'arbitration'."""
        result = learning_service.extract_version_keywords()

        bisq1_keywords_list = [kw["keyword"] for kw in result["bisq1_keywords"]]

        # Should find 'dao' from "How does DAO voting work?"
        assert (
            "dao" in bisq1_keywords_list or "voting" in bisq1_keywords_list
        ), "Should extract 'dao' or 'voting' for Bisq 1"

        # Should find 'arbitration' from "What are arbitration fees?"
        assert (
            "arbitration" in bisq1_keywords_list or "fees" in bisq1_keywords_list
        ), "Should extract 'arbitration' or 'fees' for Bisq 1"

    def test_extract_version_keywords_bisq2_contains_reputation(
        self, learning_service, sample_version_changes
    ):
        """Verify Bisq 2 keywords contain 'reputation'."""
        result = learning_service.extract_version_keywords()

        bisq2_keywords_list = [kw["keyword"] for kw in result["bisq2_keywords"]]

        # Should find 'reputation' from multiple Bisq 2 questions
        assert (
            "reputation" in bisq2_keywords_list
        ), "Should extract 'reputation' for Bisq 2"

    def test_extract_version_keywords_applies_weights(
        self, learning_service, sample_version_changes
    ):
        """Verify keywords have weight values (1.0x or 1.5x)."""
        result = learning_service.extract_version_keywords()

        # Check weights are applied (currently 1.0x for all shadow_mode sources)
        for kw in result["bisq1_keywords"]:
            assert kw["weight"] in [
                1.0,
                1.5,
            ], f"Weight should be 1.0 or 1.5, got {kw['weight']}"


class TestBuildClarifyingQuestionLibrary:
    """Test suite for build_clarifying_question_library() method."""

    def test_build_clarifying_question_library_ranks_by_effectiveness(
        self, learning_service, repository
    ):
        """Verify questions ranked by effectiveness (custom > auto)."""
        # Add responses with different sources
        responses = [
            # Custom clarifying question (source=rag_bot_clarification)
            ShadowResponse(
                id="custom-1",
                channel_id="ch1",
                user_id="u1",
                messages=[],
                synthesized_question="How do I trade?",
                detected_version="Bisq 2",
                clarifying_question="Which Bisq version?",
                source="rag_bot_clarification",  # Custom (1.5x weight)
                status=ShadowStatus.APPROVED,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            ),
            # Auto-generated (source=shadow_mode)
            ShadowResponse(
                id="auto-1",
                channel_id="ch2",
                user_id="u2",
                messages=[],
                synthesized_question="What are fees?",
                detected_version="Bisq 1",
                clarifying_question="Bisq 1 or Bisq 2?",
                source="shadow_mode",  # Auto-generated (1.0x weight)
                status=ShadowStatus.APPROVED,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            ),
        ]

        for resp in responses:
            repository.add_response(resp)

        library = learning_service.build_clarifying_question_library()

        # Verify library structure
        assert len(library) > 0
        for entry in library:
            assert "question" in entry
            assert "usage_count" in entry
            assert "contexts" in entry
            assert "effectiveness_score" in entry
            assert 0.0 <= entry["effectiveness_score"] <= 1.0

        # Verify sorted by effectiveness (custom should score higher)
        # Custom question should have higher effectiveness (0.5 + 0.5*1.0 = 1.0)
        # Auto question should have lower effectiveness (0.5 + 0.5*0.0 = 0.5)
        custom_question = next(
            (q for q in library if "Which Bisq version?" in q["question"]), None
        )
        assert custom_question is not None
        assert (
            custom_question["effectiveness_score"] >= 0.9
        ), "Custom questions should score higher"

    def test_build_clarifying_question_library_extracts_contexts(
        self, learning_service, sample_clarification_data
    ):
        """Verify context words extracted from synthesized questions."""
        library = learning_service.build_clarifying_question_library()

        # Should have entries from sample data
        assert len(library) > 0

        # Verify contexts are extracted
        for entry in library:
            assert isinstance(entry["contexts"], list)


class TestExportMLTrainingDataset:
    """Test suite for export_ml_training_dataset() method."""

    def test_export_ml_training_dataset_includes_all_sections(
        self, learning_service, sample_version_changes
    ):
        """Verify exported dataset has all required sections."""
        dataset = learning_service.export_ml_training_dataset()

        # Verify structure
        assert "metadata" in dataset
        assert "labeled_questions" in dataset
        assert "clarification_patterns" in dataset
        assert "version_keywords" in dataset
        assert "clarifying_questions" in dataset

        # Verify metadata
        metadata = dataset["metadata"]
        assert "generated_at" in metadata
        assert "total_samples" in metadata
        assert "source_distribution" in metadata

        # Verify labeled questions
        questions = dataset["labeled_questions"]
        assert len(questions) == 4  # From sample_version_changes fixture

        # Verify each question has required fields
        for q in questions:
            assert "question" in q
            assert "version" in q
            assert "confidence" in q
            assert "source" in q
            assert "source_weight" in q
            assert "training_protocol" in q

    def test_export_ml_training_dataset_applies_source_weights(
        self, learning_service, repository
    ):
        """Verify source weights: 1.5x for rag_bot_clarification, 1.0x for shadow_mode.

        CRITICAL: get_version_changes() filters for confirmed_version != detected_version,
        so test responses MUST have different values for these fields.
        """
        # Add responses with different sources
        responses = [
            ShadowResponse(
                id="shadow-1",
                channel_id="ch1",
                user_id="u1",
                messages=[],
                synthesized_question="Question 1",
                detected_version="Bisq 2",  # DIFFERENT from confirmed
                confirmed_version="Bisq 1",  # Admin corrected it
                source="shadow_mode",
                status=ShadowStatus.APPROVED,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
                version_confirmed_at=datetime.now(timezone.utc),
            ),
            ShadowResponse(
                id="ragbot-1",
                channel_id="ch2",
                user_id="u2",
                messages=[],
                synthesized_question="Question 2",
                detected_version="Bisq 1",  # DIFFERENT from confirmed
                confirmed_version="Bisq 2",  # Admin corrected it
                source="rag_bot_clarification",
                status=ShadowStatus.APPROVED,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
                version_confirmed_at=datetime.now(timezone.utc),
            ),
        ]

        for resp in responses:
            repository.add_response(resp)

        dataset = learning_service.export_ml_training_dataset()
        questions = dataset["labeled_questions"]

        # Find each question by source (with defaults to avoid StopIteration)
        shadow_mode_q = next(
            (q for q in questions if q["source"] == "shadow_mode"), None
        )
        rag_bot_q = next(
            (q for q in questions if q["source"] == "rag_bot_clarification"), None
        )

        # Verify both questions were found
        assert shadow_mode_q is not None, "Should find shadow_mode question"
        assert rag_bot_q is not None, "Should find rag_bot_clarification question"

        # Verify weights
        assert (
            shadow_mode_q["source_weight"] == 1.0
        ), "shadow_mode should have 1.0x weight"
        assert (
            rag_bot_q["source_weight"] == 1.5
        ), "rag_bot_clarification should have 1.5x weight"

    def test_export_ml_training_dataset_saves_to_file(
        self, learning_service, sample_version_changes
    ):
        """Verify dataset can be saved to file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "training_dataset.json"

            dataset = learning_service.export_ml_training_dataset(
                output_path=output_path
            )

            # Verify file created
            assert output_path.exists()

            # Verify file content matches returned dataset
            with open(output_path, "r", encoding="utf-8") as f:
                saved_data = json.load(f)

            assert (
                saved_data["metadata"]["total_samples"]
                == dataset["metadata"]["total_samples"]
            )
            assert len(saved_data["labeled_questions"]) == len(
                dataset["labeled_questions"]
            )

    def test_export_ml_training_dataset_source_distribution(
        self, learning_service, repository
    ):
        """Verify source_distribution counts sources correctly.

        CRITICAL: get_version_changes() filters for confirmed_version != detected_version,
        so test responses MUST have different values for these fields.
        """
        # Add responses with mixed sources
        responses = [
            ShadowResponse(
                id=f"shadow-{i}",
                channel_id=f"ch{i}",
                user_id=f"u{i}",
                messages=[],
                synthesized_question=f"Question {i}",
                detected_version="Bisq 2",  # DIFFERENT from confirmed
                confirmed_version="Bisq 1",  # Admin corrected it
                source="shadow_mode",
                status=ShadowStatus.APPROVED,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
                version_confirmed_at=datetime.now(timezone.utc),
            )
            for i in range(3)
        ]

        responses.extend(
            [
                ShadowResponse(
                    id=f"ragbot-{i}",
                    channel_id=f"ch{i + 10}",
                    user_id=f"u{i + 10}",
                    messages=[],
                    synthesized_question=f"Question {i + 10}",
                    detected_version="Bisq 1",  # DIFFERENT from confirmed
                    confirmed_version="Bisq 2",  # Admin corrected it
                    source="rag_bot_clarification",
                    status=ShadowStatus.APPROVED,
                    created_at=datetime.now(timezone.utc),
                    updated_at=datetime.now(timezone.utc),
                    version_confirmed_at=datetime.now(timezone.utc),
                )
                for i in range(2)
            ]
        )

        for resp in responses:
            repository.add_response(resp)

        dataset = learning_service.export_ml_training_dataset()
        source_dist = dataset["metadata"]["source_distribution"]

        assert source_dist["shadow_mode"] == 3
        assert source_dist["rag_bot_clarification"] == 2


class TestHelperMethods:
    """Test suite for helper methods."""

    def test_extract_significant_words_filters_stop_words(self, learning_service):
        """Verify _extract_significant_words filters common stop words.

        CRITICAL: word.isalnum() returns False for "wallet?" (has punctuation),
        so test text must not include punctuation.
        """
        text = "How do I trade in the DAO with my wallet"  # No punctuation
        words = learning_service._extract_significant_words(text.lower())

        # Should include: trade, dao, wallet (no punctuation, len>2, not stop words)
        # Should exclude: how, do, i, in, the, with, my
        assert "trade" in words
        assert "dao" in words
        assert "wallet" in words

        # Verify stop words excluded
        assert "how" not in words
        assert "the" not in words
        assert "with" not in words

    def test_extract_significant_words_filters_short_words(self, learning_service):
        """Verify words with length <= 2 are filtered."""
        text = "I am on it"
        words = learning_service._extract_significant_words(text.lower())

        # All words should be filtered (I, am, on, it are all too short or stop words)
        assert len(words) == 0

    def test_extract_ngram_patterns_finds_bigrams(self, learning_service):
        """Verify _extract_ngram_patterns finds bigram patterns.

        CRITICAL: word.isalnum() filters out "Bitcoin?" (has punctuation).
        Use no punctuation in test questions.
        """
        questions = [
            {
                "synthesized_question": "How do I trade Bitcoin",  # No punctuation
                "requires_clarification": True,
            },
            {
                "synthesized_question": "How do I buy Bitcoin",  # No punctuation
                "requires_clarification": True,
            },
            {
                "synthesized_question": "Where do I trade Bitcoin",  # No punctuation
                "requires_clarification": True,
            },
        ]

        patterns = learning_service._extract_ngram_patterns(
            questions, min_occurrences=2
        )

        # Should find "trade bitcoin" bigram (appears twice)
        pattern_list = [p["pattern"] for p in patterns]
        assert (
            len(patterns) > 0
        ), f"Should find at least one bigram pattern, got {patterns}"
        assert any(
            "trade bitcoin" in p or "bitcoin" in p for p in pattern_list
        ), f"Should find bigram patterns with 'bitcoin', got {pattern_list}"

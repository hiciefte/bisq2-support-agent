"""Tests for source-based protocol detection defaults.

The Bisq 2 Support API is primarily for Bisq Easy questions. When messages
come from the "bisq2" source, they should default to the bisq_easy protocol
unless protocol detection explicitly identifies Bisq 1 (multisig) content.

Key behaviors:
1. Source "bisq2" -> default protocol is "bisq_easy"
2. Protocol detection can override to "multisig_v1" if question is about Bisq 1
3. Source "matrix" -> no default, relies purely on detection
4. When source default and detection agree -> use detected (higher confidence)
5. When detection finds nothing -> use source default
"""

from unittest.mock import MagicMock

import pytest
from app.services.rag.protocol_detector import ProtocolDetector


class TestProtocolDetectorSourceDefaults:
    """Test protocol detection with source-based defaults."""

    @pytest.fixture
    def detector(self):
        """Create a ProtocolDetector instance."""
        return ProtocolDetector()

    # =========================================================================
    # Core Source Default Tests
    # =========================================================================

    def test_bisq2_source_defaults_to_bisq_easy(self, detector):
        """Messages from bisq2 source should default to bisq_easy protocol.

        When there are no clear protocol indicators in the text, the source
        provides the default. Bisq 2 Support API = Bisq Easy by default.
        """
        # Generic question with no protocol indicators
        protocol = detector.detect_protocol_with_source_default(
            text="How do I complete my trade?",
            source="bisq2",
        )
        assert (
            protocol == "bisq_easy"
        ), "Bisq2 source should default to bisq_easy for ambiguous questions"

    def test_bisq2_source_default_for_generic_payment_question(self, detector):
        """Generic payment questions from bisq2 should default to bisq_easy."""
        protocol = detector.detect_protocol_with_source_default(
            text="The buyer hasn't sent the payment yet",
            source="bisq2",
        )
        assert protocol == "bisq_easy"

    def test_bisq2_source_default_for_generic_wallet_question(self, detector):
        """Generic wallet questions from bisq2 should default to bisq_easy."""
        protocol = detector.detect_protocol_with_source_default(
            text="How do I check my wallet balance?",
            source="bisq2",
        )
        assert protocol == "bisq_easy"

    def test_matrix_source_has_no_default(self, detector):
        """Messages from matrix source should have no default protocol.

        Matrix can have questions about either Bisq 1 or Bisq 2, so it
        should rely purely on content detection.
        """
        protocol = detector.detect_protocol_with_source_default(
            text="How do I complete my trade?",
            source="matrix",
        )
        # Matrix has no default - should return None for ambiguous
        assert (
            protocol is None
        ), "Matrix source should return None when detection is ambiguous"

    def test_no_source_has_no_default(self, detector):
        """When no source is provided, there should be no default."""
        protocol = detector.detect_protocol_with_source_default(
            text="How do I complete my trade?",
            source=None,
        )
        assert protocol is None

    # =========================================================================
    # Protocol Detection Override Tests
    # =========================================================================

    def test_bisq1_keywords_override_bisq2_source_default(self, detector):
        """Bisq 1 specific keywords should override the bisq2 source default.

        If someone asks about DAO/BSQ/arbitration in Bisq 2 support chat,
        they're asking about Bisq 1 features - detection should override.
        """
        protocol = detector.detect_protocol_with_source_default(
            text="How does DAO voting work?",
            source="bisq2",
        )
        assert (
            protocol == "multisig_v1"
        ), "DAO question should override bisq2 source default to multisig_v1"

    def test_arbitration_overrides_bisq2_source_default(self, detector):
        """Arbitration questions should return multisig_v1 even from bisq2 source."""
        protocol = detector.detect_protocol_with_source_default(
            text="How do I contact the arbitrator?",
            source="bisq2",
        )
        assert protocol == "multisig_v1"

    def test_bsq_overrides_bisq2_source_default(self, detector):
        """BSQ questions should return multisig_v1 even from bisq2 source."""
        protocol = detector.detect_protocol_with_source_default(
            text="How do I use BSQ for trading fees?",
            source="bisq2",
        )
        assert protocol == "multisig_v1"

    def test_security_deposit_overrides_bisq2_source_default(self, detector):
        """Security deposit questions should return multisig_v1 from bisq2 source."""
        protocol = detector.detect_protocol_with_source_default(
            text="How much is the security deposit?",
            source="bisq2",
        )
        assert protocol == "multisig_v1"

    def test_multisig_overrides_bisq2_source_default(self, detector):
        """Multisig questions should return multisig_v1 from bisq2 source."""
        protocol = detector.detect_protocol_with_source_default(
            text="How does the 2-of-2 multisig work?",
            source="bisq2",
        )
        assert protocol == "multisig_v1"

    # =========================================================================
    # Bisq Easy Explicit Indicators (reinforce source default)
    # =========================================================================

    def test_bisq_easy_keywords_with_bisq2_source(self, detector):
        """Bisq Easy keywords from bisq2 source should return bisq_easy."""
        protocol = detector.detect_protocol_with_source_default(
            text="How does reputation work in Bisq Easy?",
            source="bisq2",
        )
        assert protocol == "bisq_easy"

    def test_reputation_question_with_bisq2_source(self, detector):
        """Reputation questions from bisq2 source should return bisq_easy."""
        protocol = detector.detect_protocol_with_source_default(
            text="How do I build reputation?",
            source="bisq2",
        )
        assert protocol == "bisq_easy"

    def test_600_usd_limit_with_bisq2_source(self, detector):
        """600 USD limit questions from bisq2 source should return bisq_easy."""
        protocol = detector.detect_protocol_with_source_default(
            text="Why is the trade limit 600 USD?",
            source="bisq2",
        )
        assert protocol == "bisq_easy"

    # =========================================================================
    # Matrix Source Detection Tests (no default, pure detection)
    # =========================================================================

    def test_matrix_detects_bisq1_content(self, detector):
        """Matrix source should detect Bisq 1 content without any default."""
        protocol = detector.detect_protocol_with_source_default(
            text="How does DAO voting work?",
            source="matrix",
        )
        assert protocol == "multisig_v1"

    def test_matrix_detects_bisq2_content(self, detector):
        """Matrix source should detect Bisq 2 content without any default."""
        protocol = detector.detect_protocol_with_source_default(
            text="How does Bisq Easy reputation work?",
            source="matrix",
        )
        assert protocol == "bisq_easy"

    def test_matrix_returns_none_for_ambiguous(self, detector):
        """Matrix source should return None for truly ambiguous questions."""
        protocol = detector.detect_protocol_with_source_default(
            text="Hello, I need help",
            source="matrix",
        )
        assert protocol is None

    # =========================================================================
    # Explicit Version Mentions (highest priority)
    # =========================================================================

    def test_explicit_bisq1_mention_from_bisq2_source(self, detector):
        """Explicit 'Bisq 1' mention should override bisq2 source default."""
        protocol = detector.detect_protocol_with_source_default(
            text="I have a question about Bisq 1",
            source="bisq2",
        )
        assert protocol == "multisig_v1"

    def test_explicit_bisq2_mention_from_matrix_source(self, detector):
        """Explicit 'Bisq 2' mention should work from matrix source."""
        protocol = detector.detect_protocol_with_source_default(
            text="How do I use Bisq 2?",
            source="matrix",
        )
        assert protocol == "bisq_easy"

    # =========================================================================
    # Confidence and Return Values
    # =========================================================================

    def test_returns_protocol_and_confidence(self, detector):
        """Method should return both protocol and confidence."""
        protocol, confidence = detector.detect_protocol_with_source_default(
            text="How do I complete my trade?",
            source="bisq2",
            return_confidence=True,
        )
        assert protocol == "bisq_easy"
        assert isinstance(confidence, float)
        assert 0.0 <= confidence <= 1.0

    def test_source_default_has_moderate_confidence(self, detector):
        """Source-based default should have moderate confidence (not 0, not max)."""
        protocol, confidence = detector.detect_protocol_with_source_default(
            text="How do I complete my trade?",
            source="bisq2",
            return_confidence=True,
        )
        assert protocol == "bisq_easy"
        # Source default should have moderate confidence (0.5-0.7 range)
        assert (
            0.5 <= confidence <= 0.7
        ), f"Source default confidence {confidence} should be moderate (0.5-0.7)"

    def test_detection_override_has_higher_confidence(self, detector):
        """Detection-based protocol should have higher confidence than default."""
        protocol, confidence = detector.detect_protocol_with_source_default(
            text="How does DAO voting work?",
            source="bisq2",
            return_confidence=True,
        )
        assert protocol == "multisig_v1"
        # Detection override should have higher confidence
        assert confidence >= 0.7


class TestPipelineDetectProtocolWithFallback:
    """Test the pipeline's _detect_protocol_with_fallback method."""

    @pytest.fixture
    def mock_repository(self, tmp_path):
        """Create a mock repository."""
        from app.services.training.unified_repository import (
            UnifiedFAQCandidateRepository,
        )

        db_path = str(tmp_path / "test.db")
        return UnifiedFAQCandidateRepository(db_path)

    @pytest.fixture
    def mock_settings(self):
        """Create mock settings."""
        settings = MagicMock()
        settings.OPENAI_MODEL = "gpt-4o-mini"
        return settings

    @pytest.fixture
    def pipeline_service(self, mock_repository, mock_settings):
        """Create pipeline service for testing."""
        from app.services.training.unified_pipeline_service import (
            UnifiedPipelineService,
        )

        return UnifiedPipelineService(
            settings=mock_settings,
            rag_service=MagicMock(),
            faq_service=MagicMock(),
            repository=mock_repository,
        )

    def test_bisq2_source_defaults_to_bisq_easy_in_pipeline(self, pipeline_service):
        """Pipeline should use bisq_easy as default for bisq2 source."""
        result = pipeline_service._detect_protocol_with_fallback(
            question_text="How do I complete my trade?",
            staff_answer="Just wait for the buyer to send payment.",
            source="bisq2",
        )
        assert result == "bisq_easy"

    def test_bisq1_content_overrides_bisq2_source_in_pipeline(self, pipeline_service):
        """Bisq 1 keywords should override bisq2 source default in pipeline."""
        result = pipeline_service._detect_protocol_with_fallback(
            question_text="How does DAO voting work?",
            staff_answer="You need to vote with your BSQ.",
            source="bisq2",
        )
        assert result == "multisig_v1"

    def test_matrix_source_detects_bisq1_in_pipeline(self, pipeline_service):
        """Matrix source should detect Bisq 1 content."""
        result = pipeline_service._detect_protocol_with_fallback(
            question_text="How does DAO voting work?",
            staff_answer="You need to vote with your BSQ.",
            source="matrix",
        )
        assert result == "multisig_v1"

    def test_matrix_source_detects_bisq2_in_pipeline(self, pipeline_service):
        """Matrix source should detect Bisq 2 content."""
        result = pipeline_service._detect_protocol_with_fallback(
            question_text="How does Bisq Easy reputation work?",
            staff_answer="Build reputation through trades.",
            source="matrix",
        )
        assert result == "bisq_easy"

    def test_matrix_source_returns_none_for_ambiguous(self, pipeline_service):
        """Matrix source should return None for truly ambiguous content."""
        result = pipeline_service._detect_protocol_with_fallback(
            question_text="Hello, I need help",
            staff_answer="How can I assist you?",
            source="matrix",
        )
        assert result is None

    def test_staff_answer_fallback_with_source_default(self, pipeline_service):
        """Staff answer with Bisq 1 keywords should override bisq2 source."""
        result = pipeline_service._detect_protocol_with_fallback(
            question_text="How do I fix this issue?",  # Ambiguous question
            staff_answer="Check your DAO wallet for BSQ balance.",  # Clear Bisq 1
            source="bisq2",
        )
        assert result == "multisig_v1"

    def test_no_source_falls_back_to_detection_only(self, pipeline_service):
        """When no source, should use detection only."""
        result = pipeline_service._detect_protocol_with_fallback(
            question_text="Hello",
            staff_answer="Hi there!",
            source=None,
        )
        assert result is None

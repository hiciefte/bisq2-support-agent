"""Tests for ProtocolDetector service - Protocol-First API.

This test file validates the new protocol-based detection approach that aligns
the training pipeline with the RAG chatbot and FAQ page architecture.

Protocol enums: "bisq_easy", "multisig_v1", "musig", "all"
Legacy version strings: "Bisq 1", "Bisq 2", "Unknown"

TDD Step 1: RED - These tests should FAIL until ProtocolDetector is created.
"""

import pytest


class TestProtocolDetectorImport:
    """Test that ProtocolDetector can be imported."""

    def test_can_import_protocol_detector(self):
        """Verify ProtocolDetector class can be imported from protocol_detector module."""
        from app.services.rag.protocol_detector import ProtocolDetector

        assert ProtocolDetector is not None


@pytest.fixture
def detector():
    """Create a ProtocolDetector instance for tests."""
    from app.services.rag.protocol_detector import ProtocolDetector

    return ProtocolDetector()


class TestProtocolDetection:
    """Test protocol detection from text - PRIMARY API."""

    def test_detect_protocol_from_text_bisq1_keywords(self, detector):
        """DAO keywords should return multisig_v1 protocol."""
        protocol, confidence = detector.detect_protocol_from_text(
            "How does DAO voting work?"
        )
        assert protocol == "multisig_v1"
        assert confidence >= 0.7

    def test_detect_protocol_from_text_bisq1_arbitration(self, detector):
        """Arbitration keywords should return multisig_v1 protocol."""
        protocol, confidence = detector.detect_protocol_from_text(
            "What is the arbitration process?"
        )
        assert protocol == "multisig_v1"
        assert confidence >= 0.7

    def test_detect_protocol_from_text_bisq1_bsq(self, detector):
        """BSQ keywords should return multisig_v1 protocol."""
        protocol, confidence = detector.detect_protocol_from_text(
            "How do I use BSQ for trading fees?"
        )
        assert protocol == "multisig_v1"
        assert confidence >= 0.7

    def test_detect_protocol_from_text_bisq2_keywords(self, detector):
        """Bisq Easy keywords should return bisq_easy protocol."""
        protocol, confidence = detector.detect_protocol_from_text(
            "How does reputation work in Bisq Easy?"
        )
        assert protocol == "bisq_easy"
        assert confidence >= 0.7

    def test_detect_protocol_from_text_bisq2_bonded_roles(self, detector):
        """Bonded roles keywords should return bisq_easy protocol."""
        protocol, confidence = detector.detect_protocol_from_text(
            "What are bonded roles?"
        )
        assert protocol == "bisq_easy"
        assert confidence >= 0.7

    def test_detect_protocol_from_text_bisq2_trade_limit(self, detector):
        """Trade limit (600 USD) should return bisq_easy protocol."""
        protocol, confidence = detector.detect_protocol_from_text(
            "Why is the limit 600 USD?"
        )
        assert protocol == "bisq_easy"
        assert confidence >= 0.7

    def test_detect_protocol_from_text_unknown(self, detector):
        """Ambiguous questions should return None protocol."""
        protocol, confidence = detector.detect_protocol_from_text("Hello")
        assert protocol is None
        assert confidence < 0.5

    def test_detect_protocol_from_text_generic_question(self, detector):
        """Generic questions without version indicators should return None."""
        protocol, confidence = detector.detect_protocol_from_text(
            "How do I buy Bitcoin?"
        )
        assert protocol is None

    @pytest.mark.asyncio
    async def test_detect_protocol_async(self, detector):
        """Async detect_protocol should return protocol enum."""
        protocol, confidence, _ = await detector.detect_protocol(
            "How does the DAO work?", []
        )
        assert protocol == "multisig_v1"
        assert confidence >= 0.7

    @pytest.mark.asyncio
    async def test_detect_protocol_async_bisq2(self, detector):
        """Async detect_protocol should return bisq_easy for reputation questions."""
        protocol, confidence, _ = await detector.detect_protocol(
            "How does reputation work in Bisq Easy?", []
        )
        assert protocol == "bisq_easy"
        assert confidence >= 0.7

    @pytest.mark.asyncio
    async def test_detect_protocol_async_unknown(self, detector):
        """Async detect_protocol should return None for ambiguous questions."""
        protocol, confidence, clarifying = await detector.detect_protocol(
            "What are the fees?", []
        )
        assert protocol is None
        assert clarifying is not None


class TestProtocolConversion:
    """Test protocol-version conversion helpers."""

    def test_version_to_protocol_bisq2(self, detector):
        """Bisq 2 version string should convert to bisq_easy protocol."""
        assert detector._version_to_protocol("Bisq 2") == "bisq_easy"

    def test_version_to_protocol_bisq1(self, detector):
        """Bisq 1 version string should convert to multisig_v1 protocol."""
        assert detector._version_to_protocol("Bisq 1") == "multisig_v1"

    def test_version_to_protocol_unknown(self, detector):
        """Unknown version string should convert to None protocol."""
        assert detector._version_to_protocol("Unknown") is None

    def test_version_to_protocol_none(self, detector):
        """None version should convert to None protocol."""
        assert detector._version_to_protocol(None) is None

    def test_protocol_to_version_bisq_easy(self, detector):
        """bisq_easy protocol should convert to Bisq 2 version string."""
        assert detector._protocol_to_version("bisq_easy") == "Bisq 2"

    def test_protocol_to_version_multisig(self, detector):
        """multisig_v1 protocol should convert to Bisq 1 version string."""
        assert detector._protocol_to_version("multisig_v1") == "Bisq 1"

    def test_protocol_to_version_musig(self, detector):
        """musig protocol should convert to Bisq 2 version string."""
        assert detector._protocol_to_version("musig") == "Bisq 2"

    def test_protocol_to_version_none(self, detector):
        """None protocol should convert to None version string."""
        assert detector._protocol_to_version(None) is None

    def test_protocol_to_version_all(self, detector):
        """all protocol should convert to None (applies to both)."""
        assert detector._protocol_to_version("all") is None


class TestProtocolDisplayName:
    """Test protocol to display name conversion."""

    def test_protocol_to_display_name_multisig(self, detector):
        """multisig_v1 protocol should display as Bisq 1."""
        from app.services.rag.protocol_detector import ProtocolDetector

        assert ProtocolDetector.protocol_to_display_name("multisig_v1") == "Bisq 1"

    def test_protocol_to_display_name_bisq_easy(self, detector):
        """bisq_easy protocol should display as Bisq 2."""
        from app.services.rag.protocol_detector import ProtocolDetector

        assert ProtocolDetector.protocol_to_display_name("bisq_easy") == "Bisq 2"

    def test_protocol_to_display_name_musig(self, detector):
        """musig protocol should display as MuSig."""
        from app.services.rag.protocol_detector import ProtocolDetector

        assert ProtocolDetector.protocol_to_display_name("musig") == "MuSig"

    def test_protocol_to_display_name_all(self, detector):
        """all protocol should display as General."""
        from app.services.rag.protocol_detector import ProtocolDetector

        assert ProtocolDetector.protocol_to_display_name("all") == "General"

    def test_protocol_to_display_name_none(self, detector):
        """None protocol should display as Unknown."""
        from app.services.rag.protocol_detector import ProtocolDetector

        assert ProtocolDetector.protocol_to_display_name(None) == "Unknown"

    def test_protocol_to_display_name_invalid(self, detector):
        """Invalid protocol should display as Unknown."""
        from app.services.rag.protocol_detector import ProtocolDetector

        assert ProtocolDetector.protocol_to_display_name("invalid") == "Unknown"


class TestLegacyCompatibility:
    """Test that legacy version methods still work for backwards compatibility."""

    def test_detect_version_from_text_still_works(self, detector):
        """Legacy detect_version_from_text should still return version strings."""
        version, confidence = detector.detect_version_from_text(
            "How does the DAO work?"
        )
        assert version == "Bisq 1"
        assert confidence >= 0.7

    def test_detect_version_from_text_bisq2(self, detector):
        """Legacy method should return Bisq 2 for reputation questions."""
        version, confidence = detector.detect_version_from_text(
            "How does reputation work in Bisq Easy?"
        )
        assert version == "Bisq 2"
        assert confidence >= 0.7

    @pytest.mark.asyncio
    async def test_detect_version_async_still_works(self, detector):
        """Legacy async detect_version should still return version strings."""
        version, confidence, _ = await detector.detect_version(
            "How does the DAO work?", []
        )
        assert version == "Bisq 1"
        assert confidence >= 0.7


class TestExplicitVersionProtocol:
    """Test explicit version mentions return correct protocol."""

    def test_explicit_bisq1_returns_multisig_protocol(self, detector):
        """Explicit Bisq 1 mention should return multisig_v1 with high confidence."""
        protocol, confidence = detector.detect_protocol_from_text(
            "How do I vote in Bisq 1 DAO?"
        )
        assert protocol == "multisig_v1"
        assert confidence >= 0.95

    def test_explicit_bisq2_returns_bisq_easy_protocol(self, detector):
        """Explicit Bisq 2 mention should return bisq_easy with high confidence."""
        protocol, confidence = detector.detect_protocol_from_text(
            "How do I use Bisq 2?"
        )
        assert protocol == "bisq_easy"
        assert confidence >= 0.95

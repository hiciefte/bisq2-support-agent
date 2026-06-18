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

    def test_detect_protocol_from_text_bisq1_error_term(self, detector):
        """Bisq 1-specific trade error terms should force multisig_v1."""
        protocol, confidence = detector.detect_protocol_from_text(
            "What does BuyerVerifiesPreparedDelayedPayoutTx mean?"
        )
        assert protocol == "multisig_v1"
        assert confidence >= 0.7

    def test_detect_protocol_from_text_bisq1_deposit_transaction(self, detector):
        """Deposit transaction wording should map to Bisq 1/multisig flows."""
        protocol, confidence = detector.detect_protocol_from_text(
            "If the deposit transaction is confirmed on-chain but the trade is stuck"
        )
        assert protocol == "multisig_v1"
        assert confidence >= 0.7

    def test_detect_protocol_from_text_bisq1_deposit_txid(self, detector):
        """Deposit txid wording should map to Bisq 1/multisig flows."""
        protocol, confidence = detector.detect_protocol_from_text(
            "The trade failed and there is no valid deposit txid."
        )
        assert protocol == "multisig_v1"
        assert confidence >= 0.7

    def test_detect_protocol_from_text_bisq1_market_price_tolerance(self, detector):
        """Market-price tolerance trade failures are Bisq 1 signals."""
        protocol, confidence = detector.detect_protocol_from_text(
            "The offer failed because of a market price tolerance error."
        )
        assert protocol == "multisig_v1"
        assert confidence >= 0.7

    def test_detect_protocol_from_text_bisq1_price_tolerance(self, detector):
        """Price tolerance trade failures are Bisq 1 signals."""
        protocol, confidence = detector.detect_protocol_from_text(
            "The offer failed because of a price tolerance error."
        )
        assert protocol == "multisig_v1"
        assert confidence >= 0.7

    def test_detect_protocol_from_text_bisq1_support_ticket_shortcut(self, detector):
        """Bisq 1 support ticket shortcuts should route to multisig_v1."""
        protocol, confidence = detector.detect_protocol_from_text(
            "Select the trade and press Ctrl+O to open a support ticket."
        )
        assert protocol == "multisig_v1"
        assert confidence >= 0.7

    def test_detect_protocol_from_text_support_ticket_alone_is_ambiguous(
        self, detector
    ):
        """Support-ticket wording alone is shared enough to stay ambiguous."""
        protocol, confidence = detector.detect_protocol_from_text(
            "How do I open a support ticket?"
        )
        assert protocol is None
        assert confidence == 0.0

    def test_detect_protocol_from_text_mediation_chat_alone_is_ambiguous(
        self, detector
    ):
        """Mediation-chat wording alone should not force Bisq 1 routing."""
        protocol, confidence = detector.detect_protocol_from_text("mediation chat")
        assert protocol is None
        assert confidence == 0.0

    def test_detect_protocol_from_text_bisq1_dispute_resolution_wiki_url(
        self, detector
    ):
        """Bisq 1 dispute-resolution wiki URLs are precise multisig signals."""
        protocol, confidence = detector.detect_protocol_from_text(
            "See https://bisq.wiki/Dispute_resolution#Level_2:_Mediation for details."
        )
        assert protocol == "multisig_v1"
        assert confidence >= 0.7

    def test_detect_protocol_from_text_bisq1_account_signing_terms(self, detector):
        """Account-signing limits are Bisq 1 support signals."""
        protocol, confidence = detector.detect_protocol_from_text(
            "What is the minimum payment to get the account info signed?"
        )
        assert protocol == "multisig_v1"
        assert confidence >= 0.7

    def test_detect_protocol_from_text_bisq1_output_errors(self, detector):
        """Payout/output error wording should map to Bisq 1."""
        protocol, confidence = detector.detect_protocol_from_text(
            "After confirming payment received, a trade shows cancelled/output errors"
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


class TestHistorySignals:
    """Test version detection behavior for mixed history prompts."""

    @pytest.mark.asyncio
    async def test_prefers_user_history_signal_over_mixed_assistant_prompt(
        self, detector
    ):
        """User history saying Bisq Easy should not be overridden by assistant compare prompt."""
        history = [
            {"role": "user", "content": "Ich nutze Bisq Easy"},
            {
                "role": "assistant",
                "content": "Verwenden Sie Bisq 1 oder Bisq Easy (Bisq 2)?",
            },
        ]
        version, confidence, _ = await detector.detect_version(
            "Wie kann ich BTC mit Euro kaufen?",
            history,
        )
        assert version == "Bisq 2"
        assert confidence >= 0.7

    @pytest.mark.asyncio
    async def test_mixed_assistant_prompt_only_does_not_force_bisq1(self, detector):
        """Assistant compare prompts mentioning both versions should not force Bisq 1."""
        history = [
            {
                "role": "assistant",
                "content": "Are you using Bisq 1 or Bisq Easy (Bisq 2)?",
            },
        ]
        version, confidence, clarifying = await detector.detect_version(
            "How can I buy Bitcoin?",
            history,
        )
        assert version == "Unknown"
        assert confidence == 0.30
        assert clarifying is not None


class TestOperationalSupportQuestions:
    """Operational support questions should not force version clarification."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("question"),
        [
            "How can I open a mediation?",
            "How can I cancel a trade if I haven't received payment?",
            "Can I cancel a trade if the delivery address is invalid?",
            "What should I do if my Bisq wallet fails to restore from seed?",
            "Can I start trading after installing an update, or is there something I should be aware of?",
            "How do I verify the Bisq installer on Linux?",
            "If PGP says good signature, is it safe to use?",
            "I wanna talk to a manager!!",
        ],
    )
    async def test_operational_support_question_skips_version_clarification(
        self, detector, question
    ):
        version, confidence, clarifying = await detector.detect_version(question, [])
        assert version == "Unknown"
        assert confidence == 0.45
        assert clarifying is None

    @pytest.mark.asyncio
    async def test_generic_question_still_requests_clarification(self, detector):
        version, confidence, clarifying = await detector.detect_version(
            "What are the fees?",
            [],
        )
        assert version == "Unknown"
        assert confidence == 0.30
        assert clarifying is not None


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

    def test_bisq2_problem_with_bisq1_comparator_returns_bisq_easy(self, detector):
        """A Bisq 1 comparison must not retag a Bisq 2 problem as Bisq 1."""
        protocol, confidence = detector.detect_protocol_from_text(
            "My Bisq2 says 0 connections to Tor and does not list any offers. "
            "Bisq1 connects just fine. Using MacOS version. Any ideas?"
        )
        assert protocol == "bisq_easy"
        assert confidence >= 0.85

    def test_mixed_explicit_versions_without_clear_target_stays_ambiguous(
        self, detector
    ):
        """Mixed explicit version text should not default to Bisq 1 by order."""
        protocol, confidence = detector.detect_protocol_from_text(
            "Can I import my Bisq2 account to Bisq1?"
        )
        assert protocol is None
        assert confidence == 0.0

    def test_single_explicit_version_with_opposite_domain_signal_stays_ambiguous(
        self, detector
    ):
        """A secondary cross-version reference must not override the main topic."""
        protocol, confidence = detector.detect_protocol_from_text(
            "Are Cash by Mail accounts signed after making a valid buy from a "
            "signed account, despite not being limited by signing, for use in "
            "Bisq2 signed age?"
        )
        assert protocol is None
        assert confidence == 0.0

    def test_single_explicit_with_opposite_domain_keywords_stays_ambiguous(
        self, detector
    ):
        """Ambiguity must not fall through into keyword scoring."""
        protocol, confidence = detector.detect_protocol_from_text(
            "In Bisq2, do account limits and deposit txid rules still apply?"
        )
        assert protocol is None
        assert confidence == 0.0


class TestSourceAwareDefaults:
    """Test source-aware default protocol detection for ambiguous questions."""

    def test_bisq2_source_defaults_to_bisq_easy(self, detector):
        """Ambiguous text from bisq2 source should default to bisq_easy."""
        protocol, confidence = detector.detect_protocol_with_source_default(
            "WTF?!",
            source="bisq2",
            return_confidence=True,
        )
        assert protocol == "bisq_easy"
        assert confidence >= 0.6

    def test_matrix_source_stays_ambiguous_without_content_signals(self, detector):
        """Matrix has no source default and should remain ambiguous."""
        protocol, confidence = detector.detect_protocol_with_source_default(
            "WTF?!",
            source="matrix",
            return_confidence=True,
        )
        assert protocol is None
        assert confidence == 0.0

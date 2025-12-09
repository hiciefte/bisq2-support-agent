"""
Test suite for Matrix message classification layers.

Tests follow TDD methodology - write tests first, then implement.
"""

import pytest
from app.services.shadow_mode.classifiers import (
    ContentTypeFilter,
    ConversationContextAnalyzer,
    MessageIntentClassifier,
    MultiLayerClassifier,
    SpeakerRoleClassifier,
)

# Official Bisq support agents from https://bisq.wiki/Support_Agent
OFFICIAL_SUPPORT_STAFF = [
    "darawhelan",
    "luis3672",
    "mwithm",  # MnM
    "pazza83",
    "strayorigin",
    "suddenwhipvapor",
]


class TestSpeakerRoleClassifier:
    """Test speaker role detection (staff vs user)."""

    def test_detect_official_support_staff_by_username(self):
        """Should identify official support agents by username."""
        classifier = SpeakerRoleClassifier()

        # Test exact matches
        role, confidence = classifier.classify_speaker_role(
            "You can try resyncing the DAO",
            "@pazza83:matrix.org",
            OFFICIAL_SUPPORT_STAFF,
        )
        assert role == "staff"
        assert confidence == 1.0

        role, confidence = classifier.classify_speaker_role(
            "Check your logs at the time",
            "@suddenwhipvapor:matrix.org",
            OFFICIAL_SUPPORT_STAFF,
        )
        assert role == "staff"
        assert confidence == 1.0

    def test_detect_staff_by_advisory_language(self):
        """Should detect staff by advisory language patterns."""
        classifier = SpeakerRoleClassifier()

        messages = [
            "You should try restarting the application",
            "You can check your logs for more details",
            "It is best to wait it out",
            "I recommend syncing with these seed nodes",
            "You might want to restart Bisq",
        ]

        for msg in messages:
            role, confidence = classifier.classify_speaker_role(
                msg, "@unknown:matrix.org", OFFICIAL_SUPPORT_STAFF
            )
            assert role == "staff", f"Failed for: {msg}"
            assert confidence > 0.6

    def test_detect_staff_by_diagnostic_questions(self):
        """Should detect staff asking diagnostic questions."""
        classifier = SpeakerRoleClassifier()

        messages = [
            "Are you seeing this in all markets?",
            "What market was the offer on?",
            "Which version are you running?",
            "Did you try restarting?",
            "Is it always the same taker?",
        ]

        for msg in messages:
            role, confidence = classifier.classify_speaker_role(
                msg, "@helper:matrix.org", OFFICIAL_SUPPORT_STAFF
            )
            assert role == "staff", f"Failed for: {msg}"
            assert confidence > 0.6

    def test_detect_staff_by_explanatory_statements(self):
        """Should detect staff providing explanations."""
        classifier = SpeakerRoleClassifier()

        messages = [
            "This means the DAO is not synchronized",
            "This indicates a seed node issue",
            "This happens when the price nodes are down",
            "The reason is that your snapshot height doesn't match",
            "This can prevent traders from making offers",
        ]

        for msg in messages:
            role, confidence = classifier.classify_speaker_role(
                msg, "@explainer:matrix.org", OFFICIAL_SUPPORT_STAFF
            )
            assert role == "staff", f"Failed for: {msg}"
            assert confidence > 0.6

    def test_detect_user_by_first_person_problems(self):
        """Should detect users describing their own problems."""
        classifier = SpeakerRoleClassifier()

        messages = [
            "I'm getting this error with my offers",
            "My DAO is not syncing",
            "I have been restarting for 6 hours",
            "I can't see any offers in the market",
            "I tried resyncing but it didn't work",
        ]

        for msg in messages:
            role, confidence = classifier.classify_speaker_role(
                msg, "@user123:matrix.org", OFFICIAL_SUPPORT_STAFF
            )
            assert role == "user", f"Failed for: {msg}"
            assert confidence > 0.6

    def test_detect_user_by_help_seeking(self):
        """Should detect users asking for help."""
        classifier = SpeakerRoleClassifier()

        messages = [
            "Can someone help me with this error?",
            "Anyone know how to fix the DAO sync issue?",
            "How do I check if my DAO is synchronized?",
            "What should I do if offers won't load?",
            "Any advice would be appreciated",
        ]

        for msg in messages:
            role, confidence = classifier.classify_speaker_role(
                msg, "@needshelp:matrix.org", OFFICIAL_SUPPORT_STAFF
            )
            assert role == "user", f"Failed for: {msg}"
            assert confidence > 0.6

    def test_unknown_role_for_ambiguous_messages(self):
        """Should return unknown for ambiguous messages."""
        classifier = SpeakerRoleClassifier()

        messages = [
            "Same here",
            "Interesting",
            "Good point",
        ]

        for msg in messages:
            role, confidence = classifier.classify_speaker_role(
                msg, "@someone:matrix.org", OFFICIAL_SUPPORT_STAFF
            )
            assert role == "unknown", f"Should be unknown for: {msg}"
            assert confidence == 0.0


class TestConversationContextAnalyzer:
    """Test conversation context analysis."""

    def test_detect_follow_up_acknowledgments(self):
        """Should detect follow-up acknowledgments."""
        analyzer = ConversationContextAnalyzer()

        messages = [
            "Yes, I tried that",
            "No, it didn't work",
            "Okay, I'll try that",
            "Thanks for the help",
            "Got it, makes sense",
            "Alrighty no problem",
        ]

        prev = ["Have you tried restarting the application?"]

        for msg in messages:
            assert analyzer.is_follow_up_message(msg, prev), f"Failed for: {msg}"

    def test_detect_follow_up_by_content_overlap(self):
        """Should detect follow-ups by referencing previous message content."""
        analyzer = ConversationContextAnalyzer()

        prev = ["You can resync the DAO with the option --seedNodes"]
        msg = "I tried the seedNodes option but still having issues"

        assert analyzer.is_follow_up_message(msg, prev)

    def test_not_follow_up_for_initial_questions(self):
        """Should not classify initial questions as follow-ups."""
        analyzer = ConversationContextAnalyzer()

        messages = [
            "Hi, I'm having trouble syncing my DAO",
            "Hello, can someone help with this error?",
            "I have a quick question about offers",
        ]

        prev = []

        for msg in messages:
            assert not analyzer.is_follow_up_message(
                msg, prev
            ), f"Should not be follow-up: {msg}"

    def test_detect_initial_questions(self):
        """Should detect messages starting new support requests."""
        analyzer = ConversationContextAnalyzer()

        messages = [
            "Hi, I'm getting an error when taking offers",
            "Hello, my DAO won't sync",
            "Hey, quick question about reputation",
            "I have a problem with my wallet",
            "I got this error message today",
        ]

        for msg in messages:
            assert analyzer.is_initial_question(msg), f"Failed for: {msg}"


class TestMessageIntentClassifier:
    """Test message intent classification."""

    def test_classify_support_questions(self):
        """Should classify genuine support questions."""
        classifier = MessageIntentClassifier()

        messages = [
            "How do I restore my wallet?",
            "I'm getting this error with my offers",
            "My DAO is not working",
            "I can't see any offers",
            "What should I do if sync fails?",
        ]

        for msg in messages:
            intent, confidence = classifier.classify_intent(msg)
            assert intent == "support_question", f"Failed for: {msg}"
            assert confidence > 0.6

    def test_classify_warnings(self):
        """Should classify warning messages."""
        classifier = MessageIntentClassifier()

        messages = [
            "Scammers are impersonating support agents",
            "Be careful of phishing attempts",
            "Watch out for fake support websites",
            "Someone tried to scam me with a fake Bisq site",
        ]

        for msg in messages:
            intent, confidence = classifier.classify_intent(msg)
            assert intent == "warning", f"Failed for: {msg}"
            assert confidence > 0.6

    def test_classify_acknowledgments(self):
        """Should classify acknowledgment messages."""
        classifier = MessageIntentClassifier()

        messages = [
            "Thanks, that worked!",
            "Got it, understood",
            "Thank you for the help",
            "That fixed the issue",
            "Appreciate the assistance",
        ]

        for msg in messages:
            intent, confidence = classifier.classify_intent(msg)
            assert intent == "acknowledgment", f"Failed for: {msg}"
            assert confidence > 0.6

    def test_classify_information_sharing(self):
        """Should classify information sharing messages."""
        classifier = MessageIntentClassifier()

        messages = [
            "FYI, the seed nodes are having issues",
            "I found this in the FAQs",
            "Just letting you know about the DAO sync problem",
            "Here is the community forum link",
        ]

        for msg in messages:
            intent, confidence = classifier.classify_intent(msg)
            assert intent == "information_sharing", f"Failed for: {msg}"
            assert confidence > 0.6

    def test_classify_staff_explanations(self):
        """Should classify staff explanation messages."""
        classifier = MessageIntentClassifier()

        messages = [
            "This means the snapshot height doesn't match",
            "You can try resyncing with these seed nodes",
            "If there is an issue with seed nodes it can prevent trades",
            "Once it resolved Bisq will run normally again",
        ]

        for msg in messages:
            intent, confidence = classifier.classify_intent(msg)
            assert intent == "staff_explanation", f"Failed for: {msg}"
            assert confidence > 0.6


class TestContentTypeFilter:
    """Test content type filtering."""

    def test_detect_url_only_messages(self):
        """Should detect messages containing only URLs."""
        messages = [
            "https://matrix.to/#/!room:server",
            "https://bisq.community/t/psa-ongoing-dao-sync-issue/13399/3",
            "http://example.com/path?param=value",
        ]

        for msg in messages:
            assert ContentTypeFilter.is_url_only(msg), f"Failed for: {msg}"

    def test_not_url_only_for_text_with_url(self):
        """Should not classify text with URLs as URL-only."""
        messages = [
            "Check this out: https://bisq.wiki/Support",
            "See the forum post at https://bisq.community for details",
        ]

        for msg in messages:
            assert not ContentTypeFilter.is_url_only(
                msg
            ), f"Should not be URL-only: {msg}"

    def test_detect_quoted_text(self):
        """Should detect messages with >50% quoted text."""
        msg = 'I found something in the FAQs: "My currency market has few or no offers. What can I do? Market liquidity varies..."'
        assert ContentTypeFilter.is_quoted_text(msg)

    def test_extract_original_content(self):
        """Should extract only original content."""
        msg = 'The FAQ says "try restarting" but https://example.com also has info'
        content = ContentTypeFilter.extract_original_content(msg)

        assert "try restarting" not in content
        assert "https://example.com" not in content
        assert "FAQ says" in content
        assert "also has info" in content

    def test_has_meaningful_content(self):
        """Should detect if message has meaningful content."""
        # Has meaningful content
        assert ContentTypeFilter.has_meaningful_content(
            "I'm having trouble syncing my DAO wallet"
        )

        # Too short
        assert not ContentTypeFilter.has_meaningful_content("ok")

        # Only quoted text
        assert not ContentTypeFilter.has_meaningful_content(
            '"This is all quoted text from elsewhere"'
        )

        # Only URL
        assert not ContentTypeFilter.has_meaningful_content("https://example.com")


class TestMultiLayerClassifier:
    """Test complete multi-layer classification pipeline."""

    def test_filter_url_only_messages(self):
        """Should filter out URL-only messages."""
        classifier = MultiLayerClassifier(OFFICIAL_SUPPORT_STAFF)

        result = classifier.classify_message(
            "https://matrix.to/#/!room:server", "@user:matrix.org"
        )

        assert result["is_question"] is False
        assert result["reason"] == "url_only"
        assert result["confidence"] == 1.0

    def test_filter_support_staff_responses(self):
        """Should filter out support staff responses."""
        classifier = MultiLayerClassifier(OFFICIAL_SUPPORT_STAFF)

        result = classifier.classify_message(
            "You can try resyncing the DAO with the option --seedNodes",
            "@pazza83:matrix.org",
        )

        assert result["is_question"] is False
        assert result["reason"] == "support_staff_response"
        assert result["speaker_role"] == "staff"

    def test_filter_follow_up_messages(self):
        """Should filter out follow-up acknowledgments."""
        classifier = MultiLayerClassifier(OFFICIAL_SUPPORT_STAFF)

        prev_messages = ["Have you tried restarting the application?"]
        result = classifier.classify_message(
            "Yes, I tried that already", "@user:matrix.org", prev_messages
        )

        assert result["is_question"] is False
        assert result["reason"] == "follow_up_message"
        assert result["is_follow_up"] is True

    def test_filter_warnings(self):
        """Should filter out warning messages."""
        classifier = MultiLayerClassifier(OFFICIAL_SUPPORT_STAFF)

        result = classifier.classify_message(
            "Scammers set up similar names to support agents", "@user:matrix.org"
        )

        assert result["is_question"] is False
        assert result["reason"] == "intent_warning"
        assert result["intent"] == "warning"

    def test_filter_acknowledgments(self):
        """Should filter out acknowledgment messages."""
        classifier = MultiLayerClassifier(OFFICIAL_SUPPORT_STAFF)

        result = classifier.classify_message(
            "Thanks, that fixed the issue!", "@user:matrix.org"
        )

        assert result["is_question"] is False
        assert result["reason"] == "intent_acknowledgment"

    def test_accept_genuine_user_questions(self):
        """Should accept genuine user support questions."""
        classifier = MultiLayerClassifier(OFFICIAL_SUPPORT_STAFF)

        messages = [
            "I'm getting this error with my offers when someone tries to accept them",
            "My DAO is not syncing, been restarting for 6 hours",
            "How do I check if my DAO is synchronized?",
            "I can't see any offers after moving my Bisq to another computer",
        ]

        for msg in messages:
            result = classifier.classify_message(msg, "@user123:matrix.org")
            assert result["is_question"] is True, f"Should accept: {msg}"
            assert result["reason"] == "support_question", f"Wrong reason for: {msg}"
            assert result["confidence"] > 0.5

    def test_real_world_false_positives(self):
        """Test real-world false positive examples from production data."""
        classifier = MultiLayerClassifier(OFFICIAL_SUPPORT_STAFF)

        # Support staff responses (from production data)
        false_positives = [
            (
                "If there is an issue with the seed nodes it can prevent traders...",
                "support_staff_response",
            ),
            (
                "Are seeing no offers in any market or just specific ones?",
                "support_staff_response",
            ),
            (
                "Sometimes if the pricenodes are off then the error can also appear",
                None,
            ),
            ("You can also check your logs at the time the offer was taken", None),
            # Follow-ups
            ("alrighty no problem, i was tryna make an offer", "follow_up_message"),
            ("Indeed, I don't have that problem at the moment.", None),
            # Warnings
            (
                "Scammers set up similar names to support agents and monitor this chat",
                "intent_warning",
            ),
            # URLs
            (
                "https://bisq.community/t/psa-ongoing-dao-sync-issue/13399/3",
                "url_only",
            ),
        ]

        for msg, expected_reason in false_positives:
            result = classifier.classify_message(msg, "@someone:matrix.org")
            assert result["is_question"] is False, f"Should reject: {msg}"
            if expected_reason:
                assert result["reason"] == expected_reason, f"Wrong reason for: {msg}"

    def test_real_world_true_positives(self):
        """Test real-world true positive examples from production data."""
        classifier = MultiLayerClassifier(OFFICIAL_SUPPORT_STAFF)

        # Genuine user questions (from production data)
        true_positives = [
            "Have been restarting and resyncing for 6 hours, and my bsq-wallet is still empty",
            "Hello, if I only use the Bisq daemon, how can I check if the DAO is synchronized?",
            "I performed a BSQ Swap, but I can't see any BSQ anywhere in my wallet",
            "I'm getting this error with my offers when someone tries to accept them",
            "Hi, I moved my bisq to another computer. It seems okay, but I don't see any offers",
        ]

        for msg in true_positives:
            result = classifier.classify_message(msg, "@user456:matrix.org")
            assert result["is_question"] is True, f"Should accept: {msg}"
            assert result["confidence"] > 0.5


# Integration tests
class TestClassifierIntegration:
    """Integration tests for classifier workflow."""

    def test_progressive_filtering(self):
        """Test that messages are filtered progressively through layers."""
        classifier = MultiLayerClassifier(OFFICIAL_SUPPORT_STAFF)

        # URL filtered by Layer 4 (content type)
        result = classifier.classify_message("https://example.com")
        assert result["reason"] == "url_only"

        # Staff filtered by Layer 1 (speaker role)
        result = classifier.classify_message("You can try this", "@pazza83:matrix.org")
        assert result["reason"] == "support_staff_response"

        # Follow-up filtered by Layer 2 (context)
        result = classifier.classify_message(
            "Yes, I tried that", "@user:matrix.org", ["Have you tried X?"]
        )
        assert result["reason"] == "follow_up_message"

        # Warning filtered by Layer 3 (intent)
        result = classifier.classify_message("Beware of scammers", "@user:matrix.org")
        assert result["reason"] == "intent_warning"

        # Question passes all layers
        result = classifier.classify_message(
            "I'm getting an error with my DAO", "@user:matrix.org"
        )
        assert result["is_question"] is True

    def test_confidence_scoring(self):
        """Test confidence scores are appropriate."""
        classifier = MultiLayerClassifier(OFFICIAL_SUPPORT_STAFF)

        # High confidence rejections (content type filters)
        result = classifier.classify_message("https://example.com")
        assert result["confidence"] == 1.0

        # High confidence rejections (known staff)
        result = classifier.classify_message("You can try this", "@pazza83:matrix.org")
        assert result["confidence"] >= 0.9

        # Medium-high confidence (pattern-based)
        result = classifier.classify_message(
            "I'm getting this error", "@user:matrix.org"
        )
        assert 0.6 <= result["confidence"] <= 1.0


# Edge cases
class TestClassifierEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_empty_message(self):
        """Should handle empty messages."""
        classifier = MultiLayerClassifier(OFFICIAL_SUPPORT_STAFF)
        result = classifier.classify_message("", "@user:matrix.org")
        assert result["is_question"] is False
        assert result["reason"] == "no_content"

    def test_very_short_message(self):
        """Should filter very short messages."""
        classifier = MultiLayerClassifier(OFFICIAL_SUPPORT_STAFF)
        result = classifier.classify_message("ok", "@user:matrix.org")
        assert result["is_question"] is False

    def test_mixed_signals(self):
        """Should handle messages with mixed classification signals."""
        classifier = MultiLayerClassifier(OFFICIAL_SUPPORT_STAFF)

        # User asking follow-up question (should still be classified as question)
        result = classifier.classify_message(
            "Yes, but how do I fix it?",
            "@user:matrix.org",
            ["Have you tried restarting?"],
        )
        # This is ambiguous - could be follow-up or new question
        # Implementation should decide conservative approach

    def test_unicode_and_special_characters(self):
        """Should handle unicode and special characters."""
        classifier = MultiLayerClassifier(OFFICIAL_SUPPORT_STAFF)

        messages = [
            "I'm getting errors with €50 offers",
            "My DAO won't sync 😞",
            "How do I restore from 12-word seed?",
        ]

        for msg in messages:
            result = classifier.classify_message(msg, "@user:matrix.org")
            # Should not crash, should classify based on content
            assert isinstance(result["is_question"], bool)

    def test_multiline_messages(self):
        """Should handle multiline messages."""
        classifier = MultiLayerClassifier(OFFICIAL_SUPPORT_STAFF)

        msg = """Hi everyone,

I'm having trouble with my DAO sync.
It's been stuck for hours.

Any advice?"""

        result = classifier.classify_message(msg, "@user:matrix.org")
        assert result["is_question"] is True

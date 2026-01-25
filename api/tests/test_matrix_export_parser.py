"""Tests for Matrix export parser."""

import pytest
from app.services.training.matrix_export_parser import (
    TRUSTED_STAFF_IDS,
    MatrixExportParser,
)


class TestMatrixExportParser:
    """Test cases for MatrixExportParser."""

    @pytest.fixture
    def parser(self):
        """Create a parser instance for testing."""
        return MatrixExportParser()

    @pytest.fixture
    def custom_staff_parser(self):
        """Create a parser with custom staff list."""
        return MatrixExportParser(
            trusted_staff_ids={
                "@teststaff:matrix.bisq.network",
                "@admin:matrix.bisq.network",
            }
        )

    # === Staff Detection Tests (Security v2.0) ===

    def test_is_staff_with_full_matrix_id(self, parser):
        """Test staff detection uses full Matrix ID, not just username."""
        # Known staff member with correct homeserver
        assert parser._is_staff("@mwithm:matrix.bisq.network") is True
        assert parser._is_staff("@suddenwhipvapor:matrix.bisq.network") is True

    def test_is_staff_case_insensitive(self, parser):
        """Test staff detection is case insensitive."""
        assert parser._is_staff("@MWITHM:matrix.bisq.network") is True
        assert parser._is_staff("@MwItHm:MATRIX.bisq.NETWORK") is True

    def test_is_staff_rejects_wrong_homeserver(self, parser):
        """SECURITY: Test that username on different homeserver is NOT staff."""
        # Same username but different homeserver - should be rejected
        assert parser._is_staff("@mwithm:attacker.com") is False
        assert parser._is_staff("@suddenwhipvapor:evil.org") is False

    def test_is_staff_rejects_unknown_users(self, parser):
        """Test that unknown users are not identified as staff."""
        assert parser._is_staff("@random_user:matrix.org") is False
        assert parser._is_staff("@someone:matrix.bisq.network") is False

    def test_custom_staff_list(self, custom_staff_parser):
        """Test parser with custom staff list."""
        assert custom_staff_parser._is_staff("@teststaff:matrix.bisq.network") is True
        assert custom_staff_parser._is_staff("@admin:matrix.bisq.network") is True
        # Default staff should NOT be recognized
        assert custom_staff_parser._is_staff("@mwithm:matrix.bisq.network") is False

    # === PII Anonymization Tests (GDPR v2.0) ===

    def test_anonymize_pii_email(self, parser):
        """Test email addresses are anonymized."""
        text = "Contact me at user@example.com for help"
        result, detected = parser._anonymize_pii(text)

        assert "[EMAIL_REDACTED]" in result
        assert "user@example.com" not in result
        assert len(detected) == 1
        assert detected[0]["type"] == "email"

    def test_anonymize_pii_btc_address(self, parser):
        """Test Bitcoin addresses are anonymized."""
        # Legacy address
        text = "Send to 1BvBMSEYstWetqTFn5Au4m4GFg7xJaNVN2"
        result, detected = parser._anonymize_pii(text)

        assert "[BTC_ADDRESS_REDACTED]" in result
        assert len(detected) >= 1

        # Bech32 address
        text2 = "Pay to bc1qar0srrr7xfkvy5l643lydnw9re59gtzzwf5mdq"
        result2, detected2 = parser._anonymize_pii(text2)

        assert "[BTC_ADDRESS_REDACTED]" in result2

    def test_anonymize_pii_ip_address(self, parser):
        """Test IP addresses are anonymized."""
        text = "My server is at 192.168.1.100 and backup at 10.0.0.1"
        result, detected = parser._anonymize_pii(text)

        assert "[IP_ADDRESS_REDACTED]" in result
        assert "192.168.1.100" not in result
        assert "10.0.0.1" not in result
        assert len(detected) == 2

    def test_anonymize_pii_multiple_types(self, parser):
        """Test multiple PII types in same text."""
        text = "Email me at test@example.com from 192.168.1.1"
        result, detected = parser._anonymize_pii(text)

        assert "[EMAIL_REDACTED]" in result
        assert "[IP_ADDRESS_REDACTED]" in result
        assert len(detected) == 2

    def test_anonymize_pii_no_pii(self, parser):
        """Test text without PII is unchanged."""
        text = "How do I resync the DAO?"
        result, detected = parser._anonymize_pii(text)

        assert result == text
        assert len(detected) == 0

    # === Reply Fallback Stripping Tests ===

    def test_strip_reply_fallback_simple(self, parser):
        """Test stripping simple Matrix reply quote."""
        body = "> <@user:server> Original message\n\nActual reply"
        result = parser._strip_reply_fallback(body)
        assert result == "Actual reply"

    def test_strip_reply_fallback_multiline_quote(self, parser):
        """Test stripping multiline Matrix reply quote."""
        body = """> <@user:server> First line
> Second line
> Third line

My actual response"""
        result = parser._strip_reply_fallback(body)
        assert result == "My actual response"

    def test_strip_reply_fallback_no_quote(self, parser):
        """Test text without quote is unchanged."""
        body = "Just a normal message"
        result = parser._strip_reply_fallback(body)
        assert result == "Just a normal message"

    def test_strip_reply_fallback_empty(self, parser):
        """Test empty string handling."""
        assert parser._strip_reply_fallback("") == ""
        assert parser._strip_reply_fallback(None) is None

    # === Q&A Pair Extraction Tests ===

    def test_extract_qa_pairs_basic(self, parser):
        """Test basic Q&A pair extraction."""
        data = {
            "messages": [
                {
                    "type": "m.room.message",
                    "event_id": "$question1",
                    "sender": "@user:matrix.org",
                    "origin_server_ts": 1700000000000,
                    "content": {"body": "How do I resync?"},
                },
                {
                    "type": "m.room.message",
                    "event_id": "$answer1",
                    "sender": "@mwithm:matrix.bisq.network",
                    "origin_server_ts": 1700000001000,
                    "content": {
                        "body": "Go to Settings > Resync DAO",
                        "m.relates_to": {"m.in_reply_to": {"event_id": "$question1"}},
                    },
                },
            ]
        }

        pairs = parser.extract_qa_pairs(data)
        assert len(pairs) == 1
        assert pairs[0].question_text == "How do I resync?"
        assert pairs[0].answer_text == "Go to Settings > Resync DAO"
        assert pairs[0].question_sender == "@user:matrix.org"
        assert pairs[0].answer_sender == "@mwithm:matrix.bisq.network"

    def test_extract_qa_pairs_skip_staff_to_staff(self, parser):
        """Test that staff-to-staff replies are skipped."""
        data = {
            "messages": [
                {
                    "type": "m.room.message",
                    "event_id": "$staff_msg",
                    "sender": "@mwithm:matrix.bisq.network",
                    "origin_server_ts": 1700000000000,
                    "content": {"body": "I think we should do X"},
                },
                {
                    "type": "m.room.message",
                    "event_id": "$staff_reply",
                    "sender": "@pazza83:matrix.bisq.network",
                    "origin_server_ts": 1700000001000,
                    "content": {
                        "body": "Agreed, let's do X",
                        "m.relates_to": {"m.in_reply_to": {"event_id": "$staff_msg"}},
                    },
                },
            ]
        }

        pairs = parser.extract_qa_pairs(data)
        assert len(pairs) == 0  # Staff-to-staff should be skipped

    def test_extract_qa_pairs_skip_non_reply(self, parser):
        """Test that non-reply messages are skipped."""
        data = {
            "messages": [
                {
                    "type": "m.room.message",
                    "event_id": "$user_msg",
                    "sender": "@user:matrix.org",
                    "origin_server_ts": 1700000000000,
                    "content": {"body": "How do I resync?"},
                },
                {
                    "type": "m.room.message",
                    "event_id": "$staff_msg",
                    "sender": "@mwithm:matrix.bisq.network",
                    "origin_server_ts": 1700000001000,
                    "content": {"body": "Here's some general info"},  # No reply
                },
            ]
        }

        pairs = parser.extract_qa_pairs(data)
        assert len(pairs) == 0  # Not a reply

    def test_extract_qa_pairs_deduplicate(self, parser):
        """Test that same question doesn't get multiple answers."""
        data = {
            "messages": [
                {
                    "type": "m.room.message",
                    "event_id": "$question1",
                    "sender": "@user:matrix.org",
                    "origin_server_ts": 1700000000000,
                    "content": {"body": "How do I resync?"},
                },
                {
                    "type": "m.room.message",
                    "event_id": "$answer1",
                    "sender": "@mwithm:matrix.bisq.network",
                    "origin_server_ts": 1700000001000,
                    "content": {
                        "body": "First answer",
                        "m.relates_to": {"m.in_reply_to": {"event_id": "$question1"}},
                    },
                },
                {
                    "type": "m.room.message",
                    "event_id": "$answer2",
                    "sender": "@pazza83:matrix.bisq.network",
                    "origin_server_ts": 1700000002000,
                    "content": {
                        "body": "Second answer",
                        "m.relates_to": {"m.in_reply_to": {"event_id": "$question1"}},
                    },
                },
            ]
        }

        pairs = parser.extract_qa_pairs(data)
        assert len(pairs) == 1  # Only first answer is kept
        assert pairs[0].answer_text == "First answer"

    def test_extract_qa_pairs_with_pii_anonymization(self, parser):
        """Test that PII is anonymized during extraction."""
        data = {
            "messages": [
                {
                    "type": "m.room.message",
                    "event_id": "$question1",
                    "sender": "@user:matrix.org",
                    "origin_server_ts": 1700000000000,
                    "content": {"body": "My email is user@example.com"},
                },
                {
                    "type": "m.room.message",
                    "event_id": "$answer1",
                    "sender": "@mwithm:matrix.bisq.network",
                    "origin_server_ts": 1700000001000,
                    "content": {
                        "body": "Contact support at 192.168.1.1",
                        "m.relates_to": {"m.in_reply_to": {"event_id": "$question1"}},
                    },
                },
            ]
        }

        pairs = parser.extract_qa_pairs(data, anonymize_pii=True)
        assert len(pairs) == 1
        assert "[EMAIL_REDACTED]" in pairs[0].question_text
        assert "[IP_ADDRESS_REDACTED]" in pairs[0].answer_text

    def test_extract_qa_pairs_without_pii_anonymization(self, parser):
        """Test extraction without PII anonymization."""
        data = {
            "messages": [
                {
                    "type": "m.room.message",
                    "event_id": "$question1",
                    "sender": "@user:matrix.org",
                    "origin_server_ts": 1700000000000,
                    "content": {"body": "My email is user@example.com"},
                },
                {
                    "type": "m.room.message",
                    "event_id": "$answer1",
                    "sender": "@mwithm:matrix.bisq.network",
                    "origin_server_ts": 1700000001000,
                    "content": {
                        "body": "Got it",
                        "m.relates_to": {"m.in_reply_to": {"event_id": "$question1"}},
                    },
                },
            ]
        }

        pairs = parser.extract_qa_pairs(data, anonymize_pii=False)
        assert len(pairs) == 1
        assert "user@example.com" in pairs[0].question_text

    # === Path Validation Tests (Security) ===

    def test_validate_file_path_rejects_non_json(self, parser):
        """Test that non-JSON files are rejected."""
        parser.allowed_export_dir = "/tmp"
        with pytest.raises(ValueError, match="Invalid file extension"):
            parser._validate_file_path("/tmp/export.txt")

    def test_validate_file_path_rejects_traversal(self, parser):
        """Test that path traversal is rejected."""
        parser.allowed_export_dir = "/tmp/exports"
        # Use a .json file outside the allowed directory
        with pytest.raises(ValueError, match="outside allowed directory"):
            parser._validate_file_path("/etc/secrets.json")


class TestDefaultStaffList:
    """Test default staff list configuration."""

    def test_default_staff_includes_known_members(self):
        """Verify default staff list includes known Bisq support staff."""
        assert "@mwithm:matrix.bisq.network" in TRUSTED_STAFF_IDS
        assert "@pazza83:matrix.bisq.network" in TRUSTED_STAFF_IDS
        assert "@suddenwhipvapor:matrix.bisq.network" in TRUSTED_STAFF_IDS

    def test_default_staff_uses_full_matrix_ids(self):
        """Verify all default staff entries use full Matrix IDs."""
        # Staff can be from different homeservers (bisq.network, matrix.org, etc.)
        allowed_homeservers = [":matrix.bisq.network", ":matrix.org"]
        for staff_id in TRUSTED_STAFF_IDS:
            assert staff_id.startswith("@"), f"{staff_id} should start with @"
            assert ":" in staff_id, f"{staff_id} should contain homeserver"
            assert any(
                staff_id.endswith(hs) for hs in allowed_homeservers
            ), f"{staff_id} should be on a known homeserver"

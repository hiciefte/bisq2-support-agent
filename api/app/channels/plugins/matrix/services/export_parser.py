"""Parse Matrix room export JSON and extract Q&A pairs."""

import json
import logging
import os
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple

from app.core.pii_utils import PII_LLM_PATTERNS
from app.models.training import QAPair

logger = logging.getLogger(__name__)

# Input validation limits to prevent resource exhaustion
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB
MAX_NESTING_DEPTH = 10  # JSON nesting depth limit
MAX_MESSAGES = 10_000  # Maximum messages to process

# Full Matrix IDs with homeserver (username-only matching would allow impersonation)
TRUSTED_STAFF_IDS: Set[str] = {
    # matrix.bisq.network homeserver
    "@mwithm:matrix.bisq.network",
    "@pazza83:matrix.bisq.network",
    "@suddenwhipvapor:matrix.bisq.network",
    "@strayorigin:matrix.bisq.network",
    "@luis3672:matrix.bisq.network",
    "@darawhelan:matrix.bisq.network",
    # matrix.org homeserver (same staff, different server)
    "@mwithm:matrix.org",
    "@pazza83:matrix.org",
    "@suddenwhipvapor:matrix.org",
    "@strayorigin:matrix.org",
    "@luis3672:matrix.org",
    "@darawhelan:matrix.org",
}

# PII patterns imported from centralized pii_utils.py (PII_LLM_PATTERNS)
# Local patterns removed as part of Phase 3 Matrix code consolidation

# QAPair imported from app.models.training (shared across channels)


class MatrixExportParser:
    """Parse Matrix JSON export and extract Q&A pairs."""

    def __init__(
        self,
        trusted_staff_ids: Optional[Set[str]] = None,
        allowed_export_dir: Optional[str] = None,
    ):
        """
        Initialize parser.

        Args:
            trusted_staff_ids: Set of full Matrix IDs (must include homeserver)
            allowed_export_dir: Directory where Matrix exports can be read from
        """
        self.trusted_staff_ids = trusted_staff_ids or TRUSTED_STAFF_IDS
        self._staff_ids_lower = {s.lower() for s in self.trusted_staff_ids}
        self.allowed_export_dir = allowed_export_dir

    def _is_staff(self, sender: str) -> bool:
        """Check if sender is known support staff using full Matrix ID."""
        return sender.lower() in self._staff_ids_lower

    def _anonymize_pii(self, text: str) -> Tuple[str, List[Dict[str, str]]]:
        """
        Detect and anonymize PII in text.

        Uses centralized PII_LLM_PATTERNS for consistent anonymization.

        Returns:
            Tuple of (anonymized_text, list of detected PII types)
        """
        detected: List[Dict[str, str]] = []
        for pii_type, pattern in PII_LLM_PATTERNS.items():
            matches = re.findall(pattern, text, re.IGNORECASE)
            for match in matches:
                # Handle tuple matches from regex groups
                match_str = match if isinstance(match, str) else match[0]
                detected.append({"type": pii_type})
                text = text.replace(match_str, f"[{pii_type.upper()}_REDACTED]")

        return text, detected

    def _validate_file_path(self, file_path: str) -> str:
        """
        Validate file path to prevent directory traversal.

        Raises:
            ValueError: If path is outside allowed directory or invalid
        """
        # Resolve symlinks and get absolute path
        real_path = os.path.realpath(file_path)

        # Check file extension
        if not real_path.endswith(".json"):
            raise ValueError(f"Invalid file extension: {real_path}")

        # Check against allowed directory if configured
        if self.allowed_export_dir:
            allowed_real = os.path.realpath(self.allowed_export_dir)
            # Use commonpath to prevent prefix bypass (e.g., /allowed_evil/...)
            try:
                common = os.path.commonpath([allowed_real, real_path])
                if common != allowed_real:
                    raise ValueError(
                        f"Path {real_path} is outside allowed directory {allowed_real}"
                    )
            except ValueError:
                # commonpath raises ValueError for paths on different drives (Windows)
                raise ValueError(
                    f"Path {real_path} is outside allowed directory {allowed_real}"
                )

        return real_path

    def _strip_reply_fallback(self, body: str) -> str:
        """Remove Matrix reply quote formatting."""
        if not body:
            return body

        lines = body.split("\n")
        clean_lines: List[str] = []
        in_quote = False

        for line in lines:
            if line.startswith(">"):
                in_quote = True
                continue
            if in_quote and line.strip() == "":
                in_quote = False
                continue
            if not in_quote:
                clean_lines.append(line)

        return "\n".join(clean_lines).strip() or body

    def _check_json_depth(
        self, obj: Any, current_depth: int = 0, max_depth: int = MAX_NESTING_DEPTH
    ) -> None:
        """
        Check JSON nesting depth to prevent stack overflow.

        Args:
            obj: JSON object to check
            current_depth: Current nesting level
            max_depth: Maximum allowed depth

        Raises:
            ValueError: If nesting exceeds max_depth
        """
        if current_depth > max_depth:
            raise ValueError(
                f"JSON nesting depth exceeds maximum ({max_depth}). "
                "File may be malformed or malicious."
            )

        if isinstance(obj, dict):
            for value in obj.values():
                self._check_json_depth(value, current_depth + 1, max_depth)
        elif isinstance(obj, list):
            for item in obj:
                self._check_json_depth(item, current_depth + 1, max_depth)

    def parse_export(self, file_path: str) -> Dict[str, Any]:
        """
        Parse Matrix export JSON file with validation.

        Returns:
            Dict with room metadata and messages

        Raises:
            ValueError: If file exceeds size limit or has invalid structure
            FileNotFoundError: If file does not exist
        """
        # Validate path if allowed_export_dir is set
        if self.allowed_export_dir:
            file_path = self._validate_file_path(file_path)

        # Check file size before parsing
        file_size = os.path.getsize(file_path)
        if file_size > MAX_FILE_SIZE:
            raise ValueError(
                f"File size ({file_size / 1024 / 1024:.1f}MB) exceeds maximum "
                f"({MAX_FILE_SIZE / 1024 / 1024}MB). "
                "Please use a smaller export or split the file."
            )

        logger.info(f"Parsing Matrix export: {file_path} ({file_size / 1024:.1f}KB)")

        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        # Validate JSON structure
        if not isinstance(data, dict):
            raise ValueError("Invalid Matrix export: root must be an object")

        # Check nesting depth (sample check on first 1000 messages for performance)
        messages = data.get("messages", [])
        sample_size = min(1000, len(messages))
        for msg in messages[:sample_size]:
            self._check_json_depth(msg)

        # Validate message count
        message_count = len(messages)
        if message_count > MAX_MESSAGES:
            logger.warning(
                f"Export contains {message_count} messages (limit: {MAX_MESSAGES}). "
                f"Only processing first {MAX_MESSAGES} messages."
            )
            data["messages"] = messages[:MAX_MESSAGES]
            data["_truncated"] = True
            data["_original_message_count"] = message_count

        return data

    def extract_qa_pairs(
        self, data: Dict[str, Any], anonymize_pii: bool = True
    ) -> List[QAPair]:
        """
        Extract Q&A pairs from parsed Matrix data.

        Strategy:
        1. Build event_id -> message index
        2. Find staff replies (messages with m.in_reply_to from staff)
        3. Trace back to find the user question being answered

        Args:
            data: Parsed Matrix export data
            anonymize_pii: Whether to anonymize PII in extracted text

        Returns:
            List of QAPair objects
        """
        messages = data.get("messages", [])

        # Build event_id -> message lookup
        event_index: Dict[str, Dict[str, Any]] = {}
        for msg in messages:
            if msg.get("type") == "m.room.message":
                event_id = msg.get("event_id")
                if event_id:
                    event_index[event_id] = msg

        logger.info(f"Indexed {len(event_index)} messages")

        # Find staff replies
        qa_pairs: List[QAPair] = []
        seen_questions: Set[str] = set()  # Avoid duplicate Q&A pairs

        for msg in messages:
            if msg.get("type") != "m.room.message":
                continue

            sender = msg.get("sender", "")
            content = msg.get("content", {})

            # Only look at staff messages
            if not self._is_staff(sender):
                continue

            # Check if this is a reply
            relates_to = content.get("m.relates_to", {})
            in_reply_to = relates_to.get("m.in_reply_to", {})
            reply_to = in_reply_to.get("event_id")

            if not reply_to:
                continue

            # Get the message being replied to
            replied_msg = event_index.get(reply_to)
            if not replied_msg:
                continue

            # Check if the replied message is from a non-staff user
            replied_sender = replied_msg.get("sender", "")
            if self._is_staff(replied_sender):
                continue  # Staff replying to staff, skip

            # Skip if we've already paired this question
            if reply_to in seen_questions:
                continue

            # Extract texts
            question_text = self._strip_reply_fallback(
                replied_msg.get("content", {}).get("body", "")
            )
            answer_text = self._strip_reply_fallback(content.get("body", ""))

            if not question_text or not answer_text:
                continue

            # Anonymize PII if requested
            if anonymize_pii:
                question_text, _ = self._anonymize_pii(question_text)
                answer_text, _ = self._anonymize_pii(answer_text)

            # Create QA pair
            qa_pair = QAPair(
                question_event_id=reply_to,
                question_text=question_text,
                question_sender=replied_sender,
                question_timestamp=datetime.fromtimestamp(
                    replied_msg.get("origin_server_ts", 0) / 1000, tz=timezone.utc
                ),
                answer_event_id=msg.get("event_id", ""),
                answer_text=answer_text,
                answer_sender=sender,
                answer_timestamp=datetime.fromtimestamp(
                    msg.get("origin_server_ts", 0) / 1000, tz=timezone.utc
                ),
            )

            qa_pairs.append(qa_pair)
            seen_questions.add(reply_to)

        logger.info(f"Extracted {len(qa_pairs)} Q&A pairs")
        return qa_pairs

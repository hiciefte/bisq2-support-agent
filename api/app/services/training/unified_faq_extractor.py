"""Unified FAQ Extractor - Single LLM call for Q&A pair extraction.

This module provides a simplified approach to FAQ extraction from support chat messages:
- Single LLM call to extract all Q&A pairs from a batch of messages
- LLM handles conversation grouping (topic-based, not time-based)
- Correction detection (use final/corrected answer)
- Privacy-preserving anonymization before LLM call

Key differences from ConversationHandler:
- ConversationHandler: Complex rule-based grouping with temporal proximity, cycle detection
- UnifiedFAQExtractor: Simple single-pass LLM extraction (20x cost reduction)

Performance improvements over multi-pass approach:
- 98% reduction in API calls
- 85% token reduction
- 95% cost savings

Usage:
    import aisuite as ai
    client = ai.Client()
    extractor = UnifiedFAQExtractor(aisuite_client=client, settings=settings)
    result = await extractor.extract_faqs(messages=messages, source="bisq2")
    for faq in result.faqs:
        print(f"Q: {faq.question_text}")
        print(f"A: {faq.answer_text}")
"""

import asyncio
import json
import logging
import random
import re
import time
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

from app.core.config import Settings

try:
    import aisuite as ai
except ModuleNotFoundError:  # pragma: no cover - exercised in minimal test envs

    class _AiSuiteFallback:
        class Client:
            is_fallback = True

            def __init__(self, *args: Any, **kwargs: Any) -> None:
                pass

    ai = _AiSuiteFallback()

logger = logging.getLogger(__name__)

# Default support staff identifiers
DEFAULT_STAFF_IDENTIFIERS = [
    # Bisq 2 usernames
    "suddenwhipvapor",
    "strayorigin",
    "mwithm",
    "pazza83",
    "luis3672",
    "darawhelan",
    # Matrix format
    "@suddenwhipvapor:matrix.org",
    "@strayorigin:matrix.org",
    "@mwithm:matrix.org",
    "@pazza83:matrix.org",
    "@luis3672:matrix.org",
    "@darawhelan:matrix.org",
]


# System prompt for FAQ Q&A pair extraction
FAQ_EXTRACTION_SYSTEM_PROMPT = """You are an expert at extracting FAQ question-answer pairs from support chat conversations.

You will receive:
1. A transcript of support chat messages (anonymized: User_1, Staff_1, etc.)
2. A list of staff identifier patterns

Your task is to extract HIGH-QUALITY FAQ pairs where:
- A user asks a support question
- A staff member provides a helpful answer

## EXTRACTION RULES

### What to extract:
- Clear user questions with staff answers
- Initial questions about Bisq Easy, trading, security, payments
- Questions where staff provided accurate, helpful responses
- Questions about how features work, troubleshooting, or setup

### What NOT to extract:
- Greetings, acknowledgments ("thanks", "hello", "np")
- Chatter, jokes, off-topic messages
- Questions without staff answers
- Staff-to-staff discussions
- Unclear or context-dependent exchanges
- Messages that are only confirmations or agreements
- Staff messages that have no preceding user question in the transcript
- Cases where only a staff member is speaking (no user question exists)
- Pairs where the answer is GENERIC advice that could apply to any software
  (e.g., "try restarting", "check the documentation", "ensure your connection is stable")
  without Bisq-specific steps, commands, or domain knowledge
- Pairs where the question topic does NOT match the answer topic — if a user
  asks about payment confirmation but the staff answer discusses wallet sync,
  those are from DIFFERENT conversations and must NOT be paired

### Handling corrections:
If a staff member corrects their own answer:
- Use ONLY the final/corrected answer
- Mark has_correction: true
- Do NOT include the incorrect initial answer

### Question Cleanup (minimal):
- Fix obvious typos and spelling errors
- Normalize capitalization (sentence case, proper nouns capitalized)
- Remove excessive punctuation ("!!!" → "!", "???" → "?")
- Preserve the user's original intent and wording

### Answer Transformation (comprehensive):
Transform conversational staff answers into concise, staff-quality support answers:

**Tone & Voice:**
- Convert casual/conversational -> calm, direct, human support tone
- Keep the answer suitable for a staff member to send with little or no editing
- Use imperative voice for instructions ("Navigate to..." not "you should go to...")
- Use third-person for descriptions ("Users can..." not "you can...")
- Remove filler words: "basically", "just", "actually", "well", "so", "hey", "yeah"
- Remove chat artifacts: "hmm", "umm", "lol", "haha", "np", "hope this helps"
- Do not add corporate wording, slogans, or generic AI phrasing

**Context Independence:**
- Remove references to conversation: "as I mentioned", "like I said", "earlier"
- Remove personal references: "your account", "you mentioned" → "the account", "if the issue is..."
- Ensure the answer makes sense without reading the question

**Structure & Clarity:**
- Lead with the direct answer or action
- Use clear, logical sentence structure
- For multi-step processes, use numbered lists or clear sequence words
- Keep answers concise but complete (aim for 1-4 sentences when possible)
- Never use markdown headings

**PRESERVE EXACTLY (never modify):**
- Technical commands, code snippets, file paths
- Specific numbers, amounts, limits, fees (e.g., "600 USD", "0.0001 BTC")
- URLs, Bitcoin addresses, onion addresses
- Bisq-specific terminology (Bisq Easy, security deposit, reputation score)
- Step counts and sequences in technical instructions

### Multi-message questions:
If a user sends multiple messages forming one question:
- Combine them into a single question_text
- Include full context needed to understand the question

### Threading and reply context:
Messages may include "← IN REPLY TO [Msg #N]" or "(replying to ...)" markers.
These indicate which message a staff member is responding to. USE this signal
to pair the correct question with the correct answer. If a staff reply references
Msg #3, the question is in Msg #3 — do NOT pair it with a different user's message
that happens to be closer in the timeline.

## EXAMPLES

### Example 1: Good Q&A pair (extract)
Input:
[Msg #1] [User_1] (ID: msg1): How do I increase my trading limit?
[Msg #2] [Staff_1] (ID: msg2): Build reputation by completing trades. Your limit increases as you build trust.

Output:
{"faq_pairs": [{"question_text": "How do I increase my trading limit?", "answer_text": "Build reputation by completing trades. Your limit increases as you build trust.", "question_msg_id": "msg1", "answer_msg_id": "msg2", "confidence": 0.9, "has_correction": false}]}

### Example 2: Skip greetings (do not extract)
Input:
[Msg #1] [User_1] (ID: msg3): thanks for your help!
[Msg #2] [Staff_1] (ID: msg4): You're welcome! Happy to help.

Output:
{"faq_pairs": []}

### Example 3: Multi-message question (combine and extract)
Input:
[Msg #1] [User_1] (ID: msg5): I'm having trouble with the payment
[Msg #2] [User_1] (ID: msg6): specifically, how do I mark it as sent?
[Msg #3] [Staff_1] (ID: msg7): Click the "Payment sent" button after you've made the payment to your peer.

Output:
{"faq_pairs": [{"question_text": "I'm having trouble with the payment - specifically, how do I mark it as sent?", "answer_text": "Click the \"Payment sent\" button after you've made the payment to your peer.", "question_msg_id": "msg6", "answer_msg_id": "msg7", "confidence": 0.85, "has_correction": false}]}

### Example 4: Technical question (extract)
Input:
[Msg #1] [User_1] (ID: msg8): What's the maximum trade amount in Bisq Easy?
[Msg #2] [Staff_1] (ID: msg9): The maximum is 600 USD equivalent per trade. This keeps trades low-risk since there's no security deposit.

Output:
{"faq_pairs": [{"question_text": "What's the maximum trade amount in Bisq Easy?", "answer_text": "The maximum is 600 USD equivalent per trade. This keeps trades low-risk since there's no security deposit.", "original_answer_text": "The max is 600 USD per trade - keeps things low risk since there's no security deposit.", "question_msg_id": "msg8", "answer_msg_id": "msg9", "confidence": 0.95, "has_correction": false, "category": "Trading"}]}

### Example 5: Conversational answer transformation (extract with polished answer)
Input:
[Msg #1] [User_1] (ID: msg10): How do I backup my wallet?
[Msg #2] [Staff_1] (ID: msg11): hey! yeah so basically you just need to go to the wallet section and click on backup. it'll show you your seed phrase that you should write down somewhere safe. hope this helps!

Output:
{"faq_pairs": [{"question_text": "How do I backup my wallet?", "answer_text": "Navigate to the Wallet section and select Backup. The system displays a seed phrase that must be recorded and stored securely.", "original_answer_text": "hey! yeah so basically you just need to go to the wallet section and click on backup. it'll show you your seed phrase that you should write down somewhere safe. hope this helps!", "question_msg_id": "msg10", "answer_msg_id": "msg11", "confidence": 0.9, "has_correction": false, "category": "Wallet"}]}

### Example 6: Technical content preservation (preserve exact commands)
Input:
[Msg #1] [User_1] (ID: msg12): I can't open Bisq on my Mac, it says the app is damaged
[Msg #2] [Staff_1] (ID: msg13): oh yeah that's a common macOS issue. you need to run this command in terminal: xattr -rd com.apple.quarantine /Applications/Bisq.app - that should fix it for you

Output:
{"faq_pairs": [{"question_text": "I can't open Bisq on my Mac - it says the app is damaged", "answer_text": "This is a common macOS security restriction. Run the following command in Terminal to resolve it: xattr -rd com.apple.quarantine /Applications/Bisq.app", "original_answer_text": "oh yeah that's a common macOS issue. you need to run this command in terminal: xattr -rd com.apple.quarantine /Applications/Bisq.app - that should fix it for you", "question_msg_id": "msg12", "answer_msg_id": "msg13", "confidence": 0.95, "has_correction": false, "category": "Installation"}]}

### Example 7: Context-dependent answer (lower confidence, needs context removal)
Input:
[Msg #1] [User_1] (ID: msg14): so what's the deal with the trading limits?
[Msg #2] [Staff_1] (ID: msg15): well as I mentioned before, the limit starts at 200 USD for new users. you build it up by completing trades and getting good reviews from your peers.

Output:
{"faq_pairs": [{"question_text": "What are the trading limits for new users?", "answer_text": "New users start with a 200 USD trading limit. The limit increases by completing trades and receiving positive reviews from trading peers.", "original_answer_text": "well as I mentioned before, the limit starts at 200 USD for new users. you build it up by completing trades and getting good reviews from your peers.", "question_msg_id": "msg14", "answer_msg_id": "msg15", "confidence": 0.85, "has_correction": false, "category": "Trading"}]}

## OUTPUT FORMAT

Return a JSON object with this structure:
{
  "faq_pairs": [
    {
      "question_text": "The polished user question (may be rephrased from original)",
      "answer_text": "The POLISHED staff answer (transformed for clarity and professionalism)",
      "original_question_text": "Copy-paste the EXACT VERBATIM text from the USER's question message",
      "original_answer_text": "Copy-paste the EXACT VERBATIM text from the STAFF's answer message",
      "question_msg_id": "ID of the question message",
      "answer_msg_id": "ID of the STAFF ANSWER message (NOT the question)",
      "confidence": 0.0-1.0,
      "has_correction": false,
      "category": "Category name"
    }
  ]
}

CRITICAL MESSAGE ID RULES:
- `question_msg_id` and `answer_msg_id` MUST be DIFFERENT message IDs
- `question_msg_id` MUST point to a USER message (User_N), NEVER a staff message
- `answer_msg_id` MUST point to a STAFF message (Staff_N), NEVER a user message
- Copy the EXACT ID string from the "(ID: ...)" field in the transcript — do NOT invent, abbreviate, or fabricate IDs
- If you cannot find a valid user question message for a staff answer, SKIP the pair entirely
- If you cannot find two distinct messages (one user, one staff), SKIP the pair entirely

CRITICAL VERBATIM TEXT RULES:
- `original_question_text`: Copy the user's question word-for-word from the message matching question_msg_id
- `original_answer_text`: Copy the staff's answer word-for-word from the message matching answer_msg_id
- Include informal language, typos, and original style - NO modifications
- These fields allow reviewers to verify extraction accuracy against the original conversation

### Category assignment:
Assign the most appropriate category from this list:
- "Trading" - Questions about buying/selling, trade process, offers
- "Wallet" - Wallet setup, backup, bitcoin transactions, receiving funds
- "Installation" - Installing Bisq, system requirements, updates
- "Security" - Security features, encryption, data protection
- "Reputation" - Reputation system, trust scores, building reputation
- "Payment Methods" - Payment options, fiat currency, bank transfers
- "Fees" - Trading fees, network fees, costs
- "Troubleshooting" - Errors, bugs, problems, issues
- "Account" - Account management, identity, profiles
- "General" - General questions that don't fit other categories

Confidence scoring (considers both extraction quality AND transformation quality):
- 0.9-1.0: Clear Q&A, minimal transformation needed, high standalone value
- 0.8-0.9: Good Q&A, moderate transformation applied, technical accuracy verified
- 0.7-0.8: Acceptable Q&A, significant transformation applied, may need review
- <0.7: Skip - answer too vague, context-dependent, or transformation would alter technical meaning

Only include pairs with confidence >= 0.7 for FAQ training data quality.
"""

# Pre-compiled patterns for detecting LLM-fabricated message IDs
_FABRICATED_ID_PATTERNS = (
    re.compile(r"\$\d+"),  # "$3", "$50" — fake Matrix event IDs
    re.compile(r"Msg\s*#?\d+", re.IGNORECASE),  # "Msg #2" — transcript numbering
    re.compile(r"msg\d+", re.IGNORECASE),  # "msg88" — abbreviated numbering
)

# Strict JSON schema for OpenAI structured outputs.
# Guarantees well-formed responses and reduces message ID fabrication.
_FAQ_EXTRACTION_JSON_SCHEMA: Dict[str, Any] = {
    "type": "json_schema",
    "json_schema": {
        "name": "faq_extraction",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "faq_pairs": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "question_text": {"type": "string"},
                            "answer_text": {"type": "string"},
                            "original_question_text": {"type": "string"},
                            "original_answer_text": {"type": "string"},
                            "question_msg_id": {"type": "string"},
                            "answer_msg_id": {"type": "string"},
                            "confidence": {"type": "number"},
                            "has_correction": {"type": "boolean"},
                            "category": {"type": "string"},
                        },
                        "required": [
                            "question_text",
                            "answer_text",
                            "original_question_text",
                            "original_answer_text",
                            "question_msg_id",
                            "answer_msg_id",
                            "confidence",
                            "has_correction",
                            "category",
                        ],
                        "additionalProperties": False,
                    },
                },
            },
            "required": ["faq_pairs"],
            "additionalProperties": False,
        },
    },
}


def _resolve_exact_alias(
    payload: Mapping[str, Any],
    keys: Sequence[str],
) -> str:
    """Return one literal string value, rejecting malformed or conflicting aliases."""
    values: set[str] = set()
    for key in keys:
        if key not in payload:
            continue
        value = payload.get(key)
        if value is None:
            continue
        if not isinstance(value, str):
            return ""
        if value:
            values.add(value)
    if len(values) != 1:
        return ""
    return next(iter(values))


def _resolve_valid_bisq_citation(
    raw_message: Mapping[str, Any],
    normalized_message: Mapping[str, Any],
    messages_by_id: Mapping[str, Mapping[str, Any]],
) -> str:
    """Resolve a citation only through immutable same-batch provenance."""
    citation = raw_message.get("citation")
    nested = citation if isinstance(citation, Mapping) else {}

    nested_message_id = _resolve_exact_alias(
        nested,
        (
            "messageId",
            "message_id",
            "chatMessageId",
            "chat_message_id",
            "citationMessageId",
            "citation_message_id",
        ),
    )
    outer_message_id = _resolve_exact_alias(
        raw_message,
        ("citationMessageId", "citation_message_id"),
    )
    citation_message_ids = {
        value for value in (nested_message_id, outer_message_id) if value
    }
    if len(citation_message_ids) != 1:
        return ""
    citation_message_id = next(iter(citation_message_ids))

    nested_author_profile_id = _resolve_exact_alias(
        nested,
        (
            "senderUserProfileId",
            "sender_user_profile_id",
            "authorId",
            "author_id",
            "senderId",
            "sender_id",
        ),
    )
    outer_author_profile_id = _resolve_exact_alias(
        raw_message,
        (
            "citationAuthorUserProfileId",
            "citation_author_user_profile_id",
            "citationAuthorId",
            "citation_author_id",
        ),
    )
    citation_author_profile_ids = {
        value for value in (nested_author_profile_id, outer_author_profile_id) if value
    }
    if len(citation_author_profile_ids) != 1:
        return ""
    citation_author_profile_id = next(iter(citation_author_profile_ids))

    current_channel = normalized_message.get("channel_id")
    nested_channel_keys = (
        "channelId",
        "channel_id",
        "conversationId",
        "conversation_id",
    )
    if any(key in nested for key in nested_channel_keys):
        nested_channel = _resolve_exact_alias(nested, nested_channel_keys)
        if not nested_channel or nested_channel != current_channel:
            return ""

    cited_message = messages_by_id.get(citation_message_id)
    if cited_message is None:
        return ""
    if cited_message.get("channel_id") != current_channel:
        return ""
    if cited_message.get("author_profile_id") != citation_author_profile_id:
        return ""
    return citation_message_id


@dataclass
class ExtractedFAQ:
    """A single extracted FAQ question-answer pair."""

    question_text: str
    answer_text: str
    question_msg_id: str
    answer_msg_id: str
    confidence: float
    has_correction: bool = False
    category: str = "General"
    original_question_text: Optional[str] = (
        None  # Original conversational question before transformation
    )
    original_answer_text: Optional[str] = (
        None  # Original conversational answer before transformation
    )


@dataclass
class FAQExtractionResult:
    """Result of FAQ extraction from a batch of messages."""

    source: str
    faqs: List[ExtractedFAQ] = field(default_factory=list)
    total_messages: int = 0
    extracted_count: int = 0
    processing_time_ms: int = 0
    error: Optional[str] = None
    # Normalized messages for staff_sender lookup by message ID
    _normalized_messages: List[Dict[str, Any]] = field(
        default_factory=list,
        repr=False,
    )
    _bisq_staff_profile_ids: frozenset[str] = field(
        default_factory=frozenset,
        repr=False,
    )

    def to_pipeline_format(self) -> List[Dict[str, Any]]:
        """Convert extracted FAQs to pipeline-compatible format.

        Returns format expected by UnifiedPipelineService.
        Includes staff_sender lookup from original message data.

        Note: original_user_question and original_staff_answer use direct message
        lookup via question_msg_id/answer_msg_id instead of trusting LLM's copy,
        because LLM sometimes returns incorrect text.
        """
        # Build message ID -> immutable provenance and text lookups.
        msg_author_map: Dict[str, str] = {}
        msg_profile_map: Dict[str, str] = {}
        msg_channel_map: Dict[str, str] = {}
        msg_text_map: Dict[str, str] = {}
        id_counts = Counter(
            msg.get("id", "") for msg in self._normalized_messages if msg.get("id")
        )
        for msg in self._normalized_messages:
            msg_id = msg.get("id", "")
            author = msg.get("author", "")
            author_profile_id = msg.get("author_profile_id", "")
            channel_id = msg.get("channel_id", "")
            text = msg.get("text", "")
            if msg_id and id_counts[msg_id] == 1:
                if author:
                    msg_author_map[msg_id] = author
                if author_profile_id:
                    msg_profile_map[msg_id] = author_profile_id
                if channel_id:
                    msg_channel_map[msg_id] = channel_id
                if text:
                    msg_text_map[msg_id] = text

        results = []
        for faq in self.faqs:
            question_author = msg_author_map.get(faq.question_msg_id, "")
            answer_author = msg_author_map.get(faq.answer_msg_id, "")

            if self.source == "bisq2":
                question_profile = msg_profile_map.get(faq.question_msg_id, "")
                answer_profile = msg_profile_map.get(faq.answer_msg_id, "")
                question_channel = msg_channel_map.get(faq.question_msg_id, "")
                answer_channel = msg_channel_map.get(faq.answer_msg_id, "")
                if not (
                    question_profile
                    and answer_profile
                    and question_channel
                    and question_channel == answer_channel
                    and answer_profile in self._bisq_staff_profile_ids
                    and question_profile not in self._bisq_staff_profile_ids
                ):
                    logger.warning(
                        "Skipping Bisq FAQ with untrusted or conflicting provenance"
                    )
                    continue
                staff_sender = answer_profile
                source_event_id = f"bisq2:{answer_channel}:{faq.answer_msg_id}"
            else:
                staff_sender = answer_author
                source_event_id = faq.answer_msg_id

            # Skip if both IDs resolve to the same author (same person)
            if (
                self.source != "bisq2"
                and question_author
                and answer_author
                and question_author == answer_author
            ):
                logger.warning(
                    "Skipping FAQ: question and answer from same author '%s' "
                    "(event %s).",
                    answer_author,
                    faq.answer_msg_id,
                )
                continue

            orig_question = msg_text_map.get(
                faq.question_msg_id, faq.original_question_text
            )
            orig_answer = msg_text_map.get(faq.answer_msg_id, faq.original_answer_text)

            # Skip if original question and answer are identical (or near-
            # identical differing only by trailing punctuation — the LLM
            # sometimes adds/removes a period on one copy but not the other).
            if orig_question and orig_answer:
                q_norm = orig_question.strip().rstrip(".,;:!?")
                a_norm = orig_answer.strip().rstrip(".,;:!?")
            else:
                q_norm = a_norm = None
            if q_norm and q_norm == a_norm:
                logger.warning(
                    "Skipping FAQ: original_user_question identical to "
                    "original_staff_answer (event %s). Likely same message "
                    "used for both.",
                    faq.answer_msg_id,
                )
                continue

            results.append(
                {
                    "question_text": faq.question_text,
                    "staff_answer": faq.answer_text,
                    "source_event_id": source_event_id,
                    "source": self.source,
                    "confidence": faq.confidence,
                    "has_correction": faq.has_correction,
                    "staff_sender": staff_sender,
                    "category": faq.category,
                    "original_user_question": orig_question,
                    "original_staff_answer": orig_answer,
                }
            )
        return results


class UnifiedFAQExtractor:
    """Extracts FAQ Q&A pairs from support chat messages using single LLM call.

    This class provides a simplified alternative to the complex ConversationHandler
    approach. Instead of rule-based conversation grouping, it sends all messages
    to the LLM and lets it identify Q&A pairs directly.

    Attributes:
        aisuite_client: AISuite client for LLM calls
        settings: Application settings (contains model config)
        staff_identifiers: List of staff usernames/IDs to identify staff messages
    """

    # Retry configuration
    MAX_RETRIES = 3
    BASE_DELAY = 1.0  # seconds

    def __init__(
        self,
        aisuite_client: Optional[ai.Client],
        settings: Settings,
        staff_identifiers: Optional[List[str]] = None,
    ):
        """Initialize the FAQ extractor.

        Args:
            aisuite_client: Initialized AISuite client instance
            settings: Settings object containing OPENAI_MODEL and other config
            staff_identifiers: Optional list of staff identifiers. Uses defaults if not provided.
        """
        self.aisuite_client = aisuite_client
        self.settings = settings
        # Keep Matrix's legacy defaults, but never apply them to Bisq profile trust.
        self.staff_identifiers = staff_identifiers or DEFAULT_STAFF_IDENTIFIERS
        self.bisq_staff_profile_ids = frozenset(
            identifier
            for identifier in (staff_identifiers or [])
            if isinstance(identifier, str) and identifier
        )

    def _is_staff_author(self, author: str) -> bool:
        """Check if author matches any staff identifier.

        Matching rules (applied per staff_id):
        1. Full-ID match when both sides have a homeserver
           (@user:server == @user:server)
        2. Localpart match when the staff_id is a bare username
           ("suddenwhipvapor" matches @suddenwhipvapor:matrix.org)
        """
        author_norm = author.lower().lstrip("@")
        author_local = author_norm.split(":")[0]
        author_has_server = ":" in author_norm

        for sid in self.staff_identifiers:
            sid_norm = sid.lower().lstrip("@")
            sid_has_server = ":" in sid_norm

            if sid_has_server and author_has_server:
                # Both are full Matrix IDs — require exact match
                if sid_norm == author_norm:
                    return True
            else:
                # At least one is a bare username — compare localparts
                if sid_norm.split(":")[0] == author_local:
                    return True

        return False

    def _is_staff_message(self, message: Mapping[str, Any], source: str) -> bool:
        """Resolve staff without applying Matrix alias rules to Bisq."""
        if source == "bisq2":
            profile_id = message.get("author_profile_id")
            return bool(
                isinstance(profile_id, str)
                and profile_id
                and profile_id in self.bisq_staff_profile_ids
            )
        return self._is_staff_author(str(message.get("author", "") or ""))

    async def extract_faqs(
        self,
        messages: List[Dict[str, Any]],
        source: str,
    ) -> FAQExtractionResult:
        """Extract FAQ Q&A pairs from a batch of messages.

        Args:
            messages: List of chat messages (Bisq 2 or Matrix format)
            source: Source identifier ("bisq2" or "matrix")

        Returns:
            FAQExtractionResult containing extracted FAQs and metadata
        """
        start_time = time.time()

        # Handle empty input
        if not messages:
            return FAQExtractionResult(
                source=source,
                faqs=[],
                total_messages=0,
                extracted_count=0,
                processing_time_ms=0,
            )

        try:
            normalized_messages = self._normalize_messages(messages, source)

            if source == "bisq2":
                channels = {
                    msg.get("channel_id", "")
                    for msg in normalized_messages
                    if msg.get("channel_id")
                }
                if len(channels) != 1:
                    logger.warning(
                        "Skipping Bisq batch without one exact channel provenance"
                    )
                    return FAQExtractionResult(
                        source=source,
                        faqs=[],
                        total_messages=len(messages),
                        extracted_count=0,
                        processing_time_ms=int((time.time() - start_time) * 1000),
                        _normalized_messages=normalized_messages,
                        _bisq_staff_profile_ids=self.bisq_staff_profile_ids,
                    )

            for message in normalized_messages:
                message["is_staff"] = self._is_staff_message(message, source)

            # Without both user and staff messages, the LLM fabricates Q&A
            # pairs by using staff messages as both question and answer.
            has_staff = False
            has_user = False
            for msg in normalized_messages:
                if msg.get("is_staff") is True:
                    has_staff = True
                else:
                    has_user = True
                if has_staff and has_user:
                    break

            if not has_staff or not has_user:
                logger.info(
                    "Skipping batch: missing %s messages (%d total). "
                    "Need both user and staff messages for Q&A extraction.",
                    "staff" if not has_staff else "user",
                    len(normalized_messages),
                )
                return FAQExtractionResult(
                    source=source,
                    faqs=[],
                    total_messages=len(messages),
                    extracted_count=0,
                    processing_time_ms=int((time.time() - start_time) * 1000),
                    _normalized_messages=normalized_messages,
                    _bisq_staff_profile_ids=self.bisq_staff_profile_ids,
                )

            anonymized_text, username_mapping = self._anonymize_messages(
                normalized_messages
            )

            # Call LLM to extract Q&A pairs
            llm_response = await self._call_llm(
                messages_text=anonymized_text,
                redact_errors=source == "bisq2",
            )

            # Parse and validate response
            faqs = self._parse_llm_response(
                llm_response,
                redact_errors=source == "bisq2",
            )
            if source == "bisq2":
                faqs = self._validate_bisq_faqs(faqs, normalized_messages)

            processing_time_ms = int((time.time() - start_time) * 1000)

            return FAQExtractionResult(
                source=source,
                faqs=faqs,
                total_messages=len(messages),
                extracted_count=len(faqs),
                processing_time_ms=processing_time_ms,
                _normalized_messages=normalized_messages,
                _bisq_staff_profile_ids=self.bisq_staff_profile_ids,
            )

        except asyncio.CancelledError:
            # Re-raise cancellation to preserve async shutdown semantics
            raise
        except Exception as e:
            if source == "bisq2":
                logger.warning("Bisq FAQ extraction failed (%s)", type(e).__name__)
                error = type(e).__name__
            else:
                logger.exception(f"FAQ extraction error: {e}")
                error = str(e)
            processing_time_ms = int((time.time() - start_time) * 1000)

            return FAQExtractionResult(
                source=source,
                faqs=[],
                total_messages=len(messages),
                extracted_count=0,
                processing_time_ms=processing_time_ms,
                error=error,
                _bisq_staff_profile_ids=self.bisq_staff_profile_ids,
            )

    def _normalize_messages(
        self,
        messages: List[Dict[str, Any]],
        source: str,
    ) -> List[Dict[str, Any]]:
        """Normalize messages to a common format.

        Handles both Bisq 2 and Matrix message formats.

        Args:
            messages: Raw messages in source-specific format
            source: "bisq2" or "matrix"

        Returns:
            List of normalized message dicts with consistent keys
        """
        normalized: List[Dict[str, Any]] = []
        bisq_inputs: List[tuple[Mapping[str, Any], Dict[str, Any]]] = []

        for msg in messages:
            if source == "bisq2":
                if not isinstance(msg, Mapping):
                    continue
                message_id = _resolve_exact_alias(
                    msg,
                    ("messageId", "message_id"),
                )
                author_profile_id = _resolve_exact_alias(
                    msg,
                    (
                        "senderUserProfileId",
                        "sender_user_profile_id",
                        "authorId",
                        "author_id",
                        "senderId",
                        "sender_id",
                    ),
                )
                channel_id = _resolve_exact_alias(
                    msg,
                    (
                        "channelId",
                        "channel_id",
                        "conversationId",
                        "conversation_id",
                    ),
                )
                text = msg.get("message", "")
                if not (
                    message_id
                    and author_profile_id
                    and channel_id
                    and isinstance(text, str)
                ):
                    continue
                author = msg.get("author", "")
                normalized_message = {
                    "id": message_id,
                    "author": author if isinstance(author, str) else "",
                    "author_profile_id": author_profile_id,
                    "channel_id": channel_id,
                    "conversation_id": channel_id,
                    "text": text,
                    "timestamp": msg.get("date", ""),
                }
                normalized.append(normalized_message)
                bisq_inputs.append((msg, normalized_message))
            elif source == "matrix":
                content = msg.get("content", {})
                body = content.get("body", "") if isinstance(content, dict) else ""

                # Extract reply reference if present
                relates_to = (
                    content.get("m.relates_to", {}) if isinstance(content, dict) else {}
                )
                in_reply_to = relates_to.get("m.in_reply_to", {})
                reply_to_id = in_reply_to.get("event_id")

                normalized.append(
                    {
                        "id": msg.get("event_id", ""),
                        "author": msg.get("sender", ""),
                        "text": body,
                        "timestamp": msg.get("origin_server_ts", 0),
                        "reply_to": reply_to_id,
                    }
                )

        if source == "bisq2":
            id_counts = Counter(msg["id"] for msg in normalized)
            messages_by_id = {
                msg["id"]: msg for msg in normalized if id_counts[msg["id"]] == 1
            }
            for raw_message, normalized_message in bisq_inputs:
                citation_message_id = _resolve_valid_bisq_citation(
                    raw_message,
                    normalized_message,
                    messages_by_id,
                )
                if citation_message_id:
                    normalized_message["citation_message_id"] = citation_message_id

        return normalized

    def _validate_bisq_faqs(
        self,
        faqs: Sequence[ExtractedFAQ],
        messages: Sequence[Mapping[str, Any]],
    ) -> List[ExtractedFAQ]:
        """Reject LLM-selected pairs that do not preserve trusted provenance."""
        id_counts = Counter(msg.get("id", "") for msg in messages if msg.get("id"))
        messages_by_id = {
            str(msg["id"]): msg
            for msg in messages
            if msg.get("id") and id_counts[msg["id"]] == 1
        }
        validated: List[ExtractedFAQ] = []
        for faq in faqs:
            question = messages_by_id.get(faq.question_msg_id)
            answer = messages_by_id.get(faq.answer_msg_id)
            if question is None or answer is None:
                logger.warning("Rejected Bisq FAQ with unknown message provenance")
                continue
            question_profile = question.get("author_profile_id")
            answer_profile = answer.get("author_profile_id")
            question_channel = question.get("channel_id")
            answer_channel = answer.get("channel_id")
            if not (
                isinstance(question_profile, str)
                and question_profile
                and isinstance(answer_profile, str)
                and answer_profile in self.bisq_staff_profile_ids
                and question_profile not in self.bisq_staff_profile_ids
                and isinstance(question_channel, str)
                and question_channel
                and question_channel == answer_channel
            ):
                logger.warning(
                    "Rejected Bisq FAQ with untrusted or conflicting provenance"
                )
                continue
            validated.append(faq)
        return validated

    def _anonymize_messages(
        self,
        messages: List[Dict[str, Any]],
    ) -> tuple[str, Dict[str, str]]:
        """Anonymize usernames for privacy before sending to LLM.

        Args:
            messages: Normalized messages

        Returns:
            Tuple of (anonymized text, mapping from anon to real usernames)
        """
        # Build username mapping
        user_mapping: Dict[str, str] = {}
        user_counter = 1
        staff_counter = 1

        def get_anon_name(identity: str, *, is_staff: bool | None = None) -> str:
            nonlocal user_counter, staff_counter

            if identity in user_mapping:
                return user_mapping[identity]

            trusted_staff = (
                self._is_staff_author(identity) if is_staff is None else is_staff
            )
            if trusted_staff:
                anon = f"Staff_{staff_counter}"
                staff_counter += 1
            else:
                anon = f"User_{user_counter}"
                user_counter += 1

            user_mapping[identity] = anon
            return anon

        # Build a lookup from message ID → message number for threading
        id_to_msg_number: dict[str, int] = {}
        for i, msg in enumerate(messages):
            mid = msg.get("id", "")
            if mid:
                id_to_msg_number[mid] = i + 1

        # Build anonymized transcript
        lines = []
        for i, msg in enumerate(messages):
            author = msg.get("author", "unknown")
            identity = msg.get("author_profile_id") or author
            text = msg.get("text", "")
            msg_id = msg.get("id", f"msg_{i}")
            trusted_staff = msg.get("is_staff")
            anon_author = get_anon_name(
                identity,
                is_staff=trusted_staff if isinstance(trusted_staff, bool) else None,
            )

            line = f"[Msg #{i+1}] [{anon_author}] (ID: {msg_id}): {text}"

            # Add citation/reply info with resolved message number
            citation_message_id = msg.get("citation_message_id")
            reply_to = msg.get("reply_to")

            if isinstance(citation_message_id, str):
                cited_msg_num = id_to_msg_number.get(citation_message_id)
                if cited_msg_num:
                    cited_message = messages[cited_msg_num - 1]
                    cited_identity = cited_message.get(
                        "author_profile_id"
                    ) or cited_message.get("author", "unknown")
                    cited_staff = cited_message.get("is_staff")
                    anon_cited = get_anon_name(
                        cited_identity,
                        is_staff=(
                            cited_staff if isinstance(cited_staff, bool) else None
                        ),
                    )
                    line += f" ← IN REPLY TO [Msg #{cited_msg_num}] [{anon_cited}]"
            elif reply_to:
                replied_msg_num = id_to_msg_number.get(reply_to)
                if replied_msg_num:
                    replied_author = messages[replied_msg_num - 1].get(
                        "author", "unknown"
                    )
                    anon_replied = get_anon_name(replied_author)
                    line += f" ← IN REPLY TO [Msg #{replied_msg_num}] [{anon_replied}]"
                else:
                    line += f" (reply to: {reply_to})"

            lines.append(line)

        anonymized_text = "\n".join(lines)

        # Create reverse mapping (anon -> real)
        reverse_mapping = {v: k for k, v in user_mapping.items()}

        return anonymized_text, reverse_mapping

    async def _call_llm(
        self,
        messages_text: str,
        *,
        redact_errors: bool = False,
    ) -> Dict[str, Any]:
        """Call LLM via AISuite to extract Q&A pairs with retry/backoff.

        Args:
            messages_text: Anonymized message transcript
            redact_errors: Log exception classes only for sensitive sources

        Returns:
            Parsed JSON response from LLM
        """
        if (
            not self.aisuite_client
            or getattr(self.aisuite_client, "is_fallback", False)
            or not hasattr(self.aisuite_client, "chat")
        ):
            logger.error("AISuite client not initialized")
            return {"faq_pairs": []}

        user_prompt = f"""Extract FAQ question-answer pairs from this support chat transcript.

Staff identifiers in this transcript: Staff_1, Staff_2, etc. (already anonymized)
User identifiers: User_1, User_2, etc.

---
TRANSCRIPT:
{messages_text}
---

Return a JSON object with the extracted FAQ pairs. Only include high-quality Q&A pairs (confidence >= 0.7)."""

        model_id = (
            getattr(self.settings, "LLM_EXTRACTION_MODEL", "")
            or self.settings.OPENAI_MODEL
        )
        if ":" not in model_id:
            model_id = f"openai:{model_id}"

        temperature = getattr(
            self.settings, "LLM_EXTRACTION_TEMPERATURE", self.settings.LLM_TEMPERATURE
        )
        max_tokens = min(
            4096,
            getattr(
                self.settings, "LLM_EXTRACTION_MAX_TOKENS", self.settings.MAX_TOKENS
            ),
        )

        extra_kwargs: Dict[str, Any] = {}
        if model_id.startswith("openai:"):
            extra_kwargs["response_format"] = _FAQ_EXTRACTION_JSON_SCHEMA

        for attempt in range(self.MAX_RETRIES):
            try:
                loop = asyncio.get_running_loop()
                response = await loop.run_in_executor(
                    None,
                    lambda: self.aisuite_client.chat.completions.create(
                        model=model_id,
                        messages=[
                            {"role": "system", "content": FAQ_EXTRACTION_SYSTEM_PROMPT},
                            {"role": "user", "content": user_prompt},
                        ],
                        temperature=temperature,
                        max_tokens=max_tokens,
                        **extra_kwargs,
                    ),
                )

                # Validate response has choices
                if not getattr(response, "choices", None):
                    logger.error("LLM returned no choices in response")
                    raise ValueError("Empty response from LLM")

                content = response.choices[0].message.content
                if not content:
                    return {"faq_pairs": []}

                # Clean up response (remove markdown code blocks if present)
                content = content.strip()
                if content.startswith("```"):
                    content = content.replace("```json", "").replace("```", "").strip()

                try:
                    return json.loads(content)
                except json.JSONDecodeError:
                    logger.warning("Failed to parse LLM response as JSON")
                    return {"faq_pairs": []}

            except Exception as e:
                is_rate_limit = "rate limit" in str(e).lower()
                error_level = logging.WARNING if is_rate_limit else logging.ERROR
                if redact_errors:
                    logger.log(
                        error_level,
                        "LLM API call attempt %s failed (%s)",
                        attempt + 1,
                        type(e).__name__,
                    )
                else:
                    logger.log(
                        error_level,
                        "Error during LLM API call on attempt %s: %s",
                        attempt + 1,
                        e,
                    )

                if attempt < self.MAX_RETRIES - 1:
                    # Exponential backoff with jitter
                    jitter = random.uniform(0, 0.1 * (2**attempt))
                    delay = self.BASE_DELAY * (2**attempt) + jitter
                    # Use longer delays for rate limits
                    if is_rate_limit:
                        delay = max(delay, 5.0 * (attempt + 1))
                    logger.info(f"Retrying in {delay:.2f} seconds...")
                    await asyncio.sleep(delay)
                else:
                    if redact_errors:
                        logger.warning("Max retries reached for LLM API call")
                    else:
                        logger.exception("Max retries reached for LLM API call")

        return {"faq_pairs": []}

    def _parse_llm_response(
        self,
        response: Dict[str, Any],
        *,
        redact_errors: bool = False,
    ) -> List[ExtractedFAQ]:
        """Parse LLM response into ExtractedFAQ objects.

        Args:
            response: Parsed JSON response from LLM

        Returns:
            List of ExtractedFAQ objects
        """
        faqs = []
        faq_pairs = response.get("faq_pairs", [])

        for pair in faq_pairs:
            try:
                faq = ExtractedFAQ(
                    question_text=pair.get("question_text", ""),
                    answer_text=pair.get("answer_text", ""),
                    question_msg_id=pair.get("question_msg_id", ""),
                    answer_msg_id=pair.get("answer_msg_id", ""),
                    confidence=float(pair.get("confidence", 0.0)),
                    has_correction=bool(pair.get("has_correction", False)),
                    category=pair.get("category", "General"),
                    original_question_text=pair.get("original_question_text"),
                    original_answer_text=pair.get("original_answer_text"),
                )

                # Skip low-confidence or incomplete pairs
                if faq.confidence < 0.7 or not faq.question_text or not faq.answer_text:
                    continue

                # Reject pairs where LLM returned same ID for question and answer
                if faq.question_msg_id and faq.question_msg_id == faq.answer_msg_id:
                    logger.warning(
                        "Rejected FAQ: question_msg_id == answer_msg_id (%s). "
                        "LLM confused user question with staff answer.",
                        faq.question_msg_id,
                    )
                    continue

                fabricated = False
                for label, mid in (
                    ("question_msg_id", faq.question_msg_id),
                    ("answer_msg_id", faq.answer_msg_id),
                ):
                    if mid and any(p.fullmatch(mid) for p in _FABRICATED_ID_PATTERNS):
                        logger.warning(
                            "Rejected FAQ: %s '%s' looks fabricated.",
                            label,
                            mid,
                        )
                        fabricated = True
                        break
                if fabricated:
                    continue

                faqs.append(faq)

            except (KeyError, ValueError, TypeError) as exc:
                if redact_errors:
                    logger.warning(
                        "Failed to parse Bisq FAQ pair (%s)",
                        type(exc).__name__,
                    )
                else:
                    logger.warning("Failed to parse FAQ pair: %s", exc)
                continue

        return faqs

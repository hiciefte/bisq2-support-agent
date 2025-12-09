"""Multi-layer classification system for Matrix message filtering."""

import re
from typing import TYPE_CHECKING, Dict, List, Optional, Tuple

# Avoid circular imports - only import for type hints
if TYPE_CHECKING:
    from app.services.shadow_mode.aisuite_classifier import AISuiteClassifier


class SpeakerRoleClassifier:
    """Distinguish user questions from support staff responses."""

    # Support staff indicators (advisory/explanatory language)
    STAFF_INDICATORS = [
        # Advisory language (lower weight - appears in 15.7% staff, 4% users)
        r"\b(?:you can|you should|you need to|you must)\b",
        r"\b(?:it is best to|i recommend|i suggest|you might want to)\b",
        # Diagnostic questions (staff asking user for info)
        r"^(?:are|is|do|does|did|have|has|can|could|would|will) you\b",
        r"have you (?:tried|checked|looked|contacted|seen|found)\b",  # ADDED: explicit "have you" pattern
        r"^what (?:(?:market|version|error|problem) (?:are you|do you|did you)|is the (?:deposit|trade))\b",  # FIXED: more specific
        r"^which .+ are you",
        r"^where (?:are you|did you)",
        r"can you send",  # ADDED: common staff request
        # Questions checking state (diagnostic)
        r"^is it always\b",
        r"^are seeing\b",
        # Explanatory statements
        r"\b(?:this means|this indicates|this is because|the reason is)\b",
        r"\b(?:this happens when|this occurs|this can prevent)\b",
        # References to system internals (FIXED: context-aware)
        r"\b(?:the|our|your) (?:seed nodes|price nodes|contributors|developers)\b",
        r"\b(?:logs at the time|check your logs)\b",
        r"\bthere is a .+ command\b",  # ADDED: command suggestions
        # Problem resolution language
        r"\b(?:once it resolved|wait it out|wait and retry)\b",
        r"\b(?:if you see|when you see|you will see)\b",
        r"\b(?:if there is)\b",
    ]

    # User indicators (help-seeking language)
    USER_INDICATORS = [
        # First-person problem descriptions
        r"\b(?:i am|i'm|i have|i've|i get|i got)\b",
        r"\bmy .+ (?:is|isn't|won't|doesn't|can't|can only|not|shows?|says?|tells?|displays?|vanishing|disappear(?:ing|ed)?)\b",  # ADDED: shows/says/tells, can only, vanishing/disappearing
        r"\b(?:i can't|i cannot|i couldn't|i tried|i performed|i moved)\b",
        # User actions with adversative context (ADDED: 50 real instances)
        r"\bi (?:opened|started|made|sent|performed|moved|tried|placed|created) .+ (?:but|and|however|although)\b",
        # Help-seeking (EXPANDED)
        r"\b(?:can|could|does) (?:someone|anyone)(?:\s+(?:know|help|have))?",  # EXPANDED: does anyone
        r"\banyone (?:know|having|else|experiencing)\b",  # ADDED: anyone variations
        r"\bhow (?:can (?:i|you)|do i|to|should i)\b",  # EXPANDED: added "to", "should i", "can you"
        r"\bwhat should (?:i|we|they|the (?:buyer|seller))\b",  # EXPANDED: added pronouns
        r"\b(?:where do i|where can i)\b",
        r"\b(?:any advice|please help)\b",
        # Greeting-based questions (ADDED: 216 real instances)
        r"^(?:hi|hello|hey)[\s,]+i (?:have|am|opened|made|sent|need|want|tried)\b",
        # Role identification (ADDED: 12 real instances)
        r"\bi am (?:the (?:buyer|seller)|trying|getting|having|in need of|stuck)\b",
        # Error reports from user perspective
        r"\b(?:i'm getting|getting this|seeing this|i got this) (?:error|message|warning)\b",
        r"\berror occurred.+my\b",
        # User actions
        r"\b(?:i opened|i started|i restarted|i moved|i restored)\b",
    ]

    @classmethod
    def classify_speaker_role(
        cls, message: str, sender: str, known_staff: List[str]
    ) -> Tuple[str, float]:
        """
        Classify speaker role as 'staff', 'user', or 'unknown'.

        Args:
            message: Message text
            sender: Sender ID
            known_staff: List of known support staff identifiers

        Returns:
            Tuple of (role, confidence) where role is 'staff', 'user', or 'unknown'
            and confidence is 0.0-1.0
        """
        # Check hardcoded staff list first (highest confidence)
        sender_lower = sender.lower()
        for staff in known_staff:
            if staff.lower() in sender_lower:
                return ("staff", 1.0)

        # Pattern-based role detection
        message_lower = message.lower()

        staff_score = sum(
            1 for pattern in cls.STAFF_INDICATORS if re.search(pattern, message_lower)
        )
        user_score = sum(
            1 for pattern in cls.USER_INDICATORS if re.search(pattern, message_lower)
        )

        # Calculate confidence based on score difference
        if staff_score > user_score:
            confidence = min(0.6 + (staff_score - user_score) * 0.1, 0.95)
            return ("staff", confidence)
        elif user_score > staff_score:
            confidence = min(0.6 + (user_score - staff_score) * 0.1, 0.95)
            return ("user", confidence)

        return ("unknown", 0.0)


class ConversationContextAnalyzer:
    """Analyze message position in conversation thread."""

    # Follow-up message patterns (AGGRESSIVE filtering for false positives)
    FOLLOW_UP_PATTERNS = [
        # Simple affirmatives/negatives
        r"^(?:yes|no|yeah|nah|yep|nope|yup)\b",
        r"^(?:indeed|alright|alrighty|okay|ok|sure)\b",
        # Gratitude expressions
        r"^(?:thanks|thank you|thx|ty|cheers|appreciate)",
        # State confirmations
        r"^(?:that|this|it) (?:is|was|does|doesn't|works|worked|makes sense)",
        r"^(?:i see|got it|understood|makes sense|figured it out)",
        r"\b(?:no problem|all good|never mind|nevermind)\b",
        # Agreement with previous statements (FALSE POSITIVE: "Same here")
        r"^same here\b",
        # Responses to staff members (FALSE POSITIVES: "OK username", "Yes username")
        r"^(?:ok|okay) (?:@?\w+|[a-z]+\d+)\b",  # "OK mwithm", "okay username"
        r"^(?:yes|yeah) (?:@?\w+|[a-z]+\d+)\b",  # "Yes suddenwhipvapor"
        # Clarification requests in response (FALSE POSITIVE: "What do you mean")
        r"^what do you mean\b",
        # Acknowledgments (FALSE POSITIVE: "i know")
        r"^i know\b",
        # Testing/trying based on previous advice
        r"^i (?:have not tested|tried|will try)\b",
        # Incomplete fragments or status updates
        r"^\.\.\.",  # Trailing thought from previous message
    ]

    # Initial question patterns
    INITIAL_QUESTION_PATTERNS = [
        r"^(?:hi|hello|hey|gm|good morning|morning).*(?:\?|help|issue|problem|error)",  # ADDED: GM greeting (Q11)
        r"^i (?:have|got|am having|am getting|need|want)",
        r"^(?:quick question|question|help needed|can anyone)",
        r"^hello,.+(?:won't|doesn't|can't|not|issue|problem|error)",
        r"^hey,.+(?:won't|doesn't|can't|not|issue|problem|error)",
        r"^hey,.+question\b",
        r"^gm .+(?:woke up|message about)",  # ADDED: GM + implicit problem (Q11)
    ]

    @classmethod
    def contains_staff_addressing(cls, message: str, known_staff: List[str]) -> bool:
        """
        Detect if message is addressing a known staff member.

        Args:
            message: Message text to analyze
            known_staff: List of known support staff usernames

        Returns:
            True if message contains staff username (indicating response to staff)
        """
        message_lower = message.lower()

        # Check for staff usernames in message content
        for staff_name in known_staff:
            staff_lower = staff_name.lower()
            # Check for @username or bare username at word boundaries
            if re.search(rf"\b@?{re.escape(staff_lower)}\b", message_lower):
                return True

        return False

    @classmethod
    def is_follow_up_message(
        cls,
        message: str,
        prev_messages: List[str],
        known_staff: Optional[List[str]] = None,
    ) -> bool:
        """
        Detect if message is responding to previous context.

        Args:
            message: Current message text
            prev_messages: List of previous messages in thread
            known_staff: Optional list of staff usernames to detect addressing

        Returns:
            True if message appears to be a follow-up
        """
        message_lower = message.lower().strip()

        # Check if message addresses a staff member (response to staff)
        if known_staff and cls.contains_staff_addressing(message, known_staff):
            return True

        # Check follow-up patterns
        for pattern in cls.FOLLOW_UP_PATTERNS:
            if re.search(pattern, message_lower):
                return True

        # Check if message references previous message content
        if prev_messages:
            last_msg = prev_messages[-1].lower()
            msg_words = set(message_lower.split())
            last_words = set(last_msg.split())

            # Filter out common words
            common_words = {
                "the",
                "a",
                "an",
                "is",
                "are",
                "was",
                "were",
                "i",
                "you",
                "it",
                "to",
                "in",
                "on",
                "for",
                "with",
                "but",
                "still",
            }
            msg_words -= common_words
            last_words -= common_words

            # High overlap suggests response/follow-up
            if msg_words and last_words:
                overlap = len(msg_words & last_words) / len(msg_words)
                # Special case: explicit reference to previous suggestion
                if "tried" in message_lower and len(msg_words & last_words) >= 2:
                    return True
                if overlap > 0.25:  # Lowered threshold to catch more follow-ups
                    return True

        return False

    @classmethod
    def is_initial_question(cls, message: str) -> bool:
        """
        Detect if message is starting a new support request.

        Args:
            message: Message text

        Returns:
            True if message appears to be an initial question
        """
        message_lower = message.lower()

        for pattern in cls.INITIAL_QUESTION_PATTERNS:
            if re.search(pattern, message_lower):
                return True

        return False


class MessageIntentClassifier:
    """Classify message intent using semantic patterns."""

    INTENT_TAXONOMY = {
        "support_question": [
            # Help-seeking questions
            r"\b(?:how do i|how can i|how to|what should i do|where do i)\b",
            r"\b(?:i'm trying to|i'm attempting|i want to|i need to)\b",
            r"\bi am trying to\b",  # ADDED: action + obstacle pattern (Q13)
            # Continuous problem statements
            r"\bi (?:keep|kept) having\b",  # ADDED: ongoing issues (Q2)
            # Need variations
            r"\b(?:in need of|need to get|need help with)\b",  # ADDED: help-seeking variant (Q4)
            # Direct question words at start
            r"^(?:who|what|when|where|why|which|whose) (?:is|are|was|were|do|does|did|can|could|should|would)\b",  # ADDED: Q3, Q14
            # Error reporting
            r"\b(?:getting error|getting message|getting this error|seeing error|error occurred)\b",
            r"\b(?:i'm getting|i am getting)\b",
            # Implicit problem reporting
            r"\b(?:still|yet) (?:shows?|displays?|says?)\b",  # ADDED: implicit problems (Q12)
            # Problems and obstacles
            r"\b(?:not working|doesn't work|isn't working|won't work|not syncing)\b",
            r"\b(?:can't|cannot|unable to|not able to)\b",
            # Help-seeking language
            r"\b(?:help|please help|need help|any advice|anyone know)\b",
            # Problem descriptions
            r"\b(?:my .+ (?:is|isn't|won't|doesn't|not))\b",
            r"\b(?:i moved|i restored|i performed)\b",
            r"\b(?:don't see|can't see|not seeing)\b",
        ],
        "information_sharing": [
            r"\b(?:fyi|for your information|just letting you know)\b",
            r"\b(?:i found|i discovered|i noticed)\b",
            r"^(?:this is|here is|there is)\b",
            r"\b(?:pointing out|found something)\b",
        ],
        "warning": [
            r"\b(?:scam|scammer|scammers|phishing|fake|impersonat|fraudulent)\b",
            r"\b(?:be careful|watch out|beware|warning)\b",
            r"\b(?:banned|ban them|get them banned)\b",
        ],
        "acknowledgment": [
            r"^(?:thanks|thank you|thx|ty|appreciate|cheers)\b",
            r"\b(?:thank you)\b",
            r"\b(?:got it|understood|makes sense|i see)\b",
            r"\b(?:that worked|that fixed|that solved)\b",
            r"\b(?:no problem|all good|nevermind)\b",
        ],
        "staff_explanation": [
            r"\b(?:this means|this indicates|the reason is)\b",
            r"\b(?:you can|you should|try|check your)\b",
            r"\b(?:if there is|when there is|once it resolved)\b",
        ],
    }

    @classmethod
    def classify_intent(cls, message: str) -> Tuple[str, float]:
        """
        Classify message intent.

        Args:
            message: Message text

        Returns:
            Tuple of (intent, confidence) where intent is one of the taxonomy keys
            or 'unknown', and confidence is 0.0-1.0
        """
        message_lower = message.lower()
        scores: Dict[str, int] = {}

        for intent, patterns in cls.INTENT_TAXONOMY.items():
            scores[intent] = sum(
                1 for pattern in patterns if re.search(pattern, message_lower)
            )

        if max(scores.values()) > 0:
            best_intent = max(scores, key=scores.get)
            # Calculate confidence based on score
            confidence = min(0.6 + scores[best_intent] * 0.15, 0.95)
            return (best_intent, confidence)

        return ("unknown", 0.0)


class ContentTypeFilter:
    """Filter non-textual content and quoted text."""

    @staticmethod
    def is_url_only(message: str) -> bool:
        """
        Check if message is just a URL.

        Args:
            message: Message text

        Returns:
            True if message contains only a URL
        """
        url_pattern = r"^https?://[^\s]+$"
        return bool(re.match(url_pattern, message.strip()))

    @staticmethod
    def is_quoted_text(message: str) -> bool:
        """
        Check if message is primarily quoted text.

        Args:
            message: Message text

        Returns:
            True if >50% of message is quoted
        """
        # Count quoted characters
        quoted_text = re.findall(r'["\']([^"\']+)["\']', message)
        quoted_length = sum(len(text) for text in quoted_text)

        total_length = len(message)
        if total_length == 0:
            return False

        return quoted_length / total_length > 0.5

    @staticmethod
    def extract_original_content(message: str) -> str:
        """
        Remove quoted content and URLs, return only original text.

        Args:
            message: Message text

        Returns:
            Original text content
        """
        # Remove quoted blocks
        message = re.sub(r'["\'].*?["\']', "", message)
        # Remove URLs
        message = re.sub(r"https?://[^\s]+", "", message)
        # Remove Matrix reply markers ("> <@user:server>")
        message = re.sub(r"^>\s*<@[^>]+>.*$", "", message, flags=re.MULTILINE)

        return message.strip()

    @staticmethod
    def has_meaningful_content(message: str, min_length: int = 20) -> bool:
        """
        Check if message has meaningful content after filtering.

        Args:
            message: Message text
            min_length: Minimum length for meaningful content

        Returns:
            True if message has substantial original content
        """
        original_content = ContentTypeFilter.extract_original_content(message)
        return len(original_content) >= min_length


class MultiLayerClassifier:
    """Orchestrate all classification layers for comprehensive filtering."""

    def __init__(
        self,
        known_staff: Optional[List[str]] = None,
        llm_classifier: Optional["AISuiteClassifier"] = None,
        enable_llm: bool = False,
        llm_threshold: float = 0.85,
    ):
        """
        Initialize multi-layer classifier.

        Args:
            known_staff: List of known support staff identifiers
            llm_classifier: Optional AISuite LLM classifier for fallback
            enable_llm: Enable LLM fallback for low-confidence patterns
            llm_threshold: Min pattern confidence to skip LLM (default: 0.85)
        """
        self.known_staff = known_staff or []
        self.llm_classifier = llm_classifier
        self.enable_llm = enable_llm
        self.llm_threshold = llm_threshold

    async def classify_message(
        self, message: str, sender: str = "", prev_messages: Optional[List[str]] = None
    ) -> Dict[str, any]:
        """
        Run all classification layers and return comprehensive results.

        Args:
            message: Message text
            sender: Sender ID
            prev_messages: Previous messages in conversation thread

        Returns:
            Dictionary with classification results from all layers
        """
        prev_messages = prev_messages or []

        # CRITICAL: Filter Matrix edit markers (MSC2676 - edited messages have "* " prefix)
        # These are duplicate/edited versions shown for backward compatibility
        if message.strip().startswith("* "):
            return {
                "is_question": False,
                "confidence": 1.0,
                "reason": "matrix_edit_marker",
                "speaker_role": "unknown",
                "intent": "unknown",
                "is_follow_up": False,
            }

        # Layer 4: Content type filtering (fastest, eliminate obvious non-questions)
        is_url = ContentTypeFilter.is_url_only(message)
        is_quoted = ContentTypeFilter.is_quoted_text(message)
        has_content = ContentTypeFilter.has_meaningful_content(message)

        if is_url or is_quoted or not has_content:
            return {
                "is_question": False,
                "confidence": 1.0,
                "reason": (
                    "url_only"
                    if is_url
                    else "quoted_text" if is_quoted else "no_content"
                ),
                "speaker_role": "unknown",
                "intent": "unknown",
                "is_follow_up": False,
            }

        # Layer 1: Speaker role detection
        speaker_role, role_confidence = SpeakerRoleClassifier.classify_speaker_role(
            message, sender, self.known_staff
        )

        # Log pattern classification result
        import logging

        logger = logging.getLogger(__name__)
        logger.info(
            f"📊 Classification for message from {sender}: '{message[:100]}...'"
        )
        logger.info(
            f"  ├─ Pattern classification: role={speaker_role}, confidence={role_confidence:.2f}"
        )

        # LLM Fallback: If pattern confidence is low and LLM is enabled, use LLM classifier
        if (
            self.enable_llm
            and self.llm_classifier
            and role_confidence < self.llm_threshold
        ):
            logger.info(
                f"  ├─ Pattern confidence ({role_confidence:.2f}) < threshold ({self.llm_threshold:.2f})"
            )
            logger.info(f"  ├─ 🤖 Calling LLM classifier for fallback...")

            try:
                llm_result = await self.llm_classifier.classify(
                    message=message, sender_id=sender, prev_messages=prev_messages
                )

                # Map LLM role to our speaker_role format
                llm_role = "staff" if llm_result["role"] == "STAFF_RESPONSE" else "user"
                llm_confidence = llm_result["confidence"]

                logger.info(
                    f"  ├─ LLM classification: role={llm_role}, confidence={llm_confidence:.2f}"
                )
                logger.info(
                    f"  ├─ LLM breakdown: keyword={llm_result['confidence_breakdown']['keyword_match']}/25, "
                    f"syntax={llm_result['confidence_breakdown']['syntax_pattern']}/25, "
                    f"semantic={llm_result['confidence_breakdown']['semantic_clarity']}/30, "
                    f"context={llm_result['confidence_breakdown']['context_alignment']}/20"
                )

                # Use LLM result if confidence is sufficient
                if llm_confidence >= 0.5:  # Minimum threshold for LLM results
                    speaker_role = llm_role
                    role_confidence = llm_confidence
                    logger.info(
                        f"  └─ ✅ Using LLM result (confidence={llm_confidence:.2f} >= 0.5)"
                    )
                else:
                    logger.info(
                        f"  └─ ⚠️  LLM confidence too low ({llm_confidence:.2f} < 0.5), keeping pattern result"
                    )

            except Exception as e:
                # Log error but continue with pattern-based result
                logger.warning(
                    f"  └─ ❌ LLM classification failed, using pattern result: {e}"
                )
        else:
            logger.info(
                f"  └─ ✅ Using pattern result (confidence={role_confidence:.2f} >= threshold or LLM disabled)"
            )

        # Filter staff responses (even with medium confidence if pattern is clear)
        if speaker_role == "staff" and role_confidence > 0.6:
            return {
                "is_question": False,
                "confidence": role_confidence,
                "reason": "support_staff_response",
                "speaker_role": speaker_role,
                "intent": "staff_explanation",
                "is_follow_up": False,
            }

        # Layer 3: Message intent classification (check before context for better priority)
        intent, intent_confidence = MessageIntentClassifier.classify_intent(message)

        # Layer 2: Conversation context analysis
        is_follow_up = ConversationContextAnalyzer.is_follow_up_message(
            message, prev_messages, known_staff=self.known_staff
        )
        is_initial = ConversationContextAnalyzer.is_initial_question(message)

        # AGGRESSIVE FOLLOW-UP FILTERING: Follow-ups are ALWAYS filtered
        # This prevents false positives from responses/acknowledgments/clarifications
        # User explicitly requested "more aggressive follow-up filtering"
        if is_follow_up:
            return {
                "is_question": False,
                "confidence": 0.9,  # High confidence - follow-up detection is strong
                "reason": "follow_up_message",
                "speaker_role": speaker_role,
                "intent": intent,
                "is_follow_up": True,
            }

        if intent in ["warning", "information_sharing", "acknowledgment"]:
            return {
                "is_question": False,
                "confidence": intent_confidence,
                "reason": f"intent_{intent}",
                "speaker_role": speaker_role,
                "intent": intent,
                "is_follow_up": is_follow_up,
            }

        # Positive classification: likely a user question
        if intent == "support_question" or is_initial:
            confidence = max(intent_confidence, 0.7 if is_initial else 0.5)
            return {
                "is_question": True,
                "confidence": confidence,
                "reason": "support_question",
                "speaker_role": speaker_role,
                "intent": intent,
                "is_follow_up": False,
            }

        # Unknown classification - default to not a question (conservative)
        return {
            "is_question": False,
            "confidence": 0.5,
            "reason": "unknown_intent",
            "speaker_role": speaker_role,
            "intent": intent,
            "is_follow_up": is_follow_up,
        }

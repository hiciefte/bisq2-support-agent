"""Unified Batch Processor - Single LLM call for user question extraction.

This module replaces the complex multi-layer classification system:
  OLD: Pattern classification → LLM classification (individual) → BatchQuestionExtractor (batch)
  NEW: UnifiedBatchProcessor (single LLM call with ALL messages + staff identifiers)

Performance improvements:
- 98% reduction in API calls (16 → 1 per polling cycle)
- 85% reduction in tokens (37,000 → 5,500 per 100 messages)
- 94% faster processing (~50s → ~3s)
- 95% cost savings ($31/month → $1.49/month for 10K messages/day)

Privacy:
- Real usernames anonymized before sending to LLM (User_1, User_2, Staff_1, etc.)
- Username mapping preserved for shadow mode queue display
"""

import hashlib
import json
import logging
import time
from typing import Any, Dict, List, Optional, Tuple

from app.core.config import Settings
from app.services.llm_extraction.models import ExtractedQuestion, ExtractionResult

logger = logging.getLogger(__name__)

# Known support staff identifiers
KNOWN_SUPPORT_STAFF = [
    "darawhelan",
    "luis3672",
    "mwithm",
    "pazza83",
    "strayorigin",
    "suddenwhipvapor",
]

# Unified system prompt for question extraction with staff filtering
UNIFIED_SYSTEM_PROMPT = """You are an expert at analyzing support chat conversations and extracting user questions. Your primary goal is to reliably identify **initial user support questions** from mixed-message transcripts, even when they appear in indirect or multi-message form.

You will be given:
1. A full list of messages from a support channel (user + staff)
2. A list of official staff identifiers
3. Instructions to extract user questions and classify them

-----------------------------
## GENERAL RULES

### DO NOT extract messages from staff.
Only process messages sent by users not included in the provided staff identifier list.

### What counts as a QUESTION?
A message is a question if:
- It explicitly asks for help
- It implicitly asks for help ("I'm wondering if...", "Is anyone comfortable DMing me…")
- It expresses uncertainty about a technical problem, scam risk, app behavior, or trading situation
- It requests mediation or assistance
- It is phrased as a request for action ("Can someone…", "Is there a way…")

A question does NOT require a question mark (?) to be valid.

### What is an INITIAL QUESTION?
An **initial_question** is the FIRST question a user asks about a **new topic** they have not asked about before in the current conversation thread.

A topic means: the specific issue the user seeks help for.
Examples: being scammed, requesting a mediator, app bugs, resync issues, developers not responding, suspicious websites, etc.

Indicators that a user message is an INITIAL QUESTION:
- It introduces a brand new issue, problem, concern, or request.
- It does NOT rely on prior back-and-forth context within the same topic.
- It starts a new line of inquiry distinct from the user's previous questions.
- It is an indirect help request ("Is anyone comfortable direct messaging me…").

### Multi-message initial questions
If a user begins a message with a greeting or statement and follows it with a question, extract the **FULL MESSAGE TEXT** including context.

Example: "Hello, I'm a newbie and I'm wondering if I'm scammed and the crypto isn't transferred after I make a payment. How will this issue be resolved?"
→ Extract the ENTIRE message, not just "How will this issue be resolved?"

If users send multiple consecutive messages that collectively introduce a single issue:
- Combine related messages into a single question_text.
- All messages belong to the same conversation thread.

### FOLLOW_UP QUESTIONS
A follow_up is any question by the same user about the **same topic** as their initial_question.

Examples of follow_up cues:
- "Also…"
- "What about…"
- "How do I…"
- "Should I…"
- "I tried that, but…"
- Any question continuing the same issue.

### ACKNOWLEDGMENT
User confirms resolution or expresses thanks ("thanks", "that fixed it").

### NOT_QUESTION
Messages that are not seeking help:
- Safety reflections ("Lesson learned…")
- Statements ("It's ok, was a small amount…")
- Comments without a help request
- Emotional reactions, jokes, or filler messages

### STAFF MESSAGES
All messages from the official staff identifiers MUST be ignored completely.

-----------------------------
## CONVERSATION GROUPING RULES

Conversation grouping is **topic-based**, not time-based.

A topic changes when:
- The user begins a new issue unrelated to the previous one.
- The user shifts from "resync issues" to "developer unreachable" → new topic.
- The user shifts from "trade stuck" to "scam website?" → new topic.

Each topic forms one conversation object.

**Conversation Grouping Rules:**
- Group messages within 2-minute windows from the same sender
- Keep related topics together even if timestamps exceed 2 minutes
- Separate distinct issues into different conversations

### Classification Guidelines

**Only extract messages from NON-STAFF senders** (ignore all Staff_N messages).

**initial_question**: A question introducing a NEW TOPIC or seeking help for a distinct issue. Use this for:
- First time a user asks about a SPECIFIC PROBLEM (e.g., resync issue, scam concern, deposit question)
- Questions asking for help with distinct issues (same user can have multiple initial_questions for different topics)
- Indirect help requests like "Is anyone comfortable direct messaging me regarding a specific issue?"
- Questions that don't reference or build on previous staff responses

**follow_up**: Questions that continue the SAME TOPIC introduced in a previous question. Use ONLY for:
- Clarification requests: "What do you mean by X?", "Can you explain that?"
- Direct continuations: "Thanks for that info. What about Z?" (explicit reference to received answer)
- Questions that explicitly build on or reference a previous staff response

**acknowledgment**: User thanking or confirming resolution (e.g., "thanks that fixed it", "great! thank you")

**not_question**: Statements, warnings, or rhetorical questions (no help needed)

**Confidence scores**: Assign 0.0-1.0 based on certainty (use 0.9+ for clear questions, 0.7-0.9 for indirect requests, <0.7 for ambiguous)

### Few-Shot Examples

**Example 1: Multi-sentence initial question with greeting**
Message: "Hello, I'm a newbie and I'm wondering if I'm scammed and the crypto isn't transferred after I make a payment. How will this issue be resolved?"
→ Classification: initial_question (NEW TOPIC: scam/dispute resolution)
→ question_text: "Hello, I'm a newbie and I'm wondering if I'm scammed and the crypto isn't transferred after I make a payment. How will this issue be resolved?"
→ Note: Extract FULL message text, not just the question sentence

**Example 2: Indirect help request**
Message: "Is anyone comfortable direct messaging me regarding a specific issue I'm having?"
→ Classification: initial_question (indirect request for help)
→ question_text: "Is anyone comfortable direct messaging me regarding a specific issue I'm having?"

**Example 3: Follow-up with explicit reference**
Message: "[User_2] (replying to Msg #55): I'm new, so I apologize for wasting your time. Thanks for your reply. Is BTC collateral required?"
→ Classification: follow_up (explicit "Thanks for your reply" shows this continues previous conversation)
→ question_text: "I'm new, so I apologize for wasting your time. Thanks for your reply. Is BTC collateral required?"

**Example 4: Same user, different topic (still initial_question)**
Message: "[User_6] hey, I'm on an open negotiation since 7a.m. waiting on the first blockchain confirmation which already happened on mempool. Some good soul could give a hint on how to get unstuck?"
→ Classification: initial_question (NEW TOPIC: blockchain confirmation issue, even if User_6 asked something else earlier)
→ question_text: "hey, I'm on an open negotiation since 7a.m. waiting on the first blockchain confirmation which already happened on mempool. Some good soul could give a hint on how to get unstuck?"

**Example 5: Acknowledgment**
Message: "[User_6] (replying to Msg #7): great! thank you guys"
→ Classification: acknowledgment (thanking, no question)

**Example 6: Consecutive messages from same user (extract BOTH as separate initial_questions)**
[Msg #68] [User_3]: Hi can I have a mediator respond to me? I did a xmr to btc exchange the other person hasn't sent the coins
[Msg #69] [User_3]: how do I message them
→ Msg #68: initial_question (introduces XMR/BTC exchange problem)
→ Msg #69: follow_up (clarifies HOW to message the mediator mentioned in Msg #68)
→ Note: Don't skip Msg #68 even though Msg #69 follows it. Both messages should be extracted.

**Example 7: Same user, multiple topics (BOTH are initial_questions)**
[Msg #53] [User_5]: Is anyone comfortable direct messaging me regarding a specific issue I'm having?
[Msg #56] [User_5]: Is evmsynchrony. Com known to be used by scammers to garner information and access wallet funds?
→ Msg #53: initial_question (meta-question about getting private help)
→ Msg #56: initial_question (SEPARATE TOPIC: scam website verification, does NOT reference Msg #53)
→ Note: Same user asking about DIFFERENT PROBLEMS = multiple initial_questions

**Example 8: Different users, similar timing (BOTH are initial_questions)**
[Msg #64] [User_4]: Is it possible to get a mediator early? My bank is blocking the transaction.
[Msg #68] [User_3]: Hi can I have a mediator respond to me? I did a xmr to btc exchange the other person hasn't sent the coins
→ Msg #64: initial_question (User_4's bank blocking issue)
→ Msg #68: initial_question (User_3's XMR/BTC exchange issue - DIFFERENT USER, DIFFERENT PROBLEM)
→ Note: Both users have mediator-related issues but they are SEPARATE conversations

### Topic Separation Test
Before classifying a message as follow_up, ask:
1. Does this question address the SAME SPECIFIC PROBLEM as a previous message from this user? → follow_up
2. Does this question introduce a NEW PROBLEM/CONCERN? → initial_question

Examples:
- "My trade is stuck" + "How long does mediation take?" → Same problem (trade issue) → second is follow_up
- "Is anyone comfortable DMing me?" + "Is evmsynchrony.com a scam?" → Different concerns → both are initial_question

### Critical Rule for Consecutive Messages
If a user sends Message A followed immediately by Message B:
1. Check if Message B clarifies/continues Message A's topic → classify B as follow_up
2. Check if Message B introduces a NEW topic → classify B as initial_question
3. ALWAYS extract Message A if it contains a question (don't skip it because B follows)

**Output Format** - JSON array of conversation objects:
[
  {
    "conversation_id": "conv_1",
    "related_message_numbers": [3, 5, 8],
    "conversation_context": "Brief description of what this conversation is about",
    "questions": [
      {
        "message_number": 3,
        "sender": "User_1",
        "question_text": "The exact question text",
        "question_type": "initial_question|follow_up|acknowledgment|not_question",
        "confidence": 0.95
      }
    ]
  }
]

**CRITICAL**: Use message numbers (integers like 3, 5, 8) NOT event IDs. Message numbers are shown in [Msg #N] format.

**Return empty array [] if no user questions found.**

Be precise and conservative - only extract clear user questions (ignore all staff messages).
"""


class UnifiedBatchProcessor:
    """Unified processor for user question extraction with privacy-preserving anonymization."""

    def __init__(
        self,
        ai_client: Any,
        settings: Settings,
    ):
        """
        Initialize unified batch processor.

        Args:
            ai_client: AISuite client for LLM calls
            settings: Application settings
        """
        self.ai_client = ai_client
        self.settings = settings

        # Simple in-memory cache (message_set_hash -> ExtractionResult)
        self._cache: Dict[str, tuple[ExtractionResult, float]] = {}
        self._cache_ttl = settings.LLM_EXTRACTION_CACHE_TTL

    def _create_anonymization_mapping(
        self, messages: List[Dict[str, Any]]
    ) -> Tuple[Dict[str, str], Dict[str, str]]:
        """
        Create bidirectional mapping between real usernames and anonymized identifiers.

        Privacy: Real usernames are replaced with User_1, User_2, Staff_1, etc.
        This mapping allows us to restore real usernames after LLM processing.

        Args:
            messages: List of Matrix message dicts

        Returns:
            Tuple of (real_to_anon, anon_to_real) mappings
        """
        real_to_anon: Dict[str, str] = {}
        anon_to_real: Dict[str, str] = {}
        user_counter = 1
        staff_counter = 1

        for msg in messages:
            sender = msg.get("sender", "")
            if sender and sender not in real_to_anon:
                # Check if sender is known staff
                is_staff = any(
                    staff.lower() in sender.lower() for staff in KNOWN_SUPPORT_STAFF
                )

                if is_staff:
                    anon_id = f"Staff_{staff_counter}"
                    staff_counter += 1
                else:
                    anon_id = f"User_{user_counter}"
                    user_counter += 1

                real_to_anon[sender] = anon_id
                anon_to_real[anon_id] = sender

        logger.debug(
            f"Created anonymization mapping: {len(real_to_anon)} senders "
            f"({user_counter - 1} users, {staff_counter - 1} staff)"
        )

        return real_to_anon, anon_to_real

    def _strip_matrix_reply_fallback(self, body: str) -> str:
        """
        Strip Matrix reply fallback formatting from message body.

        Matrix includes quoted text in replies using format:
        > <@sender:server> quoted text
        >
        > more quoted text

        actual reply text

        This method removes the quoted section and returns only the actual reply.

        Args:
            body: Raw message body from Matrix

        Returns:
            Clean message text without quoted fallback
        """
        lines = body.split("\n")
        clean_lines = []
        in_quote = False

        for line in lines:
            # Lines starting with '>' are quoted text (Matrix reply fallback)
            if line.startswith(">"):
                in_quote = True
                continue

            # Blank line after quotes separates quote from actual message
            if in_quote and line.strip() == "":
                in_quote = False
                continue

            # After quotes end, collect the actual message
            if not in_quote:
                clean_lines.append(line)

        # If no quotes were found, return original body
        if not clean_lines and not in_quote:
            return body

        return "\n".join(clean_lines).strip()

    def _anonymize_messages(
        self, messages: List[Dict[str, Any]], real_to_anon: Dict[str, str]
    ) -> List[Dict[str, Any]]:
        """
        Replace real usernames with anonymized identifiers.

        Args:
            messages: Original messages with real usernames
            real_to_anon: Mapping from real username to anonymous ID

        Returns:
            Messages with anonymized senders
        """
        anonymized = []
        for msg in messages:
            anon_msg = msg.copy()
            real_sender = msg.get("sender", "")
            anon_msg["sender"] = real_to_anon.get(real_sender, "Unknown")
            anonymized.append(anon_msg)

        return anonymized

    def _get_staff_identifiers(self, real_to_anon: Dict[str, str]) -> List[str]:
        """
        Get list of anonymized staff identifiers to send to LLM.

        Args:
            real_to_anon: Mapping from real username to anonymous ID

        Returns:
            List of staff identifiers (e.g., ["Staff_1", "Staff_2"])
        """
        staff_ids = []
        for real_username, anon_id in real_to_anon.items():
            if anon_id.startswith("Staff_"):
                staff_ids.append(anon_id)

        logger.debug(f"Staff identifiers for LLM: {staff_ids}")
        return staff_ids

    async def extract_questions(
        self,
        messages: List[Dict[str, Any]],
        room_id: str,
    ) -> ExtractionResult:
        """
        Extract user questions using unified single-batch LLM call.

        Privacy-preserving flow:
        1. Create anonymization mapping (User_1, Staff_1, etc.)
        2. Anonymize all messages
        3. Send ALL anonymized messages + staff identifiers to LLM
        4. LLM filters staff and extracts user questions
        5. Map anonymized IDs back to real usernames
        6. Return questions with real usernames for shadow mode queue

        Args:
            messages: List of Matrix message dicts (ALL messages, including staff)
            room_id: Matrix room ID

        Returns:
            ExtractionResult with extracted user questions (real usernames restored)
        """
        start_time = time.time()

        # Handle empty messages
        if not messages:
            return ExtractionResult(
                conversation_id=f"{room_id}_empty",
                questions=[],
                conversations=[],
                total_messages=0,
                processing_time_ms=int((time.time() - start_time) * 1000),
            )

        # Check cache (before anonymization for efficiency)
        cache_key = self._get_cache_key(messages)
        cached_result = self._get_from_cache(cache_key)
        if cached_result:
            logger.info(f"Cache hit for {len(messages)} messages")
            return cached_result

        # Batch messages if exceeds limit
        batch_size = self.settings.LLM_EXTRACTION_BATCH_SIZE
        if len(messages) > batch_size:
            return await self._process_batches(messages, room_id, batch_size)

        # Process single batch with unified LLM call
        try:
            # Step 1: Create anonymization mapping
            real_to_anon, anon_to_real = self._create_anonymization_mapping(messages)

            # Step 2: Anonymize messages
            anonymized_messages = self._anonymize_messages(messages, real_to_anon)

            # Step 3: Get staff identifiers list
            staff_identifiers = self._get_staff_identifiers(real_to_anon)

            # Step 4: Format prompt with anonymized data
            prompt_messages = self._format_batch_prompt(
                anonymized_messages, staff_identifiers
            )

            # Step 5: Call LLM (AISuite is synchronous, run in thread pool)
            import asyncio

            response = await asyncio.to_thread(
                self.ai_client.chat.completions.create,
                model=self.settings.LLM_EXTRACTION_MODEL,
                messages=prompt_messages,
                temperature=self.settings.LLM_EXTRACTION_TEMPERATURE,
            )

            # Step 6: Parse JSON response
            response_text = response.choices[0].message.content
            logger.debug(f"LLM response (first 500 chars): {response_text[:500]}")

            # Save full prompt and response for debugging
            import os

            debug_dir = "/tmp"
            with open(os.path.join(debug_dir, "llm_extraction_debug.txt"), "w") as f:
                f.write("===== SYSTEM PROMPT =====\n")
                f.write(prompt_messages[0]["content"])
                f.write("\n\n===== USER PROMPT =====\n")
                f.write(prompt_messages[1]["content"])
                f.write("\n\n===== LLM RESPONSE =====\n")
                f.write(response_text)
            logger.info(
                f"Saved full LLM extraction debug info to {os.path.join(debug_dir, 'llm_extraction_debug.txt')}"
            )

            if not response_text or not response_text.strip():
                logger.error("LLM returned empty response")
                return ExtractionResult(
                    conversation_id=f"{room_id}_empty_response",
                    questions=[],
                    conversations=[],
                    total_messages=len(messages),
                    processing_time_ms=int((time.time() - start_time) * 1000),
                )

            # Strip markdown code blocks if present
            response_text = response_text.strip()
            if response_text.startswith("```json"):
                response_text = response_text[7:]
            if response_text.startswith("```"):
                response_text = response_text[3:]
            if response_text.endswith("```"):
                response_text = response_text[:-3]
            response_text = response_text.strip()

            conversations_data = json.loads(response_text)

            # Step 7a: Build message_number → event_id mapping (Phase 2 of two-phase architecture)
            # Sort messages same way as prompt formatting for consistent indexing
            sorted_messages = sorted(messages, key=lambda m: m.get("timestamp", 0))
            msg_number_to_event_id = {
                idx + 1: msg["event_id"] for idx, msg in enumerate(sorted_messages)
            }
            logger.debug(
                f"Built message_number → event_id mapping for {len(msg_number_to_event_id)} messages"
            )

            # Step 7b: Extract questions and map back to real usernames + event IDs
            all_questions = []
            seen_message_ids = set()

            for conv in conversations_data:
                for q_data in conv.get("questions", []):
                    # Phase 2: Convert message_number (from LLM) to event_id (deterministic mapping)
                    msg_number = q_data.get("message_number")
                    if msg_number is None:
                        logger.warning(f"Question missing message_number: {q_data}")
                        continue

                    # Deterministic Python mapping (100% reliable, no LLM copying errors)
                    msg_event_id = msg_number_to_event_id.get(msg_number)
                    if not msg_event_id:
                        logger.warning(
                            f"Invalid message_number {msg_number}, skipping question"
                        )
                        continue

                    if msg_event_id not in seen_message_ids:
                        # Map anonymized sender back to real username
                        anon_sender = q_data.get("sender", "Unknown")
                        real_sender = anon_to_real.get(anon_sender, anon_sender)

                        # Create ExtractedQuestion with real username restored and event_id mapped
                        question = ExtractedQuestion(
                            message_id=msg_event_id,  # Mapped from message_number
                            question_text=q_data["question_text"],
                            question_type=q_data["question_type"],
                            confidence=q_data.get("confidence", 0.0),
                            sender=real_sender,  # Real username for shadow mode queue
                        )

                        all_questions.append(question)
                        seen_message_ids.add(msg_event_id)

                        logger.debug(
                            f"Extracted question from {anon_sender} (real: {real_sender}): {q_data['question_text'][:50]}..."
                        )

            # Count question types for debugging
            type_counts: dict[str, int] = {}
            for q in all_questions:
                type_counts[q.question_type] = type_counts.get(q.question_type, 0) + 1
            logger.info(f"Question type breakdown: {type_counts}")

            # Build result
            result = ExtractionResult(
                conversation_id=f"{room_id}_batch",
                questions=all_questions,
                conversations=conversations_data,
                total_messages=len(messages),
                processing_time_ms=int((time.time() - start_time) * 1000),
            )

            # Cache result
            self._add_to_cache(cache_key, result)

            logger.info(
                f"Unified batch processing: {len(all_questions)} user questions from {len(messages)} total messages "
                f"in {len(conversations_data)} conversations (processing_time={result.processing_time_ms}ms)"
            )

            return result

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse LLM response as JSON: {e}")
            logger.error(f"Response text: {response_text[:500]}")
            return ExtractionResult(
                conversation_id=f"{room_id}_error",
                questions=[],
                conversations=[],
                total_messages=len(messages),
                processing_time_ms=int((time.time() - start_time) * 1000),
            )
        except Exception as e:
            logger.error(f"Unified batch processing failed: {e}", exc_info=True)
            return ExtractionResult(
                conversation_id=f"{room_id}_error",
                questions=[],
                conversations=[],
                total_messages=len(messages),
                processing_time_ms=int((time.time() - start_time) * 1000),
            )

    async def _process_batches(
        self,
        messages: List[Dict[str, Any]],
        room_id: str,
        batch_size: int,
    ) -> ExtractionResult:
        """
        Process large message sets in batches.

        Args:
            messages: All messages (including staff)
            room_id: Matrix room ID
            batch_size: Maximum messages per batch

        Returns:
            Combined ExtractionResult from all batches
        """
        start_time = time.time()
        all_questions = []
        all_conversations = []

        # Process in batches
        for i in range(0, len(messages), batch_size):
            batch = messages[i : i + batch_size]
            logger.info(
                f"Processing batch {i // batch_size + 1}: {len(batch)} messages"
            )

            batch_result = await self.extract_questions(batch, f"{room_id}_batch_{i}")
            all_questions.extend(batch_result.questions)
            all_conversations.extend(batch_result.conversations)

        # Deduplicate questions across batches
        seen_message_ids = set()
        unique_questions = []
        for q in all_questions:
            if q.message_id not in seen_message_ids:
                unique_questions.append(q)
                seen_message_ids.add(q.message_id)

        return ExtractionResult(
            conversation_id=f"{room_id}_multi_batch",
            questions=unique_questions,
            conversations=all_conversations,
            total_messages=len(messages),
            processing_time_ms=int((time.time() - start_time) * 1000),
        )

    def _format_batch_prompt(
        self, messages: List[Dict[str, Any]], staff_identifiers: List[str]
    ) -> List[Dict[str, str]]:
        """
        Format ALL messages into single batch prompt with staff identifiers.

        Args:
            messages: List of anonymized messages (User_1, Staff_1, etc.)
            staff_identifiers: List of staff IDs (e.g., ["Staff_1", "Staff_2"])

        Returns:
            List of message dicts for LLM (system + user messages)
        """
        prompt_messages = []

        # Add system prompt
        prompt_messages.append({"role": "system", "content": UNIFIED_SYSTEM_PROMPT})

        # Sort messages chronologically (oldest first) for proper conversation flow
        sorted_messages = sorted(messages, key=lambda m: m.get("timestamp", 0))

        # Build message ID index for reply tracking
        msg_id_to_index = {}
        for idx, msg in enumerate(sorted_messages):
            msg_id_to_index[msg.get("event_id", "")] = (
                idx + 1
            )  # 1-based for human readability

        # Format all messages in a single user message with human-readable timestamps
        formatted_messages = []
        for idx, msg in enumerate(sorted_messages):
            timestamp_ms = msg.get("timestamp", 0)
            if timestamp_ms and timestamp_ms > 0:
                # Convert milliseconds to datetime and format as human-readable
                from datetime import datetime, timezone

                dt = datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc)
                timestamp_str = dt.strftime("%Y-%m-%d %H:%M:%S UTC")
            else:
                timestamp_str = "unknown"

            # Clean Matrix reply formatting (remove quoted fallback text)
            message_body = self._strip_matrix_reply_fallback(msg["body"])

            # Message number for reference (1-based)
            msg_number = idx + 1

            # If this is a reply, indicate which message it's replying to
            reply_to_id = msg.get("reply_to")
            if reply_to_id and reply_to_id in msg_id_to_index:
                reply_to_number = msg_id_to_index[reply_to_id]
                formatted_messages.append(
                    f"[Msg #{msg_number}] [{timestamp_str}] [{msg['sender']}] (replying to Msg #{reply_to_number}): {message_body}"
                )
            else:
                formatted_messages.append(
                    f"[Msg #{msg_number}] [{timestamp_str}] [{msg['sender']}]: {message_body}"
                )

        messages_text = "\n".join(formatted_messages)

        # Include staff identifiers in the prompt
        staff_list = ", ".join(staff_identifiers) if staff_identifiers else "None"

        prompt_messages.append(
            {
                "role": "user",
                "content": f"""Analyze these {len(messages)} messages and extract user questions (filter out staff responses).

**Staff Identifiers**: {staff_list}

**Messages**:
{messages_text}

Extract user questions only (ignore messages from staff identifiers above).""",
            }
        )

        return prompt_messages

    def _get_cache_key(self, messages: List[Dict[str, Any]]) -> str:
        """
        Generate cache key from message set.

        Args:
            messages: List of messages

        Returns:
            SHA-256 hash of message content
        """
        # Create deterministic string from messages
        content = json.dumps(
            [{"event_id": m["event_id"], "body": m["body"]} for m in messages],
            sort_keys=True,
        )
        return hashlib.sha256(content.encode()).hexdigest()

    def _get_from_cache(self, cache_key: str) -> Optional[ExtractionResult]:
        """
        Get cached result if not expired.

        Args:
            cache_key: Cache key

        Returns:
            Cached result or None
        """
        if cache_key in self._cache:
            result, cached_time = self._cache[cache_key]
            if time.time() - cached_time < self._cache_ttl:
                return result
            else:
                # Expired, remove from cache
                del self._cache[cache_key]
        return None

    def _add_to_cache(self, cache_key: str, result: ExtractionResult) -> None:
        """
        Add result to cache.

        Args:
            cache_key: Cache key
            result: Extraction result
        """
        self._cache[cache_key] = (result, time.time())

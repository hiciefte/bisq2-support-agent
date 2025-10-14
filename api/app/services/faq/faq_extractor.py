"""
FAQ Extractor for extracting FAQs from conversations using OpenAI.

This module handles the complete FAQ extraction pipeline including
conversation formatting, OpenAI API calls with retries, response processing,
and duplicate detection.
"""

import json
import logging
import random
import re
import time
import unicodedata
from typing import Any, Dict, List, Optional, Set

import aisuite as ai

logger = logging.getLogger(__name__)


class FAQExtractor:
    """Extractor for generating FAQs from support conversations using OpenAI.

    This class handles:
    - Formatting conversations for extraction prompts
    - Calling OpenAI API with retry logic
    - Processing API responses and extracting FAQs
    - Duplicate detection with text normalization
    - Batch processing to avoid token limits
    """

    def __init__(
        self,
        aisuite_client: Optional[ai.Client],
        settings: Any,
    ):
        """Initialize the FAQ extractor.

        Args:
            aisuite_client: Initialized AISuite client instance
            settings: Settings object containing OPENAI_MODEL and other config
        """
        self.aisuite_client = aisuite_client
        self.settings = settings
        self.normalized_faq_keys: Set[str] = set()

    def normalize_text(self, text: str) -> str:
        """Normalize text by converting to lowercase, normalizing Unicode characters,
        and standardizing whitespace.

        Args:
            text: The text to normalize

        Returns:
            Normalized text
        """
        if not text:
            return ""

        # Convert to lowercase
        text = text.lower()

        # Normalize Unicode characters (e.g., convert different apostrophe types to standard)
        text = unicodedata.normalize("NFKC", text)

        # Replace common Unicode apostrophes with standard ASCII apostrophe
        text = text.replace("\u2019", "'")  # Right single quotation mark
        text = text.replace("\u2018", "'")  # Left single quotation mark
        text = text.replace("\u201b", "'")  # Single high-reversed-9 quotation mark
        text = text.replace("\u2032", "'")  # Prime

        # Standardize whitespace
        text = re.sub(r"\s+", " ", text)

        # Trim leading/trailing whitespace
        text = text.strip()

        return text

    def get_normalized_faq_key(self, faq: Dict) -> str:
        """Generate a normalized key for a FAQ to identify duplicates.

        Args:
            faq: The FAQ dictionary

        Returns:
            A normalized key string
        """
        question = self.normalize_text(faq.get("question", ""))
        answer = self.normalize_text(faq.get("answer", ""))
        return f"{question}|{answer}"

    def is_duplicate_faq(self, faq: Dict) -> bool:
        """Check if a FAQ is a duplicate based on normalized content.

        Args:
            faq: The FAQ dictionary to check

        Returns:
            True if the FAQ is a duplicate, False otherwise
        """
        key = self.get_normalized_faq_key(faq)
        if key in self.normalized_faq_keys:
            return True
        self.normalized_faq_keys.add(key)
        return False

    def reset_duplicate_tracker(self):
        """Reset the duplicate FAQ tracker.

        This should be called before starting a new extraction session
        to clear the duplicate detection state.
        """
        self.normalized_faq_keys = set()

    def seed_duplicate_tracker(self, existing_faqs: List[Dict]):
        """Seed the duplicate tracker with existing FAQs.

        Args:
            existing_faqs: List of existing FAQ dictionaries
        """
        self.normalized_faq_keys = {
            self.get_normalized_faq_key(faq) for faq in existing_faqs
        }
        logger.info(
            f"Seeded duplicate tracker with {len(self.normalized_faq_keys)} existing FAQs"
        )

    def _format_conversation_for_prompt(self, conversation: Dict) -> str:
        """Format a single conversation for inclusion in the prompt.

        Args:
            conversation: A conversation dictionary with messages

        Returns:
            Formatted conversation text
        """
        conv_text = []
        for msg in conversation["messages"]:
            role = "Support" if msg["is_support"] else "User"
            conv_text.append(f"{role}: {msg['text']}")
        return "\n".join(conv_text)

    def _create_extraction_prompt(self, formatted_conversations: List[str]) -> str:
        """Create the prompt for FAQ extraction.

        Args:
            formatted_conversations: List of formatted conversation texts

        Returns:
            Complete prompt for the OpenAI API
        """
        return """You are a language model specialized in text summarization and data extraction. Your task is to analyze these conversations and extract frequently asked questions (FAQs) along with their concise, clear answers.

For each FAQ you identify, output a single-line JSON object in this format:
{{"question": "A clear, self-contained question extracted or synthesized from the support chats", "answer": "A concise, informative answer derived from the support chat responses", "category": "A one- or two-word category label that best describes the FAQ topic", "source": "Bisq Support Chat"}}

IMPORTANT: Each JSON object must be on a single line, with no line breaks or pretty printing.

Here are the conversations to analyze:

{}

Output each FAQ as a single-line JSON object. No additional text or commentary.""".format(
            "\n\n---\n\n".join(formatted_conversations)
        )

    def _call_openai_api(self, prompt: str) -> Optional[str]:
        """Call the OpenAI API via AISuite with retries and error handling.

        Args:
            prompt: The prompt to send to the API

        Returns:
            Response text if successful, None otherwise
        """
        if not self.aisuite_client:
            logger.error("AISuite client not initialized")
            return None

        max_retries = 3
        base_delay = 1

        for attempt in range(max_retries):
            try:
                # Build full model ID with provider prefix
                model_id = f"openai:{self.settings.OPENAI_MODEL}"

                response = self.aisuite_client.chat.completions.create(
                    model=model_id,
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=min(2000, self.settings.MAX_TOKENS),
                    temperature=self.settings.LLM_TEMPERATURE,
                )

                # Validate response has choices
                if not getattr(response, "choices", None):
                    logger.error("LLM returned no choices in response")
                    raise ValueError("Empty response from LLM")

                return response.choices[0].message.content.strip()

            except Exception as e:
                is_rate_limit = "rate limit" in str(e).lower()
                error_level = logging.WARNING if is_rate_limit else logging.ERROR
                logger.log(
                    error_level,
                    f"Error during OpenAI API call on attempt {attempt + 1}: {e!s}",
                )

                if attempt < max_retries - 1:
                    # Add jitter to prevent thundering herd
                    jitter = random.uniform(0, 0.1 * (2**attempt))
                    delay = base_delay * (2**attempt) + jitter
                    # Use longer delays for rate limits
                    if is_rate_limit:
                        delay = max(delay, 5.0 * (attempt + 1))
                    logger.info(f"Retrying in {delay} seconds...")
                    time.sleep(delay)
                else:
                    logger.exception("Max retries reached for OpenAI API call")

        return None

    def _process_api_response(self, response_text: str) -> List[Dict]:
        """Process the API response and extract FAQs.

        Args:
            response_text: The response text from the API

        Returns:
            List of extracted FAQ dictionaries
        """
        faqs: List[Dict[str, Any]] = []

        if not response_text:
            return faqs

        # Clean up the response text - remove markdown code blocks
        response_text = response_text.replace("```json", "").replace("```", "").strip()

        # Process each line as a potential JSON object
        for line in response_text.split("\n"):
            line = line.strip()
            if not line:
                continue
            try:
                faq = json.loads(line)
                # Basic validation
                if (
                    not faq.get("question", "").strip()
                    or not faq.get("answer", "").strip()
                ):
                    logger.warning(
                        f"Skipping FAQ with missing question or answer: {line}"
                    )
                    continue

                # Check for duplicates
                if self.is_duplicate_faq(faq):
                    logger.info(
                        f"Skipping duplicate FAQ: {faq.get('question', '')[:50]}..."
                    )
                    continue

                faqs.append(faq)
            except json.JSONDecodeError as e:
                logger.warning(f"Failed to parse FAQ entry: {e}\nLine: {line}")

        return faqs

    def extract_faqs_with_openai(
        self, conversations_to_process: List[Dict], batch_size: int = 5
    ) -> List[Dict]:
        """Extract FAQs from conversations using AISuite.

        Args:
            conversations_to_process: List of conversation dictionaries to process
            batch_size: Number of conversations to process per API call (default: 5)

        Returns:
            List of extracted FAQ dictionaries
        """
        if not self.aisuite_client:
            logger.error("AISuite client not initialized. Cannot extract FAQs.")
            return []

        if not conversations_to_process:
            logger.info("No new conversations provided to process for OpenAI.")
            return []

        logger.info(
            f"Extracting FAQs from {len(conversations_to_process)} conversations using OpenAI..."
        )

        # Prepare conversations for the prompt
        formatted_convs = [
            self._format_conversation_for_prompt(conv)
            for conv in conversations_to_process
        ]

        # Split conversations into batches to avoid token limits
        batches = [
            formatted_convs[i : i + batch_size]
            for i in range(0, len(formatted_convs), batch_size)
        ]

        all_faqs = []

        for batch in batches:
            # Create the prompt
            prompt = self._create_extraction_prompt(batch)

            # Call the OpenAI API
            response_text = self._call_openai_api(prompt)

            if response_text:
                # Process the response
                batch_faqs = self._process_api_response(response_text)
                all_faqs.extend(batch_faqs)

            time.sleep(1)  # Small delay between batches

        logger.info(
            f"Extracted {len(all_faqs)} FAQ entries from {len(conversations_to_process)} conversations"
        )
        return all_faqs

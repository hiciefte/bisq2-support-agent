"""
FAQ service for loading and processing FAQ data for the Bisq Support Assistant.

This service handles loading FAQ documentation from JSONL files,
processing the documents, preparing them for use in the RAG system,
and extracting new FAQs from support chat conversations.
"""

import json
import logging
import os
import random
import time
import re
import unicodedata
from datetime import timedelta
from io import StringIO
from pathlib import Path
from typing import Dict, List, Set, Any, Optional, cast

import pandas as pd
from fastapi import Request
from langchain_core.documents import Document
from openai import OpenAI

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class FAQService:
    """Service for loading, processing, and extracting FAQ data."""

    def __init__(self, settings=None):
        """Initialize the FAQService.

        Args:
            settings: Application settings
        """
        self.settings = settings

        # Default source weight
        self.source_weights = {
            "faq": 1.2  # Prioritize FAQ content
        }

        # Initialize paths using settings
        if settings:
            self.faq_file_path = Path(settings.FAQ_FILE_PATH)
            self.processed_convs_path = Path(settings.PROCESSED_CONVS_FILE_PATH)
            self.existing_input_path = Path(settings.CHAT_EXPORT_FILE_PATH)
            self.conversations_path = Path(settings.CONVERSATIONS_FILE_PATH)

            # Ensure data directories exist
            self.faq_file_path.parent.mkdir(parents=True, exist_ok=True)
            self.processed_convs_path.parent.mkdir(parents=True, exist_ok=True)
            self.existing_input_path.parent.mkdir(parents=True, exist_ok=True)
            self.conversations_path.parent.mkdir(parents=True, exist_ok=True)

            # Initialize OpenAI client if settings are provided
            if hasattr(settings, 'OPENAI_API_KEY'):
                self.openai_client = OpenAI(api_key=settings.OPENAI_API_KEY)
            else:
                self.openai_client = None

        # Store messages and their relationships for FAQ extraction
        self.messages: Dict[str, Dict[str, Any]] = {}  # msg_id -> message data
        self.references: Dict[str, str] = {}  # msg_id -> referenced_msg_id
        self.conversations: List[Dict[str, Any]] = []  # List of conversation threads

        # Load processed conversation IDs
        self.processed_conv_ids = self.load_processed_conv_ids()
        
        # Store normalized FAQ keys for deduplication
        self.normalized_faq_keys = set()

        logger.info("FAQ service initialized")

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
        text = unicodedata.normalize('NFKC', text)
        
        # Replace common Unicode apostrophes with standard ASCII apostrophe
        text = text.replace('\u2019', "'")  # Right single quotation mark
        text = text.replace('\u2018', "'")  # Left single quotation mark
        text = text.replace('\u201B', "'")  # Single high-reversed-9 quotation mark
        text = text.replace('\u2032', "'")  # Prime
        
        # Standardize whitespace
        text = re.sub(r'\s+', ' ', text)
        
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
        question = self.normalize_text(faq.get('question', ''))
        answer = self.normalize_text(faq.get('answer', ''))
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

    def update_source_weights(self, new_weights: Dict[str, float]) -> None:
        """Update source weights for FAQ content.

        Args:
            new_weights: Dictionary with updated weights
        """
        if "faq" in new_weights:
            self.source_weights["faq"] = new_weights["faq"]
            logger.info(f"Updated FAQ source weight to {self.source_weights['faq']}")

    def load_faq_data(self, faq_file: Optional[str] = None) -> List[Document]:
        """Load FAQ data from JSONL file.

        Args:
            faq_file: Path to the FAQ JSONL file.
                      If None, uses the default path from settings.

        Returns:
            List of Document objects
        """
        if faq_file is None and hasattr(self, 'faq_file_path'):
            faq_file = str(self.faq_file_path)
        elif faq_file is None and self.settings:
            faq_file = self.settings.FAQ_FILE_PATH

        logger.info(f"Using FAQ file path: {faq_file}")

        if not os.path.exists(faq_file):
            logger.warning(f"FAQ file not found: {faq_file}")
            return []

        documents = []
        try:
            with open(faq_file, "r", encoding="utf-8") as f:
                for line in f:
                    try:
                        data = json.loads(line.strip())
                        question = data.get("question", "")
                        answer = data.get("answer", "")
                        category = data.get("category", "General")

                        # Validate required fields
                        if not question.strip() or not answer.strip():
                            logger.warning(f"Skipping FAQ entry with missing question or answer: {data}")
                            continue

                        doc = Document(
                            page_content=f"Question: {question}\nAnswer: {answer}",
                            metadata={
                                "source": faq_file,
                                "title": question[:50] + "..." if len(
                                    question) > 50 else question,
                                "type": "faq",
                                "source_weight": self.source_weights.get("faq", 1.0),
                                "category": category
                            }
                        )
                        documents.append(doc)
                    except json.JSONDecodeError:
                        logger.error(f"Error parsing JSON line in FAQ file: {line}")
            logger.info(f"Loaded {len(documents)} FAQ documents")
            return documents
        except Exception as e:
            logger.error(f"Error loading FAQ data: {str(e)}", exc_info=True)
            return []

    # FAQ Extraction Methods from extract_faqs.py

    def load_processed_conv_ids(self) -> Set[str]:
        """Load the set of conversation IDs that have already been processed."""
        if not hasattr(self, 'processed_convs_path'):
            return set()

        if self.processed_convs_path.exists():
            try:
                with open(self.processed_convs_path, 'r') as f:
                    return set(json.load(f))
            except Exception as e:
                logger.warning(f"Error loading processed conversations: {str(e)}")
                return set()
        return set()

    def save_processed_conv_ids(self):
        """Save the set of processed conversation IDs."""
        if not hasattr(self, 'processed_convs_path'):
            logger.warning("Cannot save processed conversation IDs: path not set")
            return

        with open(self.processed_convs_path, 'w') as f:
            json.dump(list(self.processed_conv_ids), cast(Any, f))

    async def merge_csv_files(self, bisq_api=None):
        """Fetch latest messages from API and merge with existing ones.

        Args:
            bisq_api: Optional Bisq2API instance to fetch data from
        """
        if not hasattr(self, 'existing_input_path'):
            logger.warning("Cannot merge CSV files: paths not set")
            return

        logger.info("Fetching latest messages from Bisq 2 API...")

        # Read existing CSV if it exists
        existing_df = pd.DataFrame()
        logger.debug(f"Looking for existing messages at: {self.existing_input_path}")
        if self.existing_input_path.exists():
            existing_df = pd.read_csv(self.existing_input_path)
            logger.info(f"Found {len(existing_df)} existing messages")
        else:
            logger.warning(f"No existing messages found at {self.existing_input_path}")

        # Fetch latest messages from API
        latest_df = pd.DataFrame()
        try:
            if bisq_api:
                await bisq_api.setup()
                csv_content = await bisq_api.export_chat_messages()
                if csv_content:
                    latest_df = pd.read_csv(StringIO(csv_content))
                    logger.info(f"Fetched {len(latest_df)} messages from API")
        except Exception as e:
            logger.error(f"Failed to fetch messages from API: {str(e)}")
        finally:
            if bisq_api:
                await bisq_api.cleanup()

        # If both DataFrames are empty, we have no data to work with
        if existing_df.empty and latest_df.empty:
            logger.warning("No messages available for processing")
            return

        # Combine DataFrames and drop duplicates based on Message ID
        combined_df = pd.concat([existing_df, latest_df], ignore_index=True)
        combined_df.drop_duplicates(subset=['Message ID'], keep='last', inplace=True)

        # Sort by date if available
        if 'Date' in combined_df.columns:
            combined_df['Date'] = pd.to_datetime(combined_df['Date'], errors='coerce')
            combined_df.sort_values('Date', inplace=True)

        # Save the merged result
        self.existing_input_path.parent.mkdir(parents=True, exist_ok=True)
        combined_df.to_csv(self.existing_input_path, index=False)
        logger.info(f"Saved {len(combined_df)} messages to {self.existing_input_path}")

        # Store the input path for further processing
        self.input_path = self.existing_input_path

    def load_messages(self):
        """Load messages from CSV and organize them."""
        if not hasattr(self, 'input_path') or not self.input_path.exists():
            logger.warning("No input file found for loading messages")
            return

        logger.info("Loading messages from CSV...")

        try:
            # Read the CSV file
            df = pd.read_csv(self.input_path)
            logger.debug(f"CSV columns: {list(df.columns)}")
            total_lines = len(df)
            logger.info("Processing " + str(total_lines) + " lines from input file")

            # Reset message collections
            self.messages = {}
            self.references = {}

            for _, row_data in df.iterrows():
                try:
                    msg_id = row_data['Message ID']

                    # Skip empty or invalid messages
                    if pd.isna(row_data['Message']) or not row_data['Message'].strip():
                        continue

                    # Parse timestamp
                    timestamp = None
                    if pd.notna(row_data['Date']):
                        try:
                            timestamp = pd.to_datetime(row_data['Date'])
                        except Exception as exc:
                            logger.warning(f"Timestamp parse error for msg {msg_id}: {exc}")

                    # Create message object
                    msg = {
                        'msg_id': msg_id,
                        'text': row_data['Message'].strip(),
                        'author': row_data['Author'] if pd.notna(row_data['Author']) else 'unknown',
                        'channel': row_data['Channel'],
                        'is_support': row_data['Channel'].lower() == 'support',
                        'timestamp': timestamp,
                        'referenced_msg_id': row_data['Referenced Message ID'] if pd.notna(
                            row_data['Referenced Message ID']) else None
                    }
                    self.messages[msg_id] = msg

                    # Store reference if it exists
                    if msg['referenced_msg_id']:
                        self.references[msg_id] = msg['referenced_msg_id']
                        if msg['referenced_msg_id'] not in self.messages and pd.notna(
                                row_data['Referenced Message Text']):
                            ref_timestamp = None
                            ref_rows = df[df['Message ID'] == msg['referenced_msg_id']]
                            if not ref_rows.empty and pd.notna(ref_rows.iloc[0]['Date']):
                                try:
                                    ref_timestamp = pd.to_datetime(ref_rows.iloc[0]['Date'])
                                except Exception as exc:
                                    logger.warning(f"Ref timestamp parse error for msg {msg_id}: {exc}")
                            if ref_timestamp is None and timestamp is not None:
                                ref_timestamp = timestamp - pd.Timedelta(seconds=1)
                            ref_msg = {
                                'msg_id': msg['referenced_msg_id'],
                                'text': row_data['Referenced Message Text'].strip(),
                                'author': row_data['Referenced Message Author'] if pd.notna(
                                    row_data['Referenced Message Author']) else 'unknown',
                                'channel': 'user',
                                'is_support': False,
                                'timestamp': ref_timestamp,
                                'referenced_msg_id': None
                            }
                            self.messages[msg['referenced_msg_id']] = ref_msg
                except Exception as e:
                    logger.error(f"Error processing row: {e}")
                    continue

            logger.info(f"Loaded {len(self.messages)} messages with {len(self.references)} references")
        except Exception as e:
            logger.error(f"Error loading CSV file: {e}")
            raise

    def build_conversation_thread(self, start_msg_id: str, max_depth: int = 10) -> List[Dict]:
        """Build a conversation thread starting from a message, following references both ways."""
        if not self.messages:
            return []

        thread = []
        seen_messages = set()
        to_process = {start_msg_id}
        depth = 0

        while to_process and depth < max_depth:
            current_id = to_process.pop()

            if current_id in seen_messages or current_id not in self.messages:
                continue

            seen_messages.add(current_id)
            msg = self.messages[current_id].copy()
            msg['original_index'] = len(thread)

            # Add message to thread
            thread.append(msg)

            # Follow reference backward
            if msg['referenced_msg_id']:
                to_process.add(msg['referenced_msg_id'])

            # Follow references forward more conservatively
            forward_refs = [
                mid for mid, ref in self.references.items()
                if ref == current_id and
                   # Only include forward references within 30 minutes
                   self.messages[mid]['timestamp'] and
                   self.messages[current_id]['timestamp'] and
                   (self.messages[mid]['timestamp'] - self.messages[current_id][
                       'timestamp']) <= timedelta(minutes=30)
            ]
            to_process.update(forward_refs)

            depth += 1

        # Sort thread by timestamp, using the original position as tie-breaker
        thread.sort(key=lambda x: (
            x['timestamp'] if x['timestamp'] is not None else pd.Timestamp.min,
            x['original_index']
        ))

        # Remove the temporary original_index field
        for msg in thread:
            msg.pop('original_index', None)

        return thread

    def is_valid_conversation(self, thread: List[Dict]) -> bool:
        """Validate if a conversation thread is complete and meaningful."""
        if len(thread) < 2:
            return False

        # Check if there's at least one user message and one support message
        has_user = any(not msg['is_support'] for msg in thread)
        has_support = any(msg['is_support'] for msg in thread)

        if not (has_user and has_support):
            return False

        # Check if messages are too far apart in time
        timestamps = [msg['timestamp'] for msg in thread if msg['timestamp'] is not None]
        if timestamps:
            time_span = max(timestamps) - min(timestamps)
            if time_span > timedelta(hours=24):  # Max time span of 24 hours
                return False

        # Check if all messages are properly connected through references
        for i in range(1, len(thread)):
            current_msg = thread[i]
            previous_msg = thread[i - 1]

            # Check if messages are connected through references
            if (
                current_msg['referenced_msg_id'] != previous_msg['msg_id']
                and previous_msg['referenced_msg_id'] != current_msg['msg_id']
                and not (
                    current_msg['timestamp']
                    and previous_msg['timestamp']
                    and (current_msg['timestamp'] - previous_msg['timestamp']) <= timedelta(minutes=30)
                )
            ):
                return False

        return True

    def group_conversations(self) -> List[Dict]:
        """Group messages into conversations."""
        if not self.messages:
            return []

        logger.info("Grouping messages into conversations...")

        # Start with support messages that have references
        support_messages = [
            msg_id for msg_id, msg in self.messages.items()
            if msg['is_support'] and msg['referenced_msg_id']
        ]
        logger.info(f"Found {len(support_messages)} support messages with references")

        # Process each support message
        conversations = []
        processed_msg_ids = set()

        for msg_id in support_messages:
            if msg_id in processed_msg_ids:
                continue

            # Build conversation thread
            thread = self.build_conversation_thread(msg_id)

            # Mark all messages in thread as processed
            processed_msg_ids.update(msg['msg_id'] for msg in thread)

            # Validate and format conversation
            if self.is_valid_conversation(thread):
                conversation = {
                    'id': thread[0]['msg_id'],  # Use first message ID without prefix
                    'messages': thread
                }
                conversations.append(conversation)

        logger.info(f"Generated {len(conversations)} conversations")
        self.conversations = conversations
        return conversations

    def _format_conversation_for_prompt(self, conversation: Dict) -> str:
        """Format a single conversation for inclusion in the prompt.

        Args:
            conversation: A conversation dictionary with messages

        Returns:
            Formatted conversation text
        """
        conv_text = []
        for msg in conversation['messages']:
            role = "Support" if msg['is_support'] else "User"
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
            "\n\n---\n\n".join(formatted_conversations))

    def _call_openai_api(self, prompt: str) -> Optional[str]:
        """Call the OpenAI API with retries and error handling.

        Args:
            prompt: The prompt to send to the API

        Returns:
            Response text if successful, None otherwise
        """
        if not self.openai_client:
            logger.error("OpenAI client not initialized")
            return None

        max_retries = 3
        base_delay = 1

        for attempt in range(max_retries):
            try:
                response = self.openai_client.chat.completions.create(
                    model=self.settings.OPENAI_MODEL,
                    messages=[{"role": "user", "content": prompt}],
                    max_completion_tokens=2000
                )
                return response.choices[0].message.content.strip()

            except Exception as e:
                is_rate_limit = "rate limit" in str(e).lower()
                error_level = logging.WARNING if is_rate_limit else logging.ERROR
                logger.log(error_level, f"Error during OpenAI API call on attempt {attempt + 1}: {str(e)}")

                if attempt < max_retries - 1:
                    # Add jitter to prevent thundering herd
                    jitter = random.uniform(0, 0.1 * (2 ** attempt))
                    delay = base_delay * (2 ** attempt) + jitter
                    # Use longer delays for rate limits
                    if is_rate_limit:
                        delay = max(delay, 5.0 * (attempt + 1))
                    logger.info(f"Retrying in {delay} seconds...")
                    time.sleep(delay)
                else:
                    logger.error("Max retries reached for OpenAI API call")

        return None

    def _process_api_response(self, response_text: str) -> List[Dict]:
        """Process the API response and extract FAQs.

        Args:
            response_text: The response text from the API

        Returns:
            List of extracted FAQ dictionaries
        """
        faqs = []

        if not response_text:
            return faqs

        # Clean up the response text - remove markdown code blocks
        response_text = response_text.replace('```json', '').replace('```', '').strip()

        # Process each line as a potential JSON object
        for line in response_text.split('\n'):
            line = line.strip()
            if not line:
                continue
            try:
                faq = json.loads(line)
                # Basic validation
                if not faq.get('question', '').strip() or not faq.get('answer', '').strip():
                    logger.warning(f"Skipping FAQ with missing question or answer: {line}")
                    continue
                    
                # Check for duplicates
                if self.is_duplicate_faq(faq):
                    logger.info(f"Skipping duplicate FAQ: {faq.get('question', '')[:50]}...")
                    continue
                    
                faqs.append(faq)
            except json.JSONDecodeError as e:
                logger.warning(f"Failed to parse FAQ entry: {e}\nLine: {line}")

        return faqs

    def extract_faqs_with_openai(self, conversations: List[Dict]) -> List[Dict]:
        """Extract FAQs from conversations using OpenAI.

        Args:
            conversations: List of conversation dictionaries

        Returns:
            List of extracted FAQ dictionaries
        """
        if not self.openai_client:
            logger.error("OpenAI client not initialized. Cannot extract FAQs.")
            return []

        logger.info("Extracting FAQs using OpenAI...")

        # Filter out already processed conversations
        new_conversations = [conv for conv in conversations if
                             conv['id'] not in self.processed_conv_ids]

        if not new_conversations:
            logger.info("No new conversations to process")
            return []

        logger.info(f"Found {len(new_conversations)} new conversations to process")

        # Prepare conversations for the prompt
        formatted_convs = [self._format_conversation_for_prompt(conv) for conv in new_conversations]

        # Split conversations into batches to avoid token limits
        batch_size = 5
        batches = [formatted_convs[i:i + batch_size] for i in
                   range(0, len(formatted_convs), batch_size)]

        all_faqs = []
        processed_in_batch = set()

        for batch_idx, batch in enumerate(batches):
            # Create the prompt
            prompt = self._create_extraction_prompt(batch)

            # Call the OpenAI API
            response_text = self._call_openai_api(prompt)

            if response_text:
                # Process the response
                batch_faqs = self._process_api_response(response_text)
                all_faqs.extend(batch_faqs)

            # Mark conversations as processed
            start_idx = batch_idx * batch_size
            for conv in new_conversations[start_idx:start_idx + len(batch)]:
                processed_in_batch.add(conv['id'])

            time.sleep(1)  # Small delay between batches

        # Update processed conversation IDs
        self.processed_conv_ids.update(processed_in_batch)
        self.save_processed_conv_ids()

        logger.info(
            f"Extracted {len(all_faqs)} FAQ entries from {len(processed_in_batch)} new conversations")
        return all_faqs

    def load_existing_faqs(self) -> List[Dict]:
        """Load existing FAQ entries if they exist."""
        if not hasattr(self, 'faq_file_path'):
            return []

        if self.faq_file_path.exists():
            try:
                faqs = []
                with self.faq_file_path.open('r', encoding='utf-8') as f:
                    for line in f:
                        faq = json.loads(line)
                        # Add to normalized keys set for deduplication
                        self.normalized_faq_keys.add(self.get_normalized_faq_key(faq))
                        faqs.append(faq)
                logger.info(f"Loaded {len(faqs)} existing FAQ entries")
                return faqs
            except Exception as e:
                logger.warning(f"Error loading existing FAQs: {str(e)}")
                return []
        return []

    def save_faqs(self, faqs: List[Dict]):
        """Save FAQ entries to JSONL file."""
        if not hasattr(self, 'faq_file_path'):
            logger.warning("Cannot save FAQs: path not set")
            return

        if not faqs and self.faq_file_path.exists():
            logger.info("No new FAQs to save, preserving existing entries")
            return

        with self.faq_file_path.open('w', encoding='utf-8') as f:
            for faq in faqs:
                # Ensure consistent encoding by normalizing before saving
                normalized_faq = {
                    'question': faq.get('question', ''),
                    'answer': faq.get('answer', ''),
                    'category': faq.get('category', 'General'),
                    'source': faq.get('source', 'Bisq Support Chat')
                }
                f.write(json.dumps(normalized_faq, ensure_ascii=False) + '\n')
        logger.info(f"Saved {len(faqs)} FAQ entries to {self.faq_file_path}")

    def serialize_conversation(self, conv: Dict) -> Dict:
        """Convert conversation to JSON-serializable format."""
        serialized = conv.copy()
        messages = []
        for msg in conv['messages']:
            msg_copy = msg.copy()
            if msg_copy['timestamp']:
                msg_copy['timestamp'] = msg_copy['timestamp'].isoformat()
            messages.append(msg_copy)
        serialized['messages'] = messages
        return serialized

    async def extract_and_save_faqs(self, bisq_api=None) -> List[Dict]:
        """Run the complete FAQ extraction process.

        Args:
            bisq_api: Optional Bisq2API instance to fetch data

        Returns:
            List of extracted FAQ dictionaries
        """
        try:
            # Reset normalized FAQ keys for this extraction run
            self.normalized_faq_keys = set()
            
            # Merge existing and new messages
            await self.merge_csv_files(bisq_api)

            # Load and process messages
            self.load_messages()

            # Group messages into conversations
            conversations = self.group_conversations()

            # Filter out already processed conversations
            new_conversations = [
                conv for conv in conversations
                if conv['id'] not in self.processed_conv_ids
            ]

            # Save all conversations to JSONL file
            if hasattr(self, 'conversations_path'):
                with self.conversations_path.open('w', encoding='utf-8') as f:
                    for conv in conversations:
                        serialized_conv = self.serialize_conversation(conv)
                        f.write(json.dumps(serialized_conv, ensure_ascii=False) + '\n')
                logger.info(
                    f"Saved {len(conversations)} conversations to {self.conversations_path}")

            # Extract FAQs using OpenAI
            new_faqs = []
            if new_conversations:
                logger.info("Extracting FAQs using OpenAI...")
                new_faqs = self.extract_faqs_with_openai(new_conversations)

                # Load existing FAQs
                existing_faqs = self.load_existing_faqs()

                # Combine existing and new FAQs
                all_faqs = existing_faqs + new_faqs

                # Save all FAQs
                self.save_faqs(all_faqs)
                logger.info(f"Extraction complete. Generated {len(new_faqs)} new FAQ entries.")

                # Update processed conversation IDs
                for conv in new_conversations:
                    self.processed_conv_ids.add(conv['id'])
                self.save_processed_conv_ids()
            else:
                logger.info("No new conversations to process")

            return new_faqs

        except Exception as e:
            logger.error(f"Error during FAQ extraction: {str(e)}")
            raise


def get_faq_service(request: Request) -> FAQService:
    """Get the FAQ service from the request state."""
    return request.app.state.faq_service

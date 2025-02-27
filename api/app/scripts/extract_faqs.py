"""
Script to extract FAQs from Bisq support chat conversations.
Runs as a scheduled task to update the FAQ database.
"""

import json
import logging
import time
from datetime import timedelta
from io import StringIO
from pathlib import Path
from typing import Dict, List, Set, Any, cast, Optional

import pandas as pd
from asyncio import get_event_loop
from openai import OpenAI
from tqdm import tqdm

from app.core.config import get_settings
from app.integrations.bisq_api import Bisq2API

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class FAQExtractor:
    """Extract FAQ entries from Bisq support chat conversations.
    
    This class processes support chat exports to identify common questions
    and their corresponding answers, creating a structured FAQ dataset
    that can be used for the RAG-based support assistant.
    """

    def __init__(self, settings=None):
        self.settings = settings or get_settings()
        logger.info(f"Loaded settings:")
        logger.info(f"OPENAI_API_KEY: {self.settings.OPENAI_API_KEY[:8]}...")
        logger.info(f"OPENAI_MODEL: {self.settings.OPENAI_MODEL}")
        logger.info(f"DATA_DIR: {self.settings.DATA_DIR}")

        self.bisq_api = Bisq2API(self.settings)

        # Initialize paths using settings
        self.existing_input_path = Path(self.settings.SUPPORT_CHAT_EXPORT_PATH)
        self.output_path = Path(self.settings.FAQ_OUTPUT_PATH)
        self.processed_convs_path = Path(self.settings.PROCESSED_CONVERSATIONS_PATH)
        self.input_path: Optional[Path] = None

        # Log all paths for debugging
        logger.info(f"Input path: {self.existing_input_path}")
        logger.info(f"Output path: {self.output_path}")
        logger.info(f"Processed conversations path: {self.processed_convs_path}")

        # Ensure data directories exist
        self.existing_input_path.parent.mkdir(parents=True, exist_ok=True)
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        self.processed_convs_path.parent.mkdir(parents=True, exist_ok=True)

        # Initialize OpenAI client
        self.openai_client = OpenAI(
            api_key=self.settings.OPENAI_API_KEY
        )

        # Store messages and their relationships
        self.messages: Dict[str, Dict[str, Any]] = {}  # msg_id -> message data
        self.references: Dict[str, str] = {}  # msg_id -> referenced_msg_id
        self.conversations: List[Dict[str, Any]] = []  # List of conversation threads

        # Load processed conversation IDs
        self.processed_conv_ids = self.load_processed_conv_ids()

        # Track processed messages to avoid duplicates
        self.processed_messages: Set[str] = set()

    def load_processed_conv_ids(self) -> Set[str]:
        """Load the set of conversation IDs that have already been processed."""
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
        with open(self.processed_convs_path, 'w') as f:
            json.dump(list(self.processed_conv_ids), cast(Any, f))

    async def merge_csv_files(self):
        """Fetch latest messages from API and merge with existing ones."""
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
        try:
            await self.bisq_api.setup()
            csv_content = await self.bisq_api.export_chat_messages()
            if csv_content:
                latest_df = pd.read_csv(StringIO(csv_content))
                logger.info(f"Fetched {len(latest_df)} messages from API")
            else:
                logger.warning("No new messages received from API")
                if existing_df.empty:
                    # Copy the sample data if no existing messages
                    sample_path = self.existing_input_path.parent / "support_chat_export.csv"
                    if sample_path.exists():
                        logger.info(f"Using sample data from {sample_path}")
                        existing_df = pd.read_csv(sample_path)
                    else:
                        raise Exception("No messages received from API and no existing messages found")
                logger.info("Continuing with existing messages")
                latest_df = pd.DataFrame()
        except Exception as e:
            logger.error(f"Failed to fetch messages from API: {str(e)}")
            if existing_df.empty:
                # Copy the sample data if no existing messages
                sample_path = self.existing_input_path.parent / "support_chat_export.csv"
                if sample_path.exists():
                    logger.info(f"Using sample data from {sample_path}")
                    existing_df = pd.read_csv(sample_path)
                else:
                    raise
            logger.info("Continuing with existing messages only")
            latest_df = pd.DataFrame()
        finally:
            await self.bisq_api.cleanup()

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

        # Update input path to use the merged file
        self.input_path = self.existing_input_path

    def load_messages(self):
        """Load messages from CSV and organize them."""
        logger.info("Loading messages from CSV...")

        try:
            # Read the CSV file
            df = pd.read_csv(self.input_path)
            logger.debug(f"CSV columns: {list(df.columns)}")
            total_lines = len(df)
            logger.info("Processing " + str(total_lines) + " lines from input file")

            for row in tqdm(df.iterrows(), total=total_lines, desc="Loading messages"):
                try:
                    _, row_data = row
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
                   (self.messages[mid]['timestamp'] - self.messages[current_id]['timestamp']) <= timedelta(minutes=30)
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
            if time_span > timedelta(hours=24):  # Reduce max time span to 24 hours
                return False

        # Check if all messages are properly connected through references
        msg_ids = {msg['msg_id'] for msg in thread}
        for msg in thread:
            if msg['referenced_msg_id'] and msg['referenced_msg_id'] not in msg_ids:
                return False

        # Verify message continuity by checking references
        for i in range(1, len(thread)):
            current_msg = thread[i]
            previous_msg = thread[i - 1]

            # Check if messages are connected through references
            if (current_msg['referenced_msg_id'] != previous_msg['msg_id'] and
                    previous_msg['referenced_msg_id'] != current_msg['msg_id']):
                # Allow if messages are within 30 minutes of each other
                if (current_msg['timestamp'] and previous_msg['timestamp'] and
                        (current_msg['timestamp'] - previous_msg['timestamp']) > timedelta(minutes=30)):
                    return False

        return True

    def group_conversations(self) -> List[Dict]:
        """Group messages into conversations."""
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

        for msg_id in tqdm(support_messages, desc="Building conversations"):
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

    def extract_faqs_with_openai(self, conversations: List[Dict]) -> List[Dict]:
        logger.info("Extracting FAQs using OpenAI...")

        # Filter out already processed conversations
        new_conversations = [conv for conv in conversations if conv['id'] not in self.processed_conv_ids]

        if not new_conversations:
            logger.info("No new conversations to process")
            return []

        logger.info(f"Found {len(new_conversations)} new conversations to process")

        # Prepare conversations for the prompt
        formatted_convs = []
        for conv in new_conversations:
            conv_text = []
            for msg in conv['messages']:
                role = "Support" if msg['is_support'] else "User"
                conv_text.append(f"{role}: {msg['text']}")
            formatted_convs.append("\n".join(conv_text))

        # Split conversations into batches to avoid token limits
        batch_size = 5
        batches = [formatted_convs[i:i + batch_size] for i in range(0, len(formatted_convs), batch_size)]

        all_faqs = []
        processed_in_batch = set()

        for batch_idx, batch in enumerate(tqdm(batches, desc="Processing conversation batches")):
            # Prepare the prompt
            prompt = """You are a language model specialized in text summarization and data extraction. Your task is to analyze these conversations and extract frequently asked questions (FAQs) along with their concise, clear answers.

For each FAQ you identify, output a single-line JSON object in this format:
{{"question": "A clear, self-contained question extracted or synthesized from the support chats", "answer": "A concise, informative answer derived from the support chat responses", "category": "A one- or two-word category label that best describes the FAQ topic", "source": "Bisq Support Chat"}}

IMPORTANT: Each JSON object must be on a single line, with no line breaks or pretty printing.

Here are the conversations to analyze:

{}

Output each FAQ as a single-line JSON object. No additional text or commentary.""".format("\n\n---\n\n".join(batch))

            max_retries = 3
            base_delay = 1
            response = None
            for attempt in range(max_retries):
                try:
                    response = self.openai_client.chat.completions.create(
                        model=self.settings.OPENAI_MODEL,
                        messages=[{"role": "user", "content": prompt}],
                        max_completion_tokens=2000
                    )
                    break
                except Exception as e:
                    logger.error(f"Error during OpenAI API call on attempt {attempt + 1}: {str(e)}")
                    if attempt < max_retries - 1:
                        delay = base_delay * (2 ** attempt)
                        logger.info(f"Retrying in {delay} seconds...")
                        time.sleep(delay)
                    else:
                        logger.error("Max retries reached, skipping this batch.")
            if response is None:
                continue

            response_text = response.choices[0].message.content.strip()

            # Clean up the response text - remove markdown code blocks
            response_text = response_text.replace('```json', '').replace('```', '').strip()

            # Process each line as a potential JSON object
            for line in response_text.split('\n'):
                line = line.strip()
                if not line:
                    continue
                try:
                    faq = json.loads(line)
                    all_faqs.append(faq)
                except json.JSONDecodeError as e:
                    logger.warning(f"Failed to parse FAQ entry: {e}\nLine: {line}")

            start_idx = batch_idx * batch_size
            for conv in new_conversations[start_idx:start_idx + len(batch)]:
                processed_in_batch.add(conv['id'])

            time.sleep(1)

        self.processed_conv_ids.update(processed_in_batch)
        self.save_processed_conv_ids()

        logger.info(f"Extracted {len(all_faqs)} FAQ entries from {len(processed_in_batch)} new conversations")
        return all_faqs

    def load_existing_faqs(self) -> List[Dict]:
        """Load existing FAQ entries if they exist."""
        if self.output_path.exists():
            try:
                faqs = []
                with self.output_path.open('r') as f:
                    for line in f:
                        faqs.append(json.loads(line))
                logger.info(f"Loaded {len(faqs)} existing FAQ entries")
                return faqs
            except Exception as e:
                logger.warning(f"Error loading existing FAQs: {str(e)}")
                return []
        return []

    def save_faqs(self, faqs: List[Dict]):
        """Save FAQ entries to JSONL file."""
        if not faqs and self.output_path.exists():
            logger.info("No new FAQs to save, preserving existing entries")
            return

        with self.output_path.open('w') as f:
            for faq in faqs:
                f.write(json.dumps(faq) + '\n')
        logger.info(f"Saved {len(faqs)} FAQ entries to {self.output_path}")

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

    async def run(self) -> None:
        """Run the FAQ extraction process."""
        try:
            # Merge existing and new messages
            await self.merge_csv_files()

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
            conversations_path = Path(self.settings.DATA_DIR) / "conversations.jsonl"
            with conversations_path.open('w') as f:
                for conv in conversations:
                    serialized_conv = self.serialize_conversation(conv)
                    f.write(json.dumps(serialized_conv) + '\n')
            logger.info(f"Saved {len(conversations)} conversations to {conversations_path}")

            # Extract FAQs using OpenAI
            logger.info("Extracting FAQs using OpenAI...")
            if new_conversations:
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

        except Exception as e:
            logger.error(f"Error during FAQ extraction: {str(e)}")
            raise


if __name__ == "__main__":
    # Create an instance of FAQExtractor with explicit type annotation
    extractor: FAQExtractor = FAQExtractor()
    
    # Run the extractor using get_event_loop instead of asyncio.run
    loop = get_event_loop()
    try:
        loop.run_until_complete(extractor.run())
    finally:
        loop.close()

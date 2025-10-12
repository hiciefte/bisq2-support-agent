"""
FAQ service for loading and processing FAQ data for the Bisq Support Assistant.

This service handles loading FAQ documentation from JSONL files,
processing the documents, preparing them for use in the RAG system,
and extracting new FAQs from support chat conversations.
"""

import json
import logging
import os
import threading
from io import StringIO
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

import pandas as pd
import portalocker

# Import Pydantic models
from app.models.faq import FAQIdentifiedItem, FAQItem, FAQListResponse
from app.services.faq.conversation_processor import ConversationProcessor
from app.services.faq.faq_extractor import FAQExtractor
from app.services.faq.faq_rag_loader import FAQRAGLoader
from app.services.faq.faq_repository import FAQRepository
from fastapi import Request
from langchain_core.documents import Document

# Import OpenAI client
from openai import OpenAI

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class FAQService:
    """Service for managing FAQs using a JSONL file and stable content-based IDs."""

    _instance: Optional["FAQService"] = None
    _instance_lock = threading.Lock()
    _faq_file_path: Path
    _file_lock: Optional[portalocker.Lock] = None

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = super(FAQService, cls).__new__(cls)
        return cls._instance

    def __init__(self, settings: Any):
        """Initialize the FAQ service."""
        if not hasattr(self, "initialized"):
            self.settings = settings
            data_dir = Path(self.settings.DATA_DIR)
            self._faq_file_path = data_dir / "extracted_faq.jsonl"
            self.processed_convs_path = data_dir / "processed_conversations.json"
            self.processed_msg_ids_path = data_dir / "processed_message_ids.jsonl"
            self.conversations_path = data_dir / "conversations.jsonl"
            self.existing_input_path = data_dir / "support_chat_export.csv"

            self._file_lock = portalocker.Lock(
                str(self._faq_file_path) + ".lock", timeout=10
            )

            # Initialize FAQ repository for CRUD operations
            self.repository = FAQRepository(self._faq_file_path, self._file_lock)

            # Initialize conversation processor for message threading
            self.conversation_processor = ConversationProcessor()

            # Initialize FAQ RAG loader for document preparation
            self.rag_loader = FAQRAGLoader(source_weights={"faq": 1.2})

            # Initialize OpenAI client for FAQ extraction
            openai_client = None
            if (
                hasattr(self.settings, "OPENAI_API_KEY")
                and self.settings.OPENAI_API_KEY
            ):
                try:
                    openai_client = OpenAI(
                        api_key=self.settings.OPENAI_API_KEY, timeout=30.0
                    )
                    logger.info("OpenAI client initialized for FAQ extraction")
                except (ValueError, TypeError) as e:
                    logger.warning(f"Failed to initialize OpenAI client: {e}")
            else:
                logger.warning(
                    "OPENAI_API_KEY not provided. FAQ extraction will not work."
                )

            # Initialize FAQ extractor for OpenAI-based extraction
            self.faq_extractor = FAQExtractor(openai_client, self.settings)

            self.initialized = True
            logger.info("FAQService initialized with JSONL backend.")

    # CRUD operations - delegated to repository
    def get_all_faqs(self) -> List[FAQIdentifiedItem]:
        """Get all FAQs with their stable IDs."""
        return self.repository.get_all_faqs()

    def get_faqs_paginated(
        self,
        page: int = 1,
        page_size: int = 10,
        search_text: Optional[str] = None,
        categories: Optional[List[str]] = None,
        source: Optional[str] = None,
    ) -> FAQListResponse:
        """Get FAQs with pagination and filtering support."""
        return self.repository.get_faqs_paginated(
            page, page_size, search_text, categories, source
        )

    def add_faq(self, faq_item: FAQItem) -> FAQIdentifiedItem:
        """Adds a new FAQ to the FAQ file after checking for duplicates."""
        return self.repository.add_faq(faq_item)

    def update_faq(
        self, faq_id: str, updated_data: FAQItem
    ) -> Optional[FAQIdentifiedItem]:
        """Updates an existing FAQ by finding it via its stable ID."""
        return self.repository.update_faq(faq_id, updated_data)

    def delete_faq(self, faq_id: str) -> bool:
        """Deletes an FAQ by finding it via its stable ID."""
        return self.repository.delete_faq(faq_id)

    def normalize_text(self, text: str) -> str:
        """Normalize text using the FAQ extractor.

        Args:
            text: The text to normalize

        Returns:
            Normalized text
        """
        return self.faq_extractor.normalize_text(text)

    def get_normalized_faq_key(self, faq: Dict) -> str:
        """Generate a normalized key for a FAQ using the extractor.

        Args:
            faq: The FAQ dictionary

        Returns:
            A normalized key string
        """
        return self.faq_extractor.get_normalized_faq_key(faq)

    def update_source_weights(self, new_weights: Dict[str, float]) -> None:
        """Update source weights for FAQ content using the RAG loader.

        Args:
            new_weights: Dictionary with updated weights
        """
        self.rag_loader.update_source_weights(new_weights)

    def load_faq_data(self, faq_file: Optional[str] = None) -> List[Document]:
        """Load FAQ data from JSONL file using the RAG loader.

        Args:
            faq_file: Path to the FAQ JSONL file.
                      If None, uses the default path from settings.

        Returns:
            List of Document objects prepared for RAG system
        """
        faq_path = Path(faq_file) if faq_file else self._faq_file_path
        return self.rag_loader.load_faq_data(faq_path)

    # FAQ Extraction Methods from extract_faqs.py

    def load_processed_msg_ids(self) -> Set[str]:
        """Load the set of message IDs that have already been processed.

        This method supports backward compatibility by converting old conversation-based
        tracking to message-based tracking if needed.

        Returns:
            Set of processed message IDs
        """
        processed_msg_ids = set()

        # First, try loading from the new message ID tracking file
        # Use instance variable for consistency
        if self.processed_msg_ids_path.exists():
            try:
                with open(self.processed_msg_ids_path, "r") as f:
                    for line in f:
                        line = line.strip()
                        if line:
                            try:
                                # Support both plain text and JSON format
                                data = json.loads(line)
                                if isinstance(data, dict) and "msg_id" in data:
                                    processed_msg_ids.add(data["msg_id"])
                                elif isinstance(data, str):
                                    processed_msg_ids.add(data)
                            except json.JSONDecodeError:
                                # Treat as plain text message ID
                                processed_msg_ids.add(line)
                logger.info(f"Loaded {len(processed_msg_ids)} processed message IDs")
                return processed_msg_ids
            except Exception as e:
                logger.warning(f"Error loading processed message IDs: {e!s}")

        # Backward compatibility: convert old conversation tracking to message tracking
        if hasattr(self, "processed_convs_path") and self.processed_convs_path.exists():
            try:
                with open(self.processed_convs_path, "r") as f:
                    conv_ids = set(json.load(f))
                logger.info(
                    f"Found {len(conv_ids)} processed conversation IDs in legacy format"
                )

                # If conversations.jsonl exists, extract all message IDs from processed conversations
                if (
                    hasattr(self, "conversations_path")
                    and self.conversations_path.exists()
                ):
                    with open(self.conversations_path, "r") as f:
                        for line in f:
                            try:
                                conv = json.loads(line)
                                if conv.get("id") in conv_ids:
                                    # Extract all message IDs from this conversation
                                    for msg in conv.get("messages", []):
                                        if "msg_id" in msg:
                                            processed_msg_ids.add(msg["msg_id"])
                            except json.JSONDecodeError:
                                continue
                    logger.info(
                        f"Converted {len(conv_ids)} conversation IDs to {len(processed_msg_ids)} message IDs"
                    )
            except Exception as e:
                logger.warning(f"Error during backward compatibility conversion: {e!s}")

        return processed_msg_ids

    def save_processed_msg_ids(self, msg_ids: Optional[Set[str]] = None) -> None:
        """Save the set of processed message IDs.

        Uses JSONL format with one message ID per line for privacy-preserving tracking.
        This avoids storing full conversation data while maintaining deduplication.

        Args:
            msg_ids: Optional set of message IDs to save. If not provided, uses self.processed_msg_ids
        """
        if msg_ids is None:
            if not hasattr(self, "processed_msg_ids"):
                logger.warning("No processed_msg_ids to save")
                return
            msg_ids = self.processed_msg_ids

        processed_msg_ids_path = Path(self.settings.PROCESSED_MESSAGE_IDS_FILE_PATH)

        try:
            # Ensure parent directory exists
            processed_msg_ids_path.parent.mkdir(parents=True, exist_ok=True)

            # Write message IDs in JSONL format (one per line)
            # Using JSON format for consistency with the load method
            with open(processed_msg_ids_path, "w") as f:
                for msg_id in sorted(msg_ids):  # Sort for consistency
                    f.write(json.dumps({"msg_id": msg_id}) + "\n")

            logger.info(f"Saved {len(msg_ids)} processed message IDs")
        except Exception:
            logger.exception("Error saving processed message IDs")

    # Backward compatibility aliases
    def load_processed_conv_ids(self) -> Set[str]:
        """Deprecated: Use load_processed_msg_ids() instead."""
        logger.warning(
            "load_processed_conv_ids() is deprecated, use load_processed_msg_ids()"
        )
        return self.load_processed_msg_ids()

    def save_processed_conv_ids(self) -> None:
        """Deprecated: Use save_processed_msg_ids() instead."""
        logger.warning(
            "save_processed_conv_ids() is deprecated, use save_processed_msg_ids()"
        )
        if hasattr(self, "processed_conv_ids"):
            self.save_processed_msg_ids(self.processed_conv_ids)

    async def merge_csv_files(self, bisq_api=None):
        """Fetch latest messages from API and merge with existing ones.

        Args:
            bisq_api: Optional Bisq2API instance to fetch data from
        """
        if not hasattr(self, "existing_input_path"):
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
            logger.error(f"Failed to fetch messages from API: {e!s}")
        finally:
            if bisq_api:
                await bisq_api.cleanup()

        # If both DataFrames are empty, we have no data to work with
        if existing_df.empty and latest_df.empty:
            logger.warning("No messages available for processing")
            return

        # Combine DataFrames and drop duplicates based on Message ID
        combined_df = pd.concat([existing_df, latest_df], ignore_index=True)
        combined_df.drop_duplicates(subset=["Message ID"], keep="last", inplace=True)

        # Sort by date if available
        if "Date" in combined_df.columns:
            combined_df["Date"] = pd.to_datetime(combined_df["Date"], errors="coerce")
            combined_df.sort_values("Date", inplace=True)

        # Save the merged result
        self.existing_input_path.parent.mkdir(parents=True, exist_ok=True)
        combined_df.to_csv(self.existing_input_path, index=False)
        logger.info(f"Saved {len(combined_df)} messages to {self.existing_input_path}")

        # Store the input path for further processing
        self.input_path = self.existing_input_path

    def load_messages(self) -> None:
        """Load messages from CSV and organize them using the conversation processor."""
        if not hasattr(self, "input_path") or not self.input_path.exists():
            logger.warning("No input file found for loading messages")
            return

        # Delegate to conversation processor
        self.conversation_processor.load_messages(self.input_path)

    def build_conversation_thread(
        self, start_msg_id: str, max_depth: int = 10
    ) -> List[Dict]:
        """Build a conversation thread starting from a message, following references both ways."""
        return self.conversation_processor.build_conversation_thread(
            start_msg_id, max_depth
        )

    def is_valid_conversation(self, thread: List[Dict]) -> bool:
        """Validate if a conversation thread is complete and meaningful."""
        return self.conversation_processor.is_valid_conversation(thread)

    def group_conversations(self) -> List[Dict]:
        """Group messages into conversations using the conversation processor."""
        return self.conversation_processor.group_conversations()

    def extract_faqs_with_openai(
        self, conversations_to_process: List[Dict]
    ) -> List[Dict]:
        """Extract FAQs from conversations using the FAQ extractor.

        Args:
            conversations_to_process: List of conversation dictionaries to process

        Returns:
            List of extracted FAQ dictionaries
        """
        return self.faq_extractor.extract_faqs_with_openai(conversations_to_process)

    def load_existing_faqs(self) -> List[Dict]:
        """Load existing FAQs from the JSONL file for processing or extraction tasks.
        Returns a list of dictionaries.
        """
        faqs: List[Dict] = []
        if not hasattr(self, "_faq_file_path") or not self._faq_file_path.exists():
            logger.warning(
                f"FAQ file not found at {getattr(self, '_faq_file_path', 'Not set')}, cannot load existing FAQs."
            )
            return faqs

        try:
            # No need for aggressive locking here if this is mostly for internal RAG loading
            # which might happen at startup or less frequently than admin edits.
            # If admin edits become frequent and overlap with RAG reloads, locking here might be needed too.
            with open(self._faq_file_path, "r", encoding="utf-8") as f:
                for line in f:
                    try:
                        faqs.append(json.loads(line.strip()))
                    except json.JSONDecodeError:
                        logger.error(
                            f"Error parsing JSON line in load_existing_faqs: {line.strip()}"
                        )
            logger.info(f"Loaded {len(faqs)} existing FAQs from {self._faq_file_path}")
        except Exception as e:
            logger.error(f"Error in load_existing_faqs: {e!s}", exc_info=True)
        return faqs

    def save_faqs(self, faqs: List[Dict]) -> None:
        """
        Saves a list of FAQ dictionaries to the faq_file_path.
        This method is typically used by the FAQ extraction process.
        It now uses portalocker for safe concurrent writes.
        """
        try:
            # Re-use the class-level lock for this operation
            with self._file_lock, open(
                self._faq_file_path, "r+", encoding="utf-8"
            ) as f:
                # Load existing FAQs to check for duplicates
                existing_faqs = [json.loads(line) for line in f if line.strip()]

                # Create a set of normalized keys for existing FAQs using the extractor
                normalized_faq_keys = {
                    self.faq_extractor.get_normalized_faq_key(faq)
                    for faq in existing_faqs
                }

                # Filter out duplicates from the new faqs
                new_unique_faqs = [
                    faq
                    for faq in faqs
                    if self.faq_extractor.get_normalized_faq_key(faq)
                    not in normalized_faq_keys
                ]

                if new_unique_faqs:
                    # Move to the end of the file to append new content
                    f.seek(0, os.SEEK_END)
                    # Ensure file ends with a newline if not empty
                    if f.tell() > 0:
                        f.seek(f.tell() - 1)
                        if f.read(1) != "\n":
                            f.write("\n")

                    for faq in new_unique_faqs:
                        f.write(json.dumps(faq) + "\n")
                    logger.info(f"Saved {len(new_unique_faqs)} new FAQs.")
                else:
                    logger.info("No new non-duplicate FAQs to save.")

        except portalocker.exceptions.LockException as e:
            logger.error(f"Could not acquire lock on FAQ file: {e}")
        except Exception as e:
            logger.error(f"Error saving new FAQs: {e}", exc_info=True)

    def serialize_conversation(self, conv: Dict) -> Dict:
        """Helper to serialize conversation for JSON, handling non-serializable types."""
        serialized = conv.copy()
        messages = []
        for msg in conv["messages"]:
            msg_copy = msg.copy()
            if msg_copy["timestamp"]:
                msg_copy["timestamp"] = msg_copy["timestamp"].isoformat()
            messages.append(msg_copy)
        serialized["messages"] = messages
        return serialized

    async def extract_and_save_faqs(self, bisq_api=None) -> List[Dict]:
        """Run the complete FAQ extraction process.

        This method now uses message-level tracking instead of conversation-level tracking
        for more granular deduplication and privacy-preserving operation. It automatically
        handles backward compatibility with old conversation tracking.

        Args:
            bisq_api: Optional Bisq2API instance to fetch data

        Returns:
            List of extracted FAQ dictionaries
        """
        try:
            # Load the set of already processed message IDs
            # This automatically handles backward compatibility with old conversation tracking
            self.processed_msg_ids = self.load_processed_msg_ids()

            # Load existing FAQs and seed the duplicate tracker in the extractor
            existing_faqs = self.load_existing_faqs()
            self.faq_extractor.seed_duplicate_tracker(existing_faqs)

            # Merge existing and new messages from the API
            await self.merge_csv_files(bisq_api)

            # Load and process messages into memory
            self.load_messages()

            # Group all messages into conversation threads
            all_conversations = self.group_conversations()

            # Save conversations only if not in privacy mode
            if (
                hasattr(self, "conversations_path")
                and not self.settings.ENABLE_PRIVACY_MODE
            ):
                with self.conversations_path.open("w", encoding="utf-8") as f:
                    for conv in all_conversations:
                        serialized_conv = self.serialize_conversation(conv)
                        f.write(json.dumps(serialized_conv, ensure_ascii=False) + "\n")
                logger.info(
                    f"Saved {len(all_conversations)} conversations to {self.conversations_path}"
                )
            elif self.settings.ENABLE_PRIVACY_MODE:
                logger.info(
                    "Privacy mode enabled: skipping full conversation persistence"
                )

            # --- Message-Level State Management ---
            # Determine which conversations contain at least one unprocessed message
            new_conversations_to_process = []
            for conv in all_conversations:
                # Check if any message in this conversation has not been processed
                unprocessed_msg_ids = [
                    msg["msg_id"]
                    for msg in conv["messages"]
                    if msg["msg_id"] not in self.processed_msg_ids
                ]
                if unprocessed_msg_ids:
                    new_conversations_to_process.append(conv)
                    logger.debug(
                        f"Conversation {conv['id']} has {len(unprocessed_msg_ids)} unprocessed messages"
                    )

            if not new_conversations_to_process:
                logger.info("No new messages to process.")
                return []

            # Extract FAQs from conversations with unprocessed messages
            logger.info(
                f"Processing {len(new_conversations_to_process)} conversations with new messages..."
            )
            new_faqs = self.extract_faqs_with_openai(new_conversations_to_process)

            # If new FAQs were found, save them
            if new_faqs:
                self.save_faqs(new_faqs)
                logger.info(
                    f"Extraction complete. Saved {len(new_faqs)} new FAQ entries."
                )

            # Mark all messages from processed conversations as processed
            for conv in new_conversations_to_process:
                for msg in conv["messages"]:
                    self.processed_msg_ids.add(msg["msg_id"])

            # Save the updated set of processed message IDs
            self.save_processed_msg_ids(self.processed_msg_ids)

            return new_faqs

        except Exception as e:
            logger.error(f"Error during FAQ extraction: {e!s}")
            raise


def get_faq_service(request: Request) -> FAQService:
    """Get the FAQ service from the request state."""
    return request.app.state.faq_service

"""Bisq 2 live polling service for unified training pipeline.

Orchestrates Bisq 2 chat polling and LLM-based FAQ extraction, processing
messages through the unified training pipeline for FAQ candidate generation.

Uses UnifiedFAQExtractor for single-pass LLM extraction instead of
pattern-based citation matching.
"""

import asyncio
import logging
import time as time_module
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set

from app.metrics.training_metrics import (
    sync_duration_seconds,
    sync_last_status,
    sync_last_success_timestamp,
    sync_pairs_processed,
    training_errors,
)

logger = logging.getLogger(__name__)


class Bisq2SyncService:
    """Orchestrates Bisq 2 chat polling and LLM-based FAQ extraction.

    Uses UnifiedFAQExtractor via pipeline_service.extract_faqs_batch() for
    single-pass LLM extraction instead of pattern-based citation matching.
    """

    def __init__(
        self,
        settings: Any,
        pipeline_service: Any,
        bisq_api: Any,
        state_manager: Any,
    ):
        """Initialize Bisq2 sync service.

        Args:
            settings: Application settings with Bisq 2 configuration
            pipeline_service: UnifiedPipelineService for Q&A processing
            bisq_api: Bisq2API instance for fetching conversations
            state_manager: BisqSyncStateManager for state tracking
        """
        self.settings = settings
        self.pipeline_service = pipeline_service
        self.bisq_api = bisq_api
        self.state_manager = state_manager

        # Build trusted staff IDs set from settings
        staff_users = getattr(settings, "BISQ_STAFF_USERS", [])
        if isinstance(staff_users, str):
            staff_users = [s.strip() for s in staff_users.split(",") if s.strip()]
        self.staff_users: List[str] = staff_users
        self.staff_users_lower: Set[str] = {s.lower() for s in staff_users}

    def is_configured(self) -> bool:
        """Check if Bisq 2 integration is configured."""
        return self.bisq_api is not None

    async def sync_conversations(
        self, max_retries: int = 3, retry_delay: int = 5
    ) -> int:
        """Sync conversations from Bisq 2 API and process through the pipeline.

        Uses LLM-based extraction via UnifiedFAQExtractor to identify Q&A pairs
        from the message stream, rather than relying on citation patterns.
        """
        if not self.is_configured():
            logger.debug("Bisq 2 API not configured, skipping sync")
            return 0

        processed_count = 0
        sync_start_time = time_module.time()

        try:
            # Fetch messages with retry logic
            messages = await self._fetch_messages_with_retry(max_retries, retry_delay)
            if messages is None:
                raise Exception("Failed to fetch messages after multiple retries")

            logger.info(f"Fetched {len(messages)} messages from Bisq 2 API")

            if not messages:
                logger.info("No messages to process")
                return 0

            # Filter out already-processed messages
            new_messages = [
                msg
                for msg in messages
                if not self.state_manager.is_processed(msg.get("messageId", ""))
            ]
            logger.info(
                f"After deduplication: {len(new_messages)} new messages to process"
            )

            if not new_messages:
                logger.info("No new messages to process")
                return 0

            # Mark ALL input messages as processed BEFORE sending to LLM
            # This prevents duplicate processing on subsequent polls, regardless
            # of whether the LLM extracts any FAQs from them
            for msg in new_messages:
                msg_id = msg.get("messageId", "")
                if msg_id:
                    self.state_manager.mark_processed(msg_id)

            logger.info(f"Marked {len(new_messages)} input messages as processed")

            # Use LLM-based extraction via pipeline service
            # This sends all messages to UnifiedFAQExtractor for single-pass extraction
            results = await self.pipeline_service.extract_faqs_batch(
                messages=new_messages,
                source="bisq2",
                staff_identifiers=self.staff_users,
            )

            # Count successfully processed candidates
            for result in results:
                if result.candidate_id is not None:
                    processed_count += 1
                    logger.info(
                        f"Processed Bisq FAQ -> candidate {result.candidate_id} "
                        f"(routing: {result.routing})"
                    )

            # Update sync state
            if messages:
                self.state_manager.update_last_sync(datetime.now(timezone.utc))
                self.state_manager.save_state()

            # Update metrics
            sync_last_status.labels(source="bisq2").set(1)
            sync_last_success_timestamp.labels(source="bisq2").set(time_module.time())
            sync_pairs_processed.labels(source="bisq2").inc(processed_count)

            logger.info(
                f"Bisq sync complete: extracted {len(results)} FAQs, "
                f"processed {processed_count} candidates"
            )
            return processed_count

        except Exception:
            logger.exception("Bisq sync failed")
            training_errors.labels(stage="poll").inc()
            sync_last_status.labels(source="bisq2").set(0)
            raise
        finally:
            sync_duration_seconds.labels(source="bisq2").observe(
                time_module.time() - sync_start_time
            )

    async def _fetch_messages_with_retry(
        self, max_retries: int, retry_delay: int
    ) -> Optional[List[Dict[str, Any]]]:
        """Fetch messages from Bisq 2 API with retry logic."""
        for attempt in range(max_retries):
            try:
                result = await self.bisq_api.export_chat_messages(
                    since=self.state_manager.last_sync_timestamp
                )
                return result.get("messages", [])
            except Exception as e:
                logger.warning(f"Attempt {attempt + 1}/{max_retries} failed: {e}")
                if attempt + 1 == max_retries:
                    return None
                await asyncio.sleep(retry_delay)
        return None


__all__ = ["Bisq2SyncService"]

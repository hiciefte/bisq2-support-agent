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
from typing import Any, Dict, List, Optional

from app.channels.plugins.bisq2.test_scope import (
    Bisq2TestScope,
    resolve_bisq2_test_scope,
)
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
        self._test_scope: Bisq2TestScope = resolve_bisq2_test_scope(settings)

        # Bisq staff trust is bound only to immutable profile identifiers.
        staff_profile_ids = getattr(settings, "BISQ2_STAFF_PROFILE_IDS", [])
        if isinstance(staff_profile_ids, str):
            staff_profile_ids = [
                item.strip() for item in staff_profile_ids.split(",") if item.strip()
            ]
        if not isinstance(staff_profile_ids, list):
            staff_profile_ids = []
        self.staff_profile_ids = [
            item for item in staff_profile_ids if isinstance(item, str) and item
        ]

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
        if not self._test_scope.ready:
            logger.warning(
                "Bisq 2 training sync blocked by production-test scope "
                "(reason=%s, channel_count=%d, sender_profile_count=%d)",
                self._test_scope.reason,
                self._test_scope.channel_count,
                self._test_scope.sender_profile_count,
            )
            return 0

        processed_count = 0
        sync_start_time = time_module.time()

        try:
            # Fetch messages with retry logic
            messages = await self._fetch_messages_with_retry(max_retries, retry_delay)
            if messages is None:
                raise Exception("Failed to fetch messages after multiple retries")

            fetched_count = len(messages)
            messages = [
                message
                for message in messages
                if isinstance(message, dict)
                and self._test_scope.allows_payload(message)
            ]
            logger.info(
                "Fetched %d messages from Bisq 2 API; %d matched the "
                "production-test scope",
                fetched_count,
                len(messages),
            )

            if not messages:
                logger.info("No in-scope messages to process")
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

            # Never let the extractor pair messages across exact Bisq channels.
            messages_by_channel: Dict[str, List[Dict[str, Any]]] = {}
            for message in new_messages:
                channel_id = self._test_scope.resolve_payload_channel(message)
                messages_by_channel.setdefault(channel_id, []).append(message)

            results = []
            for channel_messages in messages_by_channel.values():
                channel_results = await self.pipeline_service.extract_faqs_batch(
                    messages=channel_messages,
                    source="bisq2",
                    staff_identifiers=self.staff_profile_ids,
                )
                results.extend(channel_results)

            # Mark all input messages processed only after extraction completes.
            for msg in new_messages:
                msg_id = msg.get("messageId", "")
                if msg_id:
                    self.state_manager.mark_processed(msg_id)
            logger.info(f"Marked {len(new_messages)} input messages as processed")

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

        except Exception as exc:
            logger.warning("Bisq sync failed (%s)", type(exc).__name__)
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
                    since=self.state_manager.last_sync_timestamp,
                    max_retries=max_retries,
                    retry_delay=retry_delay,
                )
                return result.get("messages", [])
            except Exception as exc:
                logger.warning(
                    "Bisq export attempt %s/%s failed (%s)",
                    attempt + 1,
                    max_retries,
                    type(exc).__name__,
                )
                if attempt + 1 == max_retries:
                    return None
                await asyncio.sleep(retry_delay)
        return None


__all__ = ["Bisq2SyncService"]

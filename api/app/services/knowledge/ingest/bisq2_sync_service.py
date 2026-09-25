"""Bisq 2 history sync service for knowledge intake.

Orchestrates Bisq 2 chat polling and LLM-based knowledge extraction, processing
messages through the knowledge intake pipeline for review candidates.

Uses KnowledgeExtractor for single-pass LLM extraction instead of
pattern-based citation matching.
"""

import asyncio
import logging
import time as time_module
from datetime import datetime, timedelta, timezone
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
from app.services.knowledge.knowledge_extractor import bisq_citation_message_id

logger = logging.getLogger(__name__)
MAX_BOUNDARY_HISTORY_MESSAGES = 1000
MAX_BOUNDARY_CITATIONS = 10
MAX_PRIOR_CONTEXT_MESSAGES = 50


class IncompleteBisqKnowledgeContextError(RuntimeError):
    """Source context needs a durable no-extraction disposition."""

    def __init__(self, message: str, reason: str = "context_unavailable"):
        super().__init__(message)
        self.reason = reason


class Bisq2SyncService:
    """Orchestrates Bisq 2 chat polling and LLM-based knowledge extraction.

    Uses KnowledgeExtractor via pipeline_service.extract_faqs_batch() for
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
            pipeline_service: KnowledgePipelineService for Q&A processing
            bisq_api: Bisq2API instance for fetching conversations
            state_manager: BisqSyncStateManager for state tracking
        """
        self.settings = settings
        self.pipeline_service = pipeline_service
        self.bisq_api = bisq_api
        self.state_manager = state_manager
        self._test_scope: Bisq2TestScope = resolve_bisq2_test_scope(settings)
        self.last_deferred_count = 0
        self.last_deferred_scopes = 0

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

        Uses LLM-based extraction via KnowledgeExtractor to identify Q&A pairs
        from the message stream, rather than relying on citation patterns.
        """
        self.last_deferred_count = 0
        self.last_deferred_scopes = 0
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
            new_ids = {message.get("messageId", "") for message in new_messages}
            for message in messages:
                channel_id = self._test_scope.resolve_payload_channel(message)
                messages_by_channel.setdefault(channel_id, []).append(message)

            results = []
            boundary_history: Optional[List[Dict[str, Any]]] = None
            boundary_error: Optional[IncompleteBisqKnowledgeContextError] = None
            channel_errors: List[Exception] = []
            for channel_id, channel_messages in messages_by_channel.items():
                deferred_ids = self.pipeline_service.repository.get_deferred_event_ids(
                    source="bisq2", source_scope=channel_id
                )
                # Reconcile dispositions committed before a source-state crash.
                for message in channel_messages:
                    if message.get("messageId") in deferred_ids:
                        self.state_manager.mark_processed(message["messageId"])
                eligible_ids = {
                    message.get("messageId", "")
                    for message in channel_messages
                    if message.get("messageId", "") in new_ids
                    and message.get("messageId", "") not in deferred_ids
                }
                if not eligible_ids:
                    self.state_manager.save_state()
                    continue
                # Reuse exported history as bounded transient context. Processed
                # questions can be paired with a newly arriving staff answer.
                context = [
                    message
                    for message in channel_messages
                    if message.get("messageId", "") not in eligible_ids
                ][-MAX_PRIOR_CONTEXT_MESSAGES:]
                fresh = [
                    message
                    for message in channel_messages
                    if message.get("messageId", "") in eligible_ids
                ]
                extraction_messages = sorted(
                    [*context, *fresh], key=lambda message: str(message.get("date", ""))
                )
                try:
                    try:
                        missing_targets, needs_prior = self._missing_context(
                            extraction_messages, eligible_ids
                        )
                        if missing_targets or needs_prior:
                            if boundary_history is None and boundary_error is None:
                                try:
                                    boundary_history = (
                                        await self._fetch_boundary_history()
                                    )
                                except IncompleteBisqKnowledgeContextError as exc:
                                    boundary_error = exc
                            if boundary_error is not None:
                                raise boundary_error
                            extraction_messages = self._recover_boundary_context(
                                channel_id,
                                extraction_messages,
                                eligible_ids,
                                boundary_history or [],
                            )
                    except IncompleteBisqKnowledgeContextError as exc:
                        # Persist the entire current eligible channel batch.
                        # Never replace a paid started/uncertain receipt.
                        count = (
                            self.pipeline_service.repository.record_intake_disposition(
                                source="bisq2",
                                source_scope=channel_id,
                                event_ids=sorted(eligible_ids),
                                reason=exc.reason,
                            )
                        )
                        self.last_deferred_count += count
                        self.last_deferred_scopes += 1
                    else:
                        if any(
                            self._has_text(msg) and self._is_staff_message(msg)
                            for msg in fresh
                        ):
                            channel_results = (
                                await self.pipeline_service.extract_faqs_batch(
                                    messages=extraction_messages,
                                    source="bisq2",
                                    staff_identifiers=self.staff_profile_ids,
                                    source_scope=channel_id,
                                    eligible_answer_ids=eligible_ids,
                                )
                            )
                            results.extend(channel_results)
                        else:
                            self.pipeline_service.repository.ensure_knowledge_scope_not_held(
                                source="bisq2", source_scope=channel_id
                            )

                    # Save completed or durably deferred channel progress now.
                    for msg in fresh:
                        msg_id = msg.get("messageId", "")
                        if msg_id:
                            self.state_manager.mark_processed(msg_id)
                    self.state_manager.save_state()
                except Exception as exc:
                    # A held/failed channel must not starve independent ones.
                    # Keep the global timestamp pending and report after saves.
                    channel_errors.append(exc)
                    logger.warning(
                        "Bisq channel intake remains pending (%s)", type(exc).__name__
                    )

            # Count successfully processed candidates
            for result in results:
                if result.candidate_id is not None:
                    processed_count += 1
                    logger.info(
                        f"Processed Bisq FAQ -> candidate {result.candidate_id} "
                        f"(routing: {result.routing})"
                    )

            if channel_errors:
                raise channel_errors[0]

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

    def _is_staff_message(self, message: Dict[str, Any]) -> bool:
        return (
            self._test_scope.resolve_payload_sender_profile(message)
            in self.staff_profile_ids
        )

    @staticmethod
    def _has_text(message: Dict[str, Any]) -> bool:
        return isinstance(message.get("message"), str) and bool(
            message["message"].strip()
        )

    def _missing_context(
        self, messages: List[Dict[str, Any]], eligible_ids: set[str]
    ) -> tuple[set[str], bool]:
        """Require referenced roots and prior readable user context for new staff."""
        readable = [message for message in messages if self._has_text(message)]
        known_ids = {message.get("messageId") for message in readable}
        missing_targets: set[str] = set()
        needs_prior = False
        user_seen = False
        for message in readable:
            if not self._is_staff_message(message):
                user_seen = True
            elif message.get("messageId") in eligible_ids:
                target = bisq_citation_message_id(message)
                if target and target not in known_ids:
                    missing_targets.add(target)
                if not user_seen:
                    needs_prior = True
        return missing_targets, needs_prior

    async def _fetch_boundary_history(self) -> List[Dict[str, Any]]:
        """One bounded read-only recovery export per sync; never a paid retry."""
        configured_days = getattr(self.settings, "DATA_RETENTION_DAYS", 30)
        days = (
            min(30, max(1, configured_days)) if isinstance(configured_days, int) else 30
        )
        try:
            result = await self.bisq_api.export_chat_messages(
                since=datetime.now(timezone.utc) - timedelta(days=days),
                max_retries=1,
                retry_delay=0,
            )
        except Exception as exc:
            raise IncompleteBisqKnowledgeContextError(
                "Bisq boundary history is unavailable"
            ) from exc
        history = result.get("messages") if isinstance(result, dict) else None
        if (
            not isinstance(history, list)
            or len(history) > MAX_BOUNDARY_HISTORY_MESSAGES
        ):
            raise IncompleteBisqKnowledgeContextError(
                "Bisq boundary history is unavailable or exceeds its bound; inputs deferred",
                "context_limit" if isinstance(history, list) else "context_unavailable",
            )
        return [
            message
            for message in history
            if isinstance(message, dict) and self._test_scope.allows_payload(message)
        ]

    def _recover_boundary_context(
        self,
        channel_id: str,
        messages: List[Dict[str, Any]],
        eligible_ids: set[str],
        history: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        by_id = {
            message["messageId"]: message
            for message in messages
            if message.get("messageId")
        }
        if len(by_id) != len(
            [message for message in messages if message.get("messageId")]
        ):
            raise IncompleteBisqKnowledgeContextError(
                "Bisq source has duplicate event provenance; inputs deferred",
                "provenance_conflict",
            )
        targets = {
            target
            for message in messages
            if message.get("messageId") in eligible_ids
            and self._is_staff_message(message)
            if (target := bisq_citation_message_id(message))
        }
        if len(targets) > MAX_BOUNDARY_CITATIONS:
            raise IncompleteBisqKnowledgeContextError(
                "Bisq reply targets exceed the bounded context; inputs deferred",
                "context_limit",
            )
        for message in history:
            if self._test_scope.resolve_payload_channel(message) != channel_id:
                continue
            message_id = message.get("messageId")
            if not message_id or not self._has_text(message):
                continue
            if message_id in by_id and by_id[message_id] != message:
                raise IncompleteBisqKnowledgeContextError(
                    "Bisq boundary history has conflicting event provenance; inputs deferred",
                    "provenance_conflict",
                )
            by_id[message_id] = message
        # Older explicit citation roots must survive the recent-context limit.
        required = [
            message for key, message in by_id.items() if key in targets - eligible_ids
        ]
        fresh = [
            message for message in messages if message.get("messageId") in eligible_ids
        ]
        first_fresh_date = min(str(message.get("date", "")) for message in fresh)
        prior = sorted(
            (
                message
                for key, message in by_id.items()
                if key not in eligible_ids | targets
                and str(message.get("date", "")) <= first_fresh_date
            ),
            key=lambda message: str(message.get("date", "")),
        )[-MAX_PRIOR_CONTEXT_MESSAGES:]
        recovered = sorted(
            [*required, *prior, *fresh],
            key=lambda message: str(message.get("date", "")),
        )
        missing_targets, needs_prior = self._missing_context(recovered, eligible_ids)
        if missing_targets or needs_prior:
            raise IncompleteBisqKnowledgeContextError(
                "Bisq prior question context remains incomplete; inputs deferred",
                "missing_reply_target" if missing_targets else "missing_prior_question",
            )
        return recovered

    async def _fetch_messages_with_retry(
        self, max_retries: int, retry_delay: int
    ) -> Optional[List[Dict[str, Any]]]:
        """Fetch messages from Bisq 2 API with retry logic."""
        for attempt in range(max_retries):
            try:
                since = self.state_manager.last_sync_timestamp
                if isinstance(since, datetime):
                    since -= timedelta(hours=1)
                result = await self.bisq_api.export_chat_messages(
                    since=since,
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

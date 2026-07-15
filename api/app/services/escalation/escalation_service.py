"""Escalation lifecycle orchestration service."""

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Literal, Optional

from app.models.escalation import (
    DuplicateEscalationError,
    Escalation,
    EscalationAlreadyClaimedError,
    EscalationClosedError,
    EscalationCountsResponse,
    EscalationCreate,
    EscalationDeliveryStatus,
    EscalationFilters,
    EscalationInvalidStateError,
    EscalationListResponse,
    EscalationNotFoundError,
    EscalationNotRespondedError,
    EscalationPriority,
    EscalationStatus,
    EscalationUpdate,
    UserPollResponse,
)
from app.services.escalation.feedback_metrics import compute_hybrid_distance
from app.services.faq.duplicate_guard import DuplicateFAQError, find_similar_faqs
from prometheus_client import Counter, Histogram

logger = logging.getLogger(__name__)
AUTO_REACTION_ESCALATION_REASON_PREFIX = "auto_reaction_negative"

ESCALATION_LIFECYCLE = Counter(
    "escalation_lifecycle_total",
    "Escalation state transitions",
    ["action"],
)
ESCALATION_DELIVERY = Counter(
    "escalation_delivery_total",
    "Delivery outcomes by channel",
    ["channel", "outcome"],
)
ESCALATION_RESPONSE_TIME = Histogram(
    "escalation_response_time_seconds",
    "Time from creation to staff response",
    buckets=[60, 300, 600, 1800, 3600, 7200, 14400, 43200, 86400],
)


class EscalationService:
    """Orchestrates the escalation lifecycle.

    Dependencies injected via constructor:
    - repository: EscalationRepository (async SQLite CRUD)
    - response_delivery: ResponseDelivery (channel routing)
    - faq_service: FAQService (FAQ creation)
    - learning_engine: LearningEngine (learning recording)
    - settings: Settings (configuration)
    """

    def __init__(
        self,
        repository,
        response_delivery,
        faq_service,
        learning_engine,
        settings,
        feedback_orchestrator=None,
        embeddings=None,
        rag_service=None,
        event_broker=None,
    ):
        self.repository = repository
        self.response_delivery = response_delivery
        self.faq_service = faq_service
        self.learning_engine = learning_engine
        self.settings = settings
        self.feedback_orchestrator = feedback_orchestrator
        self.embeddings = embeddings
        self.rag_service = rag_service
        self.event_broker = event_broker
        self._delivery_locks: dict[int, asyncio.Lock] = {}
        self._delivery_lock_refs: dict[int, int] = {}
        self._delivery_locks_guard = asyncio.Lock()

    async def _acquire_delivery_lock(self, escalation_id: int) -> asyncio.Lock:
        """Acquire a ref-counted per-case lock for save-and-deliver operations."""
        async with self._delivery_locks_guard:
            lock = self._delivery_locks.get(escalation_id)
            if lock is None:
                lock = asyncio.Lock()
                self._delivery_locks[escalation_id] = lock
            self._delivery_lock_refs[escalation_id] = (
                self._delivery_lock_refs.get(escalation_id, 0) + 1
            )
        try:
            await lock.acquire()
        except BaseException:
            await self._drop_delivery_lock_ref(escalation_id, lock)
            raise
        return lock

    async def _drop_delivery_lock_ref(
        self, escalation_id: int, lock: asyncio.Lock
    ) -> None:
        async with self._delivery_locks_guard:
            ref_count = self._delivery_lock_refs.get(escalation_id, 1) - 1
            if ref_count <= 0:
                if self._delivery_locks.get(escalation_id) is lock:
                    self._delivery_locks.pop(escalation_id, None)
                self._delivery_lock_refs.pop(escalation_id, None)
            else:
                self._delivery_lock_refs[escalation_id] = ref_count

    async def _release_delivery_lock(
        self, escalation_id: int, lock: asyncio.Lock
    ) -> None:
        lock.release()
        await self._drop_delivery_lock_ref(escalation_id, lock)

    async def _publish_update(self, escalation: Escalation) -> None:
        if self.event_broker is None:
            return
        try:
            await self.event_broker.publish(escalation)
        except Exception:
            logger.exception(
                "Failed to publish escalation event for message_id=%s",
                escalation.message_id,
            )

    # ------------------------------------------------------------------
    # Create
    # ------------------------------------------------------------------

    async def create_escalation(self, data: EscalationCreate) -> Escalation:
        """Create a new escalation. Idempotent on message_id."""
        try:
            result = await self.repository.create(data)
            ESCALATION_LIFECYCLE.labels(action="created").inc()
            return result
        except DuplicateEscalationError:
            logger.info(
                "Duplicate escalation for message_id=%s, returning existing",
                data.message_id,
            )
            existing = await self.repository.get_by_message_id(data.message_id)
            if existing is None:
                raise
            return existing

    # ------------------------------------------------------------------
    # Claim
    # ------------------------------------------------------------------

    async def claim_escalation(self, escalation_id: int, staff_id: str) -> Escalation:
        """Claim an escalation for review."""
        escalation = await self.repository.get_by_id(escalation_id)
        if escalation is None:
            raise EscalationNotFoundError(f"Escalation {escalation_id} not found")

        if escalation.status == EscalationStatus.CLOSED:
            raise EscalationClosedError(f"Escalation {escalation_id} is closed")

        # Already claimed by same staff — idempotent
        if escalation.staff_id == staff_id and escalation.status in (
            EscalationStatus.IN_REVIEW,
            EscalationStatus.RESPONDED,
        ):
            return escalation

        # Already claimed by another staff — check TTL
        if (
            escalation.status == EscalationStatus.IN_REVIEW
            and escalation.staff_id
            and escalation.staff_id != staff_id
        ):
            if escalation.claimed_at and not self._is_claim_expired(
                escalation.claimed_at
            ):
                raise EscalationAlreadyClaimedError(
                    f"Escalation {escalation_id} already claimed by "
                    f"{escalation.staff_id}"
                )

        now = datetime.now(timezone.utc)
        ESCALATION_LIFECYCLE.labels(action="claimed").inc()
        logger.info(
            "Escalation claimed",
            extra={"escalation_id": escalation_id, "staff_id": staff_id},
        )
        return await self.repository.update(
            escalation_id,
            EscalationUpdate(
                status=EscalationStatus.IN_REVIEW,
                staff_id=staff_id,
                claimed_at=now,
            ),
        )

    async def unclaim_escalation(self, escalation_id: int, staff_id: str) -> Escalation:
        """Release an escalation back to the pending queue."""
        escalation = await self.repository.get_by_id(escalation_id)
        if escalation is None:
            raise EscalationNotFoundError(f"Escalation {escalation_id} not found")

        if escalation.status == EscalationStatus.CLOSED:
            raise EscalationClosedError(f"Escalation {escalation_id} is closed")

        if escalation.status != EscalationStatus.IN_REVIEW:
            raise EscalationInvalidStateError(
                f"Escalation {escalation_id} cannot be unclaimed from {escalation.status}"
            )

        if escalation.staff_id and escalation.staff_id != staff_id:
            if escalation.claimed_at and not self._is_claim_expired(
                escalation.claimed_at
            ):
                raise EscalationAlreadyClaimedError(
                    f"Escalation {escalation_id} claimed by {escalation.staff_id}"
                )

        return await self.repository.unclaim(
            escalation_id,
            EscalationStatus.PENDING,
        )

    def _is_claim_expired(self, claimed_at: datetime) -> bool:
        ttl_minutes = getattr(self.settings, "ESCALATION_CLAIM_TTL_MINUTES", 30)
        expiry = claimed_at + timedelta(minutes=ttl_minutes)
        return datetime.now(timezone.utc) > expiry

    # ------------------------------------------------------------------
    # Respond
    # ------------------------------------------------------------------

    async def respond_to_escalation(
        self, escalation_id: int, staff_answer: str, staff_id: str
    ) -> Escalation:
        """Save staff response, deliver to user, record learning."""
        lock = await self._acquire_delivery_lock(escalation_id)
        try:
            return await self._respond_to_escalation_locked(
                escalation_id, staff_answer, staff_id
            )
        finally:
            await self._release_delivery_lock(escalation_id, lock)

    async def _respond_to_escalation_locked(
        self, escalation_id: int, staff_answer: str, staff_id: str
    ) -> Escalation:
        """Respond while holding the per-case delivery lock."""
        escalation = await self.repository.get_by_id(escalation_id)
        if escalation is None:
            raise EscalationNotFoundError(f"Escalation {escalation_id} not found")

        is_replacement = False
        # Same answer is idempotent; a failed answer may be replaced and retried.
        if (
            escalation.status == EscalationStatus.RESPONDED
            and escalation.staff_id == staff_id
        ):
            delivery_pending = escalation.channel != "web" and (
                escalation.delivery_status
                in {
                    EscalationDeliveryStatus.PENDING,
                    EscalationDeliveryStatus.FAILED,
                }
            )
            if str(escalation.staff_answer or "") == staff_answer:
                if delivery_pending:
                    return await self._retry_saved_delivery(escalation)
                return escalation
            if escalation.channel == "web":
                # Web clients poll the already-persisted response; preserve the
                # historical idempotent contract for duplicate submissions.
                return escalation
            if not delivery_pending:
                raise EscalationInvalidStateError(
                    f"Escalation {escalation_id} response was already delivered"
                )
            is_replacement = True

        if escalation.status == EscalationStatus.RESPONDED and not is_replacement:
            raise EscalationAlreadyClaimedError(
                f"Escalation {escalation_id} already responded by "
                f"{escalation.staff_id or 'another staff member'}"
            )

        # Closed — cannot respond
        if escalation.status == EscalationStatus.CLOSED:
            raise EscalationClosedError(f"Escalation {escalation_id} is closed")

        # Must be claimed by this staff (or pending)
        if (
            escalation.status == EscalationStatus.IN_REVIEW
            and escalation.staff_id
            and escalation.staff_id != staff_id
        ):
            if escalation.claimed_at and not self._is_claim_expired(
                escalation.claimed_at
            ):
                raise EscalationAlreadyClaimedError(
                    f"Escalation {escalation_id} claimed by " f"{escalation.staff_id}"
                )

        now = datetime.now(timezone.utc)
        edit_distance = await compute_hybrid_distance(
            escalation.ai_draft_answer,
            staff_answer,
            embeddings=self.embeddings,
        )

        updated = await self.repository.update(
            escalation_id,
            EscalationUpdate(
                status=EscalationStatus.RESPONDED,
                staff_answer=staff_answer,
                staff_id=staff_id,
                responded_at=now,
                edit_distance=edit_distance,
                delivery_status=(
                    EscalationDeliveryStatus.NOT_REQUIRED
                    if escalation.channel == "web"
                    else EscalationDeliveryStatus.PENDING
                ),
                delivery_error="",
                delivery_attempts=0 if is_replacement else escalation.delivery_attempts,
            ),
        )
        if not is_replacement:
            ESCALATION_LIFECYCLE.labels(action="responded").inc()
        await self._publish_update(updated)

        # Track response time only for the first staff response.
        if not is_replacement and escalation.created_at:
            delta = (now - escalation.created_at).total_seconds()
            ESCALATION_RESPONSE_TIME.observe(delta)

        logger.info(
            "Escalation responded",
            extra={
                "escalation_id": escalation_id,
                "channel": escalation.channel,
                "staff_id": staff_id,
                "replacement": is_replacement,
            },
        )

        updated = await self._attempt_delivery(
            updated,
            staff_answer,
            channel=escalation.channel,
        )

        # Record learning
        if self.learning_engine is not None:
            try:
                admin_action = "approved" if edit_distance == 0.0 else "edited"
                self.learning_engine.record_review(
                    question_id=f"escalation_{escalation.id}",
                    confidence=escalation.confidence_score,
                    admin_action=admin_action,
                    routing_action=escalation.routing_action,
                    metadata={
                        "channel": escalation.channel,
                        "staff_id": staff_id,
                        "edit_distance": edit_distance,
                    },
                )
            except Exception:
                logger.exception(
                    "Learning engine error for escalation %d", escalation_id
                )
        else:
            logger.debug(
                "No learning engine configured, skipping for escalation %d",
                escalation_id,
            )

        return updated

    async def retry_delivery(self, escalation_id: int) -> Escalation:
        """Retry a saved non-web staff response within the configured budget."""
        lock = await self._acquire_delivery_lock(escalation_id)
        try:
            escalation = await self.repository.get_by_id(escalation_id)
            if escalation is None:
                raise EscalationNotFoundError(f"Escalation {escalation_id} not found")
            return await self._retry_saved_delivery(escalation)
        finally:
            await self._release_delivery_lock(escalation_id, lock)

    async def _retry_saved_delivery(self, escalation: Escalation) -> Escalation:
        """Retry a loaded escalation while its per-case lock is held."""
        if escalation.channel == "web":
            return escalation
        if escalation.delivery_status == EscalationDeliveryStatus.DELIVERED:
            return escalation
        if not str(escalation.staff_answer or "").strip():
            raise EscalationNotRespondedError(
                f"Escalation {escalation.id} has no saved staff answer"
            )
        return await self._attempt_delivery(escalation, escalation.staff_answer)

    async def _attempt_delivery(
        self,
        escalation: Escalation,
        staff_answer: str,
        *,
        channel: str | None = None,
    ) -> Escalation:
        """Attempt one delivery after durably recording its pending state."""
        channel = str(channel or escalation.channel)
        if channel == "web":
            if self.response_delivery is None:
                return escalation
            try:
                delivered = await self.response_delivery.deliver(
                    escalation, staff_answer
                )
            except Exception:
                ESCALATION_DELIVERY.labels(channel=channel, outcome="error").inc()
                logger.exception("Delivery error for escalation %d", escalation.id)
            else:
                outcome = "success" if delivered else "failed"
                ESCALATION_DELIVERY.labels(channel=channel, outcome=outcome).inc()
            return escalation

        max_retries = max(
            0,
            int(getattr(self.settings, "ESCALATION_DELIVERY_MAX_RETRIES", 3)),
        )
        max_attempts = 1 + max_retries
        attempts = max(0, int(escalation.delivery_attempts or 0))
        if attempts >= max_attempts:
            raise EscalationInvalidStateError(
                f"Escalation {escalation.id} delivery retry limit reached"
            )

        attempt_number = attempts + 1
        attempted_at = datetime.now(timezone.utc)
        pending = await self.repository.update(
            escalation.id,
            EscalationUpdate(
                delivery_status=EscalationDeliveryStatus.PENDING,
                delivery_error="",
                delivery_attempts=attempt_number,
                last_delivery_at=attempted_at,
            ),
        )
        if self.response_delivery is None:
            ESCALATION_DELIVERY.labels(channel=channel, outcome="failed").inc()
            final = await self.repository.update(
                escalation.id,
                EscalationUpdate(
                    delivery_status=EscalationDeliveryStatus.FAILED,
                    delivery_error="Response delivery is not configured",
                    delivery_attempts=attempt_number,
                    last_delivery_at=attempted_at,
                ),
            )
            await self._publish_update(final)
            return final

        try:
            delivered = await self.response_delivery.deliver(pending, staff_answer)
        except Exception:
            ESCALATION_DELIVERY.labels(channel=channel, outcome="error").inc()
            logger.exception("Delivery error for escalation %d", escalation.id)
            final = await self.repository.update(
                escalation.id,
                EscalationUpdate(
                    delivery_status=EscalationDeliveryStatus.FAILED,
                    delivery_error="Exception during delivery",
                    delivery_attempts=attempt_number,
                    last_delivery_at=attempted_at,
                ),
            )
        else:
            if delivered:
                ESCALATION_DELIVERY.labels(channel=channel, outcome="success").inc()
                final = await self.repository.update(
                    escalation.id,
                    EscalationUpdate(
                        delivery_status=EscalationDeliveryStatus.DELIVERED,
                        delivery_error="",
                        delivery_attempts=attempt_number,
                        last_delivery_at=attempted_at,
                    ),
                )
            else:
                ESCALATION_DELIVERY.labels(channel=channel, outcome="failed").inc()
                logger.warning("Delivery failed for escalation %d", escalation.id)
                final = await self.repository.update(
                    escalation.id,
                    EscalationUpdate(
                        delivery_status=EscalationDeliveryStatus.FAILED,
                        delivery_error="Delivery returned False",
                        delivery_attempts=attempt_number,
                        last_delivery_at=attempted_at,
                    ),
                )
        await self._publish_update(final)
        return final

    # ------------------------------------------------------------------
    # Staff Rating
    # ------------------------------------------------------------------

    async def record_staff_answer_rating(
        self,
        escalation: Escalation,
        rating: int,
        rater_id: str,
        trusted: bool,
    ) -> bool:
        """Persist staff-answer rating and optionally feed trusted learning."""
        normalized_rating = 1 if int(rating) > 0 else 0
        updated = await self.repository.update_rating(
            escalation.message_id,
            normalized_rating,
        )
        if not updated:
            return False

        if trusted and self.feedback_orchestrator is not None:
            try:
                from app.services.escalation.feedback_orchestrator import (
                    StaffRatingSignal,
                )

                signal = StaffRatingSignal(
                    message_id=escalation.message_id,
                    escalation_id=escalation.id,
                    rater_id=str(rater_id),
                    confidence_score=escalation.confidence_score,
                    edit_distance=escalation.edit_distance or 0.0,
                    user_rating=normalized_rating,
                    routing_action=escalation.routing_action,
                    channel=escalation.channel,
                    trusted=True,
                    sources=escalation.sources,
                )
                self.feedback_orchestrator.record_user_rating(signal)
            except Exception:
                logger.exception(
                    "Feedback orchestrator failure for message %s",
                    escalation.message_id,
                )

        return True

    # ------------------------------------------------------------------
    # Auto-Reaction Escalation Reversal
    # ------------------------------------------------------------------

    async def auto_close_reaction_escalation(
        self,
        message_id: str,
        reason: str = "reaction_reversed",
    ) -> bool:
        """Close a pending auto-reaction escalation when user reverses feedback."""
        escalation = await self.repository.get_by_message_id(message_id)
        if escalation is None:
            return False

        routing_reason = str(escalation.routing_reason or "").strip().lower()
        is_auto_reaction = routing_reason.startswith(
            AUTO_REACTION_ESCALATION_REASON_PREFIX
        ) or ("user reported incorrect answer" in routing_reason)
        if not is_auto_reaction:
            return False

        # Only auto-close unclaimed pending escalations.
        if escalation.status != EscalationStatus.PENDING:
            return False
        if escalation.staff_id or escalation.responded_at:
            return False

        now = datetime.now(timezone.utc)
        updated = await self.repository.update(
            escalation.id,
            EscalationUpdate(
                status=EscalationStatus.CLOSED,
                closed_at=now,
            ),
        )
        await self._publish_update(updated)
        ESCALATION_LIFECYCLE.labels(action="auto_closed").inc()
        logger.info(
            "Auto-closed reaction escalation",
            extra={
                "message_id": message_id,
                "escalation_id": escalation.id,
                "reason": reason,
            },
        )
        return True

    # ------------------------------------------------------------------
    # Generate FAQ
    # ------------------------------------------------------------------

    async def generate_faq_from_escalation(
        self,
        escalation_id: int,
        question: str,
        answer: str,
        category: str = "General",
        protocol: Optional[Literal["multisig_v1", "bisq_easy", "musig", "all"]] = None,
        force: bool = False,
    ) -> Dict[str, Any]:
        """Create auto-verified FAQ from resolved escalation."""
        from datetime import datetime, timezone

        from app.models.faq import FAQItem

        escalation = await self.repository.get_by_id(escalation_id)
        if escalation is None:
            raise EscalationNotFoundError(f"Escalation {escalation_id} not found")

        if self.faq_service is None:
            raise RuntimeError("FAQ service not configured")

        if escalation.status not in (
            EscalationStatus.RESPONDED,
            EscalationStatus.CLOSED,
        ):
            raise EscalationNotRespondedError(
                f"Escalation {escalation_id} has not been responded to"
            )

        if not force:
            similar_faqs = await find_similar_faqs(
                self.rag_service,
                question=question,
            )
            if similar_faqs:
                raise DuplicateFAQError(
                    f"Cannot create FAQ: {len(similar_faqs)} similar FAQ(s) already exist",
                    similar_faqs=similar_faqs,
                )

        faq_item = FAQItem(
            question=question,
            answer=answer,
            category=category,
            protocol=protocol,
            source="Escalation",
            verified=True,
            verified_at=datetime.now(timezone.utc),
        )

        faq = self.faq_service.add_faq(faq_item)
        faq_id = getattr(faq, "id", str(faq))

        await self.repository.update(
            escalation_id,
            EscalationUpdate(generated_faq_id=str(faq_id)),
        )

        return {
            "faq_id": str(faq_id),
            "question": question,
            "answer": answer,
        }

    # ------------------------------------------------------------------
    # Close
    # ------------------------------------------------------------------

    async def close_escalation(self, escalation_id: int) -> Escalation:
        """Close an escalation."""
        escalation = await self.repository.get_by_id(escalation_id)
        if escalation is None:
            raise EscalationNotFoundError(f"Escalation {escalation_id} not found")

        now = datetime.now(timezone.utc)
        ESCALATION_LIFECYCLE.labels(action="closed").inc()
        updated = await self.repository.update(
            escalation_id,
            EscalationUpdate(
                status=EscalationStatus.CLOSED,
                closed_at=now,
            ),
        )
        await self._publish_update(updated)
        return updated

    async def prioritize_escalation(
        self,
        escalation_id: int,
        priority: EscalationPriority,
    ) -> Escalation:
        """Update escalation priority."""
        escalation = await self.repository.get_by_id(escalation_id)
        if escalation is None:
            raise EscalationNotFoundError(f"Escalation {escalation_id} not found")
        if escalation.status == EscalationStatus.CLOSED:
            raise EscalationClosedError(f"Escalation {escalation_id} is closed")
        return await self.repository.update(
            escalation_id,
            EscalationUpdate(priority=priority),
        )

    # ------------------------------------------------------------------
    # List / Query
    # ------------------------------------------------------------------

    async def list_escalations(
        self,
        status: Optional[EscalationStatus] = None,
        channel: Optional[str] = None,
        priority=None,
        search: Optional[str] = None,
        staff_id: Optional[str] = None,
        limit: int = 20,
        offset: int = 0,
    ) -> EscalationListResponse:
        """List escalations with optional filters."""
        filters = EscalationFilters(
            status=status,
            channel=channel,
            priority=priority,
            search=search,
            staff_id=staff_id,
            limit=limit,
            offset=offset,
        )
        escalations, total = await self.repository.list_escalations(filters)
        return EscalationListResponse(
            escalations=escalations,
            total=total,
            limit=limit,
            offset=offset,
        )

    async def get_escalation_counts(self) -> EscalationCountsResponse:
        """Get counts by status for dashboard badges."""
        return await self.repository.get_counts()

    # ------------------------------------------------------------------
    # User polling
    # ------------------------------------------------------------------

    async def get_user_response(self, message_id: str) -> Optional[UserPollResponse]:
        """Get staff response for web polling."""
        escalation = await self.repository.get_by_message_id(message_id)
        if escalation is None:
            return None

        if escalation.status in (
            EscalationStatus.RESPONDED,
            EscalationStatus.CLOSED,
        ):
            return UserPollResponse(
                status="resolved",
                staff_answer=escalation.staff_answer,
                responded_at=escalation.responded_at,
            )

        return UserPollResponse(status="pending")

    # ------------------------------------------------------------------
    # Maintenance
    # ------------------------------------------------------------------

    async def auto_close_stale(self) -> int:
        """Close escalations older than configured hours."""
        hours = getattr(self.settings, "ESCALATION_AUTO_CLOSE_HOURS", 72)
        threshold = datetime.now(timezone.utc) - timedelta(hours=hours)
        count = await self.repository.close_stale(threshold)
        if count:
            logger.info("Auto-closed %d stale escalations", count)
        return count

    async def purge_retention(self) -> int:
        """Delete old closed/responded escalations."""
        days = min(
            getattr(self.settings, "ESCALATION_RETENTION_DAYS", 30),
            getattr(self.settings, "DATA_RETENTION_DAYS", 30),
        )
        threshold = datetime.now(timezone.utc) - timedelta(days=days)
        count = await self.repository.purge_old(threshold)
        if count:
            logger.info("Purged %d old escalations", count)
        return count

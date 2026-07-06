"""Channel gateway for centralized message routing.

Routes messages through pre/post hooks and RAG service.
"""

import inspect
import logging
import time
import uuid
from typing import Any, AsyncIterator, Dict, List, Optional, Union

from app.channels.hooks import PostProcessingHook, PreProcessingHook
from app.channels.models import (
    ErrorCode,
    GatewayError,
    IncomingMessage,
    OutgoingMessage,
)
from app.channels.rag_query import (
    query_with_channel_context,
    stream_query_with_channel_context,
)
from app.channels.response_builder import build_metadata, build_sources
from app.channels.response_dispatcher import ChannelResponseDispatcher
from app.channels.runtime import RAGServiceProtocol
from app.channels.security import ErrorFactory

logger = logging.getLogger(__name__)


# =============================================================================
# Channel Gateway
# =============================================================================


class ChannelGateway:
    """Central message router for multi-channel RAG system.

    Processes messages through a pipeline:
    1. Pre-processing hooks (rate limit, validation, etc.)
    2. RAG query execution
    3. Post-processing hooks (PII filter, metrics, etc.)

    Example:
        gateway = ChannelGateway(rag_service=rag)
        gateway.register_pre_hook(RateLimitHook())
        gateway.register_post_hook(PIIFilterHook())

        result = await gateway.process_message(incoming_message)
        if isinstance(result, OutgoingMessage):
            await channel.send(result)
        else:
            await channel.send_error(result)
    """

    def __init__(
        self,
        rag_service: RAGServiceProtocol,
        pre_hooks: Optional[List[PreProcessingHook]] = None,
        post_hooks: Optional[List[PostProcessingHook]] = None,
        ingress_context_service: Optional[Any] = None,
        response_enricher: Optional[Any] = None,
    ):
        """Initialize gateway.

        Args:
            rag_service: RAG service for query processing.
            pre_hooks: Optional list of pre-processing hooks.
            post_hooks: Optional list of post-processing hooks.
        """
        self.rag_service = rag_service
        self._pre_hooks: List[PreProcessingHook] = sorted(
            pre_hooks or [], key=lambda h: h.priority
        )
        self._post_hooks: List[PostProcessingHook] = sorted(
            post_hooks or [], key=lambda h: h.priority
        )
        self._ingress_context_service = ingress_context_service
        self.response_enricher = response_enricher

    async def process_message(
        self, message: IncomingMessage
    ) -> Union[OutgoingMessage, GatewayError]:
        """Process message through complete gateway pipeline.

        Args:
            message: Incoming message to process.

        Returns:
            OutgoingMessage on success, GatewayError on failure.
        """
        start_time = time.time()
        hooks_executed: List[str] = []

        # Validate input
        if message is None:
            return ErrorFactory.invalid_message("Message cannot be None")

        try:
            message = await self._prepare_message(message)

            # Execute pre-processing hooks
            for hook in self._pre_hooks:
                if hook.should_skip(message):
                    logger.debug(f"Skipping pre-hook '{hook.name}' (in bypass list)")
                    continue

                try:
                    result = await hook.execute(message)
                    hooks_executed.append(hook.name)

                    if result is not None:
                        # Hook returned error, abort processing
                        logger.info(
                            f"Pre-hook '{hook.name}' blocked processing: {result.error_code}"
                        )
                        return result

                except Exception:
                    # Hook exception - log and continue
                    logger.exception(f"Pre-hook '{hook.name}' raised exception")
                    # Continue processing despite hook failure

            # Execute RAG query
            try:
                chat_history = None
                if message.chat_history:
                    chat_history = [
                        {"role": msg.role, "content": msg.content}
                        for msg in message.chat_history
                    ]

                rag_response = await query_with_channel_context(
                    rag_service=self.rag_service,
                    question=message.question,
                    chat_history=chat_history,
                    detection_source=message.channel.value,
                    language_hint=getattr(
                        getattr(message, "locale_context", None),
                        "language_code",
                        None,
                    ),
                    language_hint_confidence=getattr(
                        getattr(message, "locale_context", None),
                        "confidence",
                        None,
                    ),
                )
                rag_response = await self._enrich_response(message, rag_response)

            except Exception as e:
                logger.exception("RAG service error")
                return ErrorFactory.rag_service_error(str(e))

            # Build outgoing message
            processing_time = (time.time() - start_time) * 1000
            outgoing = self._build_outgoing_message(
                incoming=message,
                rag_response=rag_response,
                processing_time_ms=processing_time,
                hooks_executed=hooks_executed.copy(),
            )

            # Execute post-processing hooks
            for post_hook in self._post_hooks:
                if post_hook.should_skip(message):
                    logger.debug(
                        f"Skipping post-hook '{post_hook.name}' (in bypass list)"
                    )
                    continue

                try:
                    result = await post_hook.execute(message, outgoing)
                    hooks_executed.append(post_hook.name)
                    outgoing.metadata.hooks_executed.append(post_hook.name)

                    if result is not None:
                        # Hook returned error, abort
                        logger.info(
                            f"Post-hook '{post_hook.name}' blocked response: {result.error_code}"
                        )
                        return result

                except Exception:
                    # Hook exception - log and continue
                    logger.exception(f"Post-hook '{post_hook.name}' raised exception")

            # Update final processing time
            outgoing.metadata.processing_time_ms = (time.time() - start_time) * 1000

            return outgoing

        except Exception as e:
            logger.exception(f"Gateway processing error: {e}")
            return GatewayError(
                error_code=ErrorCode.INTERNAL_ERROR,
                error_message="Internal processing error",
                details={"reason": "internal_gateway_error"},
                recoverable=True,
            )

    async def stream_message(
        self, message: IncomingMessage
    ) -> AsyncIterator[Dict[str, Any]]:
        """Process a message and stream token events before final output."""
        start_time = time.time()
        hooks_executed: List[str] = []

        if message is None:
            yield {
                "event": "error",
                "data": ErrorFactory.invalid_message("Message cannot be None"),
            }
            return

        try:
            message = await self._prepare_message(message)

            for hook in self._pre_hooks:
                if hook.should_skip(message):
                    logger.debug(f"Skipping pre-hook '{hook.name}' (in bypass list)")
                    continue

                try:
                    result = await hook.execute(message)
                    hooks_executed.append(hook.name)
                    if result is not None:
                        logger.info(
                            f"Pre-hook '{hook.name}' blocked streaming: {result.error_code}"
                        )
                        yield {"event": "error", "data": result}
                        return
                except Exception:
                    logger.exception(f"Pre-hook '{hook.name}' raised exception")

            try:
                chat_history = None
                if message.chat_history:
                    chat_history = [
                        {"role": msg.role, "content": msg.content}
                        for msg in message.chat_history
                    ]

                rag_response: Dict[str, Any] | None = None
                pending_tokens: List[Dict[str, Any]] = []
                async for event in stream_query_with_channel_context(
                    rag_service=self.rag_service,
                    question=message.question,
                    chat_history=chat_history,
                    detection_source=message.channel.value,
                    language_hint=getattr(
                        getattr(message, "locale_context", None),
                        "language_code",
                        None,
                    ),
                    language_hint_confidence=getattr(
                        getattr(message, "locale_context", None),
                        "confidence",
                        None,
                    ),
                ):
                    event_name = event.get("event")
                    if event_name == "token":
                        pending_tokens.append(event)
                    elif event_name == "final":
                        raw_data = event.get("data")
                        rag_response = raw_data if isinstance(raw_data, dict) else {}
                    elif event_name == "error":
                        raise RuntimeError(str(event.get("data") or "stream error"))

                if rag_response is None:
                    raise RuntimeError("Streaming RAG query ended without final data")
                rag_response = await self._enrich_response(message, rag_response)
            except Exception as e:
                logger.exception("Streaming RAG service error")
                yield {"event": "error", "data": ErrorFactory.rag_service_error(str(e))}
                return

            processing_time = (time.time() - start_time) * 1000
            outgoing = self._build_outgoing_message(
                incoming=message,
                rag_response=rag_response,
                processing_time_ms=processing_time,
                hooks_executed=hooks_executed.copy(),
            )

            for post_hook in self._post_hooks:
                if post_hook.should_skip(message):
                    logger.debug(
                        f"Skipping post-hook '{post_hook.name}' (in bypass list)"
                    )
                    continue

                try:
                    result = await post_hook.execute(message, outgoing)
                    hooks_executed.append(post_hook.name)
                    outgoing.metadata.hooks_executed.append(post_hook.name)
                    if result is not None:
                        logger.info(
                            f"Post-hook '{post_hook.name}' blocked streaming response: {result.error_code}"
                        )
                        yield {"event": "error", "data": result}
                        return
                except Exception:
                    logger.exception(f"Post-hook '{post_hook.name}' raised exception")

            outgoing.metadata.processing_time_ms = (time.time() - start_time) * 1000
            if ChannelResponseDispatcher.should_autosend_response(outgoing):
                for event in pending_tokens:
                    yield event
            elif pending_tokens:
                logger.info(
                    "Suppressing streamed draft tokens for review-routed response",
                    extra={
                        "message_id": message.message_id,
                        "routing_action": getattr(
                            outgoing.metadata,
                            "routing_action",
                            None,
                        ),
                    },
                )
            yield {"event": "final", "data": outgoing}

        except Exception as e:
            logger.exception(f"Gateway streaming error: {e}")
            yield {
                "event": "error",
                "data": GatewayError(
                    error_code=ErrorCode.INTERNAL_ERROR,
                    error_message="Internal streaming error",
                    details={"reason": "internal_gateway_error"},
                    recoverable=True,
                ),
            }

    async def _prepare_message(self, message: IncomingMessage) -> IncomingMessage:
        if (
            getattr(message, "locale_context", None) is not None
            or getattr(message, "classification", None) is not None
        ):
            return message

        service = self._ingress_context_service
        if (
            service is None
            or inspect.getattr_static(service, "prepare_incoming", None) is None
        ):
            return message
        prepare = getattr(service, "prepare_incoming", None) if service else None
        if not callable(prepare):
            return message
        prepared = prepare(message, thread_language_hint=None)
        if inspect.isawaitable(prepared):
            prepared = await prepared
        return prepared

    async def _enrich_response(
        self,
        message: IncomingMessage,
        rag_response: Dict[str, Any],
    ) -> Dict[str, Any]:
        enricher = self.response_enricher
        if enricher is None:
            return rag_response
        enriched = enricher(message, rag_response)
        if inspect.isawaitable(enriched):
            enriched = await enriched
        return dict(enriched)

    def register_pre_hook(self, hook: PreProcessingHook) -> None:
        """Register pre-processing hook.

        Hooks are sorted by priority (lower = earlier).

        Args:
            hook: Hook to register.
        """
        self._pre_hooks.append(hook)
        self._pre_hooks.sort(key=lambda h: h.priority)
        logger.info(f"Registered pre-hook '{hook.name}' with priority {hook.priority}")

    def register_post_hook(self, hook: PostProcessingHook) -> None:
        """Register post-processing hook.

        Hooks are sorted by priority (lower = earlier).

        Args:
            hook: Hook to register.
        """
        self._post_hooks.append(hook)
        self._post_hooks.sort(key=lambda h: h.priority)
        logger.info(f"Registered post-hook '{hook.name}' with priority {hook.priority}")

    def get_hook_info(self) -> Dict[str, List[Dict[str, Any]]]:
        """Get information about registered hooks.

        Returns:
            Dictionary with pre_hooks and post_hooks info.
        """
        return {
            "pre_hooks": [
                {"name": h.name, "priority": h.priority} for h in self._pre_hooks
            ],
            "post_hooks": [
                {"name": h.name, "priority": h.priority} for h in self._post_hooks
            ],
        }

    def _build_outgoing_message(
        self,
        incoming: IncomingMessage,
        rag_response: Dict[str, Any],
        processing_time_ms: float,
        hooks_executed: List[str],
    ) -> OutgoingMessage:
        """Build outgoing message from RAG response.

        Args:
            incoming: Original incoming message.
            rag_response: Response from RAG service.
            processing_time_ms: Processing time in milliseconds.
            hooks_executed: List of executed hook names.

        Returns:
            OutgoingMessage ready for sending.
        """
        sources = build_sources(rag_response)
        metadata = build_metadata(
            rag_response=rag_response,
            processing_time_ms=processing_time_ms,
            hooks_executed=hooks_executed,
        )

        return OutgoingMessage(
            message_id=str(uuid.uuid4()),
            in_reply_to=incoming.message_id,
            channel=incoming.channel,
            answer=rag_response.get("answer", ""),
            sources=sources,
            user=incoming.user,
            metadata=metadata,
            original_question=incoming.question,
            suggested_questions=rag_response.get("suggested_questions"),
            requires_human=rag_response.get("requires_human", False),
        )

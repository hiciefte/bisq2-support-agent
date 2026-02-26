"""Channel gateway for centralized message routing.

Routes messages through pre/post hooks and RAG service.
"""

import logging
import time
import uuid
from typing import Any, Dict, List, Optional, Union

from app.channels.hooks import PostProcessingHook, PreProcessingHook
from app.channels.models import (
    ErrorCode,
    GatewayError,
    IncomingMessage,
    OutgoingMessage,
)
from app.channels.rag_query import query_with_channel_context
from app.channels.response_builder import build_metadata, build_sources
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
                )

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

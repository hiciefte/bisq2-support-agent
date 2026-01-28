"""
Resilient Retriever with automatic fallback capability.

This module provides a retriever wrapper that automatically falls back
to a secondary retriever when the primary retriever fails.

Features:
- Automatic fallback on primary retriever failure
- Health monitoring for both retrievers
- Metrics and logging for fallback events
- Manual reset to primary capability
"""

import logging
import time
from typing import Any, Dict, List, Optional

from app.services.rag.interfaces import (
    ResilientRetrieverProtocol,
    RetrievedDocument,
    RetrieverProtocol,
)

logger = logging.getLogger(__name__)


class ResilientRetriever(ResilientRetrieverProtocol):
    """Retriever with automatic fallback to secondary retriever.

    This wrapper provides resilience by automatically switching to a fallback
    retriever when the primary fails. It monitors health of both retrievers
    and can automatically reset to primary when it becomes healthy again.

    Attributes:
        primary: Primary retriever (e.g., Qdrant)
        fallback: Fallback retriever (e.g., ChromaDB)
        auto_reset: Whether to automatically try resetting to primary
        reset_interval: Seconds between reset attempts
    """

    def __init__(
        self,
        primary: RetrieverProtocol,
        fallback: RetrieverProtocol,
        auto_reset: bool = True,
        reset_interval: int = 300,  # 5 minutes
    ):
        """Initialize the resilient retriever.

        Args:
            primary: Primary retriever to use when healthy
            fallback: Fallback retriever when primary fails
            auto_reset: If True, periodically try to reset to primary
            reset_interval: Seconds between auto-reset attempts
        """
        self._primary = primary
        self._fallback = fallback
        self._using_fallback = False
        self._auto_reset = auto_reset
        self._reset_interval = reset_interval
        self._last_reset_attempt = 0.0
        self._fallback_count = 0
        self._primary_failures = 0

    @property
    def primary_retriever(self) -> RetrieverProtocol:
        """Get the primary retriever."""
        return self._primary

    @property
    def fallback_retriever(self) -> RetrieverProtocol:
        """Get the fallback retriever."""
        return self._fallback

    @property
    def using_fallback(self) -> bool:
        """Check if currently using fallback retriever."""
        return self._using_fallback

    def _get_active_retriever(self) -> RetrieverProtocol:
        """Get the currently active retriever.

        Also handles auto-reset logic if enabled.

        Returns:
            The active retriever (primary or fallback)
        """
        if self._using_fallback and self._auto_reset:
            # Check if we should try resetting to primary
            now = time.time()
            if now - self._last_reset_attempt >= self._reset_interval:
                self._last_reset_attempt = now
                if self.reset_to_primary():
                    logger.info("Successfully reset to primary retriever")

        return self._fallback if self._using_fallback else self._primary

    def _switch_to_fallback(self, error: Exception) -> None:
        """Switch to fallback retriever after primary failure.

        Args:
            error: The error that caused the switch
        """
        if not self._using_fallback:
            self._using_fallback = True
            self._fallback_count += 1
            self._primary_failures += 1
            logger.warning(
                f"Switching to fallback retriever due to primary failure: {error}. "
                f"Total fallbacks: {self._fallback_count}"
            )

    def reset_to_primary(self) -> bool:
        """Attempt to reset to primary retriever.

        Returns:
            True if successfully reset to primary, False if primary unhealthy
        """
        try:
            if self._primary.health_check():
                self._using_fallback = False
                logger.info("Reset to primary retriever successful")
                return True
            else:
                logger.debug(
                    "Primary retriever health check failed, staying on fallback"
                )
                return False
        except Exception as e:
            logger.warning(f"Error during primary health check: {e}")
            return False

    def health_check(self) -> bool:
        """Check if at least one retriever is healthy.

        Returns:
            True if any retriever is healthy, False otherwise
        """
        primary_healthy = False
        fallback_healthy = False

        try:
            primary_healthy = self._primary.health_check()
        except Exception as e:
            logger.debug(f"Primary health check failed: {e}")

        try:
            fallback_healthy = self._fallback.health_check()
        except Exception as e:
            logger.debug(f"Fallback health check failed: {e}")

        return primary_healthy or fallback_healthy

    def retrieve(
        self,
        query: str,
        k: int = 10,
        filter_dict: Optional[Dict[str, Any]] = None,
    ) -> List[RetrievedDocument]:
        """Retrieve documents with automatic fallback.

        Args:
            query: Search query text
            k: Maximum number of documents to retrieve
            filter_dict: Optional metadata filters

        Returns:
            List of RetrievedDocument objects
        """
        retriever = self._get_active_retriever()

        try:
            docs = retriever.retrieve(query, k, filter_dict)
            # If using primary and it succeeds, reset failure count
            if not self._using_fallback:
                self._primary_failures = 0
            return docs
        except Exception as e:
            if not self._using_fallback:
                # Primary failed, switch to fallback
                self._switch_to_fallback(e)
                try:
                    return self._fallback.retrieve(query, k, filter_dict)
                except Exception as fallback_error:
                    logger.error(
                        f"Both primary and fallback retrievers failed: {fallback_error}"
                    )
                    return []
            else:
                # Already on fallback, log and return empty
                logger.error(f"Fallback retriever failed: {e}")
                return []

    def retrieve_with_scores(
        self,
        query: str,
        k: int = 10,
        filter_dict: Optional[Dict[str, Any]] = None,
    ) -> List[RetrievedDocument]:
        """Retrieve documents with scores and automatic fallback.

        Args:
            query: Search query text
            k: Maximum number of documents to retrieve
            filter_dict: Optional metadata filters

        Returns:
            List of RetrievedDocument objects with scores
        """
        retriever = self._get_active_retriever()

        try:
            docs = retriever.retrieve_with_scores(query, k, filter_dict)
            if not self._using_fallback:
                self._primary_failures = 0
            return docs
        except Exception as e:
            if not self._using_fallback:
                self._switch_to_fallback(e)
                try:
                    return self._fallback.retrieve_with_scores(query, k, filter_dict)
                except Exception as fallback_error:
                    logger.error(
                        f"Both primary and fallback retrievers failed: {fallback_error}"
                    )
                    return []
            else:
                logger.error(f"Fallback retriever failed: {e}")
                return []

    def get_status(self) -> Dict[str, Any]:
        """Get the current status of the resilient retriever.

        Returns:
            Dictionary with status information
        """
        primary_healthy = False
        fallback_healthy = False

        try:
            primary_healthy = self._primary.health_check()
        except Exception:
            pass

        try:
            fallback_healthy = self._fallback.health_check()
        except Exception:
            pass

        return {
            "using_fallback": self._using_fallback,
            "primary_healthy": primary_healthy,
            "fallback_healthy": fallback_healthy,
            "fallback_count": self._fallback_count,
            "primary_failures": self._primary_failures,
            "auto_reset_enabled": self._auto_reset,
            "reset_interval_seconds": self._reset_interval,
        }

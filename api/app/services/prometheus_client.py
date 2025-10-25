"""
Prometheus client service for querying metrics.

This service provides a clean interface for querying Prometheus metrics
used throughout the application, particularly for dashboard analytics.
"""

import asyncio
import logging
import math
from typing import Any, Dict, Optional

import httpx
from app.core.config import Settings

logger = logging.getLogger(__name__)


class PrometheusClient:
    """Client for querying Prometheus metrics."""

    def __init__(self, settings: Settings):
        """Initialize the Prometheus client.

        Args:
            settings: Application settings containing Prometheus URL
        """
        self.prometheus_url = settings.PROMETHEUS_URL
        self.timeout = 10.0  # 10 second timeout for Prometheus queries
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create shared HTTP client for connection pooling.

        Returns:
            Shared AsyncClient instance for efficient connection reuse
        """
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.prometheus_url, timeout=self.timeout
            )
        return self._client

    async def close(self) -> None:
        """Close the shared HTTP client and release resources."""
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def query(self, promql: str) -> Optional[Dict[str, Any]]:
        """Execute a PromQL query against Prometheus.

        Args:
            promql: The PromQL query string

        Returns:
            Query result as a dictionary, or None if query fails

        Example:
            >>> result = await client.query('up')
            >>> print(result['data']['result'])
        """
        try:
            client = await self._get_client()
            response = await client.get("/api/v1/query", params={"query": promql})
            response.raise_for_status()
            data = response.json()

            if data.get("status") != "success":
                logger.error(f"Prometheus query failed: {data}")
                return None

            return data
        except httpx.TimeoutException:
            logger.warning(f"Prometheus query timed out: {promql}")
            return None
        except httpx.HTTPError:
            logger.exception("Prometheus HTTP error")
            return None
        except Exception:
            logger.exception("Unexpected error querying Prometheus")
            return None

    async def get_average_response_time(
        self, window_hours: int = 1, percentile: Optional[float] = None
    ) -> Optional[float]:
        """Get response time from Prometheus metrics.

        Calculates either the average (mean) or a percentile response time
        over the specified time window using histogram metrics.

        Args:
            window_hours: Time window in hours for the query (default: 1)
            percentile: If specified, return this percentile (e.g., 0.95 for P95)
                       If None, return the mean (average)

        Returns:
            Response time in seconds, or None if unavailable

        Examples:
            >>> # Get average over last 7 days
            >>> await client.get_average_response_time(window_hours=168)
            >>> # Get P95 over last 24 hours
            >>> await client.get_average_response_time(window_hours=24, percentile=0.95)
        """
        if percentile:
            # P95/P99 query using histogram buckets
            # histogram_quantile calculates the specified percentile from bucket data
            promql = (
                f"histogram_quantile({percentile}, "
                f"sum(rate(bisq_query_response_time_seconds_bucket[{window_hours}h])) by (le))"
            )
            metric_type = f"P{int(percentile * 100)}"
        else:
            # Mean (average) query using histogram sum/count
            # rate() calculates per-second average rate over time range
            # sum() aggregates across all label sets for accurate total
            promql = (
                f"sum(rate(bisq_query_response_time_seconds_sum[{window_hours}h]))"
                " / "
                f"sum(rate(bisq_query_response_time_seconds_count[{window_hours}h]))"
            )
            metric_type = "average"

        result = await self.query(promql)
        if not result or not result.get("data", {}).get("result"):
            logger.debug(
                f"No {metric_type} response time data available in Prometheus for {window_hours}h window"
            )
            return None

        # Extract the value from the result
        try:
            value = float(result["data"]["result"][0]["value"][1])
            # Check if value is finite (not NaN or infinity)
            if not math.isfinite(value):
                logger.debug(
                    f"Prometheus returned non-finite value for {metric_type} response time: {value}"
                )
                return None
            logger.info(
                f"Retrieved {metric_type} response time from Prometheus ({window_hours}h window): {value:.2f}s"
            )
            return value
        except (IndexError, KeyError, ValueError, TypeError) as e:
            logger.warning(
                f"Failed to parse {metric_type} response time from Prometheus: {e}"
            )
            return None

    async def get_total_query_count(self) -> Optional[int]:
        """Get total query count from Prometheus.

        Returns:
            Total number of queries processed, or None if unavailable
        """
        # sum() aggregates the counter across all label sets
        promql = "sum(bisq_queries_total)"

        result = await self.query(promql)
        if not result or not result.get("data", {}).get("result"):
            logger.debug("No query count data available in Prometheus")
            return None

        try:
            value = int(float(result["data"]["result"][0]["value"][1]))
            logger.info(f"Retrieved total query count from Prometheus: {value}")
            return value
        except (IndexError, KeyError, ValueError, TypeError) as e:
            logger.warning(f"Failed to parse query count from Prometheus: {e}")
            return None

    async def get_response_time_trend(self, window_hours: int = 1) -> Optional[float]:
        """Calculate response time trend over time.

        Compares current average response time to previous period to
        calculate improvement or degradation.

        Args:
            window_hours: Hours for the time window (default: 1 hour)

        Returns:
            Trend value (negative = improvement, positive = degradation),
            or None if unavailable
        """
        # Get current period average (last window_hours)
        # sum() aggregates across all label sets for accurate total
        current_promql = (
            f"sum(rate(bisq_query_response_time_seconds_sum[{window_hours}h]))"
            " / "
            f"sum(rate(bisq_query_response_time_seconds_count[{window_hours}h]))"
        )

        # Get previous period average (window before current window)
        # offset pushes the time window back by the specified duration
        previous_promql = (
            f"sum(rate(bisq_query_response_time_seconds_sum[{window_hours}h] offset {window_hours}h))"
            " / "
            f"sum(rate(bisq_query_response_time_seconds_count[{window_hours}h] offset {window_hours}h))"
        )

        # Query both periods in parallel for better performance
        current_result, previous_result = await asyncio.gather(
            self.query(current_promql), self.query(previous_promql)
        )

        if not current_result or not previous_result:
            logger.debug("Insufficient data for response time trend calculation")
            return None

        try:
            current_data = current_result.get("data", {}).get("result", [])
            previous_data = previous_result.get("data", {}).get("result", [])

            if not current_data or not previous_data:
                return None

            current_time = float(current_data[0]["value"][1])
            previous_time = float(previous_data[0]["value"][1])

            # Check if values are finite (not NaN or infinity)
            if not math.isfinite(current_time) or not math.isfinite(previous_time):
                logger.debug(
                    f"Prometheus returned non-finite values for trend: current={current_time}, previous={previous_time}"
                )
                return None

            # Calculate difference (negative = faster, positive = slower)
            trend = current_time - previous_time
            logger.info(
                f"Response time trend: {trend:+.3f}s (current: {current_time:.3f}s, previous: {previous_time:.3f}s)"
            )
            return trend
        except (IndexError, KeyError, ValueError, TypeError) as e:
            logger.warning(f"Failed to calculate response time trend: {e}")
            return None

    async def health_check(self) -> bool:
        """Check if Prometheus is accessible and healthy.

        Returns:
            True if Prometheus is accessible, False otherwise
        """
        try:
            client = await self._get_client()
            response = await client.get("/-/healthy")
            return response.status_code == 200
        except httpx.HTTPError as e:
            logger.warning(f"Prometheus health check failed: {e}")
            return False

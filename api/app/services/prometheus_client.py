"""
Prometheus client service for querying metrics.

This service provides a clean interface for querying Prometheus metrics
used throughout the application, particularly for dashboard analytics.
"""

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
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(
                    f"{self.prometheus_url}/api/v1/query",
                    params={"query": promql},
                )
                response.raise_for_status()
                data = response.json()

                if data.get("status") != "success":
                    logger.error(f"Prometheus query failed: {data}")
                    return None

                return data
        except httpx.TimeoutException:
            logger.warning(f"Prometheus query timed out: {promql}")
            return None
        except httpx.HTTPError as e:
            logger.error(f"Prometheus HTTP error: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error querying Prometheus: {e}", exc_info=True)
            return None

    async def get_average_response_time(self) -> Optional[float]:
        """Get average response time from Prometheus metrics.

        Calculates the average response time over the last hour using
        the rate of sum/count from the response time histogram.

        Returns:
            Average response time in seconds, or None if unavailable
        """
        # Query for average response time using histogram metrics
        # rate() calculates per-second average rate over time range
        # sum() aggregates across all label sets for accurate total
        promql = (
            "sum(rate(bisq_query_response_time_seconds_sum[1h]))"
            " / "
            "sum(rate(bisq_query_response_time_seconds_count[1h]))"
        )

        result = await self.query(promql)
        if not result or not result.get("data", {}).get("result"):
            logger.debug("No response time data available in Prometheus")
            return None

        # Extract the value from the result
        try:
            value = float(result["data"]["result"][0]["value"][1])
            # Check if value is finite (not NaN or infinity)
            if not math.isfinite(value):
                logger.debug(
                    f"Prometheus returned non-finite value for response time: {value}"
                )
                return None
            logger.info(
                f"Retrieved average response time from Prometheus: {value:.2f}s"
            )
            return value
        except (IndexError, KeyError, ValueError, TypeError) as e:
            logger.warning(f"Failed to parse response time from Prometheus: {e}")
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

        current_result = await self.query(current_promql)
        previous_result = await self.query(previous_promql)

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
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{self.prometheus_url}/-/healthy")
                return response.status_code == 200
        except Exception as e:
            logger.warning(f"Prometheus health check failed: {e}")
            return False

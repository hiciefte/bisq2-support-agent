"""MCP live-data response reconciliation helpers."""

import re
from typing import Any, Dict, List, Optional

_TOOL_FAILURE_MARKERS = (
    "error:",
    "data unavailable",
    "service temporarily unavailable",
)


def extract_last_tool_result(
    tool_calls: Optional[List[Dict[str, Any]]],
    tool_name: str,
) -> str:
    """Return the most recent non-empty result for a given tool name."""
    if not tool_calls:
        return ""
    for call in reversed(tool_calls):
        if str(call.get("tool", "") or "").strip() != tool_name:
            continue
        result = str(call.get("result", "") or "").strip()
        if result:
            return result
    return ""


def strip_bracket_wrapper(text: str) -> str:
    value = str(text or "").strip()
    if value.startswith("[") and value.endswith("]") and len(value) >= 2:
        return value[1:-1].strip()
    return value


def live_data_tool_calls_failed(
    tool_calls: Optional[List[Dict[str, Any]]],
) -> bool:
    """Return True when a completed live-data tool call has no usable result."""
    if not tool_calls:
        return False
    for call in tool_calls:
        result = str(call.get("result", "") or "").strip()
        if not result:
            return True
        normalized = result.casefold()
        if any(marker in normalized for marker in _TOOL_FAILURE_MARKERS):
            return True
    return False


def reconcile_live_data_fallbacks(
    response_text: str,
    tool_calls: Optional[List[Dict[str, Any]]],
) -> str:
    """Prevent contradiction: successful/no-offer tool results vs fetch-failure text."""
    text = str(response_text or "").strip()
    if not text:
        return text

    def _strip_offer_unavailable_phrases(value: str) -> str:
        value = re.sub(
            r"(?i)i'm unable to fetch live offer data at the moment\.\s*",
            "",
            value,
            count=1,
        )
        value = re.sub(
            (
                r"(?i)please try again later or check directly in the bisq 2 application"
                r"(?: for current offers to buy btc with (?:euro|euros|eur))?\.\s*"
            ),
            "",
            value,
            count=1,
        )
        return value

    def _strip_price_unavailable_phrases(value: str) -> str:
        value = re.sub(
            r"(?i)i'm unable to fetch current market prices right now\.\s*",
            "",
            value,
            count=1,
        )
        value = re.sub(
            (
                r"(?i)please try again later or check directly in the bisq 2 application"
                r"(?: for current prices)?\.\s*"
            ),
            "",
            value,
            count=1,
        )
        return value

    offer_result = extract_last_tool_result(tool_calls, "get_offerbook")
    if offer_result:
        normalized_offer = strip_bracket_wrapper(offer_result)
        if normalized_offer.lower().startswith("no offers currently available"):
            stripped = _strip_offer_unavailable_phrases(text).strip()
            if stripped:
                text = stripped
            else:
                text = f"{normalized_offer}."
        elif offer_result.startswith("[LIVE OFFERBOOK]"):
            text = _strip_offer_unavailable_phrases(text).strip()

    price_result = extract_last_tool_result(tool_calls, "get_market_prices")
    if price_result:
        normalized_price = strip_bracket_wrapper(price_result)
        if normalized_price.lower().startswith("no price data available"):
            stripped = _strip_price_unavailable_phrases(text).strip()
            if stripped:
                text = stripped
            else:
                text = f"{normalized_price}."
        elif price_result.startswith("[LIVE MARKET PRICES]"):
            text = _strip_price_unavailable_phrases(text).strip()

    text = re.sub(r"\s{2,}", " ", text).strip()
    return text

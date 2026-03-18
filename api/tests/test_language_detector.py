import pytest
from app.services.translation.language_detector import LanguageDetector


@pytest.mark.asyncio
async def test_detect_with_metadata_german_price_question_avoids_english_heuristic():
    detector = LanguageDetector(
        local_backend="none",
        enable_llm_tiebreaker=False,
    )

    details = await detector.detect_with_metadata(
        "Wie ist der aktuell BTC Preis in Euro?"
    )

    assert details.language_code == "de"
    assert details.backend in {"lexical_hint", "hint_override"}


@pytest.mark.asyncio
async def test_detect_with_metadata_english_question_uses_english_heuristic():
    detector = LanguageDetector(
        local_backend="none",
        enable_llm_tiebreaker=False,
    )

    details = await detector.detect_with_metadata(
        "What is the current BTC price in EUR?"
    )

    assert details.language_code == "en"
    assert details.backend == "english_heuristic"

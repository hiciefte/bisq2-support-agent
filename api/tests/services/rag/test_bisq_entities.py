"""Tests for bisq_entities shared module."""

from app.services.rag.bisq_entities import (
    BISQ1_ENTITY_MAP,
    BISQ1_STRONG_KEYWORDS,
    BISQ2_ENTITY_MAP,
    BISQ2_STRONG_KEYWORDS,
    build_llm_entity_examples,
)


class TestEntityMaps:
    def test_bisq1_keys_all_lowercase(self):
        for key in BISQ1_ENTITY_MAP:
            assert key == key.lower(), f"Key '{key}' not lowercase"

    def test_bisq2_keys_all_lowercase(self):
        for key in BISQ2_ENTITY_MAP:
            assert key == key.lower(), f"Key '{key}' not lowercase"

    def test_bisq1_values_non_empty(self):
        for key, val in BISQ1_ENTITY_MAP.items():
            assert val.strip(), f"Empty value for key '{key}'"

    def test_bisq2_values_non_empty(self):
        for key, val in BISQ2_ENTITY_MAP.items():
            assert val.strip(), f"Empty value for key '{key}'"

    def test_no_duplicate_keys_across_maps(self):
        overlap = set(BISQ1_ENTITY_MAP) & set(BISQ2_ENTITY_MAP)
        assert not overlap, f"Duplicate keys: {overlap}"


class TestKeywordLists:
    def test_bisq1_keywords_non_empty(self):
        assert len(BISQ1_STRONG_KEYWORDS) > 10

    def test_bisq2_keywords_non_empty(self):
        assert len(BISQ2_STRONG_KEYWORDS) > 10

    def test_entity_map_keys_in_keyword_lists(self):
        for key in BISQ1_ENTITY_MAP:
            assert key in BISQ1_STRONG_KEYWORDS, f"'{key}' missing from BISQ1 keywords"
        for key in BISQ2_ENTITY_MAP:
            assert key in BISQ2_STRONG_KEYWORDS, f"'{key}' missing from BISQ2 keywords"

    def test_original_bisq1_keywords_preserved(self):
        for kw in ["dao", "bsq", "multisig", "arbitration"]:
            assert kw in BISQ1_STRONG_KEYWORDS

    def test_original_bisq2_keywords_preserved(self):
        for kw in ["bisq easy", "reputation", "bisq 2"]:
            assert kw in BISQ2_STRONG_KEYWORDS


class TestBuildLlmEntityExamples:
    def test_returns_non_empty_string(self):
        result = build_llm_entity_examples()
        assert isinstance(result, str)
        assert len(result) > 0

    def test_contains_arrow_format(self):
        result = build_llm_entity_examples()
        assert "\u2192" in result

    def test_max_10_examples(self):
        result = build_llm_entity_examples()
        lines = [line for line in result.strip().split("\n") if line.strip()]
        assert len(lines) <= 10

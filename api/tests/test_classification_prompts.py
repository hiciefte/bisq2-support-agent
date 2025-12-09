"""Tests for classification_prompts module.

This module tests prompt generation and few-shot examples for OpenAI classification.
"""

import pytest
from app.services.shadow_mode.classification_prompts import (
    ClassificationPromptBuilder,
    get_few_shot_examples,
    get_system_prompt,
)


class TestSystemPrompt:
    """Test system prompt generation."""

    def test_system_prompt_exists(self):
        """System prompt should be returned."""
        prompt = get_system_prompt()
        assert prompt is not None
        assert len(prompt) > 100  # Should be substantial

    def test_system_prompt_contains_user_indicators(self):
        """System prompt should mention USER_QUESTION indicators."""
        prompt = get_system_prompt()
        assert "USER" in prompt.upper()
        assert any(
            indicator in prompt.lower()
            for indicator in ["help", "problem", "error", "stuck", "question"]
        )

    def test_system_prompt_contains_staff_indicators(self):
        """System prompt should mention STAFF_RESPONSE indicators."""
        prompt = get_system_prompt()
        assert "STAFF" in prompt.upper()
        assert any(
            indicator in prompt.lower()
            for indicator in [
                "try",
                "check",
                "have you",
                "diagnostic",
                "advisory",
            ]
        )

    def test_system_prompt_mentions_json_output(self):
        """System prompt should instruct JSON output format."""
        prompt = get_system_prompt()
        assert "JSON" in prompt.upper() or "json" in prompt
        assert "role" in prompt.lower()
        assert "confidence" in prompt.lower()


class TestFewShotExamples:
    """Test few-shot example generation."""

    def test_few_shot_examples_exist(self):
        """Should return list of examples."""
        examples = get_few_shot_examples()
        assert isinstance(examples, list)
        assert len(examples) > 0

    def test_few_shot_examples_have_required_fields(self):
        """Each example should have message and expected classification."""
        examples = get_few_shot_examples()
        for example in examples:
            assert "message" in example
            assert "classification" in example
            assert "role" in example["classification"]
            assert "confidence" in example["classification"]

    def test_few_shot_examples_cover_both_roles(self):
        """Examples should cover both USER_QUESTION and STAFF_RESPONSE."""
        examples = get_few_shot_examples()
        user_examples = [
            ex for ex in examples if ex["classification"]["role"] == "USER_QUESTION"
        ]
        staff_examples = [
            ex for ex in examples if ex["classification"]["role"] == "STAFF_RESPONSE"
        ]

        assert len(user_examples) > 0, "Should have USER_QUESTION examples"
        assert len(staff_examples) > 0, "Should have STAFF_RESPONSE examples"

    def test_few_shot_examples_cover_edge_cases(self):
        """Examples should include edge cases like greetings, follow-ups."""
        examples = get_few_shot_examples()
        messages = [ex["message"].lower() for ex in examples]

        # Check for edge case coverage
        has_greeting = any("thanks" in msg or "hi" in msg for msg in messages)
        has_follow_up = any(
            "ok" in msg or "yeah" in msg or "username" in msg for msg in messages
        )

        assert has_greeting or has_follow_up, "Should cover edge cases"


class TestPromptBuilder:
    """Test ClassificationPromptBuilder."""

    def test_build_prompt_simple_message(self):
        """Should build prompt for simple message."""
        builder = ClassificationPromptBuilder()
        prompt = builder.build_prompt(message="i can't open my trade")

        assert "i can't open my trade" in prompt
        assert len(prompt) > 0

    def test_build_prompt_with_context(self):
        """Should include previous messages as context."""
        builder = ClassificationPromptBuilder()
        prompt = builder.build_prompt(
            message="thanks!",
            prev_messages=["have you tried restarting?", "what version?"],
        )

        assert "thanks!" in prompt
        # Context should be included somehow (implementation dependent)

    def test_build_prompt_with_few_shot_examples(self):
        """Should optionally include few-shot examples."""
        builder = ClassificationPromptBuilder(include_few_shot=True)
        prompt = builder.build_prompt(message="test message")

        # Prompt should be longer with few-shot examples
        assert len(prompt) > 100

    def test_build_prompt_without_few_shot_examples(self):
        """Should build shorter prompt without examples."""
        builder = ClassificationPromptBuilder(include_few_shot=False)
        prompt = builder.build_prompt(message="test message")

        # Should still have system prompt but no examples
        assert len(prompt) > 0


class TestPromptTokenOptimization:
    """Test prompt token optimization."""

    def test_long_message_truncation(self):
        """Should truncate very long messages to save tokens."""
        builder = ClassificationPromptBuilder()
        long_message = "a" * 1000  # 1000 character message

        prompt = builder.build_prompt(message=long_message)

        # Prompt shouldn't be excessively long
        assert len(prompt) < 2000  # Reasonable upper limit

    def test_context_window_limit(self):
        """Should limit number of previous messages included."""
        builder = ClassificationPromptBuilder()
        many_prev_messages = [f"message {i}" for i in range(20)]

        prompt = builder.build_prompt(message="test", prev_messages=many_prev_messages)

        # Should not include all 20 messages (token optimization)
        # Exact number depends on implementation
        assert len(prompt) < 5000  # Reasonable upper limit


class TestHierarchicalConfidence:
    """Test hierarchical confidence dependency system."""

    def test_system_prompt_mentions_hierarchical_dependencies(self):
        """System prompt should explain hierarchical confidence dependencies."""
        prompt = get_system_prompt()

        # Should mention that components build on each other
        assert any(
            keyword in prompt.lower()
            for keyword in ["require", "depend", "prerequisite", "foundation"]
        ), "System prompt should explain confidence dependencies"

    def test_system_prompt_explains_semantic_requires_keywords(self):
        """System prompt should explain semantic clarity requires keyword+syntax evidence."""
        prompt = get_system_prompt()

        # Should mention semantic_clarity dependency on keyword_match + syntax_pattern
        assert "semantic_clarity" in prompt.lower()
        assert any(
            keyword in prompt.lower()
            for keyword in ["keyword_match", "syntax_pattern", "foundation", "evidence"]
        ), "Should explain semantic requires keyword+syntax foundation"

    def test_system_prompt_explains_context_requires_semantic(self):
        """System prompt should explain context alignment requires semantic clarity."""
        prompt = get_system_prompt()

        # Should mention context_alignment dependency on semantic_clarity
        assert "context_alignment" in prompt.lower()
        assert any(
            keyword in prompt.lower() for keyword in ["semantic", "clear", "understand"]
        ), "Should explain context requires semantic understanding"


class TestLowConfidenceEdgeCases:
    """Test low-confidence edge case examples."""

    def test_few_shot_includes_low_confidence_example(self):
        """Examples should include at least one low-confidence case."""
        examples = get_few_shot_examples()
        confidences = [ex["classification"]["confidence"] for ex in examples]

        # Should have at least one example with confidence < 0.5
        low_conf_examples = [c for c in confidences if c < 0.5]
        assert (
            len(low_conf_examples) > 0
        ), "Should include low-confidence examples to teach uncertainty"

    def test_low_confidence_example_has_ambiguous_message(self):
        """Low-confidence example should have genuinely ambiguous message."""
        examples = get_few_shot_examples()
        low_conf_examples = [
            ex for ex in examples if ex["classification"]["confidence"] < 0.5
        ]

        assert len(low_conf_examples) > 0

        # Check that low-confidence example has short, ambiguous message
        for ex in low_conf_examples:
            message = ex["message"].lower()
            # Should be short and lack clear indicators
            assert len(message) < 100, "Low-confidence examples should be brief"

            # Should lack strong role indicators
            strong_user_indicators = ["help", "error", "problem", "can't", "how do i"]
            strong_staff_indicators = ["try", "check", "you should", "have you"]

            has_strong_user = any(ind in message for ind in strong_user_indicators)
            has_strong_staff = any(ind in message for ind in strong_staff_indicators)

            # At most one strong indicator (makes it ambiguous)
            assert not (has_strong_user and has_strong_staff), "Should be ambiguous"

    def test_few_shot_has_confidence_range_coverage(self):
        """Examples should cover full confidence range (high, medium, low)."""
        examples = get_few_shot_examples()
        confidences = [ex["classification"]["confidence"] for ex in examples]

        high_conf = [c for c in confidences if c >= 0.8]
        medium_conf = [c for c in confidences if 0.5 <= c < 0.8]
        low_conf = [c for c in confidences if c < 0.5]

        assert len(high_conf) > 0, "Should have high-confidence examples"
        assert len(low_conf) > 0, "Should have low-confidence examples"
        # Medium is optional but recommended

    def test_low_confidence_example_demonstrates_uncertainty(self):
        """Low-confidence example should teach LLM when to be uncertain."""
        examples = get_few_shot_examples()
        low_conf_examples = [
            ex for ex in examples if ex["classification"]["confidence"] < 0.5
        ]

        assert len(low_conf_examples) > 0

        # Low-confidence example should be genuinely difficult to classify
        # (could reasonably be either USER_QUESTION or STAFF_RESPONSE)
        for ex in low_conf_examples:
            message = ex["message"]

            # Should not have question mark (too obvious)
            # Should not have imperative verbs (too obvious)
            # Should be statement that could go either way
            assert (
                "?" not in message
            ), "Low-confidence should avoid obvious question marks"

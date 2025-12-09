"""Classification prompts for OpenAI-based message classification.

This module provides prompt templates and few-shot examples for classifying
Matrix messages as USER_QUESTION or STAFF_RESPONSE.
"""

from typing import Dict, List, Optional


def get_system_prompt() -> str:
    """Get system prompt for LLM classification with hierarchical confidence.

    Returns:
        System prompt instructing the model to classify messages with
        multidimensional confidence scores that have hierarchical dependencies
    """
    return """You are a message classifier for a Bisq support channel. Your task is to classify each message as either USER_QUESTION or STAFF_RESPONSE with a multidimensional confidence score.

USER_QUESTION indicators:
- Asking for help with a problem
- Reporting an error or issue
- Expressing confusion or being stuck
- Requesting clarification
- Describing unexpected behavior

STAFF_RESPONSE indicators:
- Providing troubleshooting steps ("try this", "check that")
- Offering diagnostic suggestions ("have you checked", "what version")
- Giving advisory guidance ("you should", "you need to")
- Requesting more information for debugging
- Providing solutions or workarounds

Confidence Scoring (Hierarchical Dependencies):
Evaluate the message across these dimensions, which build on each other as a foundation:

1. keyword_match (0-25): Presence of role-specific keywords
   - USER: "help", "error", "problem", "can't", "how do i"
   - STAFF: "try", "check", "you should", "have you", "what version"

2. syntax_pattern (0-25): Grammatical patterns indicating role
   - USER: Question marks, help requests
   - STAFF: Imperative verbs, diagnostic questions

3. semantic_clarity (0-30): How clear the message intent is
   ⚠️ REQUIRES foundation: (keyword_match + syntax_pattern) ≥ 15
   If prerequisite NOT met → cap semantic_clarity at 10
   - High scores need strong keyword/syntax evidence first
   - Without evidence, message intent cannot be "clear"

4. context_alignment (0-20): How well message fits conversation flow
   ⚠️ REQUIRES prerequisite: semantic_clarity ≥ 15 AND prev_messages provided
   If prerequisite NOT met → cap context_alignment at 5
   - Can only evaluate context fit if we understand the message first
   - Without semantic understanding, context analysis is unreliable

Output Format:
Return a JSON object with:
{
    "role": "USER_QUESTION" or "STAFF_RESPONSE",
    "confidence_breakdown": {
        "keyword_match": 0-25,
        "syntax_pattern": 0-25,
        "semantic_clarity": 0-30,
        "context_alignment": 0-20
    },
    "confidence": 0.0-1.0
}

where confidence = sum(confidence_breakdown values) / 100

Important:
- Focus on the message's intent, not just keywords
- Consider conversation context when provided
- Edge cases (greetings, acknowledgments) are usually USER_QUESTION unless clearly staff follow-up
- Respect hierarchical dependencies - don't give high semantic scores without keyword/syntax evidence
- Be uncertain when appropriate - low confidence is valid for ambiguous messages
"""


def get_few_shot_examples() -> List[Dict]:
    """Get few-shot examples for classification with confidence range coverage.

    Returns:
        List of example messages with their classifications, including
        high-confidence, medium-confidence, and low-confidence examples
        to teach the model when to be uncertain
    """
    return [
        # High confidence examples
        {
            "message": "i can't open my trade, getting error: trade protocol failed",
            "classification": {"role": "USER_QUESTION", "confidence": 0.95},
        },
        {
            "message": "have you tried restarting the application? what version are you using?",
            "classification": {"role": "STAFF_RESPONSE", "confidence": 0.92},
        },
        {
            "message": "tried that already, still not working",
            "classification": {"role": "USER_QUESTION", "confidence": 0.88},
        },
        {
            "message": "you should check the logs in ~/.local/share/Bisq2/",
            "classification": {"role": "STAFF_RESPONSE", "confidence": 0.94},
        },
        # Medium confidence examples
        {
            "message": "thanks! that fixed it",
            "classification": {"role": "USER_QUESTION", "confidence": 0.75},
        },
        {
            "message": "can you share your username so i can check the backend?",
            "classification": {"role": "STAFF_RESPONSE", "confidence": 0.91},
        },
        {
            "message": "ok my username is alice123",
            "classification": {"role": "USER_QUESTION", "confidence": 0.82},
        },
        {
            "message": "hi everyone, new to bisq easy",
            "classification": {"role": "USER_QUESTION", "confidence": 0.70},
        },
        # Low confidence example - teaches model to be uncertain when appropriate
        {
            "message": "the transaction completed successfully",
            "classification": {
                "role": "STAFF_RESPONSE",  # Could be user reporting success OR staff confirming
                "confidence": 0.35,  # Low confidence - genuinely ambiguous
            },
        },
    ]


class ClassificationPromptBuilder:
    """Build optimized prompts for message classification."""

    def __init__(self, include_few_shot: bool = True):
        """Initialize prompt builder.

        Args:
            include_few_shot: Whether to include few-shot examples in prompts
        """
        self.include_few_shot = include_few_shot

    def build_prompt(
        self,
        message: str,
        prev_messages: Optional[List[str]] = None,
    ) -> str:
        """Build classification prompt with optional context.

        Args:
            message: The message to classify
            prev_messages: Optional list of previous messages for context

        Returns:
            Complete prompt for classification
        """
        # Truncate long messages to save tokens
        MAX_MESSAGE_LENGTH = 300
        truncated_message = message[:MAX_MESSAGE_LENGTH]
        if len(message) > MAX_MESSAGE_LENGTH:
            truncated_message += "..."

        # Build prompt
        prompt_parts = []

        # Add system prompt (without examples section for brevity)
        if self.include_few_shot:
            # Shorter system prompt for few-shot mode
            prompt_parts.append(
                "Classify support messages as USER_QUESTION or STAFF_RESPONSE."
            )
            prompt_parts.append("\nExamples:")

            # Add only 4 most representative few-shot examples (not all 8)
            examples = get_few_shot_examples()
            for example in examples[:4]:  # Only first 4 examples
                prompt_parts.append(
                    f"\n{example['message']} → {example['classification']['role']}"
                )

            prompt_parts.append("\n\nYour turn:")
        else:
            # Full system prompt for non-few-shot mode
            prompt_parts.append(get_system_prompt())
            prompt_parts.append("\n# Task:")

        # Add conversation context if provided (limit to last 3 messages)
        if prev_messages:
            MAX_CONTEXT_MESSAGES = 3
            context_messages = prev_messages[-MAX_CONTEXT_MESSAGES:]
            if context_messages:
                prompt_parts.append("\nContext:")
                for prev_msg in context_messages:
                    # Truncate context messages aggressively
                    truncated_prev = prev_msg[:100]
                    if len(prev_msg) > 100:
                        truncated_prev += "..."
                    prompt_parts.append(f"- {truncated_prev}")
                prompt_parts.append("")

        # Add the message to classify
        prompt_parts.append(f"\nMessage: {truncated_message}")

        return "\n".join(prompt_parts)

"""Compare generated answers with staff answers for quality scoring."""

import asyncio
import json
import logging
import random
import re
from dataclasses import dataclass
from hashlib import sha256
from typing import Any, Dict, List, Optional

import numpy as np

logger = logging.getLogger(__name__)

JUDGE_SYSTEM_PROMPT = """You are an expert at comparing support chat answers.

Given a user question and two answers (Staff Answer and Generated Answer), evaluate:

## Step 1: Identify Key Claims
First, list the key factual claims in each answer.

## Step 2: Score Each Dimension

1. **factual_alignment** (0.0-1.0): Do both answers convey the same core facts?
   - 1.0 = Identical facts
   - 0.7 = Same general direction, minor differences
   - 0.4 = Some overlap but different emphasis
   - 0.0 = Completely different information

2. **contradiction_score** (0.0-1.0): Does the generated answer contradict the staff answer?
   - 0.0 = No contradictions (GOOD)
   - 0.5 = Minor inconsistencies
   - 1.0 = Direct contradictions (BAD)

3. **completeness** (0.0-1.0): Does the generated answer cover the key points?
   - 1.0 = Covers everything staff mentioned plus helpful additions
   - 0.7 = Covers main points
   - 0.4 = Missing important information
   - 0.0 = Misses the point entirely

4. **hallucination_risk** (0.0-1.0): Does the generated answer contain claims
   that cannot be verified from the question context or staff answer?
   - 0.0 = All claims are verifiable or general knowledge (GOOD)
   - 0.3 = Minor unverifiable details that could be true
   - 0.6 = Specific technical claims with no basis in context
   - 1.0 = Clear fabrication of facts, URLs, or procedures (BAD)

## Examples

### Example 1 - HIGH ALIGNMENT
Question: "How do I resync DAO data?"
Staff: "Go to Settings > Resync DAO from resources"
Generated: "You can resync DAO data from Settings. Select 'Resync DAO from resources'."
Result: {"factual_alignment": 0.95, "contradiction_score": 0.0, "completeness": 0.9, "hallucination_risk": 0.0}

### Example 2 - HALLUCINATION
Question: "What's the trade limit?"
Staff: "The limit is 600 USD for new accounts"
Generated: "The limit is 600 USD. You can increase it to 1200 USD by visiting settings.bisq.network/limits"
Result: {"factual_alignment": 0.8, "contradiction_score": 0.1, "completeness": 0.9, "hallucination_risk": 0.9}
Note: The URL is fabricated.

Return JSON:
{
  "staff_claims": ["claim1", "claim2"],
  "generated_claims": ["claim1", "claim2"],
  "factual_alignment": 0.0-1.0,
  "contradiction_score": 0.0-1.0,
  "completeness": 0.0-1.0,
  "hallucination_risk": 0.0-1.0,
  "reasoning": "Brief explanation of scores"
}
"""

# Prompt injection patterns to filter
INJECTION_PATTERNS = [
    r"ignore\s+(all\s+)?(previous|above|prior)",
    r"disregard\s+(all\s+)?(previous|above|prior)",
    r"system:\s*",
    r"<\|im_start\|>",
    r"<\|im_end\|>",
    r"```\s*system",
]


def extract_json_from_llm_response(text: str) -> Optional[Any]:
    """
    Extract JSON from LLM response, handling markdown code fences.

    Args:
        text: Raw LLM response text

    Returns:
        Parsed JSON (dict or list), or None on parse failure
    """
    # Remove markdown code fences
    text = re.sub(r"^```(?:json)?\s*", "", text.strip())
    text = re.sub(r"\s*```$", "", text)

    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        logger.error(f"JSON parse error: {e}\nText: {text[:200]}")
        return None


@dataclass
class ComparisonResult:
    """Result of comparing generated vs staff answer."""

    question_event_id: str

    # Tier 1: Embedding similarity
    embedding_similarity: float

    # Tier 2: LLM-as-Judge scores
    factual_alignment: float
    contradiction_score: float
    completeness: float
    hallucination_risk: float
    llm_reasoning: str

    # Combined score
    final_score: float

    # Routing decision
    routing: str  # AUTO_APPROVE, SPOT_CHECK, FULL_REVIEW

    # Calibration mode flag
    is_calibration: bool = False

    # Evaluation status
    evaluation_status: str = "success"  # success, failed

    @classmethod
    def calculate_final_score(
        cls,
        embedding_sim: float,
        factual: float,
        contradiction: float,
        completeness: float,
        hallucination: float,
    ) -> float:
        """
        Calculate combined score from components.

        Weights:
          - Factual alignment: 30% (critical)
          - Contradiction avoidance: 25% (prevents harm)
          - Hallucination risk: 20% (guards against fabrication)
          - Embedding similarity: 15% (baseline)
          - Completeness: 10% (nice-to-have)
        """
        return (
            0.15 * embedding_sim
            + 0.30 * factual
            + 0.25 * (1.0 - contradiction)
            + 0.10 * completeness
            + 0.20 * (1.0 - hallucination)
        )

    @classmethod
    def determine_routing(
        cls,
        score: float,
        is_calibration_mode: bool = False,
        calibrated_thresholds: Optional[Dict[str, float]] = None,
    ) -> str:
        """
        Determine routing based on final score.

        During calibration mode, ALL samples go to FULL_REVIEW to build
        human-validated calibration data.
        """
        # Calibration mode forces human review
        if is_calibration_mode:
            return "FULL_REVIEW"

        # Use calibrated thresholds if available, else defaults
        thresholds = calibrated_thresholds or {
            "auto_approve": 0.90,
            "spot_check": 0.75,
        }

        if score >= thresholds["auto_approve"]:
            return "AUTO_APPROVE"
        elif score >= thresholds["spot_check"]:
            return "SPOT_CHECK"
        else:
            return "FULL_REVIEW"


class AnswerComparisonEngine:
    """Compare generated answers with staff answers."""

    def __init__(
        self,
        ai_client: Any,
        embeddings_model: Any,
        judge_model: str = "openai:gpt-4o-mini",
        embedding_threshold: float = 0.5,
        calibration_samples_required: int = 100,
    ):
        """
        Initialize comparison engine.

        Args:
            ai_client: AISuite client for LLM calls
            embeddings_model: Embeddings model for similarity
            judge_model: Model for LLM-as-Judge
            embedding_threshold: Min similarity for Tier 2 evaluation
            calibration_samples_required: Samples needed before auto-approve enabled
        """
        self.ai_client = ai_client
        self.embeddings = embeddings_model
        self.judge_model = judge_model
        self.embedding_threshold = embedding_threshold

        # Calibration mode
        self.calibration_samples_required = calibration_samples_required
        self.calibration_count = 0
        self.calibrated_thresholds: Optional[Dict[str, float]] = None

        # Embedding cache for cost optimization
        self._embedding_cache: Dict[str, List[float]] = {}

        # Token usage tracking
        self.total_prompt_tokens = 0
        self.total_completion_tokens = 0

    @property
    def is_calibration_mode(self) -> bool:
        """Check if still in calibration mode."""
        return self.calibration_count < self.calibration_samples_required

    def _cosine_similarity(self, vec1: List[float], vec2: List[float]) -> float:
        """Calculate cosine similarity between two vectors."""
        a = np.array(vec1)
        b = np.array(vec2)
        norm_a = np.linalg.norm(a)
        norm_b = np.linalg.norm(b)
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return float(np.dot(a, b) / (norm_a * norm_b))

    async def _get_embedding_cached(self, text: str) -> List[float]:
        """
        Get embedding with caching.

        Staff answers are cached to avoid re-embedding for each comparison.
        """
        cache_key = sha256(text.encode()).hexdigest()

        if cache_key in self._embedding_cache:
            return self._embedding_cache[cache_key]

        result = await asyncio.to_thread(self.embeddings.embed_query, text)
        self._embedding_cache[cache_key] = result
        return result

    async def _call_llm_with_retry(
        self,
        messages: List[Dict[str, str]],
        max_retries: int = 3,
    ) -> Any:
        """Call LLM with exponential backoff retry for rate limits."""
        for attempt in range(max_retries):
            try:
                response = await asyncio.to_thread(
                    self.ai_client.chat.completions.create,
                    model=self.judge_model,
                    messages=messages,
                    temperature=0.0,  # Deterministic for consistency
                    max_tokens=800,  # Increased for chain-of-thought
                )

                # Track token usage
                if hasattr(response, "usage") and response.usage:
                    self.total_prompt_tokens += response.usage.prompt_tokens
                    self.total_completion_tokens += response.usage.completion_tokens

                return response

            except Exception as e:
                if attempt == max_retries - 1:
                    raise

                # Exponential backoff with jitter
                wait_time = (2**attempt) + random.uniform(0, 1)
                logger.warning(
                    f"LLM call failed (attempt {attempt + 1}/{max_retries}): {e}. "
                    f"Retrying in {wait_time:.1f}s"
                )
                await asyncio.sleep(wait_time)

        # Should not reach here, but satisfy type checker
        raise RuntimeError("Max retries exceeded")

    def _sanitize_for_prompt(self, text: str) -> str:
        """Sanitize user content to prevent prompt injection attacks."""
        # Remove potential prompt injection patterns
        for pattern in INJECTION_PATTERNS:
            text = re.sub(pattern, "[FILTERED]", text, flags=re.IGNORECASE)

        # Escape braces to prevent format string issues
        text = text.replace("{", "{{").replace("}", "}}")

        return text

    def _extract_json(self, text: str) -> Dict[str, Any]:
        """
        Robust JSON extraction from LLM response.

        Handles markdown code fences and malformed JSON gracefully.
        """
        result = extract_json_from_llm_response(text)
        if result is None:
            return {"evaluation_status": "parse_failed", "error": "JSON parse failed"}
        if isinstance(result, list):
            # Convert list to dict format expected by caller
            return {"results": result}
        return result

    async def _llm_judge(
        self,
        question: str,
        staff_answer: str,
        generated_answer: str,
    ) -> Dict[str, Any]:
        """Use LLM to judge answer quality."""
        # Sanitize all inputs before LLM submission
        safe_question = self._sanitize_for_prompt(question)
        safe_staff = self._sanitize_for_prompt(staff_answer)
        safe_generated = self._sanitize_for_prompt(generated_answer)

        prompt = f"""Compare these two answers to the user's question:

**User Question**: {safe_question}

**Staff Answer**: {safe_staff}

**Generated Answer**: {safe_generated}

Follow the evaluation rubric in your instructions."""

        try:
            response = await self._call_llm_with_retry(
                [
                    {"role": "system", "content": JUDGE_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ]
            )

            response_text = response.choices[0].message.content or "{}"
            result = self._extract_json(response_text)

            # Check for parse failure
            if result.get("evaluation_status") == "parse_failed":
                return {
                    "factual_alignment": None,
                    "contradiction_score": None,
                    "completeness": None,
                    "hallucination_risk": None,
                    "evaluation_status": "failed",
                    "reasoning": f"JSON parse error: {result.get('error')}",
                }

            return result

        except Exception as e:
            logger.error(f"LLM judge failed after retries: {e}")
            # Return explicit failure, not fake scores
            return {
                "factual_alignment": None,
                "contradiction_score": None,
                "completeness": None,
                "hallucination_risk": None,
                "evaluation_status": "failed",
                "reasoning": f"LLM evaluation failed: {e}",
            }

    async def compare(
        self,
        question_event_id: str,
        question_text: str,
        staff_answer: str,
        generated_answer: str,
    ) -> ComparisonResult:
        """
        Compare generated answer with staff answer using three-tier evaluation.

        Tiers:
        1. Fast embedding similarity check
        2. LLM-as-Judge for candidates passing Tier 1
        3. Hallucination detection for all Tier 2 candidates

        Returns:
            ComparisonResult with scores and routing decision
        """
        # Tier 1: Embedding similarity (with caching)
        staff_emb, gen_emb = await asyncio.gather(
            self._get_embedding_cached(staff_answer),
            self._get_embedding_cached(generated_answer),
        )

        embedding_sim = self._cosine_similarity(staff_emb, gen_emb)

        # If embedding similarity is very low, skip Tier 2
        if embedding_sim < self.embedding_threshold:
            routing = ComparisonResult.determine_routing(
                score=embedding_sim * 0.15,
                is_calibration_mode=self.is_calibration_mode,
                calibrated_thresholds=self.calibrated_thresholds,
            )
            return ComparisonResult(
                question_event_id=question_event_id,
                embedding_similarity=embedding_sim,
                factual_alignment=0.0,
                contradiction_score=1.0,
                completeness=0.0,
                hallucination_risk=0.5,
                llm_reasoning="Skipped Tier 2 due to low embedding similarity",
                final_score=embedding_sim * 0.15,
                routing=routing,
                is_calibration=self.is_calibration_mode,
            )

        # Tier 2 + 3: LLM-as-Judge (includes hallucination detection)
        judge_result = await self._llm_judge(
            question_text, staff_answer, generated_answer
        )

        # Handle explicit failure - route to human review
        if judge_result.get("evaluation_status") == "failed":
            return ComparisonResult(
                question_event_id=question_event_id,
                embedding_similarity=embedding_sim,
                factual_alignment=0.0,
                contradiction_score=1.0,
                completeness=0.0,
                hallucination_risk=1.0,
                llm_reasoning=judge_result.get("reasoning", "Evaluation failed"),
                final_score=0.0,
                routing="FULL_REVIEW",
                is_calibration=self.is_calibration_mode,
                evaluation_status="failed",
            )

        factual = judge_result.get("factual_alignment", 0.5)
        contradiction = judge_result.get("contradiction_score", 0.5)
        completeness = judge_result.get("completeness", 0.5)
        hallucination = judge_result.get("hallucination_risk", 0.5)
        reasoning = judge_result.get("reasoning", "")

        final_score = ComparisonResult.calculate_final_score(
            embedding_sim, factual, contradiction, completeness, hallucination
        )

        # Determine routing (respects calibration mode)
        routing = ComparisonResult.determine_routing(
            score=final_score,
            is_calibration_mode=self.is_calibration_mode,
            calibrated_thresholds=self.calibrated_thresholds,
        )

        # Track calibration progress
        self.calibration_count += 1

        return ComparisonResult(
            question_event_id=question_event_id,
            embedding_similarity=embedding_sim,
            factual_alignment=factual,
            contradiction_score=contradiction,
            completeness=completeness,
            hallucination_risk=hallucination,
            llm_reasoning=reasoning,
            final_score=final_score,
            routing=routing,
            is_calibration=self.is_calibration_mode,
        )

    def compare_sync(
        self,
        question_event_id: str,
        question_text: str,
        staff_answer: str,
        generated_answer: str,
    ) -> ComparisonResult:
        """
        Synchronous wrapper for compare.

        Returns:
            ComparisonResult with scores and routing decision
        """
        return asyncio.run(
            self.compare(
                question_event_id, question_text, staff_answer, generated_answer
            )
        )

    def get_token_usage(self) -> Dict[str, int]:
        """Get total token usage for cost tracking."""
        return {
            "prompt_tokens": self.total_prompt_tokens,
            "completion_tokens": self.total_completion_tokens,
            "total_tokens": self.total_prompt_tokens + self.total_completion_tokens,
        }

    def clear_embedding_cache(self) -> None:
        """Clear the embedding cache to free memory."""
        self._embedding_cache.clear()

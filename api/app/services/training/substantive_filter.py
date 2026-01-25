"""LLM-based filter to identify substantive support answers."""

import asyncio
import logging
from dataclasses import dataclass
from typing import Any, List, Tuple

from app.services.training.comparison_engine import extract_json_from_llm_response
from app.services.training.matrix_export_parser import QAPair

logger = logging.getLogger(__name__)

FILTER_SYSTEM_PROMPT = """You are an expert at evaluating support chat responses.

Classify each staff answer as one of:
- **substantive**: Provides helpful information, explanation, instructions, or solution
- **trivial**: Short acknowledgment, greeting, or non-informative response (ok, thanks, np, etc.)
- **off_topic**: Unrelated to the question or general chat

Examples:

SUBSTANTIVE answers:
- "The first option and resync from resources in settings do the same thing. Do not use resync from genesis"
- "This is a known issue at the moment that is currently being addressed. Should hopefully have a workaround shortly"
- "I believe you need correct burningman data to start a trade or send to arbitration as those fees are paid to burningman"

TRIVIAL answers:
- "ok"
- "thanks"
- "np"
- "yes"
- "for DAO, yes"
- "👍"
- "will check"

OFF_TOPIC answers:
- Random chat not related to the question
- Staff asking their own unrelated question
- Community announcements

Return JSON array with classification for each answer:
[
  {"answer_index": 0, "classification": "substantive|trivial|off_topic", "confidence": 0.0-1.0}
]
"""


@dataclass
class FilterResult:
    """Result of substantive answer filtering."""

    answer_index: int
    classification: str  # substantive, trivial, off_topic
    confidence: float


class SubstantiveAnswerFilter:
    """Filter to identify substantive support answers using LLM."""

    def __init__(self, ai_client: Any, model: str = "openai:gpt-4o-mini"):
        """
        Initialize filter.

        Args:
            ai_client: AISuite client for LLM calls
            model: Model identifier
        """
        self.ai_client = ai_client
        self.model = model

    async def filter_answers(
        self,
        qa_pairs: List[QAPair],
        batch_size: int = 20,
    ) -> Tuple[List[QAPair], List[Tuple[QAPair, str]]]:
        """
        Filter Q&A pairs to keep only substantive answers.

        Args:
            qa_pairs: List of QAPair objects
            batch_size: Number of answers to classify per LLM call

        Returns:
            Tuple of (substantive_pairs, filtered_pairs_with_reasons)
        """
        if not qa_pairs:
            return [], []

        substantive: List[QAPair] = []
        filtered: List[Tuple[QAPair, str]] = []

        # Process in batches
        for i in range(0, len(qa_pairs), batch_size):
            batch = qa_pairs[i : i + batch_size]

            # Format batch for LLM
            answers_text = "\n".join(
                [
                    f"[{idx}] Q: {pair.question_text[:100]}...\n    A: {pair.answer_text}"
                    for idx, pair in enumerate(batch)
                ]
            )

            prompt = f"""Classify these {len(batch)} support answers:

{answers_text}

Return JSON array with classification for each answer."""

            try:
                response = await asyncio.to_thread(
                    self.ai_client.chat.completions.create,
                    model=self.model,
                    messages=[
                        {"role": "system", "content": FILTER_SYSTEM_PROMPT},
                        {"role": "user", "content": prompt},
                    ],
                    temperature=0.1,
                    max_tokens=1000,
                )

                response_text = response.choices[0].message.content or "[]"
                results = extract_json_from_llm_response(response_text)

                if results is None:
                    logger.warning("Failed to parse filter response, including batch")
                    substantive.extend(batch)
                    continue

                # Process results
                for result in results:
                    idx = result.get("answer_index", 0)
                    classification = result.get("classification", "trivial")

                    if idx < len(batch):
                        pair = batch[idx]
                        if classification == "substantive":
                            substantive.append(pair)
                        else:
                            filtered.append((pair, classification))

            except Exception as e:
                logger.error(f"Filter batch failed: {e}")
                # On error, include all as substantive (conservative)
                substantive.extend(batch)

        logger.info(
            f"Filtered {len(qa_pairs)} pairs: "
            f"{len(substantive)} substantive, {len(filtered)} filtered"
        )

        return substantive, filtered

    async def filter_single(self, answer_text: str) -> Tuple[bool, str]:
        """
        Filter a single answer text for substantiveness.

        This is a simplified version for real-time processing of individual
        staff answers (not batch processing from exports).

        Args:
            answer_text: The staff answer text to classify

        Returns:
            Tuple of (is_substantive: bool, classification: str)
        """
        if not answer_text or len(answer_text.strip()) < 5:
            return False, "trivial"

        # Quick heuristic checks for obvious trivial responses
        trivial_responses = {
            "ok",
            "okay",
            "thanks",
            "thank you",
            "np",
            "no problem",
            "yes",
            "no",
            "👍",
            "will check",
            "checking",
            "one moment",
            "one sec",
        }
        if answer_text.strip().lower() in trivial_responses:
            return False, "trivial"

        # For longer answers, use LLM classification
        try:
            prompt = f"Classify this single support answer:\n\n{answer_text[:500]}"

            response = await asyncio.to_thread(
                self.ai_client.chat.completions.create,
                model=self.model,
                messages=[
                    {"role": "system", "content": FILTER_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.1,
                max_tokens=100,
            )

            response_text = response.choices[0].message.content or "[]"
            results = extract_json_from_llm_response(response_text)

            if results and len(results) > 0:
                classification = results[0].get("classification", "trivial")
                return classification == "substantive", classification

        except Exception as e:
            logger.warning(f"Single filter failed, defaulting to substantive: {e}")
            # On error, default to substantive (conservative approach)
            return True, "substantive"

        return True, "substantive"

    def filter_answers_sync(
        self,
        qa_pairs: List[QAPair],
        batch_size: int = 20,
    ) -> Tuple[List[QAPair], List[Tuple[QAPair, str]]]:
        """
        Synchronous wrapper for filter_answers.

        Args:
            qa_pairs: List of QAPair objects
            batch_size: Number of answers to classify per LLM call

        Returns:
            Tuple of (substantive_pairs, filtered_pairs_with_reasons)

        Note:
            This uses asyncio.get_event_loop() to safely run in both sync and
            async contexts. If called from an async context, use filter_answers directly.
        """
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            # No running loop - safe to use asyncio.run()
            return asyncio.run(self.filter_answers(qa_pairs, batch_size))

        # There's an existing event loop - this shouldn't be called from async context
        # Log a warning and run in a new thread to avoid nested event loop issues
        import concurrent.futures

        logger.warning(
            "filter_answers_sync called from async context. "
            "Consider using filter_answers directly."
        )
        with concurrent.futures.ThreadPoolExecutor() as executor:
            future = executor.submit(
                asyncio.run, self.filter_answers(qa_pairs, batch_size)
            )
            return future.result()
